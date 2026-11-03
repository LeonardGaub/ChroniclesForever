"""The cinematic's 3D map (docs/3D_Map_Viewer.md, option "cine_3d"): the real terrain under the replay, filmed by
a drone camera.

The 3D stage mirrors the 2D cinematic instead of replacing it: the replay, its camera (centre and how much it
shows), the marker, the route, the pins and the companions all stay in the 2D scene (ui/cinematic.py,
cinematic_fx.py), in map coordinates. Each frame this stage takes them from there, places them in the 3D world
through the game's own map tables (TerrainPack.map_to_shared) and draws:
- the terrain, its liquids and the sky (terrain.py, sky.py), the buildings (buildings.py), the route as a ribbon
  on the ground (trail.py);
- over that, at screen size, the 2D items themselves where the 3D picture shows their places: the marker (its
  arrow turned to the drone's view), the pins on poles standing in the ground, bursts, the companions and the
  dashed line of a trip across the sea.
The window's overlays (titles, toasts, polaroids, clouds, the frame, the controls) lie above this widget as
before, and the video export records it like the 2D view.
"""

from __future__ import annotations

import bisect
import math
import time

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QOffscreenSurface, QOpenGLContext, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from ...domain import daylight, maps
from ...domain.terrain import TerrainPack
from ..cinematic_fx import GHOST_COLOR
from . import gl
from .camera import FOV, DroneCamera
from .director import CameraDirector
from .sky import look_for
from .buildings import BuildingRenderer
from .ground import GroundSplat
from .textures import GameTextures
from .terrain import TerrainRenderer
from .trail import GHOST, LIFT, TAXI, WALK, Trail, drape, flight_heights

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
DRONE = 0.32            # the drone shows this share of what the 2D picture shows round the marker (it is lower) ...
DRONE_NEAR, DRONE_FAR = 4000.0, 40000.0   # ... up to this many yards across; from the far one on (the opening,
                        # the credits, trips across the world) all of it
MIN_DISTANCE = 110.0
FLY_HIGH = 0.12         # an island-in-the-sky trip's marker flies this share of the camera distance high
ARC_HIGH = 0.15         # a trip across the world (boat, teleport, the spirit's flight) arcs this share of its
ARC_LOW, ARC_TOP = 60.0, 3000.0   # length high, within these yards
POLE = 0.075            # a pin's pole: this share of the camera distance tall
TAXI_STEP = 30.0        # flight paths are draped coarser (their height is smoothed anyway)
JUMP = 2.5              # a camera step longer than this many distances is a cut


def drone_share(shown: float) -> float:
    """The share of the 2D picture's width (shown yards) the drone shows."""
    f = min(1.0, max(0.0, math.log(max(shown, 1.0) / DRONE_NEAR) / math.log(DRONE_FAR / DRONE_NEAR)))
    return DRONE + (1 - DRONE) * f * f


def _game_files(window):
    """The player's game files for the textures (None without the game: then the minimap's colours)."""
    from ...wow import casc
    client = window.ctx.client() if getattr(window, "ctx", None) is not None else None
    return casc.open_client(client) if client is not None else None


def surface_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    return fmt


_SUPPORTED: bool | None = None


def supported() -> bool:
    """True when this PC gives an OpenGL 3.3 core context (checked once, off screen)."""
    global _SUPPORTED
    if _SUPPORTED is None:
        ctx = QOpenGLContext()
        ctx.setFormat(surface_format())
        surface = QOffscreenSurface()
        surface.setFormat(ctx.format())
        surface.create()
        ok = ctx.create() and surface.isValid() and ctx.makeCurrent(surface)
        if ok:
            fmt = ctx.format()
            ok = (fmt.majorVersion(), fmt.minorVersion()) >= (3, 3)
            ctx.doneCurrent()
        _SUPPORTED = bool(ok)
    return _SUPPORTED


