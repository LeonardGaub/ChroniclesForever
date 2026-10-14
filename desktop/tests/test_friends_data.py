import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from forever_chronicle.importing.sv_importer import SavedVariablesImporter
from forever_chronicle.storage.database import Database
from forever_chronicle.storage.share import export_share, import_share
from forever_chronicle.wow import friends_data
from forever_chronicle.wow.friends_data import LuaSerializeError, lua_string, lua_value, write_friends_data
from forever_chronicle.wow.lua_parser import parse_saved_variables
from forever_chronicle.wow.paths import ClientInstall

REPO = Path(__file__).resolve().parents[2]
DUMP = REPO / "tests" / "addon" / "dump_friends.js"
FIXTURE = REPO / "tests" / "fixtures" / "FriendsData.lua"
GUID = "Player-4619-0112A417"
NASTY = 'Bob"]] os.exit(1) --\n\\ä«'


def run_lua(path: Path) -> dict:
    """Executes the file in a real Lua VM (tests/addon, fengari) and returns what it defined."""
    if not shutil.which("node") or not (REPO / "tests" / "addon" / "node_modules" / "fengari").is_dir():
        pytest.skip("node + fengari needed (npm install in tests/addon)")
    out = subprocess.run(["node", str(DUMP), str(path)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr

    def fix(v):  # strings come back as one \\u00XX per UTF-8 byte
        if isinstance(v, str):
            return v.encode("latin-1").decode("utf-8")
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {fix(k): fix(x) for k, x in v.items()}
        return v
    return fix(json.loads(out.stdout))


def test_lua_strings_are_plain_ascii():
    s = lua_string(NASTY)
    assert s.isascii() and s.startswith('"') and s.endswith('"')
    inner = s[1:-1]
    assert '"' not in inner and "\n" not in inner and "]]" in inner     # ]] is harmless inside a "..." string
    assert all(c == "\\" or c.isprintable() for c in inner)
    assert lua_string("ä") == '"\\195\\164"'


def test_serializer_rejects_odd_values():
    assert lua_value({"a": 1, "b": None, 3: [True, 1.5]}) == '{["a"]=1,[3]={true,1.5}}'
    for bad in (math.nan, math.inf, {1.5: 1}, {True: 1}, object(), {"a": set()}):
        with pytest.raises(LuaSerializeError):
            lua_value(bad)
    deep = []
    for _ in range(20):
        deep = [deep]
    with pytest.raises(LuaSerializeError):
        lua_value(deep)


@pytest.fixture
def with_friend(db, addon_fixture, tmp_path, monkeypatch):
    """My database with one friend (nasty name) who shared everything of the fixture character."""
    friend = Database(tmp_path / "friend.db")
    data = parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))
    chars = data["ForeverChronicleDB"]["characters"]
    char = chars.pop(GUID)
    char["info"]["guid"], char["info"]["name"] = "Player-4619-0FRIEND1", 'Thr"all\n'
    chars["Player-4619-0FRIEND1"] = char
    SavedVariablesImporter(friend).import_data(data, "f")
    cid = friend.conn.execute("SELECT character_id FROM characters").fetchone()[0]
    share = tmp_path / "f.fcshare"
    monkeypatch.setattr("forever_chronicle.storage.share.time.time", lambda: 1791990000)
    export_share(friend, share, "b" * 32, NASTY, {cid: {"chronicle", "routes", "sessions", "gear"}})
    friend.close()
    assert import_share(db, share, "a" * 32, tmp_path / "friends").status == "ok"
    with db.transaction():  # deterministic fixture file
        db.conn.execute("UPDATE owners SET shared_at = 1791990000, imported_at = 1791990000")
    return db


def fake_client(tmp_path) -> ClientInstall:
    root = tmp_path / "client"
    addon = root / "Interface" / "AddOns" / "ForeverChronicle"
    addon.mkdir(parents=True)
    (addon / "ForeverChronicle.toc").write_text("## Interface: 16001\n")
    return ClientInstall(root, "wow_classic_beta")


def test_written_file_is_plain_data_in_real_lua(with_friend, tmp_path, monkeypatch):
    monkeypatch.setattr(friends_data.time, "time", lambda: 1791990000)
    client = fake_client(tmp_path)
    result = write_friends_data(with_friend.conn, client)
    assert result.status == "ok" and result.friends == 1 and result.characters == 1
    assert result.path == client.addons_dir / "ForeverChronicle" / "Friends" / "FriendsData.lua"
    text = result.path.read_text(encoding="ascii")                    # pure ASCII
    assert text.startswith("-- Forever Chronicle: friends' characters")

    lua = run_lua(result.path)
    assert lua["extraGlobals"] == []                                   # defines nothing but ForeverChronicleFriends
    data = lua["data"]
    friend = data["friends"][0]
    assert friend["name"] == NASTY.replace("\n", "")                    # control characters removed by the import
    char = friend["characters"][0]
    assert char["info"]["name"] == 'Thr"all\n' and char["info"]["key"] == "Player-4619-0FRIEND1"
    streams = char["streams"]
    assert len(streams["events"]["records"]) == 6 and len(streams["sessions"]["records"]) == 2
    assert streams["sessions"]["records"][0]["endReason"] == "logout"
    assert len(streams["positions"]["records"]) >= 12
    assert streams["positions"]["records"][0].count(",") == 6           # addon's compact point format
    assert char["stats"]["kills"] == 2 and data["maps"]["1413"]["continent"] == 1414
    gear = char["snapshots"]["gear"]["slots"]
    assert [g["slotName"] for g in gear] == ["HeadSlot", "MainHandSlot"] and gear[0]["quality"] == 3
    assert "Green Tinted Goggles" in gear[0]["link"] and gear[0]["icon"] == 133001
    quest = next(e for e in streams["events"]["records"] if e["type"] == "quest_completed")
    assert quest["data"]["title"] == "The Runaway Shipment" and quest["location"]["mapID"] == 1413

    # The addon tests load this file (tests/addon, phase 12).
    FIXTURE.write_text(text, encoding="ascii", newline="\n")


def test_limits_and_status(with_friend, tmp_path, monkeypatch):
    monkeypatch.setattr(friends_data, "EVENTS_PER_CHARACTER", 2)
    monkeypatch.setattr(friends_data, "ROUTE_SESSIONS", 1)
    data = friends_data.build_friends_data(with_friend.conn)
    char = data["friends"][0]["characters"][0]
    events = char["streams"]["events"]["records"]
    assert [e["type"] for e in events] == ["achievement_earned", "session_started"]   # the newest two, in order
    last_session = char["streams"]["sessions"]["records"][-1]["startedAt"]
    assert all(int(p.split(",")[0]) >= last_session for p in char["streams"]["positions"]["records"])

    assert write_friends_data(with_friend.conn, None).status == "no_client"
    no_addon = ClientInstall(tmp_path / "empty", "wow_classic_beta")
    assert write_friends_data(with_friend.conn, no_addon).status == "no_addon"


def test_no_friends_writes_empty_list(db, tmp_path):
    client = fake_client(tmp_path)
    result = write_friends_data(db.conn, client)
    assert result.status == "ok" and result.characters == 0
    assert run_lua(result.path)["data"]["friends"] == []
