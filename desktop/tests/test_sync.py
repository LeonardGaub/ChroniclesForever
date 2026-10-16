"""The cloud sync script (sync/ForeverSync.ps1), run for real with PowerShell against temporary folders:
setup, addon install from the repository clone, upload, download with the pure-data check, the friends file in a
real Lua VM, backups, addon updates and turning off the old automation (versions 1 and 2 ran by themselves)."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SHARE_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle_Share.lua"
FRIEND_FILE = "Bob_the_Friend-ffffffff-0badc0de.lua"

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
    for name in ("ForeverSync.ps1", "Einrichten.bat", "Abgleichen.bat"):
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
    (cloud / "players" / FRIEND_FILE).write_text(text, encoding="utf-8")
    (cloud / "players" / f"{'e' * 32}-00000001.lua").write_text(
        'ForeverChronicleShareDB = { name = "x" } os.exit(1) ForeverChronicleFriends = nil', encoding="utf-8")
    (cloud / "players" / "Mallory-dddddddd-00000002.lua").write_text(
        'ForeverChronicleShareDB = { ["name"] = ("Mallory"):rep(3) }', encoding="utf-8")
    (cloud / "players" / "readme.lua").write_text("ForeverChronicleShareDB = {}", encoding="utf-8")
    startup = tmp_path / "Startup"
    startup.mkdir()
    return {"repo": repo, "cloud": cloud, "client": client, "data": tmp_path / "data", "saved": saved,
            "startup": startup}


def setup(world):
    return ps("-File", world["repo"] / "sync" / "ForeverSync.ps1", "-Setup", "-CloudFolder", world["cloud"],
              "-ClientFolder", world["client"], "-DataDir", world["data"], "-StartupFolder", world["startup"])


def once(world):
    return ps("-File", world["repo"] / "sync" / "ForeverSync.ps1", "-Once", "-DataDir", world["data"],
              "-StartupFolder", world["startup"])

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
    assert len(config["shareId"]) == 32 and config["scriptVersion"] == 3 and "interval" not in config
    assert not (world["data"] / "ForeverSync.ps1").exists(), "runs from the repository, no copy"
    assert list(world["startup"].iterdir()) == [], "no Startup entry: the sync runs only when asked"

    # 1. addon installed from the repository clone (both addons), friends file written
    addons = world["client"] / "Interface" / "AddOns"
    assert (addons / "ForeverChronicle" / "ForeverChronicle.toc").is_file()
    assert (addons / "ForeverChronicle_Share" / "ForeverChronicle_Share.toc").is_file()

    # 2. my share file uploaded under my name and ID, the account number hidden behind a hash
    mine = list((world["cloud"] / "players").glob(f"*-{config['shareId'][:8]}-*.lua"))
    assert len(mine) == 1 and mine[0].name.startswith("Blind-") and "123456" not in mine[0].name
    assert mine[0].read_bytes() == (world["saved"] / "ForeverChronicle_Share.lua").read_bytes()

    # 3. friends: only the plain-data friend file, never my own, the malicious or the oddly named one
    friends = addons / "ForeverChronicle_Share" / "Friends" / "FriendsData.lua"
    text = friends.read_text(encoding="utf-8")
    assert FRIEND_FILE in text and config["shareId"][:8] not in text
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

    # The game wrote new share data under a new name: uploaded under that name, my older uploads (also one named
    # the way scripts before 2026-10-16 did) removed, a friend's file kept.
    players = world["cloud"] / "players"
    share_id = json.loads((world["data"] / "config.json").read_text(encoding="utf-8-sig"))["shareId"]
    [mine] = players.glob(f"Blind-{share_id[:8]}-*.lua")
    account = mine.stem.rsplit("-", 1)[1]
    (players / f"{share_id}-{account}.lua").write_bytes(mine.read_bytes())
    share = world["saved"] / "ForeverChronicle_Share.lua"
    share.write_text(share.read_text(encoding="utf-8").replace('\n\t["name"] = "Blind",', '\n\t["name"] = "Blindy",', 1),
                     encoding="utf-8")
    once(world)
    assert "uploaded" in "".join(log(world).splitlines(True)[lines:])
    assert sorted(p.name for p in players.glob(f"*{account}.lua")) == [f"Blindy-{share_id[:8]}-{account}.lua"]
    assert (players / FRIEND_FILE).is_file()

    # A newer addon in the repository (git pull) is installed; the friends file in the game folder is kept.
    toc = world["repo"] / "addons" / "ForeverChronicle" / "ForeverChronicle.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Version: ", "## Version: 9", 1), encoding="utf-8")
    once(world)
    installed = world["client"] / "Interface" / "AddOns" / "ForeverChronicle" / "ForeverChronicle.toc"
    assert "## Version: 9" in installed.read_text(encoding="utf-8") and friends.is_file()
    assert "addon installed" in log(world)



def test_pure_data_check_is_fast_on_big_files(world, tmp_path):
    """A friend file of several MB is checked in well under a minute."""
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




def test_setup_before_version_2_gets_this_repository(world):
    """A version 1 setup has no repository in its settings: the first run from the repository adds it, so addon
    updates come with the next sync after a git pull."""
    setup(world)
    config_path = world["data"] / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    del config["repo"]
    config["scriptVersion"] = 1
    config_path.write_text(json.dumps(config), encoding="utf-8")
    toc = world["repo"] / "addons" / "ForeverChronicle" / "ForeverChronicle.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Version: ", "## Version: 9", 1), encoding="utf-8")
    once(world)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    assert config["repo"] == str(world["repo"]) and config["scriptVersion"] == 3
    addons = world["client"] / "Interface" / "AddOns"
    assert "## Version: 9" in (addons / "ForeverChronicle" / "ForeverChronicle.toc").read_text(encoding="utf-8")
    assert "failed" not in log(world)


def shortcut(path, arguments):
    ps("-Command", f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut('{path}'); "
                   rf"$l.TargetPath = 'C:\Windows\System32\wscript.exe'; $l.Arguments = '{arguments}'; $l.Save()")


def test_old_automation_is_turned_off(world):
    """Versions 1 and 2 ran by themselves: a Startup entry started a hidden loop from copies of the script in the
    data folder. A run turns exactly that off; another setup's Startup entry stays."""
    setup(world)
    data, link = world["data"], world["startup"] / "Journey Forever Sync.lnk"
    shortcut(link, f'"{world["repo"] / "elsewhere" / "ForeverSync.vbs"}"')
    once(world)
    assert link.exists(), "an entry for another data folder is not ours"

    shortcut(link, f'"{data / "ForeverSync.vbs"}"')
    (data / "ForeverSync.vbs").write_text("' old launcher\n", encoding="utf-8")
    (data / "ForeverSync.ps1").write_text("param([switch]$Loop)\nStart-Sleep -Seconds 120\n", encoding="utf-8")
    loop = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(data / "ForeverSync.ps1"), "-Loop"])
    try:
        time.sleep(2)                                   # until its command line is visible
        once(world)
        assert loop.wait(timeout=30) is not None, "the background loop was stopped"
    finally:
        loop.kill()
    assert not link.exists() and not (data / "ForeverSync.ps1").exists() and not (data / "ForeverSync.vbs").exists()
    assert "automatic sync turned off: Startup entry removed" in log(world)
    assert "automatic sync turned off: background run stopped" in log(world)
