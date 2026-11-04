"""Professions are only events now: learned and new rank (the cinematic plays both). Recipes, the skill and the
profession page are gone; what older addon files and databases still hold of them is left out."""

import sqlite3

from conftest import unpack_all
from forever_chronicle.domain import event_types
from forever_chronicle.importing.sv_importer import SavedVariablesImporter
from forever_chronicle.storage.database import MIGRATIONS, SCHEMA_VERSION, Database
from forever_chronicle.storage.repository import EventRow, Repository

GUID = "Player-4619-0112A417"


def event(kind, payload):
    return EventRow("c", "e", kind, 0, None, None, None, None, None, payload)


def test_profession_event_texts():
    assert event_types.describe(event("profession_rank", {"name": "Leatherworking", "maxRank": 225})) == \
        "Leatherworking: Experte"
    assert event_types.describe(event("profession_rank", {"name": "Mining", "maxRank": 375})) == "Mining: 375"
    assert event_types.describe(event("profession_learned", {"name": "Fishing"})) == "Beruf erlernt: Fishing"


def test_old_addon_files_keep_only_the_profession_events(db, sv_data):
    data = unpack_all(sv_data)["ForeverChronicleDB"]
    char = data["characters"][GUID]
    records = char["streams"]["events"]["records"]
    last = records[-1]
    seq = last["seq"]
    old = [dict(last, id="old-recipe", seq=seq + 1, type="recipe_learned", data={"recipeID": 2149}),
           dict(last, id="old-rank", seq=seq + 2, type="profession_rank",
                data={"name": "Leatherworking", "maxRank": 225})]
    records += old
    char["streams"]["events"]["nextSeq"] = seq + 3
    char["snapshots"]["professions"] = {"baseline": True, "list": [
        {"skillLine": 165, "name": "Leatherworking", "rank": 126, "maxRank": 150, "kind": "primary",
         "recipes": {"status": "complete", "list": ["2881,2550,134252,1,Light Leather"]}}]}
    data["diagnostics"]["capabilities"]["recipes"] = {"status": "confirmed", "confirmedAt": 1}

    result = SavedVariablesImporter(db).import_data(sv_data, "old addon")
    assert result.status == "ok" and result.invalid == 0 and result.gaps == 0
    repo = Repository(db.conn)
    types = [r[0] for r in db.conn.execute("SELECT event_type FROM events")]
    assert "recipe_learned" not in types and "profession_rank" in types
    assert "recipes" not in [c["capability"] for c in repo.capabilities()]
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not tables & {"professions", "recipes", "recipe_categories"}


def test_migration_removes_the_profession_data(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for script in MIGRATIONS[:13]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version = 13")
    conn.execute("INSERT INTO characters (character_id, natural_key, identity_quality, name, created_at) "
                 "VALUES ('c1', 'Player-1', 'guid', 'Oldie', 1)")
    for event_id, kind in (("e1", "recipe_learned"), ("e2", "profession_learned")):
        conn.execute("INSERT INTO events (character_id, event_id, seq, event_type, occurred_at, payload_json, "
                     "schema_version) VALUES ('c1', ?, 1, ?, 1, '{}', 2)", (event_id, kind))
    conn.execute("INSERT INTO screenshot_events VALUES ('c1', 's1', 'e1')")
    conn.execute("INSERT INTO recipes (character_id, skill_line, recipe_id, name) VALUES ('c1', 165, 1, 'x')")
    conn.execute("INSERT INTO client_capabilities (capability, status, updated_at) VALUES ('recipes', 'confirmed', 1)")
    conn.commit()
    conn.close()

    db = Database(path, tmp_path / "backups")
    try:
        assert db.version == SCHEMA_VERSION
        assert [r[0] for r in db.conn.execute("SELECT event_type FROM events")] == ["profession_learned"]
        assert db.conn.execute("SELECT COUNT(*) FROM screenshot_events").fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM client_capabilities").fetchone()[0] == 0
        tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not tables & {"professions", "recipes", "recipe_categories"}
    finally:
        db.close()
