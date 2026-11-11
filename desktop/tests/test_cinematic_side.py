"""Cinematic mode, screenshots at the side (option "cine_side_photos", the default): the replay goes on while
the pictures land in a pile over the right edge; bursts wait their turn, big moments slow it down gently, a click
shows a picture large."""

import dataclasses
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from forever_chronicle.domain.cinematic import Cue, is_big  # noqa: E402
from forever_chronicle.ui import cinematic as cine  # noqa: E402
from forever_chronicle.ui.cinematic import CinematicWindow  # noqa: E402
from forever_chronicle.ui.cinematic_fx import SIDE_FLY, SIDE_LIFE, SIDE_STACK  # noqa: E402


def shot_cue(t, path, **kw):
    return Cue(t, "screenshot", "x", path=str(path), heading="Zone discovered", title="Elwynn", place="Goldshire",
               event_type=kw.pop("event_type", "zone_discovered"), trigger=kw.pop("trigger", "zone"), **kw)


def test_big_moments():
    assert is_big(shot_cue(1, "a", event_type="level_up", trigger="level", level=5))
    assert is_big(shot_cue(1, "a", event_type="boss_killed", trigger="boss"))
    assert is_big(shot_cue(1, "a", event_type="", trigger="manual")), "the player's own screenshot"
    assert is_big(shot_cue(1, "a", event_type="moment", trigger="moment"))
    assert not is_big(shot_cue(1, "a")), "a zone discovery plays without slowing down"
    assert not is_big(Cue(1, "level", "x", level=5, event_type="level_up")), "only screenshots"


def _window(ctx, tmp_path):
    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    start, end = points[0].time, max(p.end for p in points)
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    path = tmp_path / "shot.png"
    image.save(str(path))
    window = CinematicWindow(ctx, cid, start, end, speed=10)
    window.resize(1200, 800)
    window.show()
    window.timer.stop()                          # drive it by hand
    window.intro = None
    window.still_mode = "normal"
    return window, path, start, end


def _put_cues(window, cues):
    window.cues = sorted(window.cues[:window.cue_index] + cues + window.cues[window.cue_index:], key=lambda c: c.time)
    window.cue_times = [c.time for c in window.cues]


def test_side_pictures_play_while_the_replay_goes_on(app, ctx, imported, tmp_path):
    window, path, start, end = _window(ctx, tmp_path)
    assert window.side_style, "on by default"
    t0 = int(start + (end - start) / 3)
    window.seek(t0)

    # A burst: three pictures a second apart land SIDE_GAP apart in the pile on the right.
    _put_cues(window, [shot_cue(t0 + 5 + i, path) for i in range(3)])
    window.set_speed(1)
    landed, held = [], False
    for step in range(80):
        before = window.t
        window.advance(0.1)
        window.images.wait()       # pictures are decoded in the background
        held = held or window.photo_on or (window.t == before and not window.ended)
        if len(window.side.cards) > len(landed):
            landed.append(step * 0.1)
        if len(landed) == 3 and window.side.cards[-1].age >= SIDE_FLY:
            break
    assert not window.ended
    gaps = [b - a for a, b in zip(landed, landed[1:])]
    assert all(g >= cine.SIDE_GAP - 0.15 for g in gaps), gaps
    assert len(window.side.cards) == 3
    assert not held, "the replay never stops for a picture"
    assert "screenshot" in ctx.sound.played
    assert [c.slot for c in window.side.cards] == [2, 1, 0], "the newest on top, the ones before under it"
    assert window.keep_right < cine.KEEP_INSIDE, "the camera makes room on the right"
    assert all(window.side.screen_rect(c).center().x() > window.width() * 0.6 for c in window.side.cards)
    # Each one further under peeks out lower than the one above it.
    ys = [window.side.screen_rect(c).center().y() for c in window.side.cards]
    assert ys[0] > ys[1] > ys[2], ys

    # The pile holds SIDE_STACK; one more pushes the oldest off.
    assert SIDE_STACK == 5
    pixmap = window.side.cards[0].pixmap
    for i in range(SIDE_STACK + 1 - 3):
        window.side.add(shot_cue(t0 + 9 + i, path), pixmap, QPointF(600, 400))
    for _ in range(20):
        window.side.advance(0.1)
    assert len(window.side.cards) == SIDE_STACK, "the oldest fell off"
    assert sorted(c.slot for c in window.side.cards) == list(range(SIDE_STACK))

    # The alerts drop in at the top centre.
    event = Cue(t0, "event", "x", "•", "#ffd100", heading="h", title="t", event_type="rare_killed")
    window._show_cue(event)
    toast = window.toasts[-1]
    assert abs(toast.x() + toast.width() / 2 - window.width() / 2) <= 2 and toast.centred

    # A click on a picture shows it large and holds the replay; another click lets it fly back.
    card = next(c for c in window.side.cards if c.slot == 0 and c.age >= SIDE_FLY)
    window._clicked(window.side.screen_rect(card).center())
    assert window.enlarged and window.photo_on
    t = window.t
    for _ in range(20):
        window.advance(0.1)
        window.images.wait()       # pictures are decoded in the background
    assert window.t == t and window.photo_on, "held while the picture is shown large"
    window.toggle_pause()                        # Space goes on
    for _ in range(15):
        window.advance(0.1)
        window.images.wait()       # pictures are decoded in the background
    assert not window.photo_on and not window.enlarged and not window.paused

    # Pictures fade after a while; a jump clears the pile.
    for _ in range(int((SIDE_LIFE + 2) / 0.5)):
        window.side.advance(0.5)
    assert not window.side.cards and window.side.isHidden()
    window.side.add(shot_cue(t0, path), card.pixmap, QPointF(1, 1))
    _put_cues(window, [shot_cue(t0 + 20, path)])
    window.seek(start)
    assert not window.side.cards and not window.side_queue
    window.close()


def test_big_moments_slow_down_gently(app, ctx, imported, tmp_path):
    window, path, start, end = _window(ctx, tmp_path)
    t0 = int(start + (end - start) / 2)
    window.seek(t0)
    window.zone_share = 1.0
    small = shot_cue(t0 + 3, path)
    _put_cues(window, [small])
    window.seek(t0)
    window.zone_share = 1.0
    assert window.pace() == 1.0, "a zone discovery's picture does not slow it down"
    big = dataclasses.replace(small, event_type="boss_killed", trigger="boss")
    window.cues = [big if c is small else c for c in window.cues]
    window.seek(t0)
    window.zone_share = 1.0
    near = window.pace()
    assert cine.SIDE_SLOW <= near < 1.0, near
    window._queue_side(big)
    window.cue_index += 1                        # passed
    assert window.pace() == cine.SIDE_SLOW, "right after it, from SIDE_SLOW back to speed"
    window.side_ramp = cine.SIDE_RAMP / 2
    assert window.pace() > cine.SIDE_SLOW
    window.close()


def test_option_off_keeps_the_pauses(app, ctx, imported, tmp_path):
    ctx.config.extra["cine_side_photos"] = False
    window, path, start, end = _window(ctx, tmp_path)
    t0 = int(start + (end - start) / 3)
    window.seek(t0)
    _put_cues(window, [shot_cue(t0 + 2, path)])
    for _ in range(40):
        window.advance(0.1)
        window.images.wait()       # pictures are decoded in the background
        if window.photo_on:
            break
    assert window.photo_on and not window.side.cards, "the replay pauses for the picture in the middle"
    window.close()
