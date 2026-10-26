"""Cinematic mode: cue script, teleport breaks and gliding in the route, and a headless run of the window."""

import dataclasses
import math
import os

import pytest
from conftest import event as E

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from forever_chronicle.domain.cinematic import Levels, banner, build_cues  # noqa: E402
from forever_chronicle.i18n import tr  # noqa: E402
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint  # noqa: E402
from forever_chronicle.ui import cinematic as cine  # noqa: E402
from forever_chronicle.ui.cinematic import CinematicWindow  # noqa: E402


def P(t, x=0.5, y=0.5, map_id=1413):
    return PositionPoint(t, None, map_id, x, y, None, False)


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


def test_cinematic_window_plays_with_screenshots(app, ctx, imported, tmp_path, monkeypatch):
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
    event = next((c for c in window.cues if c.kind == "event" and c.event_type != "player_died"), None)
    if event:
        window._show_cue(dataclasses.replace(event, has_screenshot=True))
        assert not window.toasts, "no toast when the event's screenshot follows with the same banner"
        window._show_cue(dataclasses.replace(event, has_screenshot=False))
        assert window.toasts and window.pins.bursts, "an event slides in as a toast and flashes on the map"
        first = window.toasts[0]
        for _ in range(cine.MAX_TOASTS):
            window._show_cue(dataclasses.replace(event, has_screenshot=False))
        assert first not in window.toasts and first.isHidden(), \
            "pushed out: hidden at once (the video export never gets to deleteLater)"
    level = next((c for c in window.cues if c.kind == "level"), None)
    if level:
        ctx.sound.played.clear()
        ctx.sound._last.clear()
        window._show_cue(level)
        assert list(ctx.sound.played) == ["level_up"] and ctx.sound.music.duck_left > 0,             "a level-up plays the fanfare and lowers the music under it"
    death = next((c for c in window.cues if c.event_type == "player_died"), None)
    if death:
        window.toasts.clear()
        window._show_cue(death)
        assert window.title.tone == "death" and window.hold > 0 and not window.toasts, \
            "a death holds the replay on a dark red title instead of a toast"
        window.hold = 0.0
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
    window.still_mode = "normal"            # far from it: full speed, unless standing still
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


def test_short_zone_visits_slow_the_replay_down():
    from types import SimpleNamespace

    def zone(a, b, map_id):
        return [P(t, 0.5, 0.5, map_id) for t in range(a, b, 5)]

    # A long visit, a step into another zone and back, three quick zones, then a long visit again.
    points = (zone(0, 3000, 1) + zone(3000, 3010, 2) + zone(3010, 6000, 1) + zone(6000, 6120, 3)
              + zone(6120, 6400, 4) + zone(6400, 6420, 5) + zone(6420, 12000, 6))
    window = SimpleNamespace(route=Route(points), start=0, end=12000, speed=10, t=0.0)
    window._zone_visits = lambda: cine.CinematicWindow._zone_visits(window)
    window._update_zone_share = lambda dt, now=False: cine.CinematicWindow._update_zone_share(window, dt, now)
    visits = window._zone_visits()
    assert [(a, b) for a, b, _ in visits] == [(0, 6000), (6000, 6120), (6120, 6400), (6400, 6420),
                                              (6420, 12000)], "the step into zone 2 and back is no visit"
    rate = 10 * cine.BASE_SPEED
    assert visits[0][2] > rate and visits[-1][2] > rate, "long visits play at the chosen speed"
    assert visits[1][2] == cine.BASE_SPEED, "never slower than 1×"
    assert visits[2][2] == pytest.approx(280 / cine.ZONE_SECONDS), "each zone stays on screen for a while"
    assert visits[3][2] == math.inf, "too short to be readable at any speed: not slowed down"

    window.zone_visits, window.zone_visit_starts = visits, [a for a, _, _ in visits]
    window.zone_share = 1.0
    window._update_zone_share(0.0, now=True)
    assert window.zone_share == 1.0
    window.t = 6000 - rate * cine.ZONE_AHEAD / 2
    window._update_zone_share(0.0, now=True)
    assert window.zone_share == pytest.approx(1 / 10), "slow already shortly before the next zone"
    window.t = 7000
    window._update_zone_share(0.1)
    assert 0.1 < window.zone_share < 0.5, "back to speed gently"


