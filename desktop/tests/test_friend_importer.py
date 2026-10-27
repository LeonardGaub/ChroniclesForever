"""Friends' characters from the cloud folder: every other player's folder with dated addon copies is imported
read-only under that friend (newest copy per account), skipped when unchanged, added to by a newer copy (stable IDs,
no duplicates), removed when the folder is gone; my own folder and the old layout are left alone."""

import os
import time
from pathlib import Path

import pytest

from forever_chronicle.importing.friend_importer import import_friends

REPO = Path(__file__).resolve().parents[2]
ADDON_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle.lua"   # written by tests/addon (npm test)


@pytest.fixture
def cloud(tmp_path):
    if not ADDON_FIXTURE.exists():
        pytest.skip("run npm test in tests/addon first (writes tests/fixtures/ForeverChronicle.lua)")
    folder = tmp_path / "cloud"
    (folder / "players").mkdir(parents=True)          # the old friends sync's layout: never a friend
    (folder / "players" / "Bob-ffffffff-0badc0de.lua").write_text("ForeverChronicleShareDB = {}", encoding="utf-8")
    return folder


def put(cloud, player, text, stamp="2026-10-27_210000", pc="PC1", account="0badc0de", age=0):
    path = cloud / player / "addon" / account / f"ForeverChronicle_{stamp}_{pc}.lua"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def fixture_text():
    return ADDON_FIXTURE.read_text(encoding="utf-8")


def friends(db):
    from forever_chronicle.storage.repository import Repository
    return [c for c in Repository(db.conn).list_characters() if c.is_friend]


def count(db, sql, *args):
    return db.conn.execute(sql, args).fetchone()[0]


