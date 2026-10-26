"""Cinematic mode extras: teleports that fly, time of day, end credits and the game's own sounds."""

import os
import wave

import pytest
from conftest import event as E

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.domain import daylight, maps  # noqa: E402
from forever_chronicle.domain.cinematic import Death, Levels, teleports  # noqa: E402
from forever_chronicle.domain.credits import journey, km, sections  # noqa: E402
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint  # noqa: E402
from forever_chronicle.ui import sound  # noqa: E402

EK, KAL = maps.EASTERN_KINGDOMS, maps.KALIMDOR


def P(t, x, y=0.5, map_id=EK, until=None, taxi=False):
    return PositionPoint(t, until, map_id, x, y, None, taxi)


def test_teleports_fly_boats_sail():
    hearth = [P(0, 0.30), P(5, 0.30, until=20), P(30, 0.70)]          # cast standing, then far away at once
    found = teleports(Route(hearth), [], 0, 100)
    assert len(found) == 1 and (found[0].depart, found[0].arrive) == (20, 30) and not found[0].spirit
    assert found[0].origin == maps.world_xy(EK, 0.30, 0.5) and found[0].target == maps.world_xy(EK, 0.70, 0.5)
    assert teleports(Route(hearth), [], 25, 100) == [], "a teleport before the range is not flown"

    boat = [P(0, 0.30), P(10, 0.32), P(20, 0.34), P(50, 0.6, 0.5, KAL)]  # moving until the loading screen
    assert teleports(Route(boat), [], 0, 100) == [], "a boat or zeppelin crosses the sea instead"
    portal = [P(0, 0.40), P(4, 0.40, until=12), P(40, 0.6, 0.5, KAL)]
    assert len(teleports(Route(portal), [], 0, 100)) == 1, "standing before the other continent: a portal"

    assert teleports(Route([P(0, 0.30, until=20), P(500, 0.70)]), [], 0, 1000) == [], "a logout, not a teleport"
    assert teleports(Route([P(0, 0.30, until=20), P(22, 0.305)]), [], 0, 100) == [], "too short to fly"
    spirit = teleports(Route(hearth), [Death(10, 30, 60)], 0, 100)
    assert spirit[0].spirit, "the ghost's release to the graveyard"


def test_voyage_kinds():
    from PySide6.QtCore import QPointF
    from forever_chronicle.ui.cinematic import FLIGHTS, _Voyage

    a, b = QPointF(0, 0), QPointF(100, 0)
    sea = _Voyage(1, a, a, b, 1, 0.5, 1, a, b)
    flight = _Voyage(1, a, a, b, 1, 0.5, 1, a, b, kind="teleport")
    assert sea.life == sum(FLIGHTS["sea"][:3]) and flight.life == sum(FLIGHTS["teleport"][:3]) < sea.life
    flight.age = flight.life
    assert flight.marker() == b and flight.camera()[0] == pytest.approx(1)


def test_daylight():
    assert daylight.light(12) == daylight.DAY and daylight.light(2) == daylight.NIGHT
    assert daylight.light(19.5) == pytest.approx(daylight.DUSK) and daylight.light(23) == daylight.NIGHT
    dusk = daylight.light(19.0)
    assert all(d <= v <= 1 for d, v in zip(daylight.DUSK, dusk)), "between the keyframes it blends"


def test_sky_item_hides_by_day(app):
    from forever_chronicle.ui.cinematic_fx import SkyItem

    sky = SkyItem()
    sky.set_light(daylight.NIGHT)
    assert sky.isVisible() and sky.color.blue() > sky.color.red()
    sky.set_light(daylight.DAY)
    assert not sky.isVisible(), "full daylight draws nothing"