def test_deaths_from_the_route():
    from forever_chronicle.domain.cinematic import NO_ROUTE_DEATH, SPIRIT_HEALER, death_spans

    # Unknown zone geometry: one map unit is 0.1 continent widths (route.UNKNOWN_ZONE_SCALE).
    corpse_run = [P(90, 0.49), P(100, 0.5), P(110, 0.5), P(128, 0.5),
                  P(130, 0.8, 0.8),                                  # released: the graveyard, far away at once
                  P(150, 0.7, 0.7), P(170, 0.6, 0.6), P(190, 0.52, 0.52), P(200, 0.45)]
    d = death_spans([E(100, "player_died")], Route(corpse_run))[0]
    assert (d.time, d.released, d.revived) == (100, 130, 190), "back to life on reaching the body"
    assert d.dead(150) and d.ghost(150) and d.dead(110) and not d.ghost(110) and not d.dead(190)

    rezzed = [P(290, 0.3), P(300, 0.3), P(320, 0.3), P(340, 0.35), P(350, 0.4)]
    d = death_spans([E(300, "player_died")], Route(rezzed))[0]
    assert (d.released, d.revived) == (None, 340), "brought back where the body lay: alive on moving on"

    healer = [P(90, 0.5), P(100, 0.5), P(128, 0.5), P(130, 0.8, 0.8), P(200, 0.82, 0.8), P(400, 0.9, 0.8)]
    d = death_spans([E(100, "player_died")], Route(healer))[0]
    assert (d.released, d.revived) == (130, 130 + SPIRIT_HEALER), "never walked back: the spirit healer"

    dungeon = [P(90, 0.5), PositionPoint(100, 120, None, None, None, 36, False), P(150, 0.5, 0.2),
               PositionPoint(250, 300, None, None, None, 36, False)]
    d = death_spans([E(110, "player_died")], Route(dungeon))[0]
    assert (d.released, d.revived) == (150, 250), "out of the dungeon to the graveyard, and back in"

    assert death_spans([E(5000, "player_died")], Route(corpse_run))[0].revived == 5000 + NO_ROUTE_DEATH


def test_standstills():
    from forever_chronicle.domain.cinematic import STILL_EDGE, still_spans

    afk = [P(t, 0.5) for t in range(0, 302, 2)]                                     # 5 minutes on one spot
    walk = [P(310 + t, 0.6 + t * 0.002) for t in range(0, 60, 2)]
    short = [P(400 + t, 0.9) for t in range(0, 60, 2)]                                # a minute only
    spans = still_spans(Route(afk + walk + short), 0, 1000)
    assert spans == [(0 + STILL_EDGE, 300 - STILL_EDGE)], spans
    assert still_spans(Route(afk), 100, 200) == [(100 + STILL_EDGE, 200 - STILL_EDGE)], "cut to the range"
    long_point = [PositionPoint(0, 500, 1413, 0.5, 0.5, None, False), P(510, 0.6)]
    assert still_spans(Route(long_point), 0, 600) == [(STILL_EDGE, 500 - STILL_EDGE)], "one point standing long"
    hunt = [P(t, 0.5 + (0.004 if t % 4 else 0)) for t in range(0, 302, 2)]        # 5 minutes running round a camp
    assert still_spans(Route(hunt), 0, 400) == [], "fighting round one camp: always moving"
    step = [P(t, 0.5 + (0.0001 if t >= 150 else 0)) for t in range(0, 302, 2)]     # one step after 2.5 minutes
    assert still_spans(Route(step), 0, 400) == [(STILL_EDGE, 148 - STILL_EDGE), (150 + STILL_EDGE, 300 - STILL_EDGE)], \
        "a single step ends a standstill"


