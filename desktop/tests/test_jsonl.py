import json
import os
import time

import pytest

from forever_chronicle.importing.sv_importer import SavedVariablesImporter
from forever_chronicle.storage.database import KEEP_BACKUPS, Database
from forever_chronicle.storage.jsonl import FORMAT_VERSION, RECORD_TYPES, export_jsonl, import_jsonl
from forever_chronicle.wow.lua_parser import parse_saved_variables

TABLES = sorted({rt.table for rt in RECORD_TYPES})


@pytest.fixture
def filled(db, addon_fixture):
    """The addon fixture imported, plus data the fixture does not contain (entrance, gap, screenshot path)."""
    data = parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))
    data["ForeverChronicleDB"]["entrances"] = {"389": {"mapID": 1413, "x": 0.45, "y": 0.6, "source": "walked"}}
    SavedVariablesImporter(db).import_data(data, "fixture")
    cid = db.conn.execute("SELECT character_id FROM characters").fetchone()[0]
    with db.transaction():
        db.conn.execute("INSERT INTO data_gaps (character_id, stream, from_seq, to_seq, detected_at) "
                        "VALUES (?, 'events', 1, 3, 100)", (cid,))
        db.conn.execute("UPDATE screenshots SET file_path = 'C:/old-pc/WoWScrnShot_1.jpg', file_match = 'matched'")
    return db


@pytest.fixture
def other_db(tmp_path):
    database = Database(tmp_path / "other" / "other.db", tmp_path / "other" / "backups")
    yield database
    database.close()