def test_credits_journey():
    walk = [P(0, 0.1), P(60, 0.2), P(120, 0.3), P(180, 0.4)]
    flight = [P(200, 0.4, taxi=True), P(260, 0.5, taxi=True), P(320, 0.6, taxi=True)]
    events = [E(100, "level_up", level=12), E(150, "quest_completed"), E(160, "quest_completed"),
              E(170, "player_died", killer="Hogger"), E(5000, "quest_completed")]
    j = journey(Route(walk + flight), events, Levels(events, 12), 0, 400, [Death(170, None, 175)])
    assert j.walked_yards == pytest.approx(0.3 * 40741, rel=1e-3) and km(j.walked_yards) == "11"
    assert j.flights == 1 and j.flown_yards == pytest.approx(0.2 * 40741, rel=1e-3)
    assert j.counts["quest_completed"] == 2, "only the range counts"
    assert j.deaths == 1 and j.killer[1] == 1 and "Hogger" in j.killer[0]
    assert (j.level_from, j.level_to) == (11, 12)

    inside = [PositionPoint(400, 450, None, None, None, 389, False), P(460, 0.4),
              PositionPoint(470, 520, None, None, None, 2999, False)]
    boss = [E(430, "boss_killed", instanceID=389)]
    assert journey(Route(walk + inside), boss, Levels([]), 0, 600).dungeons == [389], \
        "a dungeon is an instance where a boss died (a city's instance is none)"

    title, parts = sections(j, "Thrall", 0, 400, lambda m: f"zone {m}", lambda i: f"dungeon {i}")
    assert title[0] == "Thrall" and parts
    names = [line.name for part in parts for line in part.lines]
    assert "2" in names and any("km" in n for n in names) and not any(not n for n in names)


def test_game_sounds_replace_the_built_in_ones(tmp_path, monkeypatch, app):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    from forever_chronicle.wow import game_sounds

    assert sound.effect_path("teleport") == sound.ASSETS / "event.wav", "no game sound: the built-in alert"
    game = game_sounds.cache_dir() / "teleport.wav"
    game.parent.mkdir(parents=True)
    game.write_bytes(b"RIFF")
    assert sound.effect_path("teleport") == game and sound.effect_path("teleport", game=False) == \
        sound.ASSETS / "event.wav", "the game's sound plays while the option is on"
    assert game_sounds.missing() == [n for n in game_sounds.SOUNDS if n != "teleport"]
    assert sound.install_game_sounds(None) is None, "without the game nothing is taken"
    assert sound.game_sounds_on(AppConfig()) and not sound.game_sounds_on(AppConfig(extra={"game_sounds": False}))
    if sound.AUDIO:
        out = tmp_path / "decoded.wav"
        assert sound.decode_to_wav(sound.ASSETS / "level_up.wav", out)
        with wave.open(str(out)) as w:
            assert w.getframerate() == sound.WAV_RATE and w.getnchannels() == 2 and w.getnframes() > 1000


def test_window_ends_with_credits(app, ctx, imported, monkeypatch):
    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    start, end = points[0].time, max(p.end for p in points)
    from forever_chronicle.ui.cinematic import CinematicWindow

    window = CinematicWindow(ctx, cid, start, end, speed=10)
    window.resize(1200, 800)
    window.show()
    window.timer.stop()
    assert window.sky is not None and window.light is not None, "the time of day lies over the map"
    for _ in range(3000):
        window.advance(0.1)
        if window.ended:
            break
    assert window.ended and window.credits is not None and window.credits.isVisible(), "the credits roll"
    for _ in range(10):
        window.advance(0.1)
    assert not window.title.isVisible(), "instead of the end title (a last title makes way)"
    assert window.credits_seconds() > 5 and window.credits.sections
    seconds = window.credits.duration()
    for _ in range(int(seconds / 0.1) + 5):
        window.advance(0.1)
    assert window.credits.finished, "the last card stands"
    window.toggle_pause()                       # Space at the end: from the start again
    assert not window.ended and window.credits is None

    ctx.config.extra["cine_credits"] = False
    plain = CinematicWindow(ctx, cid, start, end, speed=10)
    plain.resize(800, 600)
    plain.show()
    plain.timer.stop()
    plain.seek(end - 1)
    plain.paused = False
    for _ in range(50):
        plain.advance(0.1)
    assert plain.ended and plain.credits is None and plain.title.isVisible(), "without credits: the end title"
    plain.close()
    window.close()


