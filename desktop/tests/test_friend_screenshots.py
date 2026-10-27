"""Friends' screenshots: the pictures their records point to are copied from <cloud>\\<friend>\\screenshots\\ into the
app's own folder and linked; pictures no longer pointed to and friends who are gone are removed."""

from pathlib import Path

from forever_chronicle.importing.friend_importer import import_friends
from forever_chronicle.importing.friend_screenshots import local_folder, sync_friend_screenshots
from forever_chronicle.storage.repository import Repository

from test_friend_importer import cloud, fixture_text, put  # noqa: F401  (cloud is a fixture)


def friend_shots(db):
    return db.conn.execute("""SELECT s.screenshot_id, s.file_path, s.character_id, s.file_stamp FROM screenshots s
                              JOIN characters c USING (character_id) WHERE c.owner_id IS NOT NULL
                              AND s.file_stamp IS NOT NULL ORDER BY s.screenshot_id""").fetchall()


def upload(cloud, stamp, data=b"\xff\xd8 picture \xff\xd9", player="Bob"):
    path = Path(cloud) / player / "screenshots" / f"WoWScrnShot_{stamp}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_pictures_copied_and_linked(db, cloud, tmp_path):
    home = tmp_path / "home"
    put(cloud, "Bob", fixture_text())
    import_friends(db, cloud, "Leon")
    shot_id, path, character_id, stamp = friend_shots(db)[0]
    assert path is None

    # Not uploaded yet: nothing to link.
    assert not sync_friend_screenshots(db, cloud, "Leon", home).copied

    source = upload(cloud, stamp)
    upload(cloud, "010101_000000")                                     # a picture without a record: not copied
    result = sync_friend_screenshots(db, cloud, "Leon", home)
    copy = local_folder(home) / "Bob" / source.name
    assert result.copied == 1 and result.relinked >= 1
    assert copy.read_bytes() == source.read_bytes()
    assert [p.name for p in (local_folder(home) / "Bob").iterdir()] == [source.name]
    assert dict((r[0], r[1]) for r in friend_shots(db))[shot_id] == str(copy)
    rows = Repository(db.conn).screenshots(character_id, only_files=True)
    assert str(copy) in [r["file_path"] for r in rows], "the cinematic and the gallery get the picture"

    # Unchanged: nothing copied again, nothing relinked.
    assert not sync_friend_screenshots(db, cloud, "Leon", home).changed

    # Gone from the cloud: the local copy goes too, the record loses its picture.
    source.unlink()
    result = sync_friend_screenshots(db, cloud, "Leon", home)
    assert result.removed == 1 and not copy.exists()
    assert dict((r[0], r[1]) for r in friend_shots(db))[shot_id] is None


def test_friend_gone_takes_the_pictures(db, cloud, tmp_path):
    home = tmp_path / "home"
    put(cloud, "Bob", fixture_text())
    import_friends(db, cloud, "Leon")
    upload(cloud, friend_shots(db)[0][3])
    sync_friend_screenshots(db, cloud, "Leon", home)
    assert any((local_folder(home) / "Bob").iterdir())

    import shutil
    shutil.rmtree(Path(cloud) / "Bob")
    import_friends(db, cloud, "Leon")
    result = sync_friend_screenshots(db, cloud, "Leon", home)
    assert result.removed == 1 and list(local_folder(home).iterdir()) == []


def test_cloud_offline_keeps_the_pictures(db, cloud, tmp_path):
    home = tmp_path / "home"
    put(cloud, "Bob", fixture_text())
    import_friends(db, cloud, "Leon")
    upload(cloud, friend_shots(db)[0][3])
    sync_friend_screenshots(db, cloud, "Leon", home)
    assert not sync_friend_screenshots(db, tmp_path / "offline", "Leon", home).changed
    assert any((local_folder(home) / "Bob").iterdir())
