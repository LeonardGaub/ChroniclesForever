import copy

import pytest

from forever_chronicle.importing.sv_importer import SavedVariablesImporter, check_gap
from forever_chronicle.storage.repository import Repository
from forever_chronicle.wow.lua_parser import parse_saved_variables

GUID = "Player-4619-0112A417"


@pytest.fixture
def data(addon_fixture):
    return parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))


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
    quest = next(e for e in events if e.event_type == "quest_completed")
    assert quest.payload["title"] == "The Runaway Shipment" and quest.x == pytest.approx(0.4403)

    sessions = repo.sessions(char.character_id)
    first = sessions[-1]
    assert first["end_reason"] == "logout" and first["reload_count"] == 1 and first["played_total_seconds"] == 74113


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
