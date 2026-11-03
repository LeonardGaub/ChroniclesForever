"""The cinematic's 3D map without a graphics card: its choice in the settings, the 2D fallback, the drone's framing,
the sky by the hour and the pins' poles. The GL drawing itself needs a real screen (tools/terrain_spike.py)."""

import math

import numpy as np
import pytest

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from forever_chronicle.ui.cinematic import CinematicWindow  # noqa: E402
from forever_chronicle.ui.cinematic_fx import Pin, PinsItem  # noqa: E402
from forever_chronicle.ui.stage3d import sky, stage  # noqa: E402


def window(ctx, **kw):
    cid = ctx.repo.list_characters()[0].character_id
    points = ctx.repo.positions(cid)
    w = CinematicWindow(ctx, cid, points[0].time, max(p.end for p in points), speed=10, **kw)
    w.timer.stop()
    return w


def test_3d_map_is_off_until_chosen(app, ctx, imported, monkeypatch):
    monkeypatch.setattr(stage, "available", lambda: True)
    monkeypatch.setattr(stage, "CinemaStage3D", lambda w: pytest.fail("built although not chosen"))
    w = window(ctx)
    assert w.stage3d is None
    assert w.view.viewport().updatesEnabled()


def test_3d_map_falls_back_to_2d_where_it_cannot_run(app, ctx, imported, monkeypatch):
    ctx.config.extra["cine_3d"] = True
    monkeypatch.setattr(stage, "available", lambda: False)     # no terrain pack or no OpenGL 3.3
    w = window(ctx)
    assert w.stage3d is None
    w.resize(800, 500)
    w.show()
    for _ in range(20):
        w.advance(0.1)                                         # plays in 2D as ever
    assert w.view.viewport().updatesEnabled()


class _Stage:
    """Stands in for the GL widget: records the steps and can fail like a broken driver."""

    def __init__(self, window):
        from PySide6.QtWidgets import QWidget
        self.steps, self.failed, self.shut = [], None, False
        self.items = QWidget(window)
        self._widget = QWidget(window)

    def step(self, dt):
        self.steps.append(dt)

    def setGeometry(self, r):
        self._widget.setGeometry(r)

    def setMouseTracking(self, on):
        pass

    def installEventFilter(self, f):
        pass

    def hide(self):
        self._widget.hide()

    def deleteLater(self):
        self._widget.deleteLater()

    def shutdown(self):
        self.shut = True


def test_3d_map_follows_the_replay_and_steps_back_to_2d_if_it_fails(app, ctx, imported, monkeypatch):
    ctx.config.extra["cine_3d"] = True
    monkeypatch.setattr(stage, "available", lambda: True)
    monkeypatch.setattr(stage, "CinemaStage3D", _Stage)
    w = window(ctx)
    assert isinstance(w.stage3d, _Stage)
    assert not w.view.viewport().updatesEnabled(), "the 2D view does not paint under the 3D map"
    w.advance(0.1)
    w.advance(0.05)
    assert w.stage3d.steps == [0.1, 0.05], "the drone moves with the replay's own clock (also in the export)"
    w.stage3d.failed = "no context"
    w.advance(0.1)
    assert w.stage3d is None and w.view.viewport().updatesEnabled()


def test_the_settings_offer_the_3d_map_off_and_only_where_it_runs(ctx, app, monkeypatch):
    from forever_chronicle.ui.pages import settings
    monkeypatch.setattr(settings, "three_d_available", lambda: True)
    page = settings.SettingsPage(ctx)
    page.refresh()
    box = next(b for k, b in page.options if k == "cine_3d")
    assert box.isEnabled() and not box.isChecked()
    box.setChecked(True)
    assert ctx.config.flag("cine_3d", False) is True
    monkeypatch.setattr(settings, "three_d_available", lambda: False)
    page.refresh()
    assert not box.isEnabled()


def test_the_drone_shows_less_close_up_and_everything_far_out():
    assert stage.drone_share(1000) == pytest.approx(stage.DRONE)
    assert stage.drone_share(stage.DRONE_FAR * 2) == pytest.approx(1.0)
    shares = [stage.drone_share(x) for x in (3000, 8000, 15000, 30000, 60000)]
    assert shares == sorted(shares)


def test_the_sky_follows_the_hour():
    noon = sky.look_for(13.0, (1.0, 1.0, 1.0), 0.0, 260)
    night = sky.look_for(1.0, (0.5, 0.58, 0.82), 0.0, 260)
    dusk = sky.look_for(19.6, (1.0, 0.8, 0.58), 0.0, 260)
    assert noon.sun[2] > 0.6 and noon.stars == 0.0
    assert night.stars > 0.9 and night.light < noon.light
    assert sum(night.zenith) < sum(noon.zenith)
    assert dusk.horizon[0] > dusk.horizon[2], "a warm horizon at dusk"
    assert sky.look_for(None, (0.5, 0.58, 0.82), 0.0, 260).stars == 0.0, "time of day off: always afternoon"
    morning, evening = sky.look_for(7.0, (1, 1, 1), 0, 260), sky.look_for(18.0, (1, 1, 1), 0, 260)
    assert morning.sun[0] > 0 > evening.sun[0], "the sun rises in the east and sets in the west"


def test_pins_stand_on_poles_where_the_3d_map_puts_them(app):
    pins = PinsItem([Pin(10, QPointF(5, 5), "!", QColor("gold"))])
    pins.set_time(20, animate=False)
    image = QImage(200, 200, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    pins.paint_at(painter, lambda p: QPointF(100, 60), stand=lambda p: QPointF(100, 150))
    painter.end()
    assert image.pixelColor(100, 120).alpha() > 0, "the pole runs from the ground up to the pin"
    assert image.pixelColor(100, 60).alpha() > 0
    image.fill(0)
    painter = QPainter(image)
    pins.paint_at(painter, lambda p: None)                     # not in view: nothing
    painter.end()
    assert not any(image.pixelColor(x, y).alpha() for x in range(0, 200, 10) for y in range(0, 200, 10))


def test_3d_map_needs_its_terrain_pack(tmp_path, monkeypatch):
    from forever_chronicle.domain import terrain
    monkeypatch.setattr(terrain, "pack_dir", lambda: tmp_path)
    monkeypatch.setattr(stage, "supported", lambda: True)
    assert not stage.available()


def test_the_drone_floats_over_cliffs_instead_of_riding_them():
    from forever_chronicle.ui.stage3d.camera import CLEARANCE, DroneCamera
    cliffs = lambda e, n: 150.0 if (e // 100) % 2 else 0.0          # noqa: E731  150 yd cliffs every 100 yd
    cam = DroneCamera()
    d, heights = 260.0, []
    for i in range(600):
        e = i * 3.0                                                  # walking east over the cliffs
        cam.follow(1 / 30, (e, 0.0, cliffs(e, 0.0)), d, (e, 0.0, cliffs(e, 0.0)), cliffs, jump=i == 0)
        eye = cam.eye()
        heights.append(eye[2])
        assert eye[2] >= cliffs(eye[0], eye[1]) + CLEARANCE - 60, "never deep in the ground"
    steps = np.abs(np.diff(heights[30:]))
    assert steps.max() < 0.03 * d, "no jolts: the height changes by at most 3 % of the distance a frame"