def counts(db):
    return {t: db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_round_trip_to_another_computer(filled, other_db, tmp_path):
    path = tmp_path / "export.jsonl"
    exported = export_jsonl(filled, path)
    recs = lines(path)
    assert recs[0]["record_type"] == "header" and recs[0]["format_version"] == FORMAT_VERSION
    assert exported.records == len(recs) - 1 and exported.characters == 1
    assert all("character_id" not in r and "import_id" not in r and "gap_id" not in r for r in recs)
    assert all("file_path" not in r for r in recs if r["record_type"] == "screenshot")  # local to the old PC
    assert {r["character"] for r in recs if "character" in r} == {"Player-4619-0112A417"}

    result = import_jsonl(other_db, path)
    assert result.status == "ok" and result.invalid == 0 and result.inserted == exported.records
    assert counts(other_db) == counts(filled)
    a = filled.conn.execute("SELECT character_id, name, natural_key FROM characters").fetchone()
    b = other_db.conn.execute("SELECT character_id, name, natural_key FROM characters").fetchone()
    assert (a["name"], a["natural_key"]) == (b["name"], b["natural_key"]) and a["character_id"] != b["character_id"]
    assert other_db.conn.execute("SELECT file_path FROM screenshots").fetchone()[0] is None
    run = other_db.conn.execute("SELECT * FROM import_runs").fetchone()
    assert run["source_type"] == "jsonl" and run["status"] == "ok"

    # Importing the same file again changes nothing.
    again = import_jsonl(other_db, path)
    assert again.inserted == 0 and again.updated == 0 and again.unchanged == exported.records
    assert counts(other_db) == counts(filled)


def test_merge_keeps_the_more_complete_record(filled, other_db, tmp_path):
    path = tmp_path / "export.jsonl"
    export_jsonl(filled, path)
    import_jsonl(other_db, path)
    # The other computer has older data: a session still open, a shorter standing-still point.
    with other_db.transaction():
        other_db.conn.execute("UPDATE sessions SET ended_at = NULL, end_reason = 'open'")
        other_db.conn.execute("UPDATE positions SET until_at = NULL")
        other_db.conn.execute("UPDATE characters SET level = 99, last_seen_at = 1")
    result = import_jsonl(other_db, path)
    assert result.updated > 0 and result.inserted == 0
    assert other_db.conn.execute("SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL").fetchone()[0] == 0
    assert other_db.conn.execute("SELECT COUNT(*) FROM positions WHERE until_at IS NOT NULL").fetchone()[0] == \
        filled.conn.execute("SELECT COUNT(*) FROM positions WHERE until_at IS NOT NULL").fetchone()[0]
    assert other_db.conn.execute("SELECT level FROM characters").fetchone()[0] == 22   # newer last_seen_at wins

    # Data that is newer on this computer is kept.
    with other_db.transaction():
        other_db.conn.execute("UPDATE characters SET level = 30, last_seen_at = 9999999999")
    import_jsonl(other_db, path)
    assert other_db.conn.execute("SELECT level FROM characters").fetchone()[0] == 30


def test_invalid_rows_are_reported_not_fatal(other_db, tmp_path):
    path = tmp_path / "broken.jsonl"
    header = {"record_type": "header", "format": "forever-chronicle", "format_version": 1}
    char = {"record_type": "character", "natural_key": "Player-1", "identity_quality": "guid", "name": "Ann",
            "created_at": 5, "last_seen_at": 10}
    rows = [
        json.dumps(header),
        "{not json",
        json.dumps(char),
        json.dumps({"record_type": "event", "character": "Player-1", "event_id": "e1", "seq": 1,
                    "event_type": "level_up", "occurred_at": 100, "payload_json": "{}", "schema_version": 1}),
        json.dumps({"record_type": "event", "character": "Player-404", "event_id": "e2", "seq": 2,
                    "event_type": "level_up", "occurred_at": 101, "payload_json": "{}", "schema_version": 1}),
        json.dumps({"record_type": "event", "character": "Player-1", "event_id": "e3", "seq": "three",
                    "event_type": "level_up", "occurred_at": 102, "payload_json": "{}", "schema_version": 1}),
        json.dumps({"record_type": "event", "character": "Player-1", "seq": 4}),
        json.dumps({"record_type": "event", "character": "Player-1", "event_id": "e5", "seq": 5}),  # NOT NULL
        json.dumps({"record_type": "hologram", "anything": 1}),
        "",
    ]
    path.write_text("\n".join(rows), encoding="utf-8")
    result = import_jsonl(other_db, path)
    assert result.status == "partial" and result.inserted == 2 and result.invalid == 5 and result.unknown == 1
    assert result.messages[0].startswith("line 2:")
    assert any("line 5" in m and "unknown character" in m for m in result.messages)
    assert any("line 6" in m and "seq" in m for m in result.messages)
    assert any("line 7" in m and "event_id" in m for m in result.messages)
    assert other_db.conn.execute("SELECT event_id FROM events").fetchall()[0][0] == "e1"


@pytest.mark.parametrize("first_line,reason", [
    ('{"record_type": "event"}', "header"),
    ('{"record_type": "header", "format": "something-else", "format_version": 1}', "header"),
    ('{"record_type": "header", "format": "forever-chronicle", "format_version": 99}', "newer"),
])
def test_rejected_files(other_db, tmp_path, first_line, reason):
    path = tmp_path / "x.jsonl"
    path.write_text(first_line + "\n", encoding="utf-8")
    result = import_jsonl(other_db, path)
    assert result.status == "rejected" and reason in result.messages[0]
    assert other_db.conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 0


def test_backup_before_import_and_retention(filled, other_db, tmp_path):
    path = tmp_path / "export.jsonl"
    export_jsonl(filled, path)
    result = import_jsonl(other_db, path)
    assert result.backup is not None and result.backup.exists() and "before-jsonl-import" in result.backup.name

    for i in range(KEEP_BACKUPS + 2):
        other_db.backup(f"manual{i}")
        time.sleep(0.01)
    assert len(other_db.backups()) <= KEEP_BACKUPS


def test_daily_backup(other_db):
    assert other_db.backups() == []
    first = other_db.backup_if_older(24 * 3600, "daily")
    assert first is not None and other_db.backups() == [first]
    assert other_db.backup_if_older(24 * 3600, "daily") is None       # already one today
    old = time.time() - 2 * 24 * 3600
    os.utime(first, (old, old))
    assert other_db.backup_if_older(24 * 3600, "daily") is not None   # older than a day: back up again


def test_restore_backup(filled, tmp_path):
    db = filled
    before_counts = counts(db)
    chosen = db.backup("manual")
    with db.transaction():
        db.conn.execute("DELETE FROM events")
        db.conn.execute("UPDATE characters SET name = 'Changed'")
    previous = db.restore(chosen)
    assert counts(db) == before_counts and db.conn.execute("SELECT name FROM characters").fetchone()[0] == "Blind"
    assert previous is not None and "before-restore" in previous.name
    # The state before the restore can itself be restored.
    db.restore(previous)
    assert db.conn.execute("SELECT name FROM characters").fetchone()[0] == "Changed"


def test_restore_keeps_the_chosen_backup_when_rotating(other_db):
    paths = []
    for i in range(KEEP_BACKUPS):
        paths.append(other_db.backup(f"manual{i}"))
        time.sleep(1.01 if i == 0 else 0)  # distinct timestamps: the first one is the oldest
    oldest = other_db.backups()[0]
    other_db.restore(oldest)
    assert oldest.exists(), "the chosen backup must not be removed by the backup made before restoring"


def test_restore_migrates_older_backups_and_refuses_bad_files(other_db, tmp_path):
    import sqlite3
    from forever_chronicle.storage.database import MIGRATIONS, SCHEMA_VERSION
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    for script in MIGRATIONS[:4]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 4")
    conn.execute("INSERT INTO characters (character_id, natural_key, identity_quality, name, created_at) "
                 "VALUES ('c1', 'Player-1', 'guid', 'Oldie', 1)")
    conn.commit()
    conn.close()
    other_db.restore(old)
    assert other_db.version == SCHEMA_VERSION
    assert other_db.conn.execute("SELECT name FROM characters").fetchone()[0] == "Oldie"
    assert other_db.conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] == 0  # migrated tables exist

    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database at all" * 100)
    newer = tmp_path / "newer.db"
    c = sqlite3.connect(newer)
    c.execute("CREATE TABLE characters (x)")
    c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    c.commit()
    c.close()
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    for bad, reason in ((garbage, "not a Forever Chronicle"), (newer, "newer"), (empty, "not a Forever Chronicle")):
        with pytest.raises(ValueError, match=reason):
            other_db.restore(bad)
    assert other_db.conn.execute("SELECT name FROM characters").fetchone()[0] == "Oldie"  # untouched


def test_backup_names_are_unique_and_labelled(other_db):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from forever_chronicle.ui.pages.import_page import backup_label
    a, b = other_db.backup("manual"), other_db.backup("manual")
    assert a != b and a.exists() and b.exists()           # same second: the second one gets a counter
    assert backup_label(b).endswith("·  manuell") and backup_label(a).endswith("·  manuell")
    from pathlib import Path
    assert backup_label(Path("chronicle-20261014-153000-before-migration-4-to-7.db")) == \
        "14.10.2026 15:30  ·  vor Datenbank-Update"
    assert backup_label(Path("weird.db")) == "weird.db"
