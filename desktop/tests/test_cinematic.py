"""Cinematic mode: cue script, teleport breaks and gliding in the route, and a headless run of the window."""

import dataclasses
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle.app_context import AppContext  # noqa: E402
from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.domain.cinematic import Levels, banner, build_cues  # noqa: E402
from forever_chronicle.i18n import tr  # noqa: E402
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
    assert cues[0].has_screenshot and not cues[2].has_screenshot,         "an event knows its screenshot is shown (no toast), not when the file is missing"
    assert (cues[1].heading, cues[1].title, cues[1].level) == (tr("cine.banner.level_up"), tr("cine.level", level=5), 5), \
        "the screenshot's banner names what happened"
    assert banner(None, "manual") == (tr("cine.banner.screenshot"), tr("trigger.manual"), "")
    assert (cues[2].heading, cues[2].event_type) == (tr("cine.banner.player_died"), "player_died"),         "event cues carry their toast's banner"
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
    assert "screenshot" in ctx.sound.played, "the picture comes with a shutter sound"
    assert ctx.sound.music.active, "the music plays while the window is open"
    assert window.route_item.painted() > before
    image = QImage(400, 300, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    window.view.scene().render(painter)          # exercises the route painting
    painter.end()
    assert window.pins.shown, "events leave pins on the map"
    assert any(pin.thumb is not None for pin in window.pins.pins), "a screenshot leaves a small polaroid"
    event = next((c for c in window.cues if c.kind == "event"), None)
    if event:
        window._show_cue(dataclasses.replace(event, has_screenshot=True))
        assert not window.toasts, "no toast when the event's screenshot follows with the same banner"
        window._show_cue(dataclasses.replace(event, has_screenshot=False))
        assert window.toasts and window.pins.bursts, "an event slides in as a toast and flashes on the map"
    level = next((c for c in window.cues if c.kind == "level"), None)
    if level:
        ctx.sound.played.clear()
        ctx.sound._clocks.clear()
        window._show_cue(level)
        assert list(ctx.sound.played) == ["level_up"] and ctx.sound.music.duck_left > 0,             "a level-up plays the fanfare and lowers the music under it"
    window.seek(start)
    assert not window.ended and window.t == start
    assert not window.toasts and not window.pins.bursts, "a jump clears toasts and bursts of another moment"

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

    # A screenshot right after a level-up waits until the level-up title has been seen.
    from forever_chronicle.domain.cinematic import Cue
    from forever_chronicle.ui.cinematic import LEVEL_HOLD
    t0 = int(shot_cue.time) - 600
    window.seek(t0)
    window.paused = False
    level = Cue(t0, "level", "x", "▲", "#ffd100", level=7, event_type="level_up")
    window.cues = window.cues[:window.cue_index] + [
        dataclasses.replace(shot_cue, time=t0 + 1)] + window.cues[window.cue_index:]
    window.cue_times = [c.time for c in window.cues]
    window._show_cue(level)
    window.advance(0.1)
    assert window.pending_photo is not None and not window.photo_on, "the picture waits for the title"
    held = window.t
    waited = 0.1
    while not window.photo_on and waited < 10:
        window.advance(0.1)
        waited += 0.1
    assert window.photo_on and waited >= LEVEL_HOLD - 0.2 and window.t == held, (waited, window.t, held)
    window.seek(start)

    # M turns the music off and on; the choice is kept.
    window.toggle_music()
    assert not ctx.config.music and not ctx.sound.music.active and not window.music_button.isChecked()
    window.toggle_music()
    assert ctx.config.music and ctx.sound.music.active and window.music_button.isChecked()
    window.close()
    assert not ctx.sound.music.active, "the music fades out with the window"


def test_timeline_collapses_breaks():
    route = Route([P(0), P(100), P(1000), P(1100)])
    tl = route.timeline(0, 1100, gap=300)
    assert tl.total == 200 and tl.breaks() == [100]
    assert tl.to_value(1050) == 150 and tl.to_time(150) == 1050 and tl.to_value(500) == 100


def test_route_colors_match_the_addon():
    from forever_chronicle.domain.route_colors import RouteColors, zone_colors, hex_color, PALETTE, ROUTE, TAXI

    levels = Levels([E(100, "level_up", level=5), E(200, "level_up", level=6)])
    by_level = RouteColors("level", levels, [0, 150])
    assert by_level.at(50) == hex_color(PALETTE[3]), "level 4 before the first level-up"
    assert by_level.at(150) == hex_color(PALETTE[4]) and by_level.at(250) == hex_color(PALETTE[5])
    assert by_level.at(150, taxi=True) == hex_color(TAXI) == "#69ccf0", "flight paths stay blue"
    assert by_level.runs([90, 110, 120, 210]) == [(0, 2, "#ffffff"), (2, 3, "#ff9e1a")], \
        "a line takes the colour of the moment it ends at"
    by_session = RouteColors("session", levels, [150, 0])
    assert (by_session.key_at(10), by_session.key_at(160)) == (1, 2)
    assert RouteColors("plain", levels, []).at(150) == hex_color(ROUTE) == "#ffd100"
    assert RouteColors("bogus", levels, []).mode == "level"

    from types import SimpleNamespace
    seg = SimpleNamespace(taxi=False, points=[(50, 0, 0), (120, 0, 0), (250, 0, 0)])
    assert [label for _, label in by_level.legend([seg])] == [tr("cine.level", level=n) for n in (4, 5, 6)], \
        "the legend lists levels reached inside a segment, not only at its ends"
    assert len(by_session.legend([seg])) == 2

    route = Route([P(0, map_id=1), P(10, map_id=1), P(20, map_id=2),
                   PositionPoint(30, None, None, None, None, 48, False), P(40, map_id=1)])
    runs = route.zone_runs(0, 40)
    assert [(r.start, r.map_id, r.instance_id) for r in runs] == [(0, 1, None), (20, 2, None), (30, None, 48),
                                                                   (40, 1, None)]
    color = zone_colors(runs)
    assert color(runs[0]) == color(runs[3]) == "#9e7840" and color(runs[1]) == "#54854d"
    assert color(runs[2]) == "#382e47", "dungeons are dark"


def test_voyage_camera_and_crossing():
    from PySide6.QtCore import QPointF
    from forever_chronicle.ui.cinematic import VOYAGE_OUT, VOYAGE_TRAVEL, _Voyage

    v = _Voyage(1420, QPointF(10, 20), QPointF(50, 50), QPointF(90, 80), 8.0, 1.0, 4.0,
                QPointF(0, 100), QPointF(200, 100))
    assert v.camera() == (pytest.approx(8.0), QPointF(10, 20)) and v.marker() == QPointF(0, 100),         "starts where the old zone's view is"
    v.age = VOYAGE_OUT + VOYAGE_TRAVEL / 2
    assert v.camera() == (1.0, QPointF(50, 50)), "both continents in view while crossing"
    assert v.marker().y() < 100 and v.marker().x() == pytest.approx(100), "the crossing bulges northwards"
    v.age = v.life
    scale, center = v.camera()
    assert scale == pytest.approx(4.0) and center == QPointF(90, 80) and v.marker() == QPointF(200, 100),         "ends exactly where the new zone's view takes over"
