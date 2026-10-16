"""Friends' characters from the cloud folder: imported read-only under the friend, skipped when unchanged, replaced
by a newer file (stable IDs, no duplicates), removed when the file is gone; my own file, code and old desktop-share
friends are left alone."""

import json
import os
import time
from pathlib import Path

import pytest

from forever_chronicle import cloud_sync
from forever_chronicle.importing.friend_importer import import_friends

REPO = Path(__file__).resolve().parents[2]
SHARE_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle_Share.lua"   # written by tests/addon (npm test)


@pytest.fixture
def cloud(tmp_path):
    if not SHARE_FIXTURE.exists():
        pytest.skip("run npm test in tests/addon first (writes tests/fixtures/ForeverChronicle_Share.lua)")
    folder = tmp_path / "sync"
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps({"cloud": str(tmp_path / "cloud"), "client": str(tmp_path / "WoW"),
                                                    "shareId": "a" * 32}), encoding="utf-8")
    (tmp_path / "cloud" / "players").mkdir(parents=True)
    return cloud_sync.find_setup(folder)


def friend_text(name="Bob"):
    text = SHARE_FIXTURE.read_text(encoding="utf-8")
    renamed = text.replace('\n\t["name"] = "Blind",', f'\n\t["name"] = "{name}",', 1)
    assert renamed != text or name == "Blind"
    return renamed


def put(setup, file_name, text, age=0):
    path = Path(setup.cloud) / "players" / file_name
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def friends(db):
    return [c for c in db_characters(db) if c.is_friend]


def db_characters(db):
    from forever_chronicle.storage.repository import Repository
    return Repository(db.conn).list_characters()


def count(db, sql, *args):
    return db.conn.execute(sql, args).fetchone()[0]


def test_friends_from_the_cloud(db, cloud):
    put(cloud, "Blind-aaaaaaaa-282b7857.lua", friend_text("Blind"))            # mine: never a friend
    path = put(cloud, "Bob-ffffffff-0badc0de.lua", friend_text(), age=60)
    put(cloud, f"{'e' * 32}-00000001.lua", 'ForeverChronicleShareDB = { name = "x" } os.exit(1)')
    db.conn.execute("INSERT INTO owners (share_id, display_name) VALUES (?, 'Gigel')", ("9" * 32,))  # old share
    db.conn.commit()

    result = import_friends(db, cloud)
    assert result.imported == ["Bob"] and result.friends == 2 and len(result.failed) == 1
    chars = friends(db)
    assert chars and {c.owner_name for c in chars} == {"Bob"}
    assert count(db, "SELECT COUNT(*) FROM characters WHERE owner_id IS NULL") == 0, "my file is not imported"
    ids = {c.character_id for c in chars}
    events = count(db, "SELECT COUNT(*) FROM events e JOIN characters c USING (character_id) "
                       "WHERE c.owner_id IS NOT NULL")
    assert events > 0
    assert count(db, "SELECT COUNT(*) FROM data_gaps") == 0, "a friend's file holds only the newest records"
    assert count(db, "SELECT COUNT(*) FROM import_runs WHERE source_type = 'friend' AND account = 'Bob'") == 1

    # Unchanged: skipped. Newer (renamed in game): replaced, same characters, no duplicates.
    assert import_friends(db, cloud).unchanged == 1
    path.write_text(friend_text("Bobby"), encoding="utf-8")
    result = import_friends(db, cloud)
    assert result.imported == ["Bobby"]
    chars = friends(db)
    assert {c.character_id for c in chars} == ids and {c.owner_name for c in chars} == {"Bobby"}
    assert count(db, "SELECT COUNT(*) FROM events e JOIN characters c USING (character_id) "
                     "WHERE c.owner_id IS NOT NULL") == events

    # The file is gone from the cloud: the friend goes; the old desktop-share friend stays.
    path.unlink()
    result = import_friends(db, cloud)
    assert result.removed == ["Bobby"] and friends(db) == []
    assert count(db, "SELECT COUNT(*) FROM events") == 0
    assert count(db, "SELECT COUNT(*) FROM owners") == 1


def test_cloud_folder_missing_keeps_friends(db, cloud):
    put(cloud, "Bob-ffffffff-0badc0de.lua", friend_text())
    import_friends(db, cloud)
    for f in (Path(cloud.cloud) / "players").iterdir():
        f.unlink()
    (Path(cloud.cloud) / "players").rmdir()
    result = import_friends(db, cloud)
    assert result.removed == [] and friends(db), "OneDrive offline is not 'every friend left'"


def test_replaces_the_same_character_from_an_old_share_file(db, cloud):
    """Before 2026-10-14 friends came as desktop share files: the same character (natural key without "friend:")
    is replaced by the cloud one, and the old friend goes once they have no characters left. Mine stay."""
    conn = db.conn
    old = conn.execute("INSERT INTO owners (share_id, display_name) VALUES (?, 'Gigel')", ("9" * 32,)).lastrowid
    for cid, key, owner in (("old-alt", "Player-4619-0ALT0001", old), ("mine", "Player-4619-0MINE001", None)):
        conn.execute("INSERT INTO characters (character_id, natural_key, identity_quality, name, owner_id, created_at) "
                     "VALUES (?, ?, 'guid', 'X', ?, 0)", (cid, key, owner))
    conn.commit()
    put(cloud, "Bob-ffffffff-0badc0de.lua", friend_text())
    import_friends(db, cloud)
    assert count(db, "SELECT COUNT(*) FROM characters WHERE character_id = 'old-alt'") == 0
    assert count(db, "SELECT COUNT(*) FROM owners WHERE display_name = 'Gigel'") == 0
    assert count(db, "SELECT COUNT(*) FROM characters WHERE natural_key = 'friend:ffffffff-0badc0de:"
                     "Player-4619-0ALT0001'") == 1
    assert count(db, "SELECT COUNT(*) FROM characters WHERE character_id = 'mine' AND owner_id IS NULL") == 1
