"""The cloud sync script (sync/ForeverSync.ps1), run for real with PowerShell against temporary folders:
setup, addon install from the repository clone, upload, download with the pure-data check, the friends file in a
real Lua VM, backups and addon updates."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SHARE_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle_Share.lua"
FRIEND_ID = "f" * 32

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"),
                                reason="Windows PowerShell needed")


def ps(*args, timeout=120):
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *map(str, args)],
                         capture_output=True, text=True, timeout=timeout)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


@pytest.fixture
def world(tmp_path):
    """A repository clone (sync, addons), a cloud folder (players only) and a WoW client with one account."""
    if not SHARE_FIXTURE.exists():
        pytest.skip("run npm test in tests/addon first (writes tests/fixtures/ForeverChronicle_Share.lua)")
    repo = tmp_path / "repo"
    (repo / "sync").mkdir(parents=True)
    for name in ("ForeverSync.ps1", "ForeverSync.vbs", "Einrichten.bat"):
        shutil.copy(REPO / "sync" / name, repo / "sync" / name)
    for addon in ("ForeverChronicle", "ForeverChronicle_Share"):
        shutil.copytree(REPO / "addons" / addon, repo / "addons" / addon)
    cloud = tmp_path / "cloud"
    (cloud / "players").mkdir(parents=True)
    client = tmp_path / "WoW" / "_classic_beta_"
    (client / "Interface" / "AddOns").mkdir(parents=True)
    (client / ".flavor.info").write_text("#Flavor\nwow_classic_beta\n")
    saved = client / "WTF" / "Account" / "123456#1" / "SavedVariables"
    saved.mkdir(parents=True)
    shutil.copy(SHARE_FIXTURE, saved / "ForeverChronicle_Share.lua")
    (saved / "ForeverChronicle.lua").write_text("ForeverChronicleDB = {}\n")
    # A friend's file (the same data, under their ID), a malicious one, and an unexpected name.
    text = SHARE_FIXTURE.read_text(encoding="utf-8")
    renamed = text.replace('\n\t["name"] = "Blind",', '\n\t["name"] = "Bob \\"the\\" Friend",', 1)
    renamed = renamed.replace('\t\t\t\t["name"] = "Blind",', '\t\t\t\t["name"] = "Thrall",', 1)
    assert renamed.count("Thrall") == 1 and 'Bob \\"the\\" Friend' in renamed
    text = renamed
    (cloud / "players" / f"{FRIEND_ID}-0badc0de.lua").write_text(text, encoding="utf-8")
    (cloud / "players" / f"{'e' * 32}-00000001.lua").write_text(
        'ForeverChronicleShareDB = { name = "x" } os.exit(1) ForeverChronicleFriends = nil', encoding="utf-8")
    (cloud / "players" / f"{'d' * 32}-00000002.lua").write_text(
        'ForeverChronicleShareDB = { ["name"] = ("Mallory"):rep(3) }', encoding="utf-8")
    (cloud / "players" / "readme.lua").write_text("ForeverChronicleShareDB = {}", encoding="utf-8")
    return {"repo": repo, "cloud": cloud, "client": client, "data": tmp_path / "data", "saved": saved}


def setup(world):
    return ps("-File", world["repo"] / "sync" / "ForeverSync.ps1", "-Setup", "-CloudFolder", world["cloud"],
              "-ClientFolder", world["client"], "-DataDir", world["data"], "-NoStartup")


def once(world):
    return ps("-File", world["data"] / "ForeverSync.ps1", "-Once", "-DataDir", world["data"])


def log(world):
    return (world["data"] / "sync.log").read_text(encoding="utf-8-sig")


def run_lua(path):
    out = subprocess.run(["node", str(REPO / "tests" / "addon" / "dump_friends.js"), str(path)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_setup_installs_shares_and_receives(world):
    out = setup(world)
    assert "eingerichtet" in out
    config = json.loads((world["data"] / "config.json").read_text(encoding="utf-8-sig"))
    assert config["cloud"] == str(world["cloud"]) and config["client"] == str(world["client"])
    assert config["repo"] == str(world["repo"])
    assert len(config["shareId"]) == 32 and (world["data"] / "ForeverSync.ps1").is_file()

    # 1. addon installed from the repository clone (both addons), friends file written
    addons = world["client"] / "Interface" / "AddOns"
    assert (addons / "ForeverChronicle" / "ForeverChronicle.toc").is_file()
    assert (addons / "ForeverChronicle_Share" / "ForeverChronicle_Share.toc").is_file()

    # 2. my share file uploaded under my ID, the account number hidden behind a hash
    mine = list((world["cloud"] / "players").glob(f"{config['shareId']}-*.lua"))
    assert len(mine) == 1 and "123456" not in mine[0].name
    assert mine[0].read_bytes() == (world["saved"] / "ForeverChronicle_Share.lua").read_bytes()

    # 3. friends: only the plain-data friend file, never my own, the malicious or the oddly named one
    friends = addons / "ForeverChronicle_Share" / "Friends" / "FriendsData.lua"
    text = friends.read_text(encoding="utf-8")
    assert f"{FRIEND_ID}-0badc0de.lua" in text and config["shareId"] not in text
    assert "os.exit" not in text and "Mallory" not in text
    lua = run_lua(friends)
    assert lua["extraGlobals"] == []
    [friend] = lua["data"]["friends"]
    assert friend["name"] == 'Bob "the" Friend' and friend["characters"][0]["info"]["name"] == "Thrall"
    assert friend["characters"][0]["snapshots"]["gear"]["slots"][0]["slotName"] == "HeadSlot"
    assert lua["data"]["maps"]["1413"]["continent"] == 1414
    assert "rejected" in log(world) and "ignored unexpected file readme.lua" in log(world)

    # The addon tests (phase 12) load exactly this file.
    (REPO / "tests" / "fixtures" / "FriendsData.lua").write_bytes(friends.read_bytes())

    # The cloud folder holds player data only.
    assert [p.name for p in world["cloud"].iterdir()] == ["players"]

    # 4. daily backup of the addon's SavedVariables
    today = time.strftime("%Y-%m-%d")
    assert (world["data"] / "backups" / today / "123456#1" / "ForeverChronicle.lua").is_file()


def test_second_run_changes_nothing_then_updates(world):
    setup(world)
    friends = world["client"] / "Interface" / "AddOns" / "ForeverChronicle_Share" / "Friends" / "FriendsData.lua"
    stamp = friends.stat().st_mtime_ns
    lines = log(world).count("\n")
    once(world)
    assert friends.stat().st_mtime_ns == stamp                         # nothing new: nothing rewritten
    assert "uploaded" not in "".join(log(world).splitlines(True)[lines:])

    # The game wrote new share data: uploaded again.
    share = world["saved"] / "ForeverChronicle_Share.lua"
    share.write_text(share.read_text(encoding="utf-8").replace('"Blind"', '"Blindy"', 1), encoding="utf-8")
    once(world)
    assert "uploaded" in "".join(log(world).splitlines(True)[lines:])

    # A newer addon in the repository (git pull) is installed; the friends file in the game folder is kept.
    toc = world["repo"] / "addons" / "ForeverChronicle" / "ForeverChronicle.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Version: ", "## Version: 9", 1), encoding="utf-8")
    once(world)
    installed = world["client"] / "Interface" / "AddOns" / "ForeverChronicle" / "ForeverChronicle.toc"
    assert "## Version: 9" in installed.read_text(encoding="utf-8") and friends.is_file()
    assert "addon installed" in log(world)

    # A newer script in the repository replaces the installed one.
    script = world["repo"] / "sync" / "ForeverSync.ps1"
    script.write_text(script.read_text(encoding="utf-8") + "\n# new version\n", encoding="utf-8")
    once(world)
    assert "# new version" in (world["data"] / "ForeverSync.ps1").read_text(encoding="utf-8")


def test_pure_data_check_is_fast_on_big_files(world, tmp_path):
    """A friend file of several MB is checked in well under the sync interval."""
    setup(world)
    rows = ",\n".join(f'"{1791961000 + i},1413,0.{i % 9999:04d},0.5000,,,"' for i in range(120000))
    big = 'ForeverChronicleShareDB = {\n["name"] = "Big",\n["characters"] = {{["info"] = {["name"] = "B"}, ' \
          '["streams"] = {["positions"] = {["records"] = {\n' + rows + '\n}}}}},\n}\n'
    (world["cloud"] / "players" / f"{'a' * 32}-0000000b.lua").write_text(big, encoding="utf-8")
    start = time.time()
    once(world)
    assert time.time() - start < 60
    friends = world["client"] / "Interface" / "AddOns" / "ForeverChronicle_Share" / "Friends" / "FriendsData.lua"
    assert '"Big"' in friends.read_text(encoding="utf-8")


def test_setup_before_version_2_keeps_syncing_without_updates(world):
    """An older setup has no repository in its config: player data still syncs, no update is looked for."""
    setup(world)
    config_path = world["data"] / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    del config["repo"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    toc = world["repo"] / "addons" / "ForeverChronicle" / "ForeverChronicle.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Version: ", "## Version: 9", 1), encoding="utf-8")
    (world["cloud"] / "players" / f"{'b' * 32}-0000000c.lua").write_text(
        SHARE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    once(world)
    addons = world["client"] / "Interface" / "AddOns"
    assert "## Version: 9" not in (addons / "ForeverChronicle" / "ForeverChronicle.toc").read_text(encoding="utf-8")
    assert f"{'b' * 32}-0000000c.lua" in (addons / "ForeverChronicle_Share" / "Friends" / "FriendsData.lua").read_text(
        encoding="utf-8")
    assert "failed" not in log(world)