def test_ghost_route_and_grey_view(app):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QGraphicsScene

    from forever_chronicle.domain.route_colors import RouteColors
    from forever_chronicle.ui.cinematic_fx import GHOST_COLOR, CinemaView, RouteItem

    seg = SimpleNamespace(taxi=False, points=[(t, 0.1 * i, 0.1) for i, t in enumerate((0, 10, 20, 30, 40))])
    item = RouteItem([seg], RouteColors("plain", Levels([]), []), ghost_spans=[(15, 30)])
    times, _, _, runs, line_colors = item.segs[0]
    assert [c == GHOST_COLOR for c in line_colors[1:]] == [False, True, True, False], \
        "lines ending inside the ghost span are the corpse run"
    assert [(a, b) for a, b, _ in runs] == [(0, 1), (1, 3), (3, 4)]

    view = CinemaView()
    scene = QGraphicsScene()
    scene.addRect(0, 0, 400, 300, brush=QColor("#d02020"))
    view.setScene(scene)
    view.resize(200, 150)
    view.show()
    red = view.grab().toImage().pixelColor(100, 75)
    view.set_grey(1.0)
    grey = view.grab().toImage().pixelColor(100, 75)
    assert red.saturation() > 200 and grey.saturation() < 90, (red.name(), grey.name())
    assert grey.blue() >= grey.red(), "the spirit world's light is cold"
    view.close()


def test_zone_music_table_and_cache(tmp_path, monkeypatch):
    from forever_chronicle.wow import zone_music

    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    durotar = zone_music.entry(1411)
    assert durotar and durotar["day"] and durotar["night"], "the table in git knows Durotar's music"
    assert zone_music.entry(None, 36), "the Deadmines have their own"
    assert zone_music.entry(1411, 99999) == durotar, "a dungeon without music keeps the zone's"
    assert all(zone_music.adventure_file_ids(c) for c in range(len(zone_music.ADVENTURE))), "every theme is there"
    themes = [zone_music.adventure_file_ids(c) for c in range(len(zone_music.ADVENTURE))]
    assert len(set(themes)) == len(themes), "each theme is music of its own"
    assert zone_music.adventure_file_ids(len(themes)) == themes[0], "the themes start again"
    assert zone_music.adventure_file_ids(0, "Goblin") == themes[0], "an unknown race: the common themes"
    for race, zones in zone_music.RACE_THEMES.items():
        assert all(zone_music.entry(z) for z in zones), f"{race}: every theme is in the table"
    undead = [zone_music.adventure_file_ids(c, "Scourge") for c in range(13)]
    lands = {tuple(zone_music.entry(z)["day"]) for z in zone_music.RACE_THEMES["Scourge"]}
    assert undead[0] == tuple(zone_music.entry(1420)["day"]), "the undead start with Tirisfal"
    assert [m in lands for m in undead] == [c % 2 == 0 for c in range(13)], "every other theme is undead"
    assert all(a != b for a, b in zip(undead, undead[1:])), "never the same theme twice in a row"
    assert [zone_music.chapter(lv) for lv in (None, 1, 7, 8, 59, 60)] == [0, 0, 0, 1, 12, 12]
    widths = [b - a for a, b in zip(zone_music.CHAPTER_LEVELS, zone_music.CHAPTER_LEVELS[1:])]
    assert widths == sorted(widths, reverse=True) and widths[0] > widths[-1], "chapters get shorter"
    files = list(themes[0] + themes[1])

    cache = zone_music.cache_dir()
    cache.mkdir(parents=True)
    (cache / f"{files[0]}.mp3").write_bytes(b"ID3")
    assert zone_music.paths(files[:2]) == [cache / f"{files[0]}.mp3"]
    assert zone_music.missing(files[:2]) == [files[1]]
    assert zone_music.extract_missing(None, files) == 0, "without the game nothing is taken"


