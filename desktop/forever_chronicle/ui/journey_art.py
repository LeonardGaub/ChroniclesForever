"""The whole journey as one picture: the route on the seamless world map (Kino page banner, home card).

- frame(): where the picture looks. The route's bounds (world units) fill a chosen part of the picture (the
  banner keeps its left side free for the title), zoomed in no further than MAX_SCALE.
- background(): the world map for that frame, from the world's base picture or, close enough, its detail tiles
  (as in cinematic mode, ui/world_art.py); without the art a dark parchment instead. Darkened for the text.
- draw_route(): the route in the route colours (domain/route_colors.py), flight paths dashed: "dim" thin and quiet
  under everything, "bright" with a soft glow for the part being looked at.
- journey_colors() gives the colours with a key that changes when they could; with the Route from Route.cached
  (the same object while no point changed) callers keep finished pictures instead of painting tens of thousands of
  points on every refresh (cached_picture() for the home card, the Kino banner its own layers).
"""

from __future__ import annotations

import math
from weakref import WeakKeyDictionary

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from ..domain import maps
from ..domain.cinematic import Levels
from ..domain.route import Route, Segment
from ..domain.route_colors import RouteColors
from ..wow import map_art
from . import theme

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
PAD = 0.18                 # share of the route's size added round it
MIN_SIZE = 70              # world units the frame shows at least (a journey in one zone is not a smudge)
MAX_SCALE = 14.0           # screen px per world unit at most
MAX_TILES = 48             # more detail tiles than this and the base picture is enough
_base: tuple | None = None    # (path, picture) of the world's base picture
_run_memo: "WeakKeyDictionary[RouteColors, dict]" = WeakKeyDictionary()   # colours -> {id(segment): (segment, runs)}
_pictures: dict[tuple, tuple[tuple, Route, QPixmap | None]] = {}           # see cached_picture


def journey_colors(ctx, character_id: str, char=None, sessions=None) -> tuple[RouteColors, tuple]:
    """A character's route colours (the chosen mode, its level-ups and sessions) and a key that changes whenever
    they could. sessions: repo.sessions(character_id) if already at hand."""
    repo = ctx.repo
    level_ups = repo.events(character_id, types=("level_up",))
    if sessions is None:
        sessions = repo.sessions(character_id)
    starts = [s["started_at"] for s in sessions]
    level = char.level if char else None
    colors = RouteColors(ctx.map_colors, Levels(level_ups, level), starts)
    key = (ctx.map_colors, level, tuple((e.event_id, e.occurred_at) for e in level_ups), tuple(starts))
    return colors, key

def bounds(route: Route, start: int | None = None, end: int | None = None) -> QRectF | None:
    """The part of the world map (world units) the route of [start, end] crosses; None if nothing of it is on it."""
    xs, ys = [], []
    for seg in route.segments(maps.WORLD, start, end):
        for _, x, y in seg.points:
            xs.append(x * W)
            ys.append(y * H)
    if not xs:
        return None
    return QRectF(min(xs), min(ys), max(max(xs) - min(xs), 1.0), max(max(ys) - min(ys), 1.0))


class Frame:
    """World units to picture pixels: p = (world - origin) * scale."""

    def __init__(self, origin: QPointF, scale: float, size: QSize):
        self.origin, self.scale, self.size = origin, scale, size

    def to_screen(self, x: float, y: float) -> QPointF:
        return QPointF((x - self.origin.x()) * self.scale, (y - self.origin.y()) * self.scale)

    def view(self) -> QRectF:
        """The world units the picture shows."""
        return QRectF(self.origin.x(), self.origin.y(), self.size.width() / self.scale,
                      self.size.height() / self.scale)


def frame(area: QRectF, size: QSize, region: QRectF | None = None) -> Frame:
    """The frame showing area (world units) inside region (picture pixels; the whole picture if None)."""
    region = region or QRectF(0, 0, size.width(), size.height())
    w = max(area.width() * (1 + 2 * PAD), MIN_SIZE)
    h = max(area.height() * (1 + 2 * PAD), MIN_SIZE * H / W)
    scale = min(region.width() / w, region.height() / h, MAX_SCALE)
    centre = area.center()
    origin = QPointF(centre.x() - (region.center().x()) / scale, centre.y() - (region.center().y()) / scale)
    return Frame(origin, scale, size)


def _world_base() -> QImage | None:
    """The world's base picture, loaded once (per file)."""
    global _base
    path = map_art.world_base()
    if path is None:
        return None
    if _base is None or _base[0] != path:
        image = QImage(str(path))
        if image.isNull():
            return None
        _base = (path, image)
    return _base[1]


def _tiles(view: QRectF) -> list[tuple[int, int]] | None:
    unit = map_art.TILE_UNITS
    keys = [(i, j) for i in range(math.floor(view.left() / unit), math.floor(view.right() / unit) + 1)
            for j in range(math.floor(view.top() / unit), math.floor(view.bottom() / unit) + 1)]
    return keys if len(keys) <= MAX_TILES else None


