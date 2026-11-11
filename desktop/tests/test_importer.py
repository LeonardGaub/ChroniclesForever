import copy
import os
import time

import pytest
from conftest import unpack_all

from forever_chronicle.importing.sv_importer import SavedVariablesImporter, check_gap, prepare, read_saved_file
from forever_chronicle.storage.database import Database
from forever_chronicle.storage.repository import PositionPoint, Repository

GUID = "Player-4619-0112A417"


@pytest.fixture
def data(sv_data):
    return unpack_all(sv_data)


def character_id(db):
    return db.conn.execute("SELECT character_id FROM characters").fetchone()[0]


def test_import_addon_fixture(db, data):
    result = SavedVariablesImporter(db).import_data(data, "fixture")
    assert result.status == "ok", result.messages
    assert result.characters == 1
    assert result.imported == 6 and result.duplicates == 0 and result.invalid == 0
    assert result.sessions == 2 and result.gaps == 0

    repo = Repository(db.conn)
    [char] = repo.list_characters()
    assert char.name == "Blind" and char.class_file == "HUNTER" and char.level == 22  # level at the last login
    events = repo.events(char.character_id)
    assert [e.event_type for e in reversed(events)] == [
        "session_started", "quest_completed", "player_died", "level_up", "achievement_earned", "session_started"]
    death = next(e for e in events if e.event_type == "player_died")
    assert death.zone_name == "Ragefire Chasm" and death.map_id is None
    assert death.payload["killer"] == "Taragaman the Hungerer" and death.payload["damage"] == 412  # the death recap
    quest = next(e for e in events if e.event_type == "quest_completed")
    assert quest.payload["title"] == "The Runaway Shipment" and quest.x == pytest.approx(0.4403)

    sessions = repo.sessions(char.character_id)
    first = sessions[-1]
    assert first["end_reason"] == "logout" and first["reload_count"] == 1 and first["played_total_seconds"] >= 74113  # re-based at the level-up


def test_reimport_is_idempotent(db, data):
    importer = SavedVariablesImporter(db)
    importer.import_data(data, "fixture")
    again = importer.import_data(copy.deepcopy(data), "fixture")
    assert again.imported == 0 and again.duplicates == 6 and again.gaps == 0
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 6
    assert db.conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 1


def test_gap_detected_when_records_were_dropped(db, data):
    importer = SavedVariablesImporter(db)
    first = copy.deepcopy(data)
    records = first["ForeverChronicleDB"]["characters"][GUID]["streams"]["events"]["records"]
    del records[2:]                              # first import sees seq 1-2
    importer.import_data(first, "fixture")
    second = copy.deepcopy(data)
    records = second["ForeverChronicleDB"]["characters"][GUID]["streams"]["events"]["records"]
    del records[:4]                              # later file only has seq 5-6: 3-4 were dropped
    result = importer.import_data(second, "fixture")
    assert result.gaps == 1
    gap = Repository(db.conn).gaps(character_id(db))[0]
    assert (gap["from_seq"], gap["to_seq"]) == (3, 4)


def test_invalid_records_are_skipped_not_fatal(db, data):
    records = data["ForeverChronicleDB"]["characters"][GUID]["streams"]["events"]["records"]
    records.append({"id": 5, "type": None})
    records.append("garbage")
    result = SavedVariablesImporter(db).import_data(data, "fixture")
    assert result.status == "partial" and result.invalid == 2 and result.imported == 6


def test_newer_schema_is_rejected(db, data):
    data["ForeverChronicleDB"]["schemaVersion"] = 99
    result = SavedVariablesImporter(db).import_data(data, "fixture")
    assert result.status == "rejected"
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_import_file_falls_back_to_backup(db, tmp_path, addon_fixture):
    sv = tmp_path / "ForeverChronicle.lua"
    sv.write_text("ForeverChronicleDB = { [\"schemaVersion\"] = 1, ", encoding="utf-8")  # truncated
    (tmp_path / "ForeverChronicle.lua.bak").write_text(addon_fixture.read_text(encoding="utf-8"), encoding="utf-8")
    result = SavedVariablesImporter(db).import_file(sv, "131324136#1")
    assert result.used_backup and result.imported == 6


def test_import_file_unreadable_is_reported(db, tmp_path):
    sv = tmp_path / "ForeverChronicle.lua"
    sv.write_text("ForeverChronicleDB = os.execute('x')", encoding="utf-8")
    result = SavedVariablesImporter(db).import_file(sv)
    assert result.status == "failed"
    assert Repository(db.conn).import_runs()[0]["status"] == "failed"


def test_unchanged_file_is_skipped(db, tmp_path, addon_fixture):
    sv = tmp_path / "ForeverChronicle.lua"
    sv.write_bytes(addon_fixture.read_bytes())
    importer = SavedVariablesImporter(db)
    assert importer.import_file(sv).imported == 6
    assert importer.import_file(sv, skip_unchanged=True).status == "unchanged"


def positions_of(db):
    return Repository(db.conn).positions(character_id(db))


def test_reimport_writes_only_new_and_grown_points(db, data):
    """Points before the newest one imported last time are left alone; that one (it may have grown) and the new
    ones are written."""
    stream = data["ForeverChronicleDB"]["characters"][GUID]["streams"]["positions"]
    full = list(stream["records"])
    t = int(full[9].split(",")[0])
    stream["records"], stream["nextSeq"] = full[:9] + [f"{t},1413,0.4403,0.5913,,,"], 11   # the newest stands still
    importer = SavedVariablesImporter(db)
    importer.import_data(copy.deepcopy(data), "first")
    first = positions_of(db)[0]
    db.conn.execute("UPDATE positions SET until_at = 1 WHERE occurred_at = ?", (first.time,))   # marks: not rewritten

    stream["records"], stream["nextSeq"] = full[:9] + [f"{t},1413,0.4403,0.5913,{t + 60},,"] + full[10:], 16
    result = importer.import_data(copy.deepcopy(data), "second")
    points = {p.time: p for p in positions_of(db)}
    assert result.positions == 15 and len(points) == 15 and result.gaps == 0
    assert points[t].until == t + 60, "the grown point was updated"
    assert points[first.time].until == 1, "older points were not written again"


