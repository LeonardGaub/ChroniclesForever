"""Friends' screenshots: copied from <cloud>\\screenshots\\<player>\\<character>\\ into the app's own folder (same
sorting), linked to the friend's screenshot records, and removed again when the friend no longer shares them."""

from pathlib import Path

from forever_chronicle.importing.friend_importer import import_friends
from forever_chronicle.importing.friend_screenshots import local_folder, sync_friend_screenshots
from forever_chronicle.storage.repository import Repository

from test_friend_importer import cloud, friend_text, put  # noqa: F401  (cloud is a fixture)

PLAYER = "Bob-ffffffff-0badc0de"
CHARACTER = "Blind-Classic Beta PvP"     # the shared character of the fixture (renamed only as a player)
SHOT = "WoWScrnShot_100726_101005.jpg"   # the screenshot the addon test shares (tests/addon/scenario.lua)


def friend_shots(db):
    return db.conn.execute("""SELECT s.screenshot_id, s.file_path, s.character_id FROM screenshots s
                              JOIN characters c USING (character_id) WHERE c.owner_id IS NOT NULL""").fetchall()


def upload(setup, name=SHOT, data=b"\xff\xd8 picture \xff\xd9"):
    path = Path(setup.cloud) / "screenshots" / PLAYER / CHARACTER / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_pictures_copied_per_character_and_linked(db, cloud, tmp_path):
    home = tmp_path / "home"
    put(cloud, f"{PLAYER}.lua", friend_text())
    import_friends(db, cloud)
    [(shot_id, path, character_id)] = friend_shots(db)
    assert shot_id == "shot-share-1" and path is None

    # Not uploaded yet: nothing to link.
    assert not sync_friend_screenshots(db, cloud, home).changed

    source = upload(cloud)
    upload(cloud, "notes.txt")
    result = sync_friend_screenshots(db, cloud, home)
    copy = local_folder(home) / PLAYER / CHARACTER / SHOT
    assert result.copied == 1 and result.relinked == 1
    assert copy.read_bytes() == source.read_bytes()
    assert sorted(p.name for p in (local_folder(home) / PLAYER / CHARACTER).iterdir()) == [SHOT]
    [(_, path, _)] = friend_shots(db)
    assert path == str(copy)
    [row] = Repository(db.conn).screenshots(character_id, only_files=True)
    assert row["file_path"] == str(copy), "the cinematic and the gallery get the picture"

    # Unchanged: nothing copied again, nothing relinked.
    assert not sync_friend_screenshots(db, cloud, home).changed

    # A newer share file (friend played on): the record keeps its picture.
    put(cloud, f"{PLAYER}.lua", friend_text() + "\n")
    import_friends(db, cloud)
    sync_friend_screenshots(db, cloud, home)
    assert friend_shots(db)[0][1] == str(copy)

    # No longer shared: the local copy goes too, the record loses its picture.
    source.unlink()
    result = sync_friend_screenshots(db, cloud, home)
    assert result.removed == 1 and not (local_folder(home) / PLAYER).exists()
    assert friend_shots(db)[0][1] is None


def test_friend_gone_takes_the_pictures(db, cloud, tmp_path):
    home = tmp_path / "home"
    friend = put(cloud, f"{PLAYER}.lua", friend_text())
    import_friends(db, cloud)
    upload(cloud)
    sync_friend_screenshots(db, cloud, home)
    assert (local_folder(home) / PLAYER / CHARACTER / SHOT).is_file()

    friend.unlink()
    import_friends(db, cloud)
    result = sync_friend_screenshots(db, cloud, home)
    assert result.removed == 1 and list(local_folder(home).iterdir()) == []


def test_cloud_offline_keeps_the_pictures(db, cloud, tmp_path):
    home = tmp_path / "home"
    put(cloud, f"{PLAYER}.lua", friend_text())
    import_friends(db, cloud)
    upload(cloud)
    sync_friend_screenshots(db, cloud, home)
    (Path(cloud.cloud) / "players").rename(Path(cloud.cloud) / "players_offline")
    assert not sync_friend_screenshots(db, cloud, home).changed
    assert (local_folder(home) / PLAYER / CHARACTER / SHOT).is_file()
