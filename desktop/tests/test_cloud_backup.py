"""The cloud backup (cloud_backup.py): dated copies that never overwrite, the newest 30 kept, screenshots only added,
restore with the local files saved aside, the hint about my other PC, and the app's part (button, runner, banner)."""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from forever_chronicle import cloud_backup
from forever_chronicle.cloud_backup import BackupSettings
from forever_chronicle.config import AppConfig, app_home
from forever_chronicle.wow.paths import ClientInstall


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A client with one account's addon file and two screenshots, an empty cloud folder, this PC named PC-A."""
    monkeypatch.setenv("COMPUTERNAME", "PC-A")
    root = tmp_path / "WoW" / "_forever_"
    saved = root / "WTF" / "Account" / "123456#1" / "SavedVariables"
    saved.mkdir(parents=True)
    (root / ".flavor.info").write_text("#\nwowf\n")
    (saved / "ForeverChronicle.lua").write_text("ForeverChronicleDB = { schemaVersion = 2 }\n", encoding="utf-8")
    shots = root / "Screenshots"
    shots.mkdir()
    (shots / "WoWScrnShot_102726_200000.jpg").write_bytes(b"\xff\xd8 one \xff\xd9")
    (shots / "WoWScrnShot_102726_200100.jpg").write_bytes(b"\xff\xd8 two \xff\xd9")
    (shots / "notes.txt").write_text("not a screenshot")
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    return {"client": ClientInstall(root, "wowf"), "saved": saved / "ForeverChronicle.lua", "shots": shots,
            "settings": BackupSettings(cloud, "Leon"), "cloud": cloud}


def addon_dir(world):
    return world["settings"].player_dir / "addon" / cloud_backup.account_id("123456#1")


def test_upload_makes_dated_copies_and_never_overwrites(world, db):
    s, client = world["settings"], world["client"]
    snapshot = cloud_backup.database_snapshot(db, app_home() / "snap.db")
    result = cloud_backup.upload(s, client, snapshot)
    assert result.addon == 1 and result.database and result.screenshots == 2 and not result.errors
    [copy] = cloud_backup.versions(addon_dir(world))
    assert copy.pc == "PC-A" and copy.mine and copy.path.read_bytes() == world["saved"].read_bytes()
    assert copy.path.name.startswith("ForeverChronicle_") and copy.path.name.endswith("_PC-A.lua")
    assert "123456" not in str(copy.path), "the account number is hidden behind a hash"
    [dbcopy] = cloud_backup.database_versions(s)
    assert dbcopy.path.stat().st_size > 0 and not snapshot.exists()
    assert sorted(p.name for p in (s.player_dir / "screenshots").iterdir()) == [
        "WoWScrnShot_102726_200000.jpg", "WoWScrnShot_102726_200100.jpg"]

    # Unchanged: no new copies.
    again = cloud_backup.upload(s, client, cloud_backup.database_snapshot(db, app_home() / "snap.db"))
    assert not again.changed and not cloud_backup.has_changes(s, client)

    # The game saved again: a new copy next to the old one; a deleted screenshot stays in the cloud.
    world["saved"].write_text("ForeverChronicleDB = { schemaVersion = 2, createdAt = 1 }\n", encoding="utf-8")
    (world["shots"] / "WoWScrnShot_102726_200000.jpg").unlink()
    assert cloud_backup.has_changes(s, client)
    time.sleep(1.1)                                    # a new second, a new name
    assert cloud_backup.upload(s, client, None).addon == 1
    assert len(cloud_backup.versions(addon_dir(world))) == 2
    assert len(list((s.player_dir / "screenshots").iterdir())) == 2
    assert cloud_backup.summary(s) == (2, 1, 2)
    assert cloud_backup.load_state()["last_upload"] > 0


def test_only_the_newest_30_are_kept(world):
    folder = addon_dir(world)
    folder.mkdir(parents=True)
    for day in range(1, 32):
        (folder / f"ForeverChronicle_2025-01-{day:02d}_120000_PC-B.lua").write_text(str(day))
    (folder / "readme.txt").write_text("kept")
    cloud_backup.upload(world["settings"], world["client"], None)
    kept = cloud_backup.versions(folder)
    assert len(kept) == 30 and kept[0].mine and kept[-1].when == datetime(2025, 1, 3, 12, 0)
    assert (folder / "readme.txt").is_file()


