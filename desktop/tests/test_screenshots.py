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
from forever_chronicle.ui.cards import THUMB, TITLE  # noqa: E402

GUID = "Player-4619-0112A417"


@pytest.fixture
def data(sv_data):
    return unpack_all(sv_data)


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


def test_chronicle_shows_screenshots_inline(db, data, tmp_path, monkeypatch):
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

    timeline = window.page("tab.timeline")
    window.show_page(timeline)
    cards = timeline.list
    with_shot = [item for item in cards.entries() if item.data(THUMB) is not None]
    texts = [item.data(TITLE) for item in with_shot]
    assert len(with_shot) == 2  # level-up and achievement share the screenshot
    assert any("Stufe 23 erreicht" in t for t in texts)
    assert timeline.count.text().endswith("2 Screenshots")
    loading = with_shot[0].data(THUMB).toImage()
    timeline.thumbnails.wait()
    assert timeline.thumbnails.cache, "thumbnail loaded"
    assert with_shot[0].data(THUMB).toImage() != loading, "the picture replaces the placeholder"

    viewer = timeline.open_screenshot(cards.row(with_shot[0]))
    assert viewer is not None and not viewer._pixmap.isNull()
    assert "Stufe 23 erreicht" in viewer.caption.text() or "Erfolg" in viewer.caption.text()
    assert viewer.picture.cue is not None and viewer.picture.cue.heading, "the picture comes with its banner"
    assert viewer.position.text() == "1 von 2"
    viewer.step(1)
    assert viewer.position.text() == "2 von 2" and not viewer.next_button.isEnabled()
    viewer.close()
    assert timeline.open_screenshot(cards.row(next(i for i in cards.entries() if i not in with_shot))) is None

    # Favourites: the viewer's star is kept in the database; the gallery shows it.
    viewer = timeline.open_screenshot(cards.row(with_shot[0]))
    shot = viewer.current
    viewer.star.setChecked(True)
    viewer.toggle_favorite()
    assert ctx.repo.favorite_screenshots(shot.character_id) == {shot.screenshot_id}
    gallery = window.page("tab.gallery")
    window.show_page(gallery)
    assert len(gallery.tiles) == 1 and gallery.tiles[0].favorite, "one picture (shared by two events), starred"
    assert gallery.count.text() == "1 Bilder  ·  1 Favoriten"
    gallery.thumbnails.wait()
    assert gallery.tiles[0].pixmap is not None
    for key in ("zone", "level", "type", "session"):
        gallery.group_by.setCurrentIndex(gallery.group_by.findData(key))
        assert len(gallery.sections) == 1 and len(gallery.tiles) == 1, key
    assert ctx.config.extra["gallery_group"] == "session", "the grouping is kept"
    gallery._star_tile(gallery.tiles[0], False)
    gallery.only_favorites.setChecked(True)
    assert not gallery.tiles and gallery.empty.isVisible() is not None
    gallery.only_favorites.setChecked(False)
    big = gallery.open_viewer(0)
    assert big is not None and big.isVisible() and big.replay.isEnabled()
    cinematic = big.play_replay()
    assert cinematic is not None and cinematic.start <= shot.time <= cinematic.end, "the replay starts before it"
    cinematic.close()
    viewer.close()

    # Filter: only entries with a screenshot. A test screenshot (no entry) is an entry of its own.
    window.show_page(timeline)
    timeline.type_filter.setCurrentIndex(timeline.type_filter.findData("__screenshots__"))
    assert len(cards.entries()) == 2
    db.conn.execute("""INSERT INTO screenshots (character_id, screenshot_id, seq, trigger_type, status, requested_at,
                       captured_at, file_stamp) SELECT character_id, 'test-1', seq + 1, 'manual', 'confirmed',
                       captured_at + 60, captured_at + 60, NULL FROM screenshots""")
    timeline.refresh()
    first = cards.entries()[0]
    assert len(cards.entries()) == 3 and first.data(TITLE).endswith("Test-Screenshot")
    assert first.toolTip().startswith("Keine Datei")  # no file: placeholder
    timeline.type_filter.setCurrentIndex(0)
    assert any(item.data(TITLE).endswith("Test-Screenshot") for item in cards.entries())
    window.close()