@pytest.mark.parametrize("world_art", [True, False])
def test_trips_to_and_from_a_sky_island_go_through_the_clouds(app, ctx, imported, monkeypatch, world_art):
    """Zephras Isle lies nowhere on the world map: a portal up and the flight down pass through the clouds, and the
    maps change under them (no fade from black). Without the seamless world map's art every place has its own map."""
    from forever_chronicle.ui import cinematic
    from forever_chronicle.ui.cinematic import CinematicWindow

    monkeypatch.setattr(cinematic.world_art, "available", lambda: world_art)
    cid = ctx.repo.list_characters()[0].character_id
    island = next(iter(maps.SKY_ISLANDS))
    ctx.repo.upsert_map_info(island, {"name": "Zephras Isle", "mapType": 3, "parent": maps.WORLD})
    t0 = max(p.end for p in ctx.repo.positions(cid)) + 10_000
    walk = lambda start, map_id, x0: [PositionPoint(start + 2 * i, None, map_id, x0 + 0.002 * i, 0.5, None, False)
                                      for i in range(30)]
    barrens, isle, down = walk(t0, 1413, 0.4), walk(t0 + 70, island, 0.6), walk(t0 + 142, 1413, 0.45)
    for p in barrens + isle + down:        # a portal up after 10 s, a flight down after 12 s
        ctx.repo.upsert_position(cid, p)
    ctx.repo.conn.commit()

    window = CinematicWindow(ctx, cid, t0, down[-1].time, speed=1)
    window.resize(1000, 640)
    window.show()
    window.timer.stop()
    window.paused = False
    trips, cloudy, black, held = [], 0.0, 0.0, 1.0
    for _ in range(2000):
        window.advance(0.05)
        trip = window.sky_trip
        if trip is not None:
            if not trips or trips[-1] is not trip:
                trips.append(trip)
            cloudy = max(cloudy, window.clouds.amount)
            black = max(black, window.cover_effect.opacity())
            if trip.target is not None and trip.age <= cinematic.SKY_RISE + cinematic.SKY_HOLD:
                held = min(held, window.clouds.amount)
        if window.ended:
            break
    assert [(t.portal, t.to_view) for t in trips] == [(True, island), (False, 1413)], "up by portal, down by flight"
    assert cloudy > 0.99 and black == 0.0, "the clouds close (almost) completely; no fade from black"
    assert held == 1.0, "the new map comes in under closed clouds, which stay closed a moment before parting"
    assert window.sky_trip is None and not window.clouds.isVisible() and window.marker.scale() == 1.0
    assert window.view_map == (maps.WORLD if window.seamless else 1413), "down on the Barrens"
    assert trips[0].target is not None and trips[1].end_scale > 0

    window.seek(isle[5].time)               # a jump onto the island is no trip
    assert window.sky_trip is None and window.view_map == island
    window.close()


def test_window_opens_with_a_dive(app, ctx, imported):
    """The replay starts over the whole map under the character's title and dives to where it begins; a jump
    skips the opening."""
    from forever_chronicle.ui import cinematic
    from forever_chronicle.ui.cinematic import CinematicWindow

    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    start, end = points[0].time, max(p.end for p in points)
    window = CinematicWindow(ctx, cid, start, end, speed=10)
    window.resize(1200, 800)
    window.show()
    window.timer.stop()
    t0 = window.t
    window.advance(0.05)
    far = window.view.transform().m11()
    assert window.intro is not None and window.title.isVisible() and window.title.text == window.char_name
    for _ in range(int((cinematic.INTRO_HOLD + cinematic.INTRO_DIVE) / 0.05) - 2):
        window.advance(0.05)
    assert window.t == t0 and window.view.transform().m11() > far, "the camera dives in; the replay waits"
    for _ in range(4):
        window.advance(0.05)
    assert window.intro is None and window.view.transform().m11() == pytest.approx(window._scale())
    window.advance(0.5)
    assert window.t > t0, "then it plays"
    window.seek(start)
    assert window.intro is None, "a jump never opens again"
    window.close()


def test_flight_marker_is_the_factions_mount(app):
    """On a flight path the marker is the faction's flying mount: a wind rider or a gryphon, wings beating."""
    from PySide6.QtGui import QImage, QPainter
    from forever_chronicle.ui.cinematic_fx import MarkerItem

    drawn = {}
    for kind in ("wyvern", "gryphon"):
        marker = MarkerItem()
        marker.flyer = kind
        marker.set_mode("taxi")
        frames = []
        for clock in (0.0, 0.14, 2.0):          # beating, beating, gliding
            marker.clock = clock
            image = QImage(144, 144, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            painter.translate(72, 72)
            marker.paint(painter, None)
            painter.end()
            frames.append(image)
        assert frames[0] != frames[1], "the wings beat"
        drawn[kind] = frames[2]
    assert drawn["wyvern"] != drawn["gryphon"], "each faction its own mount"