def background(f: Frame, dpr: float = 1.0) -> QImage:
    """The world map behind the route for frame f (at dpr device pixels per pixel), darkened."""
    image = QImage(f.size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor(theme.BG))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    rect = QRectF(0, 0, f.size.width(), f.size.height())
    view = f.view()
    base = _world_base()
    if base is not None:
        px = base.width() / W
        painter.drawImage(rect, base, QRectF(view.left() * px, view.top() * px, view.width() * px,
                                             view.height() * px))
        keys = _tiles(view) if f.scale > map_art.BASE_PX * 1.1 else None
        unit, margin = map_art.TILE_UNITS, map_art.TILE_MARGIN
        for i, j in keys or ():
            path = map_art.world_tile(i, j)
            tile = QImage(str(path)) if path else QImage()
            if tile.isNull():
                continue
            target = QRectF(f.to_screen(i * unit, j * unit), f.to_screen((i + 1) * unit, (j + 1) * unit))
            painter.drawImage(target, tile, QRectF(margin, margin, tile.width() - 2 * margin,
                                                   tile.height() - 2 * margin))
        painter.fillRect(rect, QColor(10, 8, 6, 120))
    else:
        glow = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.7)
        glow.setColorAt(0, QColor("#2b2116"))
        glow.setColorAt(1, QColor(theme.BG))
        painter.fillRect(rect, glow)
    painter.end()
    return image


def draw_route(painter: QPainter, f: Frame, route: Route, colors: RouteColors, start: int | None = None,
               end: int | None = None, bright: bool = True) -> QPointF | None:
    """The route of [start, end] on the picture; returns where it ends (picture pixels), or None."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    width = 2.4 if bright else 1.3
    last = None
    for seg in route.segments(maps.WORLD, start, end):
        pts = [f.to_screen(x * W, y * H) for _, x, y in seg.points]
        if not pts:
            continue
        last = pts[-1]
        if len(pts) < 2:
            continue
        runs = _runs(colors, seg)
        if bright:      # a dark edge, then a soft glow under the whole segment
            path = QPainterPath(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            for w, color in ((width + 3.5, QColor(15, 9, 3, 190)), (width + 9, QColor(255, 209, 0, 34))):
                painter.setPen(_pen(color, w))
                painter.drawPath(path)
        for a, b, color in runs:
            path = QPainterPath(pts[a])
            for p in pts[a + 1:b + 1]:
                path.lineTo(p)
            c = QColor(color)
            c.setAlpha(240 if bright else 110)
            pen = _pen(c, width)
            if seg.taxi:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPath(path)
    return last


def _runs(colors: RouteColors, seg: Segment) -> list[tuple[int, int, str]]:
    """colors.runs for a segment, kept while both live (the dim and the bright route share them)."""
    memo = _run_memo.get(colors)
    if memo is None:
        memo = _run_memo[colors] = {}
    hit = memo.get(id(seg))
    if hit is None or hit[0] is not seg:
        hit = memo[id(seg)] = (seg, colors.runs([t for t, _, _ in seg.points], seg.taxi))
    return hit[1]


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_marker(painter: QPainter, at: QPointF, glow: float = 0.5) -> None:
    """Where the journey stands now: a gold point in a glow (glow 0..1 sizes the glow, for a calm pulse)."""
    radius = 12 + 8 * glow
    halo = QRadialGradient(at, radius)
    halo.setColorAt(0, QColor(255, 209, 0, int(150 + 60 * glow)))
    halo.setColorAt(0.35, QColor(255, 170, 0, 70))
    halo.setColorAt(1, QColor(255, 140, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(halo)
    painter.drawEllipse(at, radius, radius)
    painter.setPen(QPen(QColor("black"), 1.5))
    painter.setBrush(QColor(theme.GOLD))
    painter.drawEllipse(at, 4.5, 4.5)


def picture(route: Route, colors: RouteColors, size: QSize) -> QPixmap | None:
    """The whole journey in a small picture (home card); None if no part of the route is on the world map."""
    area = bounds(route)
    if area is None:
        return None
    f = frame(area, size)
    image = background(f)
    painter = QPainter(image)
    end = draw_route(painter, f, route, colors)
    if end is not None:
        draw_marker(painter, end)
    painter.setPen(QPen(QColor(theme.BORDER), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(QRectF(0.5, 0.5, size.width() - 1, size.height() - 1))
    painter.end()
    return QPixmap.fromImage(image)


def cached_picture(character_id: str, route: Route, colors: RouteColors, colors_key: tuple,
                   size: QSize) -> QPixmap | None:
    """picture(), painted again only when the route (a new Route from Route.cached), its colours, the size or the
    world art changed."""
    key = (colors_key, size.width(), size.height(), map_art.world_base())
    hit = _pictures.get(character_id)
    if hit is not None and hit[0] == key and hit[1] is route:
        return hit[2]
    pixmap = picture(route, colors, size)
    _pictures[character_id] = (key, route, pixmap)
    return pixmap
