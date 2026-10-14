import json
import os
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle.importing.sv_importer import SavedVariablesImporter  # noqa: E402
from forever_chronicle.storage.database import Database  # noqa: E402
from forever_chronicle.storage.jsonl import export_jsonl  # noqa: E402
from forever_chronicle.storage.repository import Repository  # noqa: E402
from forever_chronicle.storage.share import export_share, import_share, remove_friend  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402

ALICE, BOB = "a" * 32, "b" * 32
GUID = "Player-4619-0112A417"
ALL = {"chronicle", "routes", "sessions", "screenshots"}


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def alice(db, addon_fixture, tmp_path):
    """Alice's database: the addon fixture, one screenshot with a real picture."""
    SavedVariablesImporter(db).import_data(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")), "fx")
    picture = tmp_path / "WoWScrnShot.jpg"
    image = QImage(2400, 1200, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    assert image.save(str(picture), "JPG")
    with db.transaction():
        db.conn.execute("UPDATE screenshots SET file_path = ?, file_match = 'matched'", (str(picture),))
    return db


@pytest.fixture
def bob(tmp_path):
    database = Database(tmp_path / "bob" / "bob.db", tmp_path / "bob" / "backups")
    yield database
    database.close()


def alice_char(db):
    return db.conn.execute("SELECT character_id FROM characters WHERE owner_id IS NULL").fetchone()[0]


def shot_ids(db, cid):
    return {(cid, r[0]) for r in db.conn.execute("SELECT screenshot_id FROM screenshots WHERE character_id = ?",
                                                  (cid,))}


def count(db, table, cid=None):
    if cid is None:
        return db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return db.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE character_id = ?", (cid,)).fetchone()[0]


def test_share_round_trip(alice, bob, tmp_path):
    cid = alice_char(alice)
    path = tmp_path / "alice.fcshare"
    exported = export_share(alice, path, ALICE, "Alice \x07", {cid: ALL}, shot_ids(alice, cid))
    assert exported.characters == 1 and exported.images >= 1 and exported.missing_images == 0
    with zipfile.ZipFile(path) as zf:
        header = json.loads(zf.read("share.jsonl").decode().splitlines()[0])
        assert header["kind"] == "share" and header["sender"] == "Alice" and header["characters"] == {GUID: sorted(ALL)}
        picture = QImage.fromData(zf.read(next(n for n in zf.namelist() if n.startswith("screenshots/"))))
        assert picture.width() == 1600   # scaled down

    friends = tmp_path / "bob" / "friends"
    result = import_share(bob, path, BOB, friends)
    assert result.status == "ok" and result.sender == "Alice" and result.characters == 1 and result.invalid == 0
    [char] = Repository(bob.conn).list_characters()
    assert char.is_friend and char.owner_name == "Alice" and char.full_name == "Blind Bullseye"
    fid = char.character_id
    for table in ("events", "sessions", "positions", "screenshots", "character_stats", "professions", "recipes"):
        assert count(bob, table, fid) == count(alice, table, cid), table
    path_row = bob.conn.execute("SELECT file_path, file_match FROM screenshots WHERE file_path IS NOT NULL").fetchone()
    assert path_row["file_match"] == "shared" and os.path.isfile(path_row["file_path"])
    assert str(friends / ALICE) in path_row["file_path"]

    # The same file again: nothing to do.
    assert import_share(bob, path, BOB, friends).status == "unchanged"


def test_newer_file_replaces_everything(alice, bob, tmp_path, monkeypatch):
    cid = alice_char(alice)
    friends = tmp_path / "bob" / "friends"
    first = tmp_path / "1.fcshare"
    export_share(alice, first, ALICE, "Alice", {cid: ALL}, shot_ids(alice, cid))
    import_share(bob, first, BOB, friends)
    fid = bob.conn.execute("SELECT character_id FROM characters").fetchone()[0]

    import time as _time
    later = int(_time.time()) + 60
    monkeypatch.setattr("forever_chronicle.storage.share.time.time", lambda: later)
    second = tmp_path / "2.fcshare"
    export_share(alice, second, ALICE, "Alice R.", {cid: {"chronicle"}})   # routes, sessions, pictures withdrawn
    result = import_share(bob, second, BOB, friends)
    assert result.status == "ok"
    assert bob.conn.execute("SELECT character_id FROM characters").fetchone()[0] == fid   # same local ID
    assert count(bob, "positions", fid) == 0 and count(bob, "sessions", fid) == 0 and count(bob, "screenshots", fid) == 0
    assert count(bob, "events", fid) == count(alice, "events", cid)
    assert not (friends / ALICE).exists()
    assert Repository(bob.conn).owners()[0]["display_name"] == "Alice R."

    monkeypatch.setattr("forever_chronicle.storage.share.time.time", lambda: later + 60)
    third = tmp_path / "3.fcshare"
    export_share(alice, third, ALICE, "Alice", {})                          # character no longer shared
    import_share(bob, third, BOB, friends)
    assert count(bob, "characters") == 0 and count(bob, "events") == 0
    assert Repository(bob.conn).owners()[0]["characters"] == 0


def test_own_data_is_never_touched(alice, tmp_path):
    cid = alice_char(alice)
    path = tmp_path / "self.fcshare"
    export_share(alice, path, ALICE, "Alice", {cid: ALL})
    assert import_share(alice, path, ALICE, tmp_path / "f").status == "rejected"      # my own file
    events = count(alice, "events", cid)
    result = import_share(alice, path, BOB, tmp_path / "f")                          # same GUID from "someone else"
    assert result.skipped_characters == [GUID] and result.characters == 0
    assert count(alice, "events", cid) == events and count(alice, "characters") == 1
    with pytest.raises(ValueError):
        export_share(alice, path, ALICE, "Alice", {"not-mine": ALL})


def test_friends_are_not_exported_again(alice, bob, tmp_path):
    cid = alice_char(alice)
    path = tmp_path / "a.fcshare"
    export_share(alice, path, ALICE, "Alice", {cid: ALL})
    import_share(bob, path, BOB, tmp_path / "friends")
    fid = bob.conn.execute("SELECT character_id FROM characters").fetchone()[0]
    backup = tmp_path / "bob.jsonl"
    export_jsonl(bob, backup)
    recs = [json.loads(line) for line in backup.read_text(encoding="utf-8").splitlines()[1:]]
    assert recs and not [r for r in recs if r["record_type"] == "character" or "character" in r]
    with pytest.raises(ValueError):
        export_share(bob, tmp_path / "b.fcshare", BOB, "Bob", {fid: ALL})


def test_remove_friend(alice, bob, tmp_path):
    cid = alice_char(alice)
    path = tmp_path / "a.fcshare"
    friends = tmp_path / "friends"
    export_share(alice, path, ALICE, "Alice", {cid: ALL}, shot_ids(alice, cid))
    import_share(bob, path, BOB, friends)
    assert (friends / ALICE).is_dir()
    remove_friend(bob, Repository(bob.conn).owners()[0]["owner_id"], friends)
    assert count(bob, "characters") == 0 and count(bob, "owners") == 0 and count(bob, "events") == 0
    assert not (friends / ALICE).exists()


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def header(**extra):
    h = {"record_type": "header", "format": "forever-chronicle", "format_version": 1, "kind": "share",
         "share_id": ALICE, "sender": "Mallory", "created_at": 100, "characters": {"Player-9": ["chronicle"]}}
    h.update(extra)
    return json.dumps(h)


def test_hostile_share_files(bob, tmp_path):
    friends = tmp_path / "friends"
    char = json.dumps({"record_type": "character", "natural_key": "Player-9", "identity_quality": "guid",
                       "name": "Eve", "created_at": 1})
    shot = json.dumps({"record_type": "screenshot", "character": "Player-9", "screenshot_id": "s1", "seq": 1,
                       "trigger_type": "manual", "status": "confirmed"})
    gap = json.dumps({"record_type": "data_gap", "character": "Player-9", "stream": "events", "from_seq": 1,
                      "to_seq": 2, "detected_at": 1})
    evil = tmp_path / "evil.fcshare"
    _zip(evil, {"share.jsonl": "\n".join([header(), char, shot, gap]),
                "../../escape.jpg": b"x", "screenshots/../../escape2.jpg": b"x", "screenshots/s1.jpg": b"jpegdata"})
    result = import_share(bob, evil, BOB, friends)
    assert result.status == "partial" and result.characters == 1
    assert any("data_gap" in m for m in result.messages)                         # not allowed in share files
    assert not (tmp_path / "escape.jpg").exists() and not (tmp_path.parent / "escape2.jpg").exists()
    assert sorted(p.name for p in (friends / ALICE).iterdir()) == ["s1.jpg"]

    cases = {
        "not_zip.fcshare": None,
        "no_jsonl.fcshare": {"other.txt": "x"},
        "bad_share_id.fcshare": {"share.jsonl": header(share_id="../../x")},
        "backup_not_share.fcshare": {"share.jsonl": header(kind="backup")},
        "no_header.fcshare": {"share.jsonl": char},
    }
    for name, members in cases.items():
        p = tmp_path / name
        if members is None:
            p.write_bytes(b"definitely not a zip file")
        else:
            _zip(p, members)
        assert import_share(bob, p, BOB, friends).status == "rejected", name


def test_ui_friends(alice, tmp_path, monkeypatch, addon_fixture):
    """Window with my character and a friend's: grouped sidebar, my character first, all pages work for the
    friend, share dialog, removing the friend."""
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.config import AppConfig
    from forever_chronicle.ui.main_window import MainWindow
    from forever_chronicle.ui.share_dialog import ShareDialog
    from PySide6.QtCore import Qt

    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path / "home"))
    # A friend's database: the same fixture under another GUID and name.
    friend_db = Database(tmp_path / "friend" / "f.db", tmp_path / "friend" / "b")
    data = parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))
    chars = data["ForeverChronicleDB"]["characters"]
    char = chars.pop(GUID)
    char["info"]["guid"], char["info"]["name"] = "Player-4619-0FRIEND1", "Thrall"
    chars["Player-4619-0FRIEND1"] = char
    SavedVariablesImporter(friend_db).import_data(data, "friend")
    share = tmp_path / "thrall.fcshare"
    fcid = friend_db.conn.execute("SELECT character_id FROM characters").fetchone()[0]
    export_share(friend_db, share, BOB, "Bob", {fcid: {"chronicle", "routes", "sessions"}})
    friend_db.close()

    config = AppConfig(client_dir=str(tmp_path / "missing"))
    ctx = AppContext(config, alice)
    ctx._client_searched = True
    config.last_character = None
    window = MainWindow(ctx)
    friends_page = next(p for p in window.pages if p.title_key == "tab.friends")
    friends_page.import_file(share)
    assert "Thrall" not in friends_page.message.text() and "Bob" in friends_page.message.text()
    assert friends_page.friends.rowCount() == 1 and friends_page.friends.item(0, 1).text() == "1"

    texts = [window.characters.item(i).text() for i in range(window.characters.count())]
    assert texts[0] == "Meine Charaktere" and "Bob" in texts and window.characters.count() == 4
    assert window.char_name.text() == "Blind Bullseye"                     # my own character stays selected
    friend_row = next(i for i in range(window.characters.count())
                      if (c := window.characters.item(i).data(Qt.ItemDataRole.UserRole)) and c.is_friend)
    window.characters.setCurrentRow(friend_row)
    assert window.char_name.text() == "Thrall Bullseye" and "Charakter von Bob" in window.char_details.text()
    for i in range(window.tabs.count()):                                  # every page works for a friend
        window.tabs.setCurrentIndex(i)

    # A new window (app start) opens on my character even if the friend's was selected last.
    assert config.last_character != alice_char(alice)
    window.close()
    window = MainWindow(ctx)
    assert window.char_name.text() == "Blind Bullseye"

    dialog = ShareDialog(ctx)
    assert dialog.tree.topLevelItemCount() == 1                           # only my own characters
    top = dialog.tree.topLevelItem(0)
    top.setCheckState(0, Qt.CheckState.Checked)
    assert dialog.selection() == {alice_char(alice): ALL}
    assert dialog.shots.count() >= 1 and not dialog.picked_screenshots()  # nothing pre-picked
    # A click on a picture selects it, another click deselects it (no separate checkbox).
    from PySide6.QtTest import QTest
    dialog.show()
    item = dialog.shots.item(0)
    assert item.data(Qt.ItemDataRole.CheckStateRole) is None   # no checkbox drawn
    center = dialog.shots.visualItemRect(item).center()
    QTest.mouseClick(dialog.shots.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert len(dialog.picked_screenshots()) == 1 and "1 Screenshots" in dialog.summary.text()
    # Selection survives a change of the character list (the list is rebuilt).
    dialog._tree_changed()
    assert len(dialog.picked_screenshots()) == 1
    QTest.mouseClick(dialog.shots.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert not dialog.picked_screenshots() and "0 Screenshots" in dialog.summary.text()
    dialog.close()

    friends_page = next(p for p in window.pages if p.title_key == "tab.friends")
    friends_page.refresh()
    owner_id = ctx.repo.owners()[0]["owner_id"]
    ctx.remove_friend(owner_id)
    assert window.characters.count() == 1
    window.close()