def test_reimport_writes_all_points_when_the_stored_seq_is_not_ours(db, data):
    """A last_seq without its point in the database (e.g. merged from another PC's export) is not trusted."""
    importer = SavedVariablesImporter(db)
    importer.import_data(copy.deepcopy(data), "first")
    cid = character_id(db)
    newest = positions_of(db)[-1]
    db.conn.execute("DELETE FROM positions WHERE occurred_at = ?", (newest.time,))
    db.conn.execute("UPDATE positions SET until_at = 1")
    importer.import_data(copy.deepcopy(data), "second")
    assert len(positions_of(db)) == 15 and all(p.until != 1 for p in positions_of(db))
    # A restarted stream (seq below the stored one) is written in full as well.
    Repository(db.conn).set_last_seq(cid, "positions", 500)
    db.conn.execute("UPDATE positions SET until_at = 1")
    importer.import_data(copy.deepcopy(data), "third")
    assert all(p.until != 1 for p in positions_of(db))


def test_prepared_file_imports_like_the_raw_data(db, tmp_path, addon_fixture, sv_data):
    """read_saved_file parses and prepares (the background import does that in a worker thread); import_read gives
    the same result as import_data on the raw data."""
    sv = tmp_path / "ForeverChronicle.lua"
    sv.write_bytes(addon_fixture.read_bytes())
    os.utime(sv, (time.time() - 60, time.time() - 60))    # not just written: no wait for the game to finish
    read = read_saved_file(sv, "131324136#1")
    assert read.variables and not read.unchanged and read.size == sv.stat().st_size
    stream = read.variables["ForeverChronicleDB"]["characters"][GUID]["streams"]["positions"]
    assert all(isinstance(p, PositionPoint) for p in stream["records"])
    prepared = SavedVariablesImporter(db).import_read(read)
    other = tmp_path / "other"
    other.mkdir()
    raw_db = Database(other / "test.db", other / "backups")
    try:
        raw = SavedVariablesImporter(raw_db).import_data(sv_data, str(sv), "131324136#1")
        assert positions_of(db) == positions_of(raw_db)
    finally:
        raw_db.close()
    assert {**vars(prepared), "import_id": None} == {**vars(raw), "import_id": None}
    assert read_saved_file(sv, last=SavedVariablesImporter(db).last_seen(sv)).unchanged


def test_route_archive_points_are_imported(db, data):
    char = data["ForeverChronicleDB"]["characters"][GUID]
    char["streams"]["routeArchive"] = {"nextSeq": 2, "records": [
        "1791000000,1413,0.1000,0.1000,,,;1791000100,1413,0.1200,0.1000,1791000200,M,;bad"]}
    prepared = prepare(copy.deepcopy(data))
    result = SavedVariablesImporter(db).import_data(prepared, "fixture")
    points = positions_of(db)
    assert result.invalid == 1 and len(points) == 17
    assert points[1].time == 1791000100 and points[1].mounted and points[1].until == 1791000200


@pytest.mark.parametrize("previous,seqs,gap,new_last,reset", [
    (None, [1, 2, 3], None, 3, False),
    (None, [5, 6], (1, 4), 6, False),
    (3, [2, 3, 4, 5], None, 5, False),
    (3, [7, 8], (4, 6), 8, False),
    (10, [1, 2], None, 2, True),
    (4, [], None, 4, False),
])
def test_check_gap(previous, seqs, gap, new_last, reset):
    result = check_gap(previous, seqs)
    assert (result.gap, result.new_last, result.reset) == (gap, new_last, reset)


def test_a_death_recorded_twice_reads_as_one(db):
    """Addons up to 0.16.0 recorded a death twice where the server sent PLAYER_DEAD twice: the first event has the
    killer, the second (0-2 s later) the corpse run. Both read as one death; real deaths stay apart."""
    repo = Repository(db.conn)
    db.conn.execute("PRAGMA foreign_keys = OFF")      # no character or import rows needed for this

    def death(seq, t, **data):
        repo.insert_event("c", {"id": f"d{seq}", "seq": seq, "type": "player_died", "time": t, "data": data}, 1, 2)

    death(1, 1000, killer="Bruuz", damage=55)
    death(2, 1002, releasedAt=1002, revive="corpse", revivedAt=1060)        # the echo
    death(3, 1100, killer="Hogger")                                         # a real death, later
    death(4, 1200, killer="Raptor", revivedAt=1201, revive="self")          # revived at once (ankh) ...
    death(5, 1202, killer="Raptor")                                         # ... and died again: a death
    deaths = repo.events("c", types=("player_died",))
    assert [e.event_id for e in deaths] == ["d5", "d4", "d3", "d1"], "the echo is folded into its death"
    first = deaths[-1].payload
    assert first["killer"] == "Bruuz" and first["releasedAt"] == 1002 and first["revivedAt"] == 1060, first
    assert repo.count_events("c", "player_died") == 4, "the death count leaves the echo out"
    imported = repo.events_of_imports([1])
    assert [e.event_id for e in imported] == ["d1", "d3", "d4", "d5"]