def test_friends_from_the_cloud(db, cloud):
    put(cloud, "Leon", fixture_text())                                  # mine: never a friend
    put(cloud, "Bob", fixture_text(), stamp="2026-10-26_200000", age=120)
    path = put(cloud, "Bob", fixture_text(), age=60)                    # the newest copy counts
    put(cloud, "Eve", 'ForeverChronicleDB = { name = "x" } os.exit(1)')

    result = import_friends(db, cloud, "leon")
    assert result.imported == ["Bob"] and result.friends == 2 and len(result.failed) == 1
    chars = friends(db)
    assert chars and {c.owner_name for c in chars} == {"Bob"}
    assert count(db, "SELECT COUNT(*) FROM characters WHERE owner_id IS NULL") == 0, "my folder is not imported"
    ids = {c.character_id for c in chars}
    events = count(db, "SELECT COUNT(*) FROM events e JOIN characters c USING (character_id) "
                       "WHERE c.owner_id IS NOT NULL")
    assert events > 0
    assert count(db, "SELECT COUNT(*) FROM data_gaps") == 0
    assert count(db, "SELECT COUNT(*) FROM import_runs WHERE source_type = 'friend' AND account = 'Bob'") == 1

    # Unchanged: skipped. A newer copy: added to, same characters, no duplicates.
    assert import_friends(db, cloud, "Leon").unchanged == 1
    put(cloud, "Bob", fixture_text() + "\n", stamp="2026-10-27_220000")
    result = import_friends(db, cloud, "Leon")
    assert result.imported == ["Bob"]
    assert {c.character_id for c in friends(db)} == ids
    assert count(db, "SELECT COUNT(*) FROM events e JOIN characters c USING (character_id) "
                     "WHERE c.owner_id IS NOT NULL") == events

    # The folder is gone from the cloud: the friend goes.
    for f in sorted((cloud / "Bob").rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    (cloud / "Bob").rmdir()
    result = import_friends(db, cloud, "Leon")
    assert result.removed == ["Bob"] and friends(db) == []
    assert count(db, "SELECT COUNT(*) FROM events") == 0
    assert count(db, "SELECT COUNT(*) FROM owners") == 0


def test_cloud_folder_missing_keeps_friends(db, cloud, tmp_path):
    put(cloud, "Bob", fixture_text())
    import_friends(db, cloud, "Leon")
    result = import_friends(db, tmp_path / "offline", "Leon")
    assert result.removed == [] and friends(db), "OneDrive offline is not 'every friend left'"
    assert import_friends(db, None, None).removed == []


def small_db(characters):
    """An addon file (unpacked streams) with characters {key: (events, point times)}."""
    parts = []
    for key, (events, points) in characters.items():
        evs = ",".join(f'{{["id"] = "{e}", ["type"] = "level_up", ["seq"] = {i + 1}, ["time"] = {1791900000 + i}}}'
                       for i, e in enumerate(events))
        pts = ",".join(f'"{t},1413,0.5000,0.5000,,,"' for t in points)
        parts.append(f'["{key}"] = {{["info"] = {{["key"] = "{key}", ["name"] = "{key}", ["level"] = 5}}, '
                     f'["streams"] = {{["events"] = {{["records"] = {{{evs}}}}}, '
                     f'["positions"] = {{["nextSeq"] = {len(points) + 1}, ["records"] = {{{pts}}}}}}}}}')
    return 'ForeverChronicleDB = {\n\t["schemaVersion"] = 2,\n\t["characters"] = {' + ",".join(parts) + "}}\n"


def test_a_newer_copy_adds_to_the_friends_history(db, cloud):
    """The addon trims old records: what the app had from older copies stays."""
    put(cloud, "Bob", small_db({"P-1": (["e1", "e2"], [1791900000, 1791900060])}), stamp="2026-10-27_100000", age=60)
    import_friends(db, cloud, "Leon")
    put(cloud, "Bob", small_db({"P-1": (["e2", "e3"], [1791900060, 1791900120]), "P-2": ([], [])}),
        stamp="2026-10-27_110000", age=30)
    assert import_friends(db, cloud, "Leon").imported == ["Bob"]
    key = "friend:player:bob:P-1"
    assert count(db, "SELECT COUNT(*) FROM events JOIN characters USING (character_id) WHERE natural_key = ?",
                 key) == 3, "e1 from the older copy stays, e2 is not doubled"
    assert count(db, "SELECT COUNT(*) FROM positions JOIN characters USING (character_id) WHERE natural_key = ?",
                 key) == 3

    # A character no longer in their files goes with everything.
    put(cloud, "Bob", small_db({"P-2": ([], [])}), stamp="2026-10-27_120000")
    import_friends(db, cloud, "Leon")
    assert count(db, "SELECT COUNT(*) FROM characters WHERE natural_key = ?", key) == 0
    assert count(db, "SELECT COUNT(*) FROM events") == 0 and count(db, "SELECT COUNT(*) FROM positions") == 0


def test_a_broken_friend_file_stops_only_that_friend(db, cloud):
    put(cloud, "Ann", 'ForeverChronicleDB = { schemaVersion = "2", characters = {} }')     # TypeError before
    put(cloud, "Cid", 'ForeverChronicleDB = { schemaVersion = 2, characters = { [{}] = 1 } }')
    put(cloud, "Dan", 'ForeverChronicleDB = { schemaVersion = 2, characters = { ["P-9"] = { info = { name = "X",'
                      ' realm = { "not a string" } } } } }')                                 # cannot be stored
    put(cloud, "Bob", small_db({"P-1": (["e1"], [])}))
    result = import_friends(db, cloud, "Leon")
    assert result.imported == ["Ann", "Bob"] and sorted(f.split(":")[0] for f in result.failed) == ["Cid", "Dan"]
    assert [c.name for c in friends(db)] == ["P-1"]


def test_a_rejected_copy_is_tried_again(db, cloud, monkeypatch):
    """A friend's newer addon is rejected; once the app supports it, the same copy is imported."""
    from forever_chronicle.importing import sv_importer
    put(cloud, "Bob", small_db({"P-1": (["e1"], [])}).replace('["schemaVersion"] = 2', '["schemaVersion"] = 3'))
    assert import_friends(db, cloud, "Leon").failed
    monkeypatch.setattr(sv_importer, "SUPPORTED_SCHEMA", 3)
    assert import_friends(db, cloud, "Leon").imported == ["Bob"] and friends(db)


def test_two_accounts_one_friend(db, cloud):
    put(cloud, "Bob", small_db({"P-1": (["e1"], [])}), account="00000001")
    put(cloud, "Bob", small_db({"P-2": (["e2"], [])}), account="00000002")
    import_friends(db, cloud, "Leon")
    assert sorted(c.name for c in friends(db)) == ["P-1", "P-2"]
    assert count(db, "SELECT COUNT(*) FROM owners") == 1
