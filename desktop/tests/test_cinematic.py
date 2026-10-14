"""Cinematic mode: cue script, teleport breaks and gliding in the route, and a headless run of the window."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle.app_context import AppContext  # noqa: E402
from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.domain.cinematic import Levels, build_cues  # noqa: E402
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.storage.repository import EventRow, PositionPoint  # noqa: E402
from forever_chronicle.ui import theme  # noqa: E402
from forever_chronicle.ui.cinematic import CinematicWindow  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


def P(t, x=0.5, y=0.5, map_id=1413):
    return PositionPoint(t, None, map_id, x, y, None, False)


def E(t, kind, **payload):
    return EventRow("c", f"e{t}", kind, t, None, None, None, None, None, payload)


def test_route_breaks_at_teleports_and_glides():
    route = Route([P(0, 0.1), P(2, 0.11), P(4, 0.9), P(6, 0.91)])
    assert len(route.segments(1413)) == 2, "a step faster than any mount is a teleport"
    assert route.glide(1) == (1413, pytest.approx(0.105), 0.5), "the marker moves along a connected line"
    assert route.glide(3)[1] in (0.11, 0.9), "no gliding across a teleport"


def test_cues_and_levels(tmp_path):
    shot = tmp_path / "WoWScrnShot_101426_120000.jpg"
    QImage(40, 30, QImage.Format.Format_RGB32).save(str(shot))
    events = [E(100, "level_up", level=5), E(200, "quest_completed", title="x"), E(300, "player_died"),
              E(400, "level_up", level=6)]
    shots = [{"captured_at": 105, "requested_at": 100, "file_path": str(shot), "trigger_type": "level",
              "first_event_id": "e100"},
             {"captured_at": 305, "requested_at": 300, "file_path": str(tmp_path / "missing.jpg"),
              "trigger_type": "death", "first_event_id": "e300"}]
    cues = build_cues(events, shots, 0, 350)
    assert [(c.time, c.kind) for c in cues] == [(100, "level"), (105, "screenshot"), (300, "event")]
    assert cues[0].level == 5 and cues[1].path == str(shot), "quests are left out, missing files too"
    levels = Levels(events, current=9)
    assert (levels.at(50), levels.at(100), levels.at(399), levels.at(500)) == (4, 5, 5, 6)
    assert Levels([], current=9).at(50) == 9


def test_cinematic_window_plays_with_screenshots(app, db, tmp_path, monkeypatch, addon_fixture):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    ctx = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    ctx._client_searched = True
    ctx.importer.import_data(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")), "fixture")
    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    start, end = points[0].time, max(p.end for p in points)

    # A screenshot file for a moment within the route.
    shot = tmp_path / "shot.png"
    image = QImage(320, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    image.save(str(shot))
    row = next(r for r in ctx.repo.screenshots(cid, only_files=True))
    ctx.repo.set_screenshot_file(cid, row["screenshot_id"], str(shot), "matched")
    shot_time = row["captured_at"] or row["requested_at"]
    if not start <= shot_time <= end:
        start = min(start, shot_time)

    window = CinematicWindow(ctx, cid, start, end, speed=10)
    window.resize(1200, 800)
    window.show()
    window.timer.stop()                          # drive it by hand
    assert any(c.kind == "screenshot" for c in window.cues)
    before = window.route_item.painted() if window.route_item else 0
    saw_photo = False
    for _ in range(2000):
        window.advance(0.1)
        saw_photo = saw_photo or window.photo_on
        if window.ended:
            break
    assert window.ended and saw_photo, "plays to the end and pauses for the screenshot"
    assert window.route_item.painted() > before
    image = QImage(400, 300, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    window.view.scene().render(painter)          # exercises the route painting
    painter.end()
    window.seek(start)
    assert not window.ended and window.t == start

    # Controls: hidden until the mouse moves, gone again after a moment without movement.
    assert not window.controls.isVisible()
    window.wake_controls()
    assert window.controls.isVisible()
    for _ in range(int((3 + 1) / 0.1)):
        window.advance(0.1)
    assert not window.controls.isVisible(), "controls fade out without mouse movement"
    window.toggle_pause()
    assert window.paused and window.play_button.text() == "▶"
    before = window.t
    window.advance(1.0)
    assert window.t == before, "paused"
    window.toggle_pause()
    window.set_speed(10)
    assert [b.isChecked() for _, b in window.speed_buttons] == [False, False, False, True]
    target = (start + end) / 2
    window._seek_from_bar(target)
    assert window.t == target and window.bar.value == pytest.approx(window.bar.timeline.to_value(target))

    # Slower shortly before a screenshot, full speed far from it.
    shot_cue = next(c for c in window.cues if c.kind == "screenshot")
    window.seek(shot_cue.time - 5)
    near = window.pace()
    window.seek(shot_cue.time - 10 * 60 * 10)
    assert near < 0.5 and (window.pace() == 1.0 or window.t < start + 1), (near, window.pace())
    window.close()


def test_timeline_collapses_breaks():
    route = Route([P(0), P(100), P(1000), P(1100)])
    tl = route.timeline(0, 1100, gap=300)
    assert tl.total == 200 and tl.breaks() == [100]
    assert tl.to_value(1050) == 150 and tl.to_time(150) == 1050 and tl.to_value(500) == 100