def test_cinematic_deaths_standstills_and_music(app, ctx, imported, tmp_path, monkeypatch):
    from forever_chronicle.domain.cinematic import Cue, Death
    from forever_chronicle.wow import zone_music

    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    start, end = points[0].time, max(p.end for p in points)
    # The adventure music's files (the game is not there in tests).
    cache = zone_music.cache_dir()
    cache.mkdir(parents=True)
    race = ctx.repo.character(cid).race_file
    assert race == "Tauren"
    for c in range(2 * len(zone_music.ADVENTURE)):
        for fdid in zone_music.adventure_file_ids(c, race):
            (cache / f"{fdid}.mp3").write_bytes(b"ID3")

    window = CinematicWindow(ctx, cid, start, end, speed=4)
    assert window.race == race
    window.resize(900, 600)
    window.show()
    window.timer.stop()
    assert window.music_now and all(p.parent == cache for p in window.music_now), "adventure music from the game"
    assert set(ctx.sound.music.tracks) == set(window.music_now)
    # A new chapter's music begins at its level-up, and only there.
    window.levels = Levels([E(window.t + 100, "level_up", level=8), E(window.t + 200, "level_up", level=9)])
    window.seek(window.t + 50)
    chapter_0 = window.music_now
    assert chapter_0 == tuple(zone_music.paths(zone_music.adventure_file_ids(0, race)))
    window.seek(window.t + 100)
    assert window.music_now == tuple(zone_music.paths(zone_music.adventure_file_ids(1, race))) != chapter_0
    player = ctx.sound.music
    assert sorted(player.pending or player.tracks) == sorted(window.music_now), "the player has the next theme"
    window.seek(window.t + 100)
    assert window.music_now == tuple(zone_music.paths(zone_music.adventure_file_ids(1, race))), "level 9: same chapter"

    # A death: the replay holds, the world turns grey, the marker lies as a headstone, then walks as a ghost.
    t = int(window.t) + 200
    window.deaths = [Death(t, t + 30, t + 120)]
    window.cues = [Cue(t, "event", "x", "✝", "#ff3333", event_type="player_died")]
    window.cue_times = [t]
    window.seek(t - 100)
    window.still_mode = "normal"
    for _ in range(400):
        window.advance(0.05)
        if window.hold > 0:
            break
    assert window.hold > 0 and window.t == t and window.title.tone == "death"
    for _ in range(int(cine.DEATH_HOLD / 0.05) - 2):
        window.advance(0.05)
    assert window.t == t and window.view.grey > 0.5, "held while the colour drains"
    assert window.marker.mode in ("dead", "dungeon", "taxi")
    window.seek(t + 60)
    assert window.view.grey == 1.0 and window.marker.mode in ("ghost", "dungeon", "taxi")
    window.seek(t + 200)
    assert window.view.grey == 0.0, "alive again: colour back"

    # Standstills: faster, skipped (up to the next moment), normal.
    span = (window.t + 10, window.t + 3000)
    window.still_spans, window.still_starts = [span], [span[0]]
    window.cues, window.cue_times, window.cue_index = [], [], 0
    window.seek(span[0] + 1)
    window.still_mode = "fast"
    fast = window.pace()
    window.still_mode = "normal"
    assert fast == pytest.approx(window.pace() * cine.STILL_FASTER)
    window.still_mode = "skip"
    window.paused = False
    window.advance(0.05)
    assert window.t >= span[1] and window.still_note > 0, "skipped, and named"
    window.cycle_still()
    assert window.still_mode == "normal" and ctx.config.extra["cine_still"] == "normal"

    # City maps on the seamless map: the destination's fades in during a flight's dive; a cut shows it at once.
    class World:
        def update(self, visible, scale, zone, dt):
            self.zone, self.dt = zone, dt
    saved = window.world, window.view_map, window.zone_now, window.voyage
    window.world, window.view_map, window.zone_now = World(), cine.maps.WORLD, 1413
    window.frame_dt = 0.05
    a, b = QPointF(0, 0), QPointF(100, 0)
    window.voyage = cine._Voyage(1454, a, a, b, 1, 0.5, 1, a, b, kind="teleport")
    window._update_world(1.0)
    assert window.world.zone == 1413, "pulling back and across: still the old place"
    window.voyage.age = window.voyage.out + window.voyage.across
    window._update_world(1.0)
    assert (window.world.zone, window.world.dt) == (1454, 0.05), "diving in: the destination city fades in"
    window.voyage, window.world_cut = None, True
    window._update_world(1.0)
    assert window.world.dt == 0.0 and not window.world_cut, "after a cut: at once"
    window.world, window.view_map, window.zone_now, window.voyage = saved
    assert window.still_button.text() == tr("cine.still.normal")

    # The camera zooms gently, never beyond its limits.
    window.seek(start)
    for _ in range(40):
        window.advance(0.1)
    assert cine.ZOOM_OUT_TAXI - 1e-6 <= window.zoom <= cine.ZOOM_IN_CLOSE + 1e-6
    window.close()