def test_restore_saves_the_local_file_aside(world):
    s, client = world["settings"], world["client"]
    folder = addon_dir(world)
    folder.mkdir(parents=True)
    old = folder / "ForeverChronicle_2026-10-26_210000_PC-B.lua"
    old.write_text("ForeverChronicleDB = { from = 'PC-B' }\n", encoding="utf-8")
    before = world["saved"].read_bytes()
    [version] = cloud_backup.addon_versions(s)
    assert version.pc == "PC-B" and not version.mine
    saved = cloud_backup.restore_addon(version, client)
    assert world["saved"].read_bytes() == old.read_bytes()
    assert saved.read_bytes() == before and saved.parent == app_home() / "backups" / "before-restore"
    assert not cloud_backup.has_changes(s, client) or cloud_backup.missing_screenshots(s, client) == 0
    assert cloud_backup.upload(s, client, None).addon == 0, "the restored copy is not uploaded again as new"


def test_restore_without_an_account_folder(world, tmp_path):
    other = ClientInstall(tmp_path / "Other" / "_forever_", "wowf")
    (other.path / "WTF" / "Account").mkdir(parents=True)
    version = cloud_backup.Version(world["saved"], datetime.now(), "PC-B", cloud_backup.account_id("123456#1"))
    with pytest.raises(FileNotFoundError):
        cloud_backup.restore_addon(version, other)
    (other.path / "WTF" / "Account" / "123456#1").mkdir()
    assert cloud_backup.restore_addon(version, other) is None, "nothing there to save aside"
    assert (other.path / "WTF" / "Account" / "123456#1" / "SavedVariables" / "ForeverChronicle.lua").is_file()


def test_restore_screenshots_and_database(world, db):
    s, client = world["settings"], world["client"]
    cloud_backup.upload(s, client, cloud_backup.database_snapshot(db, app_home() / "snap.db"))
    for f in world["shots"].iterdir():
        f.unlink()
    assert cloud_backup.missing_screenshots(s, client) == 2
    assert cloud_backup.restore_screenshots(s, client) == 2 and cloud_backup.missing_screenshots(s, client) == 0

    db.conn.execute("INSERT INTO owners (share_id, display_name) VALUES ('x', 'later')")
    db.conn.commit()
    [version] = cloud_backup.database_versions(s)
    before = cloud_backup.restore_database(version, db)
    assert before is not None and before.is_file()
    assert db.conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 0


def test_newer_data_on_my_other_pc(world):
    s, client = world["settings"], world["client"]
    cloud_backup.upload(s, client, None)
    assert cloud_backup.newer_elsewhere(s, client) is None, "only my own copy"
    folder = addon_dir(world)
    old = time.time() - 3600
    os.utime(world["saved"], (old, old))
    other = folder / f"ForeverChronicle_{datetime.now().strftime(cloud_backup.STAMP)}_PC-B.lua"
    other.write_text("ForeverChronicleDB = { played = 'on PC-B' }\n", encoding="utf-8")
    hint = cloud_backup.newer_elsewhere(s, client)
    assert hint is not None and hint.pc == "PC-B"
    # This PC backing up its older file does not hide it.
    world["saved"].write_text("ForeverChronicleDB = { changed = true }\n", encoding="utf-8")
    os.utime(world["saved"], (old, old))
    time.sleep(1.1)
    cloud_backup.upload(s, client, None)
    assert cloud_backup.newer_elsewhere(s, client) is not None
    # Restored: same content, no hint.
    cloud_backup.restore_addon(hint, client)
    assert cloud_backup.newer_elsewhere(s, client) is None


def test_settings_friends_and_old_sync(world, tmp_path, monkeypatch):
    config = AppConfig()
    assert cloud_backup.settings(config) is None
    old = tmp_path / "local" / "ForeverChronicle" / "sync"
    old.mkdir(parents=True)
    (old / "config.json").write_text(json.dumps({"cloud": str(world["cloud"])}), encoding="utf-8-sig")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    config.extra["share_name"] = "Leon"
    cloud_backup.adopt_old_settings(config)
    s = cloud_backup.settings(config)
    assert s == BackupSettings(world["cloud"], "Leon")
    assert cloud_backup.folder_name('Le:on?') == "Le_on_" and cloud_backup.folder_name("  ") == "Spieler"

    (world["cloud"] / "players").mkdir()                     # the old layout
    (world["cloud"] / "Bob" / "addon").mkdir(parents=True)
    (world["cloud"] / "leon" / "addon").mkdir(parents=True)   # mine, whatever the case
    assert [f.name for f in cloud_backup.friend_folders(world["cloud"], "Leon")] == ["Bob"]