def available() -> bool:
    """The 3D map can be shown: the terrain pack is there and the graphics card can draw it."""
    return TerrainPack.available() and supported()


class CinemaStage3D(QOpenGLWidget):
    def __init__(self, window, pack: TerrainPack | None = None):
        super().__init__(window)
        self.setFormat(surface_format())
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.window3d = window
        self.pack = pack or TerrainPack()
        self.terrain = TerrainRenderer(self.pack)
        self.textures = GameTextures(lambda: _game_files(window))
        self.buildings = BuildingRenderer(self.pack, self.terrain, self.textures)
        self.terrain.splat = GroundSplat(self.textures)
        self.trail = Trail(QColor(window.char_color))
        self.camera = DroneCamera()
        self.director = CameraDirector()
        self._dt = 0.0                    # real time stepped since the last picture (the cinematic's clock)
        self._places: dict = {}           # scene points placed in 3D (pins, companions): (map, x, y) -> point
        self.ready = False
        self.failed: str | None = None
        self._route_of = None             # the RouteItem the ribbon was built from
        self._stretches: list[np.ndarray] = []   # the draped route (rows t since start, east, north, z, ...)
        self._spans: list[tuple[float, float]] = []
        self._pending_route: list[np.ndarray] | None = None   # draped, not yet uploaded (needs the GL context)
        self._arc_of = None               # the voyage the 3D arc was made for, and its ends' heights
        self._last_target: np.ndarray | None = None
        self.vp = None
        self.frame = None
        self._stale = True                # the cinematic moved on since the view was worked out
        self._step_dt = 0.0
        self.items = ItemsLayer(window, self)

    # -- coordinates ----------------------------------------------------------------------------------------

    def shared(self, p: QPointF) -> tuple[float, float] | None:
        """A point of the cinematic's scene (the map it shows) in the shared 3D world."""
        view = self.window3d.view_map
        if view is None:
            return None
        return self.pack.map_to_shared(view, p.x() / W, p.y() / H)

    def ground(self, east: float, north: float) -> float:
        return float(self.pack.surface_many(np.array([east]), np.array([north]))[0])

    def over(self, east: float, north: float) -> float:
        """What the camera must stay above: the ground or a building's roof."""
        return float(self.pack.obstacles_many(np.array([east]), np.array([north]))[0])

    def project(self, point) -> QPointF | None:
        """A 3D point on the widget (logical pixels); None behind the camera."""
        if self.vp is None:
            return None
        clip = self.vp @ np.array([point[0], point[1], point[2], 1.0])
        if clip[3] <= 1e-6:
            return None
        x, y = clip[0] / clip[3], clip[1] / clip[3]
        return QPointF((x * 0.5 + 0.5) * self.width(), (0.5 - y * 0.5) * self.height())

    def place(self, p: QPointF, lift: float = 0.0) -> np.ndarray | None:
        """A scene point on the ground in 3D, lift yards above it (kept: pins and bursts stay where they are)."""
        key = (self.window3d.view_map, round(p.x(), 4), round(p.y(), 4))
        if key not in self._places:
            if len(self._places) > 20000:
                self._places.clear()
            s = self.shared(p)
            self._places[key] = None if s is None else np.array([s[0], s[1], self.ground(*s)])
        point = self._places[key]
        return None if point is None else point + np.array([0.0, 0.0, lift])

    # -- the route ------------------------------------------------------------------------------------------

    def _sync_route(self) -> None:
        """Drapes the route of the scene's RouteItem anew when it changed. A recorded point counts from when the
        player came there until they moved on (its standstill's end), as Route.glide moves the marker, so the
        ribbon and the marker (_route_point) leave a point together."""
        item = self.window3d.route_item
        if item is self._route_of:
            return
        self._route_of = item
        stretches = []
        start = self.window3d.start
        surface = self.pack.surface_many
        ends = {p.time: p.end for p in self.window3d.route.points}
        for times, pts, taxi, _runs, line_colors in (item.segs if item is not None else []):
            run = []

            def close():
                if len(run) > 1:
                    s = drape(run, surface, TAXI_STEP if taxi else 6.0)
                    if taxi:
                        s[:, 3] = flight_heights(s, TAXI_STEP)
                    stretches.append(s)

            for i, (t, p) in enumerate(zip(times, pts)):
                here = self.shared(p)
                if here is None:
                    close()
                    run = []
                    continue
                color = line_colors[i] or (line_colors[i + 1] if i + 1 < len(line_colors) else None) \
                    or QColor(self.window3d.char_color)
                kind = TAXI if taxi else GHOST if color.rgb() == GHOST_COLOR.rgb() else WALK
                row = (color.redF(), color.greenF(), color.blueF(), kind)
                run.append((t - start, here[0], here[1], *row))
                end = ends.get(int(t), t)
                if end > t and (i + 1 >= len(times) or end < times[i + 1]):
                    run.append((end - start, here[0], here[1], *row))
            close()
        self._stretches = stretches
        self._spans = [(float(st[0, 0]), float(st[-1, 0])) for st in stretches]
        self._pending_route = stretches

    def _route_point(self, rel: float) -> np.ndarray | None:
        """Where the draped route is at rel seconds since the start (the ribbon's head), None off it."""
        i = bisect.bisect_right([a for a, _ in self._spans], rel) - 1
        if i < 0 or rel > self._spans[i][1]:
            return None
        st = self._stretches[i]
        j = int(np.clip(np.searchsorted(st[:, 0], rel, side="right") - 1, 0, len(st) - 2))
        t0, t1 = st[j, 0], st[j + 1, 0]
        f = 0.0 if t1 <= t0 else min(1.0, max(0.0, (rel - t0) / (t1 - t0)))
        return st[j, 1:4] + (st[j + 1, 1:4] - st[j, 1:4]) * f

    # -- trips across the world ------------------------------------------------------------------------------

    def _arc_point(self, voyage, f: float) -> np.ndarray | None:
        """A point of a trip's 3D arc (0: start, 1: arrival): over the 2D arc's course, rising from the start's
        ground ARC_HIGH of the trip's length and coming down onto the arrival's. The marker and the trip's line
        both use it, so the marker flies at the line's head."""
        if self._arc_of is None or self._arc_of[0] is not voyage:
            a, b = self.place(voyage.origin, LIFT), self.place(voyage.target, LIFT)
            if a is None or b is None:
                return None
            high = min(ARC_TOP, max(ARC_LOW, ARC_HIGH * math.hypot(*(b[:2] - a[:2]))))
            self._arc_of = (voyage, a[2], b[2], high)
        _, za, zb, high = self._arc_of
        s = self.shared(voyage.arc(f))
        if s is None:
            return None
        z = za + (zb - za) * f + high * math.sin(math.pi * f)
        return np.array([s[0], s[1], max(z, self.ground(*s) + LIFT)])

    # -- GL -------------------------------------------------------------------------------------------------

    def initializeGL(self) -> None:
        try:
            self.terrain.initialize()
            self.buildings.initialize()
            self.trail.initialize()
            self.ready = True
        except Exception as e:          # no 3D then: the cinematic falls back to 2D (cinematic.py)
            self.failed = str(e)

    def step(self, dt: float) -> None:
        """The cinematic moved on by dt real seconds (also in the video export, frame by frame): the 3D picture and
        the items over it are drawn anew. The drone's view is worked out when they are drawn (fresh()), after the
        cinematic's step has moved the replay on (it calls this first), so marker and ribbon show the same moment."""
        self._step_dt += dt
        self._stale = True
        self.update()
        self.items.update()

    def fresh(self) -> None:
        """The view for the cinematic's state now, once per step (the picture and the items share it)."""
        if self._stale:
            self._stale = False
            dt, self._step_dt = self._step_dt, 0.0
            self._prepare(dt)

    def _marker_point(self, d: float) -> np.ndarray | None:
        w = self.window3d
        m = w.marker
        if not m.isVisible():
            return None
        s = self.shared(m.pos())
        if s is None:
            return None
        if w.voyage is not None:
            point = self._arc_point(w.voyage, w.voyage.travelled())
            if point is not None:
                return point
        if w.voyage is not None or w.sky_trip is not None or m.mode == "flight":
            return np.array([s[0], s[1], self.ground(*s) + FLY_HIGH * d])
        # On the route the marker is the ribbon's head itself (also high on a flight path).
        self._sync_route()
        on_route = self._route_point(w.t - w.start)
        if on_route is not None and math.hypot(on_route[0] - s[0], on_route[1] - s[1]) < 0.25 * d + 30:
            return on_route
        return np.array([s[0], s[1], self.ground(*s) + LIFT])

    def _prepare(self, dt: float) -> None:
        """The drone's view for the cinematic's state now (stored in self.frame for the picture and the items)."""
        w = self.window3d
        self.frame = None
        if w.view_map is None:
            return
        view = w.view
        scale = view.transform().m11()
        port = view.viewport().rect()
        center = view.mapToScene(port.center())
        c3 = self.shared(QPointF(center))
        if c3 is None or scale <= 0 or self.width() <= 0 or self.height() <= 0:
            return
        side = self.shared(QPointF(center.x() + 1.0, center.y()))
        per_unit = math.hypot(side[0] - c3[0], side[1] - c3[1]) if side else 44.7
        shown = port.width() / scale * per_unit                       # yards across the 2D picture
        h_fov = 2 * math.atan(math.tan(FOV / 2) * self.width() / max(1, self.height()))
        k = drone_share(shown)
        d = max(MIN_DISTANCE, k * shown / (2 * math.tan(h_fov / 2)))
        # The 2D camera keeps the marker near the middle, not in it; the drone keeps the same share of its own
        # (smaller) picture, so the marker stays in view.
        m2 = self.shared(w.marker.pos()) if w.marker.isVisible() else None
        marker = self._marker_point(d)
        if m2 is not None:
            # ... and right on the marker while the director wants it centred (a chase, a moment, a cut-away)
            k *= 1 - self.director.centre
            if marker is not None:
                m2 = (m2[0] + (marker[0] - m2[0]) * self.director.centre, m2[1] + (marker[1] - m2[1]) * self.director.centre)
            c3 = (m2[0] + (c3[0] - m2[0]) * k, m2[1] + (c3[1] - m2[1]) * k)
        target = np.array([c3[0], c3[1], self.ground(*c3)])
        jump = self._last_target is None or np.linalg.norm(target[:2] - self._last_target[:2]) > JUMP * d
        self._last_target = target
        self.camera.follow(min(0.25, dt), target, d, marker, self.over, jump=jump)
        d = self.director.direct(min(0.25, dt), w, self.camera, self.pack, marker, d)
        vp, inv_vp, eye = self.camera.matrices(self.width() / max(1, self.height()))
        self.vp = vp
        hour = daylight.hour_of(w.t) if w.daylight else None
        look = look_for(hour, w.light or daylight.DAY, view.grey, d)
        self.frame = (target, d, marker, vp, inv_vp, eye, look)
        self._dt += dt

    def paintGL(self) -> None:
        f = gl.functions()
        ratio = self.devicePixelRatioF()
        pw, ph = int(self.width() * ratio), int(self.height() * ratio)
        f.glViewport(0, 0, pw, ph)
        f.glClearColor(0.0, 0.0, 0.0, 1.0)
        f.glClear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
        if not self.ready:
            return
        self.fresh()
        if self.frame is None:
            return
        dt, self._dt = min(0.25, self._dt), 0.0
        w = self.window3d
        self._sync_route()
        if self._pending_route is not None:
            self.trail.set_route(self._pending_route)
            self._pending_route = None
        target, d, marker, vp, inv_vp, eye, look = self.frame
        self.terrain.update(target[0], target[1], d)
        self.buildings.update(target[0], target[1], d)
        now = time.perf_counter()
        self.terrain.draw_sky(inv_vp, look)
        cut = self.director.cut_away(eye, marker, d)
        self.terrain.draw(vp, eye, look, now, after_ground=lambda: self.buildings.draw(vp, eye, look, now, cut))
        walking = marker is not None and w.marker.mode in ("walk", "mount", "dead")
        self.trail.draw(vp, w.t - w.start, d, marker if walking else None, (pw, ph), look.grey,
                        (time.perf_counter() * 0.8) % 1.0, QColor(w.char_color), dt)

    # -- the 2D items over the 3D picture -------------------------------------------------------------------

    def paint_items(self, painter: QPainter) -> None:
        """The 2D items where the 3D picture shows their places (painted by ItemsLayer, just above this widget:
        QPainter inside paintGL would be left out of QWidget.render, the video export's picture)."""
        w = self.window3d
        self.fresh()
        if self.frame is None:
            return
        _, d, marker, *_ = self.frame
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        voyage = w.voyage
        if voyage is not None and voyage.line is not None and voyage.line.isVisible():
            self._paint_line(painter, voyage)
        if w.pins is not None:
            pole = POLE * d
            w.pins.paint_at(painter, lambda p: self._project_place(p, pole),
                            stand=lambda p: self._project_place(p, 0.0))
        for _, _, item in w.companion_marks:
            if item.isVisible():
                spot = self._project_place(item.pos(), LIFT)
                if spot is not None:
                    painter.save()
                    painter.translate(spot)
                    item.paint(painter, None, None)
                    painter.restore()
        if marker is not None:
            self._paint_marker(painter, marker)

    def _project_place(self, p: QPointF, lift: float) -> QPointF | None:
        point = self.place(p, lift)
        return None if point is None else self.project(point)

    def _paint_marker(self, painter: QPainter, marker: np.ndarray) -> None:
        m = self.window3d.marker
        here = self.project(marker)
        if here is None:
            return
        # The 2D arrow points along the map (north up); in the drone's view the same direction turns with it.
        a = math.radians(m.angle)
        ahead = self.project(marker + np.array([math.cos(a) * 8.0, -math.sin(a) * 8.0, 0.0]))
        angle = m.angle
        if ahead is not None and (ahead - here).manhattanLength() > 0.5:
            angle = math.degrees(math.atan2(ahead.y() - here.y(), ahead.x() - here.x()))
        saved = m.angle
        m.angle = angle
        painter.save()
        painter.translate(here)
        painter.scale(m.scale(), m.scale())
        m.paint(painter, None, None)
        painter.restore()
        m.angle = saved

    def _paint_line(self, painter: QPainter, voyage) -> None:
        """A trip's dashed line so far, on the 3D arc up to the marker."""
        reached = voyage.travelled()
        if reached <= 0:
            return
        points = []
        for f in np.linspace(0.0, reached, 49):
            point = self._arc_point(voyage, float(f))
            q = self.project(point) if point is not None else None
            if q is not None:
                points.append(q)
        if len(points) > 1:
            painter.setPen(voyage.line.pen())
            painter.drawPolyline(points)

    def shutdown(self) -> None:
        if self.ready:
            self.makeCurrent()
            self.buildings.shutdown()
            self.textures.shutdown()
            self.terrain.shutdown()
            self.doneCurrent()


class ItemsLayer(QWidget):
    """The marker, pins, bursts and companions over the 3D picture (CinemaStage3D.paint_items)."""

    def __init__(self, parent, stage: CinemaStage3D):
        super().__init__(parent)
        self.stage = stage
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            self.stage.paint_items(painter)
        finally:
            painter.end()