def test_death_cause_from_the_recap():
    from forever_chronicle.domain import event_types
    hogger = E(300, "player_died", killer="Hogger", damage=1234, overkill=37)
    killed_by = tr("evt.player_died.killed_by", killer="Hogger")
    assert event_types.death_cause(hogger) == killed_by and event_types.describe(hogger) == killed_by
    assert event_types.detail(hogger) == tr("evt.player_died.blow_overkill", how=tr("evt.player_died.melee"),
                                            damage=f"1{tr('common.thousands_sep')}234", overkill="37")
    fall = E(400, "player_died", environment="falling", damage=900)
    assert event_types.describe(fall) == tr("evt.player_died.env.falling")
    plain = E(500, "player_died")
    assert event_types.describe(plain) == tr("evt.player_died.text") and event_types.detail(plain) == ""
    cues = build_cues([hogger, plain], [], 0, 1000)
    assert [c.cause for c in cues] == [killed_by, ""], "the death title names the killer"


def test_profession_progress_comes_as_a_toast():
    learned = E(100, "profession_learned", name="Tailoring", icon=136249)
    rank = E(200, "profession_rank", name="Tailoring", maxRank=150)
    cues = build_cues([learned, rank], [], 0, 1000)
    assert [(c.kind, c.event_type) for c in cues] == [("event", "profession_learned"), ("event", "profession_rank")]
    assert (cues[0].heading, cues[0].title, cues[0].icon) == (tr("cine.banner.profession_learned"), "Tailoring", 136249)
    assert (cues[1].heading, cues[1].title) == (tr("cine.banner.profession_rank"),
                                                f"Tailoring: {tr('rank.journeyman')}")


def _window(ctx):
    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    window = CinematicWindow(ctx, cid, points[0].time, max(p.end for p in points), speed=4)
    window.resize(900, 600)
    window.show()
    window.timer.stop()
    window.intro = None
    return window


