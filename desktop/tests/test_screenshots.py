import os
from datetime import datetime, timedelta

import pytest
from conftest import unpack_all

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle.importing.screenshot_matcher import STAMP_FORMAT, match_screenshots  # noqa: E402
from forever_chronicle.importing.sv_importer import SavedVariablesImporter  # noqa: E402
from forever_chronicle.storage.repository import Repository  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402

GUID = "Player-4619-0112A417"


@pytest.fixture
def data(addon_fixture):
    return unpack_all(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")))


def shot_stamp(data):
    return data["ForeverChronicleDB"]["characters"][GUID]["streams"]["screenshots"]["records"][0]["fileStamp"]


def shifted(stamp, seconds):
    return (datetime.strptime(stamp, STAMP_FORMAT) + timedelta(seconds=seconds)).strftime(STAMP_FORMAT)


def write_image(path):
    image = QImage(64, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    assert image.save(str(path), "JPG")


def test_screenshot_records_and_links_imported(db, data):
    result = SavedVariablesImporter(db).import_data(data, "fixture")
    assert result.screenshots == 1
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id
    [row] = repo.screenshots(cid)
    assert row["trigger_type"] == "level" and row["status"] == "confirmed" and row["event_count"] == 2
    first = repo.event(cid, row["first_event_id"])
    assert first.event_type == "level_up"


def test_reimport_updates_screenshot_without_duplicates(db, data):
    importer = SavedVariablesImporter(db)
    importer.import_data(data, "fixture")
    rec = data["ForeverChronicleDB"]["characters"][GUID]["streams"]["screenshots"]["records"][0]
    rec["status"] = "failed"
    importer.import_data(data, "fixture")
    rows = db.conn.execute("SELECT status FROM screenshots").fetchall()
    assert [r[0] for r in rows] == ["failed"]
    assert db.conn.execute("SELECT COUNT(*) FROM screenshot_events").fetchone()[0] == 2


@pytest.mark.parametrize("offsets,expected", [
    ([0], "matched"),
    ([1], "matched"),          # file written a second after the call
    ([-2], "matched"),
    ([3], "not_found"),        # outside tolerance
    ([1, -1], "ambiguous"),    # two equally near files: never guess
    ([0, 1], "matched"),       # exact match wins
])
def test_file_matching(db, data, tmp_path, offsets, expected):
    SavedVariablesImporter(db).import_data(data, "fixture")
    stamp = shot_stamp(data)
    for off in offsets:
        write_image(tmp_path / f"WoWScrnShot_{shifted(stamp, off)}.jpg")
    repo = Repository(db.conn)
    match_screenshots(repo, tmp_path)
    row = db.conn.execute("SELECT file_match, file_path FROM screenshots").fetchone()
    assert row["file_match"] == expected
    if expected == "matched":
        assert row["file_path"].endswith(f"WoWScrnShot_{shifted(stamp, offsets[0])}.jpg")
    else:
        assert row["file_path"] is None


def test_not_found_is_retried_later(db, data, tmp_path):
    SavedVariablesImporter(db).import_data(data, "fixture")
    repo = Repository(db.conn)
    assert match_screenshots(repo, tmp_path) == 0
    write_image(tmp_path / f"WoWScrnShot_{shot_stamp(data)}.jpg")
    assert match_screenshots(repo, tmp_path) == 1


def test_gallery_and_timeline_show_screenshot(db, data, tmp_path, monkeypatch):
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.config import AppConfig
    from forever_chronicle.ui.main_window import MainWindow
    from forever_chronicle.wow.paths import ClientInstall

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path / "home"))
    client_dir = tmp_path / "_classic_beta_"
    (client_dir / "Screenshots").mkdir(parents=True)
    write_image(client_dir / "Screenshots" / f"WoWScrnShot_{shot_stamp(data)}.jpg")

    ctx = AppContext(AppConfig(), db)
    ctx._client, ctx._client_searched = ClientInstall(client_dir, "wow_classic_beta"), True
    ctx.importer.import_data(data, "fixture")
    assert ctx.match_screenshots() == 1
    window = MainWindow(ctx)

    gallery = next(p for p in window.pages if p.title_key == "tab.gallery")
    window.tabs.setCurrentWidget(gallery)
    assert gallery.grid.count() == 1
    assert gallery.grid.item(0).text().startswith("Stufe 23 erreicht (+1)")
    gallery._load_batch()
    assert gallery._cache, "thumbnail loaded"

    timeline = next(p for p in window.pages if p.title_key == "tab.timeline")
    window.tabs.setCurrentWidget(timeline)
    marked = [timeline.table.item(r, 1).text() for r in range(timeline.table.rowCount())
              if "\U0001F4F7" in timeline.table.item(r, 1).text()]
    assert len(marked) == 2  # level-up and achievement share the screenshot
    window.close()