def test_cloud_folder_gone(world):
    s = BackupSettings(world["cloud"] / "missing", "Leon")
    result = cloud_backup.upload(s, world["client"], None)
    assert result.errors and not result.changed
    snapshot = world["cloud"].parent / "cloud-upload.db"
    snapshot.write_bytes(b"database copy")
    cloud_backup.upload(s, world["client"], snapshot)
    assert not snapshot.exists(), "the database copy is not left behind"


# -- the app ----------------------------------------------------------------------------------------------


@pytest.fixture
def window(app, db, world):
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.ui.main_window import MainWindow
    config = AppConfig(client_dir=str(world["client"].path))
    config.extra.update(cloud_folder=str(world["cloud"]), cloud_name="Leon", setup_done=True)
    ctx = AppContext(config, db)
    ctx._client, ctx._client_searched = world["client"], True
    w = MainWindow(ctx)
    yield w
    w.watcher.timer.stop()
    w.close()


def wait_for(ctx):
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    clock = QElapsedTimer()
    clock.start()
    while ctx.backup.running and clock.elapsed() < 30_000:
        QCoreApplication.processEvents()
    assert not ctx.backup.running


def test_button_backs_up_without_blocking(window, world):
    page = window.page("tab.import")
    window.show_page(page)
    assert page.cloud_button.isEnabled() and str(world["cloud"]) in page.cloud_folder.text()
    assert "Noch keine Freunde" in page.cloud_status.text()
    page.run_backup()
    assert not page.cloud_button.isEnabled(), "one run at a time"
    wait_for(window.ctx)
    assert "Gesichert: 1 Addon" in page.cloud_message.text() and "Datenbank" in page.cloud_message.text()
    assert "In der Cloud: 1 Addon-Stände, 1 Datenbank-Stände, 2 Screenshots" in page.cloud_status.text()
    page.run_backup()
    wait_for(window.ctx)
    assert "Nichts Neues" in page.cloud_message.text() or "Datenbank" in page.cloud_message.text()


def test_game_start_and_close_back_up(window, world, monkeypatch):
    from forever_chronicle.ui import backup_runner
    running = {"now": True}
    monkeypatch.setattr(backup_runner, "game_running", lambda _path: running["now"])
    window.watcher.check()
    wait_for(window.ctx)
    assert cloud_backup.versions(addon_dir(world)), "backed up when WoW started"
    world["saved"].write_text("ForeverChronicleDB = { schemaVersion = 2, after = 1 }\n", encoding="utf-8")
    running["now"] = False
    for _ in range(window.watcher.CLOSED_CHECKS - 1):
        window.watcher.check()
    assert not window.ctx.backup.running and len(cloud_backup.versions(addon_dir(world))) == 1, "not yet closed"
    time.sleep(1.1)
    window.watcher.check()
    wait_for(window.ctx)
    assert len(cloud_backup.versions(addon_dir(world))) == 2, "backed up after WoW was closed"


def test_banner_offers_the_other_pcs_data(window, world, monkeypatch):
    folder = addon_dir(world)
    folder.mkdir(parents=True)
    old = time.time() - 3600
    os.utime(world["saved"], (old, old))
    (folder / f"ForeverChronicle_{datetime.now().strftime(cloud_backup.STAMP)}_PC-B.lua").write_text(
        "ForeverChronicleDB = { schemaVersion = 2 }\n-- played on PC-B\n", encoding="utf-8")
    window.start_backup()
    assert not window.banner.isHidden() and "PC-B" in window.banner_text.text()
    wait_for(window.ctx)

    from forever_chronicle.ui import restore_dialog
    seen = {}

    def fake_exec(dialog):
        seen["checked"] = dialog.addon_box.isChecked()
        seen["picked"] = dialog.addon_versions[dialog.addon_list.currentIndex()].pc
        monkeypatch.setattr(restore_dialog.QMessageBox, "information", lambda *a: None)
        dialog.restore()
        return 1

    monkeypatch.setattr(restore_dialog.RestoreDialog, "exec", fake_exec)
    monkeypatch.setattr(restore_dialog, "game_running", lambda _path: False)
    window.banner_restore.click()
    assert seen == {"checked": True, "picked": "PC-B"}
    assert "played on PC-B" in world["saved"].read_text(encoding="utf-8")
    assert window.banner.isHidden()