def test_cinematic_quest_pops(app, ctx, imported):
    # The question mark pops up where each quest was handed in, several one after the other.
    window = _window(ctx)
    t = window.t
    window.quest_times = [t + 10, t + 10, t + 11, t + 500]
    window._crossings(t, t + 20)
    quests = [b for b in window.pins.bursts if b.kind == "quest"]
    assert len(quests) == 3 and quests[0].age == 0 > quests[1].age > quests[2].age, "one after the other"
    assert len({q.shift for q in quests}) == 3, "side by side"
    for _ in range(5):
        window.pins.tick(0.2)
    image = QImage(400, 300, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    window.view.scene().render(painter)
    painter.end()
    window._crossings(t + 20, t + 30)
    assert len([b for b in window.pins.bursts if b.kind == "quest"]) == 3, "nothing handed in meanwhile"
    window.close()


def test_cinematic_ambience_and_flights(app, ctx, imported, tmp_path, monkeypatch):
    from forever_chronicle.domain import daylight
    from forever_chronicle.wow import game_sounds, zone_music
    window = _window(ctx)

    # Ambience: the place's own, by day or night, once its files are there.
    point = window.route.point_at(int(window.t))
    files = zone_music.ambience_file_ids(window.route.view_for(point), point.instance_id, daylight.night(window.t))
    if files:
        assert window._wanted_ambience() is None, "not taken from the game yet"
        cache = zone_music.cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        for fdid in files:
            (cache / f"{fdid}.ogg").write_bytes(b"OggS")
        assert window._wanted_ambience() == tuple(zone_music.paths(files))
    # A quick pass through another place keeps the ambience playing; a stay changes it.
    a, b = (tmp_path / "a.ogg",), (tmp_path / "b.ogg",)
    wanted = [a]
    monkeypatch.setattr(window, "_wanted_ambience", lambda: wanted[0])
    window._update_ambience(0.0, now=True)
    assert window.ambience_now == a and ctx.sound.ambience.tracks == list(a)
    wanted[0] = b
    for _ in range(3):
        window._update_ambience(cine.AMBIENCE_SETTLE / 4)
    wanted[0] = a
    window._update_ambience(0.1)
    assert window.ambience_now == a, "a quick pass through another zone keeps the ambience"
    wanted[0] = b
    for _ in range(6):
        window._update_ambience(cine.AMBIENCE_SETTLE / 4)
    assert window.ambience_now == b and b[0] in (ctx.sound.ambience.pending or ctx.sound.ambience.tracks)

    # Flight paths: the mount's call and wing beats, the wind, a glide at the landing.
    wind = tmp_path / "wind.wav"
    monkeypatch.setattr(game_sounds, "loop_path", lambda name: wind)
    call = "wind_rider_call" if window.marker.flyer == "wyvern" else "gryphon_call"
    played = ctx.sound.played
    played.clear()
    ctx.sound._last.clear()
    clock = [0.0]                                    # the sound's clock follows the replay's steps
    monkeypatch.setattr(ctx.sound, "now", lambda: clock[0])

    def fly(seconds: float) -> None:
        for _ in range(round(seconds / 0.1)):
            clock[0] += 0.1
            window.marker.tick(0.1)
            window._update_flight_sounds(0.1)

    window._set_flying(True, jump=False)
    window.marker.set_mode("taxi")
    assert list(played) == [call]
    fly(2.0)
    assert played.count("wing_flap") == 3 and "wing_flap_soft" not in played, "the first beats, with the marker's"
    assert ctx.sound.wind.target == 1.0 and ctx.sound.wind.tracks == [wind]
    ctx.sound.wind.step(1.0)
    window._update_flight_sounds(0.0)
    assert ctx.sound.ambience.under == pytest.approx(cine.AMBIENCE_UNDER_WIND), "the ambience steps back"
    fly(2.0)
    assert "wing_flap_soft" in played, "later beats are softer"
    window._set_flying(False, jump=False)
    window.marker.set_mode("walk")
    assert played[-1] == "wing_glide", "a longer flight glides in"
    window._update_flight_sounds(0.1)
    assert not window.wind_on and ctx.sound.wind.target == 0.0, "the wind dies away"

    # A connecting flight is not called again, and a short one is one gust without a landing.
    played.clear()
    ctx.sound._last.clear()
    window._set_flying(True, jump=False)
    window._update_flight_sounds(0.1)
    window._set_flying(False, jump=False)
    window._update_flight_sounds(0.1)
    assert call not in played and "wing_glide" not in played
    assert window.wind_on, "the gust blows on after the short flight"
    for _ in range(int(cine.WIND_HOLD / 0.1) + 1):
        window._update_flight_sounds(0.1)
    assert not window.wind_on
    window._set_flying(True, jump=True)
    assert not played or played[-1] != call, "a jump into a flight is no take-off"
    window.close()
