"""What the cinematic mode (ui/cinematic.py) draws on top of the map art.

On the map (scene items):
- RouteItem: the route up to the current moment. Older parts are thin and dim; the last TRAIL_SECONDS grow
  brighter and wider in small steps towards the marker, the newest minutes glow. Flight paths are dashed, and
  the newest ones' dashes move along the line (in the trail); corpse runs are pale and dotted.
- MarkerItem: the player, at screen size: a disc in the class colour with a pulsing halo and an arrow in the
  direction of travel; a flapping gryphon on flight paths and a swirling portal inside dungeons. Mounted it
  carries a small medallion with the mount's game icon. Dead it is a dim grave mark, released a floating wisp
  (the ghost). Flying to a teleport's destination it is a bright arcane comet.
- CompanionItem: a friend from the player's group whose route the app knows: a small disc in their class colour
  with their name.
- PinsItem: a pin where each event of the replay happened, once it has happened (screenshots as small
  polaroids), and short bursts on the map at the moment something happens (a teleport: an arcane swirl where the
  player vanishes and a flash where they arrive; a completed quest: the game's yellow question mark pops up and
  rises away).
- SkyItem: the time of day over the map (domain/daylight.py), multiplied onto the map art.
- CinemaView: the view showing the map; while the player is dead it drains the colour like the game's spirit
  world (grey with a cold blue light).

Over the window (widgets, all transparent for the mouse):
- CinemaFrame: a vignette and letterbox bars that slide in when the replay starts.
- TitleCard: the large title of a level-up (and of the end): it scales in with a glow and a passing shine. A
  death gets the same card in dark red.
- AchievementToast: an event, as a small achievement alert that slides in from the right (drops in at the top
  centre where the screenshots stand at the side).
- CloudCover: clouds that close over the picture and part again, for trips to and from an island in the sky.
- PhotoOverlay: a screenshot as a polaroid that flies out from the marker after a white flash, drifts slowly
  under an achievement banner while it is shown, and flies back to its pin. A level-up's picture gets a
  ribbon saying "Level up" instead (its title has just named the level).
- SideShots: screenshots in a pile over the right edge of the map while the replay goes on (option
  "cine_side_photos"): each flies from where it was taken to the top of the pile.
"""

from __future__ import annotations

import bisect
import math
import random
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from PySide6.QtWidgets import QGraphicsColorizeEffect, QGraphicsItem, QGraphicsView, QWidget

from ..domain import maps
from ..domain.cinematic import Cue
from ..domain.route_colors import TAXI, RouteColors, hex_color
from ..i18n import format_datetime
from . import icons, theme

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
FADE_SECONDS = 0.45
TRAIL_SECONDS = 15 * 60
TRAIL_STEPS = 8            # the trail gets brighter in this many steps
GLOW_SECONDS = 4 * 60      # the newest part of the route glows
DASH_SPEED = 5.0           # dash pattern lengths (in pen widths) per real second on flight paths
DASH = (2.2, 1.6)          # dash and gap, in pen widths
OUTLINE = QColor("#1a0f05")
TRIM, TRIM_DARK, BANNER_HEADING = QColor("#c9a24a"), QColor(201, 162, 74, 90), QColor("#e6c77a")
PAPER, PAPER_EDGE, INK = QColor("#f3eee2"), QColor("#c9bea6"), QColor("#3b2a18")
GOLD_LETTERS = ("#fff6c8", theme.GOLD, "#b07a10")   # large gold letters: top, middle, bottom of their fill
GOLD_GLOW = QColor(255, 196, 60)
SYMBOL_FONTS = ["Segoe UI Symbol", "Segoe UI", "DejaVu Sans"]
PIN_POP = 0.35             # seconds a new pin takes to pop up
PIN_SPRITE = 56            # a pin is drawn once into a picture this size (screen px), centred on its spot
PIN_NEAR = 6               # pins closer than this on screen (px) count as one place and fan out
CARD_DETAIL = 1.5          # a side picture's paper and banner are drawn this much finer than the screen once
BURST_LIFE = {"level": 1.7, "death": 1.5, "event": 1.1, "revive": 1.8, "spirit": 1.6, "teleport": 1.5, "arrive": 1.4,
              "quest": 1.6}
BURST_REACH = {"level": 110, "death": 70, "event": 55, "revive": 90, "spirit": 60, "teleport": 80, "arrive": 95,
               "quest": 0}
QUEST_STAGGER = 0.22       # seconds between quest pops that come together (several quests handed in at once)
QUEST_SIZE = 34            # the question mark's height on screen (the game's texture is 16 px)
GHOST_COLOR = QColor("#b9d3ea")   # the corpse run on the map, and the ghost
ARCANE_COLOR = QColor("#8fc4ff")  # teleports: the swirl, the comet and its trail
GHOST_DOTS = (0.1, 2.2)    # dotted line of the corpse run, in pen widths
ROUTE_CHUNK = 96           # lines per piece of the route (pieces outside the view are not drawn)
LAYER_MARGIN = 0.25        # the old route's cached layer reaches this share of the view past each edge
LAYER_ZOOM = 1.12          # ... and the next one is drawn once the zoom moved further than this factor
LAYER_BUDGET = 0.004       # seconds per frame for drawing the next layer
LAYER_STEADY = 0.01        # ... which starts once the zoom changes less than this (log) per frame
LOD_PIXEL = 0.6            # zoomed out, route points closer than this (screen px) are left out
LOD_BASE = 0.02            # ... in steps of scene units doubling from this one
WORLD_LAYER_SCALE = 2.5    # screen px per scene unit of the whole map's layer
SPIRIT_TINT = QColor(96, 116, 142)    # the spirit world's light: grey tones in this colour
LETTERBOX = 2.2            # aspect ratio of the picture between the bars
BARS_SECONDS = 1.2         # time the bars take to slide in


# -- helpers ------------------------------------------------------------------------------------------------

_SKIN: dict[str, QPixmap] = {}


def skin_pixmap(name: str) -> QPixmap:
    """A picture of the skin (tools/build_ui_skin.py: the game's own UI textures), loaded once."""
    if name not in _SKIN:
        _SKIN[name] = QPixmap(str(theme.SKIN / name))
    return _SKIN[name]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ease_out(x: float) -> float:
    return 1 - (1 - clamp(x)) ** 3


def ease_in(x: float) -> float:
    return clamp(x) ** 3


def ease_in_out(x: float) -> float:
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out_back(x: float) -> float:
    """Overshoots a little before settling (pins popping up)."""
    x = clamp(x) - 1
    return 1 + 2.70158 * x ** 3 + 1.70158 * x ** 2


def smooth(dt: float, tau: float) -> float:
    """Share of the way to a target covered in dt seconds when following it with time constant tau."""
    return 1 - math.exp(-dt / tau)


def geo_mix(a: float, b: float, f: float) -> float:
    """Between a and b (both > 0) geometrically: zooming from scale a to b this way feels even."""
    return math.exp(math.log(a) + (math.log(b) - math.log(a)) * f)


def lerp_point(a: QPointF, b: QPointF, f: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * f, a.y() + (b.y() - a.y()) * f)


def scatter(t: int) -> int:
    """16 bits that look random but are the same for the same moment (a picture's tilt and pan)."""
    return (t * 2654435761) & 0xFFFF


def with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlpha(int(clamp(alpha, 0, 255)))
    return c


def pixel_font(px: float, bold: bool = False, families=None) -> QFont:
    font = theme.heading_font(10, bold)
    if families:
        font.setFamilies(families)
    font.setPixelSize(max(6, int(px)))
    return font


def cropped(pixmap: QPixmap, aspect: float, zoom: float = 1.0, drift: QPointF = QPointF()) -> QRectF:
    """The part of pixmap that fills a box of the given aspect ratio: centred, zoomed in by zoom and moved by
    drift (share of the free room, -1..1) for a slow pan."""
    w, h = pixmap.width(), pixmap.height()
    if w / max(1, h) > aspect:
        cw, ch = h * aspect, h
    else:
        cw, ch = w, w / aspect
    cw, ch = cw / zoom, ch / zoom
    x = (w - cw) / 2 * (1 + clamp(drift.x(), -1, 1))
    y = (h - ch) / 2 * (1 + clamp(drift.y(), -1, 1))
    return QRectF(x, y, cw, ch)


def bronze(center: QPointF, radius: float) -> QRadialGradient:
    """The dark bronze fill of a medallion, lit from center."""
    fill = QRadialGradient(center, radius)
    fill.setColorAt(0, QColor(70, 52, 28))
    fill.setColorAt(1, QColor(12, 9, 5))
    return fill


def draw_polaroid(painter: QPainter, paper: QRectF, photo: QRectF, pixmap: QPixmap, shadow: QPointF) -> None:
    """A small polaroid: the paper over a hard shadow moved by shadow, the picture cropped to fill photo."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 110))
    painter.drawRect(paper.translated(shadow))
    painter.setPen(QPen(PAPER_EDGE, 1))
    painter.setBrush(PAPER)
    painter.drawRect(paper)
    painter.drawPixmap(photo, pixmap, cropped(pixmap, photo.width() / photo.height()))


def draw_shadowed_text(painter: QPainter, rect: QRectF, text: str, pen, alpha: int = 200,
                       offset: float = 2.0) -> None:
    """Text centred in rect (pen: a colour or a pen) over a black copy (alpha) moved down and right by offset."""
    painter.setPen(QColor(0, 0, 0, alpha))
    painter.drawText(rect.translated(offset, offset), Qt.AlignmentFlag.AlignCenter, text)
    painter.setPen(pen)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def _diamond(painter: QPainter, center: QPointF, size: float, color: QColor) -> None:
    painter.save()
    painter.translate(center)
    painter.rotate(45)
    painter.fillRect(QRectF(-size / 2, -size / 2, size, size), color)
    painter.restore()


def draw_flourish_heading(painter: QPainter, center: QPointF, text: str, px: float, color: QColor, trim: QColor,
                          reach: float = 140.0, least: float = 0.0) -> None:
    """A small heading in spaced capitals centred on center, between gold lines that fade outwards from a diamond
    next to it. The lines reach `reach` past the text's half width, at least `least` from the centre."""
    font = pixel_font(px)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 135)
    text = text.upper()
    tw = QFontMetrics(font).horizontalAdvance(text)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QRectF(center.x() - tw / 2 - 10, center.y() - px, tw + 20, 2 * px), Qt.AlignmentFlag.AlignCenter,
                     text)
    end = max(least, tw / 2 + reach)
    for sign in (-1, 1):
        x0, x1 = center.x() + sign * (tw / 2 + 18), center.x() + sign * end
        line = QLinearGradient(x0, 0, x1, 0)
        line.setColorAt(0, trim)
        line.setColorAt(1, with_alpha(trim, 0))
        painter.fillRect(QRectF(min(x0, x1), center.y() - 0.75, abs(x1 - x0), 1.5), line)
        _diamond(painter, QPointF(x0, center.y()), 6, trim)


def _gold_letters(painter: QPainter, path: QPainterPath, glow: QColor, glows, outline: float, letters,
                  shine: float) -> None:
    """Large letters (path): a warm glow (glows: (pen width, alpha) from the outside in), a dark outline, a fill
    from top to bottom (letters: three colours) and a passing shine (0 to 1; none outside)."""
    box = path.boundingRect()
    for width, alpha in glows:
        pen = QPen(with_alpha(glow, alpha), width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(path, pen)
    pen = QPen(QColor(20, 10, 0, 235), outline)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.strokePath(path, pen)
    fill = QLinearGradient(0, box.top(), 0, box.bottom())
    for at, color in zip((0, 0.45, 1), letters):
        fill.setColorAt(at, QColor(color))
    painter.fillPath(path, fill)
    if 0 < shine < 1:
        band = box.height() * 0.9
        x = box.left() - band + shine * (box.width() + 2 * band)
        light = QLinearGradient(x, box.top(), x + band, box.top() + band * 0.5)
        light.setColorAt(0, QColor(255, 255, 255, 0))
        light.setColorAt(0.5, QColor(255, 255, 255, 190))
        light.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setClipPath(path)
        painter.fillRect(box.adjusted(-4, -4, 4, 4), light)
        painter.setClipping(False)


def _plate(painter: QPainter, rect: QRectF, stops, radius: float = 0.0) -> None:
    """A dark plate with a soft shadow, gold trim and a fine inner line (stops: its fill from top to bottom)."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 90))
    painter.drawRoundedRect(rect.translated(3, 4), radius, radius)
    fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    for at, color in stops:
        fill.setColorAt(at, color)
    painter.setPen(QPen(TRIM, 2))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, radius, radius)
    painter.setPen(QPen(TRIM_DARK, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inner = max(0.0, radius - 3)
    painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), inner, inner)


# -- route --------------------------------------------------------------------------------------------------

class _OldLayer:
    """The route older than the trail, drawn once and reused while the camera stays near it: its outlines (an
    alpha mask) and its lines, each at the old route's alpha, so a road walked twice looks stronger as before.
    Pieces are only ever added whole and in order, so the layer looks as if the old route had been drawn at once."""

    def __init__(self, view_transform: QTransform, rect: QRectF, dpr: float, segments: int):
        self.dpr = dpr
        self.scale = view_transform.m11()
        self.to_layer = view_transform * QTransform.fromTranslate(-rect.left(), -rect.top())   # scene -> layer
        self.from_layer = self.to_layer.inverted()[0]
        to_scene = view_transform.inverted()[0]
        self.scene_rect = to_scene.mapRect(rect)
        mx, my = rect.width() * LAYER_MARGIN / (1 + 2 * LAYER_MARGIN) / 2, \
            rect.height() * LAYER_MARGIN / (1 + 2 * LAYER_MARGIN) / 2
        self.inner = to_scene.mapRect(rect.adjusted(mx, my, -mx, -my))   # past this, a new layer is prepared
        size = QSize(math.ceil(rect.width() * dpr), math.ceil(rect.height() * dpr))
        self.outline = QImage(size, QImage.Format.Format_Alpha8)
        self.lines = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        for image in (self.outline, self.lines):
            image.setDevicePixelRatio(dpr)
            image.fill(0)
        self.done = [0] * segments          # per segment: the lines up to this point are on the layer
        pad = 8 / self.scale
        self.cull = self.scene_rect.adjusted(-pad, -pad, pad, pad)

    def ratio(self, view_transform: QTransform) -> float:
        return view_transform.m11() / self.scale

    def draw(self, painter: QPainter, image: QImage) -> None:
        """Only the part of the layer on screen: the layer reaches well past the view (LAYER_MARGIN), and blending
        all of it, scaled and smoothed, every frame cost more than drawing the trail."""
        painter.save()
        painter.setWorldTransform(self.from_layer * painter.worldTransform())
        seen = painter.worldTransform().inverted()[0].mapRect(QRectF(painter.viewport()))
        d = self.dpr
        left, top = max(0, math.floor(seen.left() * d) - 2), max(0, math.floor(seen.top() * d) - 2)
        right = min(image.width(), math.ceil(seen.right() * d) + 2)
        bottom = min(image.height(), math.ceil(seen.bottom() * d) + 2)
        if right > left and bottom > top:
            source = QRectF(left, top, right - left, bottom - top)
            painter.drawImage(QRectF(left / d, top / d, (right - left) / d, (bottom - top) / d), image, source)
        painter.restore()


class RouteItem(QGraphicsItem):
    """The route on one map, painted up to time t; the last part up to the moving marker (head). Lines within a
    ghost span (from the release to coming back to life) are the corpse run.

    The route is cut into pieces of ROUTE_CHUNK lines; pieces outside the view are skipped. Whole pieces older
    than the trail are kept on an _OldLayer while the camera stays near, so a frame draws only the trail, the glow
    and the rest of the old route since the last whole piece (old flight paths too: their dashes stand still, only
    the trail's move). When the
    camera nears the layer's edge or zooms, a new layer is drawn a few pieces per frame (LAYER_BUDGET) and takes
    over once complete. While the camera zooms fast (flights between zones) the old route is drawn directly, far
    out from a layer of the whole map; once it is steady again a layer is drawn at once. Zoomed out, points closer
    than about a pixel are left out (_points)."""

    def __init__(self, segments, colors: RouteColors, ghost_spans=()):
        super().__init__()
        self.setZValue(2)                        # above the map art and the light
        self.segs = []
        self.pieces: list[tuple[list, list[int]]] = []   # per segment: [(first, last point, colour, box)], firsts
        self.has_taxi = False
        for seg in segments:
            times = [p[0] for p in seg.points]
            # Colour of the line from point i-1 to point i: the route's colour where it ends, or the corpse run's.
            line_colors = [None] + [QColor(colors.at(t, seg.taxi)) for t in times[1:]]
            if ghost_spans and not seg.taxi:
                for i in range(1, len(times)):
                    if any(a < times[i] <= b for a, b in ghost_spans):
                        line_colors[i] = GHOST_COLOR
            pts = [QPointF(x * W, y * H) for _, x, y in seg.points]
            runs = self._runs(line_colors)
            self.segs.append((times, pts, seg.taxi, runs, line_colors))
            pieces = []
            for a, b, color in runs:
                for first in range(a, b, ROUTE_CHUNK):
                    last = min(b, first + ROUTE_CHUNK)
                    # Padded: a straight line's box has no height (or width), and such a box never intersects.
                    box = QPolygonF(pts[first:last + 1]).boundingRect().adjusted(-0.01, -0.01, 0.01, 0.01)
                    pieces.append((first, last, color, box))
            self.pieces.append((pieces, [p[0] for p in pieces]))
            self.has_taxi = self.has_taxi or seg.taxi
        self.t = 0.0
        self.head: QPointF | None = None
        self.phase = 0.0
        self.layer: _OldLayer | None = None          # the one shown
        self.next_layer: tuple[_OldLayer, list[int]] | None = None   # one being drawn, and how far it goes
        self.layered = False                          # a layer was drawn for this map
        self.world_layer: _OldLayer | None = None    # the whole map, far out (zooming fast on a flight)
        self.last_scale: float | None = None
        self._pens: dict = {}
        self._lod: dict[tuple[int, int, int], list[QPointF]] = {}   # simplified pieces, see _points

    @staticmethod
    def _runs(line_colors) -> list[tuple[int, int, QColor]]:
        """(first point, last point, colour) of the stretches whose lines share a colour."""
        runs: list[tuple[int, int, QColor]] = []
        for i in range(1, len(line_colors)):
            color = line_colors[i]
            if runs and runs[-1][1] == i - 1 and runs[-1][2] == color:
                runs[-1] = (runs[-1][0], i, color)
            else:
                runs.append((i - 1, i, color))
        return runs

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -10, W + 20, H + 20)

    def set_time(self, t: float, head: QPointF | None) -> None:
        self.t, self.head = t, head
        self.update()

    def advance_phase(self, dt: float) -> None:
        """Moves the dashes of flight paths along."""
        self.phase = (self.phase + dt * DASH_SPEED) % 1000.0
        if self.has_taxi:
            self.update()

    def _pen(self, color: QColor, width: float, alpha: float, taxi: bool) -> QPen:
        pen = QPen(with_alpha(color, alpha), width)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if taxi:
            pen.setDashPattern(list(DASH))
            period = sum(DASH)
            pen.setDashOffset(period - self.phase % period)   # a falling offset moves the dashes forward
        elif color.rgb() == GHOST_COLOR.rgb() and width < 10:
            pen.setDashPattern(list(GHOST_DOTS))
        return pen

    def _old_pen(self, color: QColor, outline: bool, taxi: bool = False) -> QPen:
        """The pen of the old route: kept, as it never changes. A flight path's dashes stand still here (only the
        trail's move): moving them meant drawing every flight ever taken anew each frame, which grew with each one."""
        taxi = taxi and not outline
        key = (OUTLINE.rgba() if outline else color.rgba(), outline, taxi)
        if key not in self._pens:
            pen = self._pen(OUTLINE, 5, 90, False) if outline else self._pen(color, 3, 120, False)
            if taxi:
                pen.setDashPattern(list(DASH))
            self._pens[key] = pen
        return self._pens[key]

    def painted(self) -> int:
        """Number of route points painted at the current time (for tests)."""
        return sum(bisect.bisect_right(seg[0], self.t) for seg in self.segs)

    def _trail_lines(self, times, pts, line_colors, first: int, n: int):
        """(age, colour, start, end) of the lines in the trail: from point first on, up to the marker."""
        lines = [(self.t - times[i], line_colors[i], pts[i - 1], pts[i]) for i in range(first + 1, n)]
        if n < len(pts) and self.head is not None:
            lines.append((0.0, line_colors[n], pts[n - 1], self.head))
        return lines

    @staticmethod
    def _group(lines, key):
        """Consecutive lines with the same key joined into polylines: [(key, points)]."""
        groups = []
        for line in lines:
            k = key(line)
            if groups and groups[-1][0] == k and groups[-1][1][-1] == line[2]:
                groups[-1][1].append(line[3])
            else:
                groups.append((k, [line[2], line[3]]))
        return groups

    def _whole(self, k: int, first: int) -> int:
        """Where the last whole piece of segment k before point first ends (layers take whole pieces only)."""
        pieces, firsts = self.pieces[k]
        i = bisect.bisect_right(firsts, first) - 1
        if i < 0:
            return 0
        start, last = pieces[i][0], pieces[i][1]
        return last if last <= first else start

    def _points(self, k: int, i: int, scale: float) -> list[QPointF]:
        """The points of piece i of segment k, without those closer than about a pixel (at scale, screen px per
        scene unit) to the one before: zoomed out, thousands of points fall on a few pixels."""
        first, last = self.pieces[k][0][i][:2]
        pts = self.segs[k][1]
        level = int(math.log2(LOD_PIXEL / scale / LOD_BASE)) if scale < LOD_PIXEL / LOD_BASE else -1
        if level < 0:
            return pts[first:last + 1]
        key = (k, i, level)
        kept = self._lod.get(key)
        if kept is None:
            near = LOD_BASE * 2 ** level
            kept = [pts[first]]
            x, y = pts[first].x(), pts[first].y()
            for p in pts[first + 1:last]:
                if abs(p.x() - x) + abs(p.y() - y) >= near:
                    kept.append(p)
                    x, y = p.x(), p.y()
            kept.append(pts[last])
            self._lod[key] = kept
        return kept

    def _draw_old(self, painter: QPainter, k: int, lo: int, hi: int, pen_of, cull: QRectF | None = None,
                  scale: float = math.inf) -> None:
        """The lines of segment k ending at points lo+1 .. hi, a polyline per piece (pieces outside cull are
        skipped), each with pen_of(colour); whole pieces simplified for the scale (screen px per scene unit)."""
        if hi <= lo:
            return
        pieces, firsts = self.pieces[k]
        pts = self.segs[k][1]
        i = max(0, bisect.bisect_right(firsts, lo) - 1)
        while i < len(pieces):
            first, last, color, box = pieces[i]
            i += 1
            if first >= hi:
                break
            if last <= lo or (cull is not None and not cull.intersects(box)):
                continue
            painter.setPen(pen_of(color))
            if lo <= first and last <= hi:
                painter.drawPolyline(self._points(k, i - 1, scale))
            else:
                painter.drawPolyline(pts[max(first, lo):min(last, hi) + 1])

    def _grow(self, layer: _OldLayer, upto: list[int], budget: float | None = None):
        """Adds the whole pieces up to upto (per segment) to the layer, in order. With a budget (seconds), it stops
        when that is used up and returns False if something is left; else returns True."""
        todo = [(k, d, self._whole(k, f)) for k, (d, f) in enumerate(zip(layer.done, upto))]
        todo = [(k, d, w) for k, d, w in todo if w > d]
        if not todo:
            return True
        clock = time.perf_counter()
        painters = [QPainter(layer.outline), QPainter(layer.lines)]
        for p in painters:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setTransform(layer.to_layer)
        finished = True
        for k, done, whole in todo:
            pieces, firsts = self.pieces[k]
            i = max(0, bisect.bisect_right(firsts, done) - 1)
            while i < len(pieces) and pieces[i][1] <= whole:
                first, last, color, box = pieces[i]
                i += 1
                if last <= done or not layer.cull.intersects(box):
                    continue
                line = self._points(k, i - 1, layer.scale)
                painters[0].setPen(self._old_pen(color, True))
                painters[0].drawPolyline(line)
                painters[1].setPen(self._old_pen(color, False, self.segs[k][2]))
                painters[1].drawPolyline(line)
                layer.done[k] = last
                if budget is not None and time.perf_counter() - clock > budget:
                    finished = False
                    break
            if not finished:
                break
            layer.done[k] = whole
        for p in painters:
            p.end()
        return finished

    def _view(self) -> QGraphicsView | None:
        scene = self.scene()
        views = scene.views() if scene is not None else []
        return views[0] if views else None

    def _old_layer(self, painter: QPainter, firsts: list[int]) -> tuple[_OldLayer | None, QRectF | None]:
        """(the old route's layer grown up to firsts, per segment the point where the trail begins; the view in
        scene coordinates, padded by a line's width). The layer is None while there is none for the view (all the
        old route is drawn directly then, as while the camera zooms fast on a flight); both are None without a
        view."""
        view = self._view()
        if view is None:
            return None, None
        transform = view.viewportTransform()
        viewport = QRectF(view.viewport().rect())
        scale = transform.m11()
        if viewport.isEmpty() or scale <= 0:
            return None, None
        visible = transform.inverted()[0].mapRect(viewport)
        pad = 8 / scale
        cull = visible.adjusted(-pad, -pad, pad, pad)
        dpr = painter.device().devicePixelRatioF()
        steady = self.last_scale is not None and abs(math.log(scale / self.last_scale)) < LAYER_STEADY
        self.last_scale = scale
        mx, my = viewport.width() * LAYER_MARGIN, viewport.height() * LAYER_MARGIN
        area = viewport.adjusted(-mx, -my, mx, my)

        def fresh() -> _OldLayer:
            return _OldLayer(transform, area, dpr, len(self.segs))

        def usable(layer: _OldLayer) -> bool:
            # Not one drawn at a much other zoom: zooming in on and on (diving in after a teleport) kept a layer
            # from far out, blown up and blurred, as long as the camera never held still for a new one.
            return (layer.dpr == dpr and layer.scene_rect.contains(visible)
                    and 1 / LAYER_ZOOM ** 2 <= layer.ratio(transform) <= LAYER_ZOOM ** 2
                    and not any(f < d for f, d in zip(firsts, layer.done)))

        layer = self.layer
        if layer is not None and any(f < d for f, d in zip(firsts, layer.done)):
            self.layer = layer = self.next_layer = None      # time went back
        if layer is not None and not usable(layer):
            self.layer = layer = None               # moved or zoomed past it
        if self.next_layer is not None and not (usable(self.next_layer[0]) and 1 / LAYER_ZOOM ** 2
                                                <= self.next_layer[0].ratio(transform) <= LAYER_ZOOM ** 2):
            self.next_layer = None                  # the camera went on: started again once it is steady
        far = scale <= WORLD_LAYER_SCALE * LAYER_ZOOM ** 2
        if layer is None and not far and (steady or not self.layered):
            layer = self.layer = fresh()            # drawn at once: it costs about what one direct frame does
            self.layered = True
            self.next_layer = None
            self._grow(layer, firsts)
            return layer, cull
        if layer is None:                           # zooming fast: far out, the whole map's layer serves
            if not far:
                return None, cull
            if steady and self.next_layer is None:
                self.next_layer = (fresh(), list(firsts))    # meanwhile the sharp one, in steps
            if self.next_layer is not None:
                new, target = self.next_layer
                if self._grow(new, target, LAYER_BUDGET):
                    self.next_layer = None
                    self.layer = layer = new
                    self.layered = True
                    self._grow(layer, firsts)
                    return layer, cull
            world = self.world_layer
            if world is None or world.dpr != dpr or any(f < d for f, d in zip(firsts, world.done)):
                size = QRectF(0, 0, W, H).adjusted(-20, -20, 20, 20)
                world = self.world_layer = _OldLayer(
                    QTransform.fromScale(WORLD_LAYER_SCALE, WORLD_LAYER_SCALE),
                    QTransform.fromScale(WORLD_LAYER_SCALE, WORLD_LAYER_SCALE).mapRect(size), dpr, len(self.segs))
            self._grow(world, firsts)
            return world, cull
        if self.next_layer is None and steady and (
                not layer.inner.contains(visible) or not 1 / LAYER_ZOOM <= layer.ratio(transform) <= LAYER_ZOOM):
            self.next_layer = (fresh(), list(firsts))    # the camera nears the edge or zooms: the next one, in steps
        if self.next_layer is not None:
            new, target = self.next_layer
            if self._grow(new, target, LAYER_BUDGET):
                self.next_layer = None
                self.layer = layer = new
        self._grow(layer, firsts)
        return layer, cull

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        firsts, trail, glow = [], [], []     # per segment, (taxi, step, colour, points), (step, colour, points)
        for times, pts, taxi, runs, line_colors in self.segs:
            n = bisect.bisect_right(times, self.t)
            if n == 0:
                firsts.append(0)
                continue
            first = max(0, bisect.bisect_right(times, self.t - TRAIL_SECONDS) - 1)
            firsts.append(first)
            lines = self._trail_lines(times, pts, line_colors, first, n)
            for (step, color), line in self._group(
                    lines, lambda ln: (min(TRAIL_STEPS - 1, int(ln[0] / TRAIL_SECONDS * TRAIL_STEPS)), ln[1])):
                trail.append((taxi, step, color, line))
            for (step, color), line in self._group(
                    [ln for ln in lines if ln[0] < GLOW_SECONDS],
                    lambda ln: (min(3, int(ln[0] / GLOW_SECONDS * 4)), ln[1])):
                glow.append((step, color, line))
        layer, cull = self._old_layer(painter, firsts)
        scale = painter.worldTransform().m11()
        done = layer.done if layer is not None else [0] * len(firsts)

        # Glow under everything (added light), then all outlines, then the lines, so joints stay clean.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for step, color, line in glow:
            k = 1 - step / 4
            for width, alpha in ((18, 26), (10, 46)):
                painter.setPen(self._pen(color, width, alpha * k, False))
                painter.drawPolyline(line)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # A dark outline keeps the line readable on bright maps (the Barrens are gold too).
        if layer is not None:
            layer.draw(painter, layer.outline)
        for k, first in enumerate(firsts):
            self._draw_old(painter, k, done[k], first, lambda c: self._old_pen(c, True), cull, scale)
        for taxi, step, color, line in trail:
            k = 1 - (step + 0.5) / TRAIL_STEPS          # 1: newest
            painter.setPen(self._pen(OUTLINE, 5 + 3 * k, 90 + 120 * k, False))
            painter.drawPolyline(line)
        if layer is not None:
            layer.draw(painter, layer.lines)
        for k, first in enumerate(firsts):
            taxi = self.segs[k][2]
            self._draw_old(painter, k, done[k], first, lambda c, taxi=taxi: self._old_pen(c, False, taxi), cull, scale)
        for taxi, step, color, line in trail:
            k = 1 - (step + 0.5) / TRAIL_STEPS
            painter.setPen(self._pen(color, 3 + 1.8 * k, 130 + 125 * k, taxi))
            painter.drawPolyline(line)


# -- flying mounts --------------------------------------------------------------------------------------

FLYER_INK = QColor(26, 16, 8, 235)


def _mirrored(half):
    """A closed path from a half outline (points with y <= 0, nose first, tail last) and its mirror."""
    path = QPainterPath(QPointF(*half[0]))
    for kind, *pts in half[1:]:
        getattr(path, kind)(*[QPointF(x, y) for x, y in pts])
    back = [(kind, *[(x, -y) for x, y in pts]) for kind, *pts in half[1:]]
    # walk the mirror backwards: reverse the segments, each segment ends at the previous start
    starts = [half[0][:2]] + [seg[-1] for seg in half[1:]]
    for i in range(len(half) - 1, 0, -1):
        kind, *pts = half[i]
        end = starts[i - 1]
        ctrl = list(reversed(pts[:-1]))
        coords = [(x, -y) for x, y in ctrl] + [(end[0], -end[1])]
        getattr(path, kind)(*[QPointF(x, y) for x, y in coords])
    path.closeSubpath()
    return path


def _mix(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _bat_wing(side, s):
    """A wind rider's wing: membrane scalloped between finger bones. side -1: left (up on screen), 1: right."""
    sweep = 2.0 * (1 - s)
    S, W, T = (6, 4.5 * side), (9 + sweep, 17 * side * s), (-3 + sweep, 29 * side * s)
    fingers = [T, (-9 + sweep * 0.6, 23 * side * s), (-12 + sweep * 0.3, 14 * side * s)]
    R = (-7, 4.5 * side)
    path = QPainterPath(QPointF(*S))
    path.cubicTo(QPointF(8, 9 * side * s), QPointF(10 + sweep, 13 * side * s), QPointF(*W))
    path.quadTo(QPointF(4 + sweep, 24 * side * s), QPointF(*T))
    chain = fingers + [R]
    for a, b in zip(chain, chain[1:]):
        mid = _mix(a, b, 0.5)
        c = _mix(mid, W, 0.32)                      # the membrane sags towards the wrist between bones
        path.quadTo(QPointF(*c), QPointF(*b))
    path.closeSubpath()
    bones = [(W, f) for f in fingers] + [(S, W)]
    return path, bones


def _feather_wing(side, s):
    """A gryphon's wing: a long swept leading edge, separate primary feathers at the tip, rounded secondaries."""
    sweep = 2.0 * (1 - s)
    S, W, T = (6, 5 * side), (7 + sweep, 17 * side * s), (-8 + sweep, 31 * side * s)
    trail = [T, (-11.5 + sweep, 27 * side * s), (-13 + sweep * 0.6, 23 * side * s), (-13.5, 18.5 * side * s),
             (-14, 14 * side * s), (-13, 9.5 * side * s), (-9, 5 * side)]
    path = QPainterPath(QPointF(*S))
    path.cubicTo(QPointF(8, 9 * side * s), QPointF(9 + sweep, 13 * side * s), QPointF(*W))
    path.quadTo(QPointF(1 + sweep, 26 * side * s), QPointF(*T))
    lines = []
    for k, (a, b) in enumerate(zip(trail, trail[1:])):
        mid = _mix(a, b, 0.5)
        primary = k < 3
        # Primaries end in separate tips (a notch between them); secondaries in a soft scallop.
        out = 2.4 if primary else 1.6
        c = (mid[0] - out, mid[1] + (0.8 * side if primary else 0))
        if primary:
            notch = _mix(a, b, 0.55)
            path.quadTo(QPointF(*c), QPointF(notch[0] + 1.6, notch[1]))
            path.lineTo(QPointF(*b))
        else:
            path.quadTo(QPointF(*c), QPointF(*b))
        root = _mix(W, S, k / 6) if k > 0 else W
        lines.append((root, a))
    path.closeSubpath()
    return path, lines


def _wind_rider_body():
    return _mirrored([(21, 0), ("quadTo", (20.8, -2.2), (17.5, -3.2)), ("cubicTo", (15, -4.0), (13, -2.8), (10.5, -3.2)),
                     ("cubicTo", (8, -5.8), (4, -6.6), (0, -5.4)), ("cubicTo", (-4, -4.4), (-7, -5.6), (-9.5, -4.6)),
                     ("lineTo", (-12.5, -1.6))])


def _gryphon_body():
    return _mirrored([(18, 0), ("cubicTo", (18.2, -3.6), (15.5, -5.0), (12.5, -4.2)), ("cubicTo", (10, -4.6), (8, -6.8), (4, -7.0)),
                     ("cubicTo", (0, -6.6), (-4, -5.4), (-7, -5.8)), ("cubicTo", (-10, -6.4), (-12.5, -4.5), (-13.5, -1.4))])


def _tail_path(points):
    path = QPainterPath(QPointF(*points[0]))
    for a, b in zip(points[1::2], points[2::2]):
        path.quadTo(QPointF(*a), QPointF(*b))
    return path


def draw_flyer(painter: QPainter, kind: str, spread: float, accent: QColor, shadow: bool = True) -> None:
    """A flying mount seen from above, nose to +x, about 64 x 62 units with the wings spread (spread 1):
    "wyvern" (the Horde's wind rider: bat wings, a scorpion's tail, horns) or "gryphon" (the Alliance's:
    feathered wings, a white eagle head, a lion's tail), its rider's shoulders in accent and a shadow below
    it (the height)."""
    horde = kind == "wyvern"
    wings = [_bat_wing(side, spread) if horde else _feather_wing(side, spread) for side in (-1, 1)]
    body = _wind_rider_body() if horde else _gryphon_body()
    tail = _tail_path([(-12, 0), (-17, 2.0), (-21, 2.4), (-25, 2.6), (-27.5, 0.2)] if horde else
                     [(-13, 0), (-17, 0.8), (-20, 2.2), (-22, 3.2), (-23.5, 2.6)])
    if shadow:
        painter.save()
        painter.translate(5, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        for w, _ in wings:
            painter.drawPath(w)
        painter.drawPath(body)
        painter.restore()
    # Tail under the body.
    if horde:                                       # a scorpion's tail: segments getting smaller, a stinger
        painter.setPen(QPen(FLYER_INK, 1.0))
        painter.setBrush(QColor("#8a4f2c"))
        for k in range(7):
            f = k / 6
            p = tail.pointAtPercent(f)
            r = 2.6 - 1.4 * f
            painter.drawEllipse(p, r * 1.15, r)
        sting = QPainterPath(QPointF(-27.5, 0.2))
        sting.lineTo(-31.5, -2.4)
        sting.lineTo(-26.6, -1.9)
        sting.closeSubpath()
        painter.setBrush(QColor("#2e1a10"))
        painter.drawPath(sting)
    else:                                           # a lion's tail with its tuft, and the hind paws tucked in
        pen = QPen(FLYER_INK, 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(tail)
        pen = QPen(QColor("#c49a5e"), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(tail)
        painter.setPen(QPen(FLYER_INK, 1.0))
        painter.setBrush(QColor("#5e3d20"))
        painter.drawEllipse(QPointF(-24.2, 2.8), 2.4, 1.8)
        painter.setBrush(QColor("#b48850"))
        for side in (-1, 1):
            painter.drawEllipse(QPointF(-12.8, 5.6 * side), 2.4, 1.6)
    # Wings.
    for (w, lines), side in zip(wings, (-1, 1)):
        if horde:
            grad = QRadialGradient(QPointF(4, 5 * side), 30)
            grad.setColorAt(0, QColor("#8c4a2c"))
            grad.setColorAt(1, QColor("#5b2a1a"))
        else:                                       # light coverts at the leading edge, dark flight feathers
            grad = QLinearGradient(QPointF(7, 10 * side), QPointF(-13, 12 * side))
            grad.setColorAt(0, QColor("#e6cc98"))
            grad.setColorAt(0.45, QColor("#b0814f"))
            grad.setColorAt(1, QColor("#5f3e22"))
        painter.setPen(QPen(FLYER_INK, 1.3))
        painter.setBrush(grad)
        painter.drawPath(w)
        painter.setPen(QPen(QColor(30, 14, 6, 170) if horde else QColor(60, 36, 16, 120), 1.0 if horde else 0.7))
        for a, b in lines:
            painter.drawLine(QPointF(*a), QPointF(*b))
    # Body.
    painter.setPen(QPen(FLYER_INK, 1.3))
    grad = QLinearGradient(0, -6, 0, 6)
    if horde:
        grad.setColorAt(0, QColor("#c9935a"))
        grad.setColorAt(1, QColor("#8f5d33"))
    else:
        grad.setColorAt(0, QColor("#ddb878"))
        grad.setColorAt(1, QColor("#a87d45"))
    painter.setBrush(grad)
    painter.drawPath(body)
    if horde:                                       # horns swept back, a dark mane
        pen = QPen(QColor("#e9dcc0"), 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for side in (-1, 1):
            painter.drawLine(QPointF(14.5, 2.4 * side), QPointF(10.5, 6.2 * side))
        mane = QPainterPath(QPointF(16.5, 0))       # a dark mane down the neck, tapering
        mane.cubicTo(QPointF(13, -2.2), QPointF(8, -1.8), QPointF(4, -0.6))
        mane.lineTo(QPointF(4, 0.6))
        mane.cubicTo(QPointF(8, 1.8), QPointF(13, 2.2), QPointF(16.5, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(52, 28, 16, 220))
        painter.drawPath(mane)
    else:                                           # white eagle head, golden beak
        painter.setPen(QPen(FLYER_INK, 1.0))
        painter.setBrush(QColor("#f5eedc"))
        painter.drawEllipse(QPointF(14, 0), 4.4, 3.9)
        beak = QPainterPath(QPointF(21.5, 0))
        beak.lineTo(17.2, -1.8)
        beak.lineTo(17.2, 1.8)
        beak.closeSubpath()
        painter.setBrush(QColor("#e8a92e"))
        painter.drawPath(beak)
    # The rider seen from above: shoulders in the class colour, the head in front.
    painter.setPen(QPen(FLYER_INK, 1.0))
    painter.setBrush(accent)
    painter.drawEllipse(QPointF(-1.2, 0), 2.6, 4.2)
    painter.setBrush(QColor("#3a2a1e"))
    painter.drawEllipse(QPointF(1.8, 0), 1.9, 1.9)


# -- marker -------------------------------------------------------------------------------------------------

class MarkerItem(QGraphicsItem):
    """The player on the map, drawn at screen size: walking (disc, halo, arrow), on a flight path (the
    faction's flying mount: flyer "wyvern" or "gryphon", wings beating and gliding) or inside a dungeon (portal at
    its entrance)."""

    TAXI_COLOR = QColor(hex_color(TAXI))      # the flight paths' blue
    PORTAL_COLOR = QColor("#a87bff")
    # The flying mount's wings: a cycle of beats (one every FLAP_BEAT seconds until FLAP_UNTIL), then a glide.
    FLAP_CYCLE, FLAP_BEAT, FLAP_UNTIL = 3.4, 0.55, 1.4
    FLAP_AT = 0.15             # seconds into a beat where it is heard (the wings at their widest)

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(10)
        self.color = QColor(theme.GOLD)
        self.flyer = "gryphon"       # the flying mount on flight paths (draw_flyer)
        self.mode = "walk"           # "walk" | "mount" | "taxi" | "dungeon" | "dead" | "ghost" | "flight"
        self.mount_icon: QPixmap | None = None    # the medallion's icon while mounted
        self.angle = 0.0             # direction of travel in degrees, as on screen (0: right, 90: down)
        self.motion = 0.0            # 0..1: how visible the arrow is (only while moving)
        self.moving = False
        self.clock = 0.0
        self.flap_from = 0.0         # the clock at take-off: the wings' cycle starts with beats there
        self.beats: list[int] = []   # wing beats since the last pop_beats(): the cycle each belongs to

    def boundingRect(self) -> QRectF:
        return QRectF(-72, -72, 144, 144)          # a flying mount's wings and shadow

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.update()

    def aim(self, dx: float, dy: float) -> None:
        """Turns towards a movement on the map (scene units); tiny steps count as standing still."""
        self.moving = math.hypot(dx, dy) > 0.004
        if self.moving:
            target = math.degrees(math.atan2(dy, dx))
            self.angle += ((target - self.angle + 180) % 360 - 180) * 0.3

    def take_off(self) -> None:
        """The flying mount sets off: its wings start a cycle of beats now."""
        self.flap_from = self.clock
        self.beats.clear()

    def pop_beats(self) -> list[int]:
        beats, self.beats = self.beats, []
        return beats

    def tick(self, dt: float) -> None:
        before = self.clock - self.flap_from
        self.clock += dt
        self.motion = clamp(self.motion + (dt * 4 if self.moving else -dt * 2))
        if self.mode == "taxi":
            after = self.clock - self.flap_from
            for cycle in range(int(before // self.FLAP_CYCLE), int(after // self.FLAP_CYCLE) + 1):
                at = cycle * self.FLAP_CYCLE + self.FLAP_AT
                while at - cycle * self.FLAP_CYCLE < self.FLAP_UNTIL:
                    if before < at <= after:
                        self.beats.append(cycle)
                    at += self.FLAP_BEAT
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pulse = (math.sin(self.clock * 3.2) + 1) / 2
        if self.mode == "dungeon":
            self._portal(painter, pulse)
        elif self.mode == "taxi":
            self._gryphon(painter, pulse)
        elif self.mode == "ghost":
            self._ghost(painter, pulse)
        elif self.mode == "flight":
            self._ghost(painter, pulse, ARCANE_COLOR, bob=False)
        elif self.mode == "dead":
            self._grave(painter, pulse)
        else:
            self._walker(painter, pulse)
            if self.mode == "mount":
                self._mount_badge(painter)

    def _halo(self, painter: QPainter, color: QColor, radius: float, alpha: float) -> None:
        glow = QRadialGradient(QPointF(0, 0), radius)
        glow.setColorAt(0, with_alpha(color, alpha))
        glow.setColorAt(0.45, with_alpha(color, alpha * 0.45))
        glow.setColorAt(1, with_alpha(color, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), radius, radius)

    def _walker(self, painter: QPainter, pulse: float) -> None:
        self._halo(painter, self.color, 21 + 8 * pulse, 200 - 60 * pulse)
        if self.motion > 0:
            painter.save()
            painter.rotate(self.angle)
            arrow = QPainterPath()
            arrow.moveTo(23, 0)
            arrow.lineTo(13, -7)
            arrow.lineTo(15, 0)
            arrow.lineTo(13, 7)
            arrow.closeSubpath()
            painter.setPen(QPen(with_alpha(QColor("black"), 220 * self.motion), 1.5))
            painter.setBrush(with_alpha(self.color, 255 * self.motion))
            painter.drawPath(arrow)
            painter.restore()
        painter.setPen(QPen(QColor("black"), 2))
        painter.setBrush(self.color)
        painter.drawEllipse(QPointF(0, 0), 8.5, 8.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 150))
        painter.drawEllipse(QPointF(-2.5, -3), 2.6, 2.6)

    def _mount_badge(self, painter: QPainter) -> None:
        """Riding: the mount's icon in a small gold-rimmed medallion at the disc's upper right."""
        center, radius = QPointF(11, -11), 8.0
        painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
        painter.setBrush(QColor(20, 16, 10))
        painter.drawEllipse(center, radius, radius)
        if self.mount_icon is not None and not self.mount_icon.isNull():
            draw_round_icon(painter, center, radius - 1, self.mount_icon)
        painter.setPen(QPen(QColor(theme.GOLD), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)

    def _ghost(self, painter: QPainter, pulse: float, color: QColor = GHOST_COLOR, bob: bool = True) -> None:
        """A floating wisp: a pale flame bobbing on a cold halo, its tail pointing back along the way (in the
        arcane colour, without bobbing: the comet flying to a teleport's destination)."""
        self._halo(painter, color, 24 + 7 * pulse, 150 - 40 * pulse)
        painter.save()
        if bob:
            painter.translate(0, -2.5 * math.sin(self.clock * 2.4))
        painter.scale(1.35, 1.35)
        painter.rotate(self.angle + 90)
        flame = QPainterPath()                       # pointing down (+y) before the rotation: tail behind
        flame.moveTo(0, -9)
        flame.cubicTo(8, -9, 9, 2, 0, 18 + 3 * pulse)
        flame.cubicTo(-9, 2, -8, -9, 0, -9)
        body = QRadialGradient(QPointF(0, -2), 16)
        body.setColorAt(0, QColor(255, 255, 255, 245))
        body.setColorAt(0.5, with_alpha(color, 225))
        body.setColorAt(1, with_alpha(color, 90))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(10, 20, 40, 110))              # a soft shadow keeps it visible on pale maps
        painter.drawPath(flame.translated(1.5, 2))
        painter.setPen(QPen(QColor(16, 28, 52, 220), 1.6))
        painter.setBrush(body)
        painter.drawPath(flame)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawEllipse(QPointF(0, -2.5), 3.4, 3.4)
        painter.restore()

    def _grave(self, painter: QPainter, pulse: float) -> None:
        """The body where the player fell: a dim headstone with a faint red glow."""
        self._halo(painter, QColor("#ff3b30"), 18 + 3 * pulse, 90)
        stone = QPainterPath()
        stone.moveTo(-7, 9)
        stone.lineTo(-7, -3)
        stone.cubicTo(-7, -12, 7, -12, 7, -3)
        stone.lineTo(7, 9)
        stone.closeSubpath()
        painter.setPen(QPen(QColor(0, 0, 0, 230), 1.8))
        painter.setBrush(QColor("#8f949a"))
        painter.drawPath(stone)
        painter.setPen(QPen(QColor(40, 40, 44, 220), 1.6))
        painter.drawLine(QPointF(0, -6), QPointF(0, 4))
        painter.drawLine(QPointF(-3.5, -2.5), QPointF(3.5, -2.5))

    def _gryphon(self, painter: QPainter, pulse: float) -> None:
        self._halo(painter, self.TAXI_COLOR, 22 + 3 * pulse, 90)
        # Two or three wing beats, then a glide with the wings held out (a beat every ~3.5 s).
        cycle = (self.clock - self.flap_from) % self.FLAP_CYCLE
        beat = math.sin(cycle * 2 * math.pi / self.FLAP_BEAT) if cycle < self.FLAP_UNTIL else 0.0
        spread = 0.86 + 0.14 * beat * (1 - ease_in(clamp((cycle - 1.1) / 0.3)))
        painter.save()
        painter.rotate(self.angle)
        painter.scale(1.8, 1.8)
        draw_flyer(painter, self.flyer, spread, self.color)
        painter.restore()

    def _portal(self, painter: QPainter, pulse: float) -> None:
        self._halo(painter, self.PORTAL_COLOR, 24 + 5 * pulse, 190)
        painter.scale(1.25, 1.25)
        core = QRadialGradient(QPointF(0, 0), 11)
        core.setColorAt(0, QColor(250, 240, 255, 230))
        core.setColorAt(0.5, QColor(130, 80, 220, 220))
        core.setColorAt(1, QColor(30, 10, 60, 230))
        painter.setPen(QPen(QColor("black"), 1.5))
        painter.setBrush(core)
        painter.drawEllipse(QPointF(0, 0), 10, 10)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        spin = self.clock * 140
        for i, (radius, width) in enumerate(((13, 2.4), (8, 1.8))):
            pen = QPen(QColor(220, 200, 255, 220), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            box = QRectF(-radius, -radius, 2 * radius, 2 * radius)
            for k in range(3):
                start = (spin * (1 if i == 0 else -1.6) + k * 120) * 16
                painter.drawArc(box, int(start), 70 * 16)


class CompanionItem(QGraphicsItem):
    """A companion from the player's group, at screen size: a small disc in the class colour and the name below."""

    def __init__(self, name: str, color: QColor):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(9)                            # under the player's marker
        self.name, self.color = name, color
        self.font = pixel_font(12, bold=True)

    def boundingRect(self) -> QRectF:
        return QRectF(-80, -10, 160, 34)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("black"), 1.6))
        painter.setBrush(self.color)
        painter.drawEllipse(QPointF(0, 0), 5.5, 5.5)
        painter.setFont(self.font)
        draw_shadowed_text(painter, QRectF(-80, 8, 160, 18), self.name, QPen(self.color))


# -- pins and bursts ----------------------------------------------------------------------------------------

@dataclass
class Pin:
    time: int
    pos: QPointF                 # on the map (scene)
    glyph: str
    color: QColor
    thumb: QPixmap | None = None  # screenshots: a small picture (it may come a little later, see photo)
    tilt: float = 0.0
    icon: QPixmap | None = None   # events: the game icon, shown instead of the glyph
    photo: bool = False           # a screenshot's polaroid, also while its picture is still being loaded


@dataclass
class Burst:
    pos: QPointF
    color: QColor
    kind: str                     # a key of BURST_LIFE
    age: float = 0.0              # below 0: waiting to start
    shift: float = 0.0            # screen pixels to the side (quest pops coming together)


@dataclass
class _Shown:
    age: float = PIN_POP


class PinsItem(QGraphicsItem):
    """Pins of the events that have happened by now, and bursts where something happens; both are drawn at
    screen size above the route. Pins at the same place (several events at a dungeon entrance) fan out."""

    def __init__(self, pins: list[Pin]):
        super().__init__()
        self.setZValue(5)
        self.pins = sorted(pins, key=lambda p: p.time)
        self.times = [p.time for p in self.pins]
        self.shown: dict[int, _Shown] = {}
        self.bursts: list[Burst] = []
        self._sprites: dict[tuple[int, float, bool], QPixmap] = {}

    def boundingRect(self) -> QRectF:
        return QRectF(-60, -60, W + 120, H + 120)

    def set_time(self, t: float, animate: bool = True) -> None:
        n = bisect.bisect_right(self.times, t)
        for i in [i for i in self.shown if i >= n]:
            del self.shown[i]
        for i in range(n):
            if i not in self.shown:
                self.shown[i] = _Shown(0.0 if animate else PIN_POP)

    def burst(self, pos: QPointF, color: QColor, kind: str) -> None:
        self.bursts.append(Burst(QPointF(pos), QColor(color), kind if kind in BURST_LIFE else "event"))

    def quest(self, pos: QPointF) -> None:
        """A completed quest: the question mark pops up at pos. Pops coming together follow one another, a little
        to the left and right, so a handful of quests handed in at once reads as a handful."""
        waiting = [b for b in self.bursts if b.kind == "quest" and b.age < QUEST_STAGGER]
        delay = max(-b.age for b in waiting) + QUEST_STAGGER if waiting else 0.0
        n = len(waiting) % 5
        shift = (n + 1) // 2 * 14 * (1 if n % 2 else -1)
        self.bursts.append(Burst(QPointF(pos), QColor(theme.GOLD), "quest", -delay, shift))

    def clear_bursts(self) -> None:
        self.bursts.clear()

    def tick(self, dt: float) -> None:
        for shown in self.shown.values():
            shown.age += dt
        for b in self.bursts:
            b.age += dt
        self.bursts = [b for b in self.bursts if b.age < BURST_LIFE[b.kind]]
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        transform = painter.worldTransform()
        painter.save()
        painter.resetTransform()          # pins are drawn at screen size
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        dpr = painter.device().devicePixelRatioF()
        views = self.scene().views() if self.scene() is not None else []
        screen = (transform.mapRect(views[0].mapToScene(views[0].viewport().rect()).boundingRect())
                  if views else QRectF(painter.viewport())).adjusted(-PIN_SPRITE, -PIN_SPRITE, PIN_SPRITE, PIN_SPRITE)
        placed: dict[tuple[int, int], list[QPointF]] = {}    # by cells of PIN_NEAR px: pins already placed
        for i in sorted(self.shown):
            pin = self.pins[i]
            p = transform.map(pin.pos)
            cx, cy = int(p.x() // PIN_NEAR), int(p.y() // PIN_NEAR)
            same = sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in placed.get((cx + dx, cy + dy), ())
                       if abs(q.x() - p.x()) + abs(q.y() - p.y()) < PIN_NEAR)
            placed.setdefault((cx, cy), []).append(p)
            if same:
                a = math.radians(same * 55 - 90)
                ring = 18 + 6 * (same // 6)
                p = QPointF(p.x() + math.cos(a) * ring, p.y() + math.sin(a) * ring)
            scale = ease_out_back(self.shown[i].age / PIN_POP)
            if scale <= 0.01 or not screen.contains(p):
                continue
            painter.save()
            painter.translate(p)
            painter.scale(scale, scale)
            half = PIN_SPRITE / 2
            painter.drawPixmap(QRectF(-half, -half, PIN_SPRITE, PIN_SPRITE), self._sprite(i, pin, dpr),
                               QRectF(0, 0, PIN_SPRITE * self._ratio(dpr), PIN_SPRITE * self._ratio(dpr)))
            painter.restore()
        for b in self.bursts:
            self._burst(painter, transform.map(b.pos), b)
        painter.restore()

    @staticmethod
    def _ratio(dpr: float) -> float:
        return max(2.0, dpr)        # drawn finer than the screen, so it stays crisp between pixels and popping up

    def _sprite(self, i: int, pin: Pin, dpr: float) -> QPixmap:
        """The pin drawn once (it never changes, but for a screenshot's picture arriving)."""
        key = (i, dpr, pin.thumb is None)
        sprite = self._sprites.get(key)
        if sprite is None:
            self._sprites.pop((i, dpr, True), None)
            ratio = self._ratio(dpr)
            sprite = QPixmap(round(PIN_SPRITE * ratio), round(PIN_SPRITE * ratio))
            sprite.fill(Qt.GlobalColor.transparent)
            painter = QPainter(sprite)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.scale(ratio, ratio)
            painter.translate(PIN_SPRITE / 2, PIN_SPRITE / 2)
            if pin.photo or pin.thumb is not None:
                self._polaroid(painter, pin)
            else:
                self._medallion(painter, pin)
            painter.end()
            self._sprites[key] = sprite
        return sprite

    @staticmethod
    def _medallion(painter: QPainter, pin: Pin) -> None:
        r = 10.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawEllipse(QPointF(1.5, 2), r, r)
        painter.setPen(QPen(TRIM, 1.6))
        painter.setBrush(bronze(QPointF(-2, -3), r * 1.4))
        painter.drawEllipse(QPointF(0, 0), r, r)
        if pin.icon is not None:
            draw_round_icon(painter, QPointF(0, 0), r - 1.6, pin.icon)
            return
        painter.setFont(pixel_font(12, True, SYMBOL_FONTS))
        painter.setPen(pin.color)
        painter.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, pin.glyph)

    @staticmethod
    def _polaroid(painter: QPainter, pin: Pin) -> None:
        painter.rotate(pin.tilt)
        if pin.thumb is None:                         # its picture is still being loaded
            paper, photo = QRectF(-14, -13, 28, 26), QRectF(-12, -11, 24, 17)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRect(paper.translated(1.5, 2.5))
            painter.setPen(QPen(PAPER_EDGE, 1))
            painter.setBrush(PAPER)
            painter.drawRect(paper)
            painter.fillRect(photo, QColor(70, 60, 48))
            return
        draw_polaroid(painter, QRectF(-14, -13, 28, 26), QRectF(-12, -11, 24, 17), pin.thumb, QPointF(1.5, 2.5))

    @staticmethod
    def _quest(painter: QPainter, p: QPointF, x: float) -> None:
        """The game's question mark of a quest ready to hand in: it pops up over the spot on a soft gold glow,
        rises a little and fades."""
        icon = skin_pixmap("quest_turnin.png")
        if icon.isNull():
            return
        pop = ease_out_back(clamp(x / 0.22))
        rise = ease_out(clamp(x / 0.7))
        fade = 1 - ease_in(clamp((x - 0.5) / 0.5))
        c = p + QPointF(0, -18 - 20 * rise)
        painter.setPen(Qt.PenStyle.NoPen)
        shade = QRadialGradient(c, 22)               # dark behind it, so it reads on the yellow steppes too
        shade.setColorAt(0, QColor(0, 0, 0, int(170 * fade)))
        shade.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(shade)
        painter.drawEllipse(c, 22, 22)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        glow = QRadialGradient(c, 18)
        glow.setColorAt(0, with_alpha(GOLD_GLOW, 110 * fade))
        glow.setColorAt(1, with_alpha(GOLD_GLOW, 0))
        painter.setBrush(glow)
        painter.drawEllipse(c, 18, 18)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        h = QUEST_SIZE * pop
        w = h * icon.width() / max(1, icon.height())
        painter.setOpacity(fade)
        painter.drawPixmap(QRectF(c.x() - w / 2, c.y() - h / 2, w, h), icon, QRectF(icon.rect()))
        painter.setOpacity(1.0)

    @classmethod
    def _burst(cls, painter: QPainter, p: QPointF, b: Burst) -> None:
        x = b.age / BURST_LIFE[b.kind]
        if x < 0:
            return
        if b.kind == "quest":
            cls._quest(painter, p + QPointF(b.shift, 0), x)
            return
        fade = 1 - x
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        glow = QRadialGradient(p, 46 if b.kind != "event" else 30)
        glow.setColorAt(0, with_alpha(b.color, 170 * fade * fade))
        glow.setColorAt(1, with_alpha(b.color, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(p, 46, 46)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        delays = (0.0, 0.2) if b.kind != "event" else (0.0,)
        reach = BURST_REACH[b.kind]
        for delay in delays:
            y = (x - delay) / (1 - delay)
            if 0 < y < 1:
                radius = 8 + reach * ease_out(y)
                painter.setPen(QPen(with_alpha(b.color, 230 * (1 - y)), 1 + 3 * (1 - y)))
                painter.drawEllipse(p, radius, radius)
        if b.kind == "level":
            # The game's level-up light: its golden glow (bright at the foot) stretched into a pillar rising
            # from the player.
            light = skin_pixmap("levelup_glow.png")
            if not light.isNull():
                rise, sink = ease_out(x / 0.25), 1 - ease_in((x - 0.45) / 0.55)
                width, height = 120.0, 380.0 * rise
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                painter.setOpacity(sink)
                for k in (1.0, 0.55):                     # twice, the second narrower: a brighter core
                    painter.drawPixmap(QRectF(p.x() - width * k / 2, p.y() + 16 - height, width * k, height),
                                       light, QRectF(light.rect()))
                painter.setOpacity(1.0)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(with_alpha(b.color, 220 * fade), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            r1 = 14 + 75 * ease_out(x)
            for i in range(12):
                a = math.radians(i * 30 + x * 25)
                d = QPointF(math.cos(a), math.sin(a))
                painter.drawLine(p + d * r1, p + d * (r1 + 16 * fade))
        if b.kind in ("teleport", "arrive"):
            # An arcane swirl: arcs turning round the spot, inwards where the player vanishes, outwards on arrival.
            pen = QPen(with_alpha(b.color, 230 * fade), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            size = 34 * (1 - ease_out(x)) + 10 if b.kind == "teleport" else 10 + 46 * ease_out(x)
            spin = x * (540 if b.kind == "teleport" else -360)
            for k in range(3):
                box = QRectF(p.x() - size, p.y() - size, 2 * size, 2 * size)
                painter.drawArc(box, int((spin + k * 120) * 16), 75 * 16)
        if b.kind in ("revive", "spirit", "teleport", "arrive"):
            # Light rising from the spot: coming back to life (gold), the ghost appearing (pale blue), a teleport.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            for i in range(9):
                dx = (i - 4) * 7 + 3 * math.sin(i * 1.7)
                rise = ease_out(clamp(x * 1.3 - (i % 3) * 0.08))
                bottom = p + QPointF(dx, 10 - 30 * rise)
                top = bottom - QPointF(0, 26 + 34 * rise * (1 - abs(i - 4) / 6))
                beam = QLinearGradient(bottom, top)
                beam.setColorAt(0, with_alpha(b.color, 0))
                beam.setColorAt(0.5, with_alpha(b.color, 200 * fade))
                beam.setColorAt(1, with_alpha(QColor("white"), 0))
                pen = QPen(QBrush(beam), 3 if i % 2 else 2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(bottom, top)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


# -- light --------------------------------------------------------------------------------------------------

class SkyItem(QGraphicsItem):
    """The time of day over the map: its colour multiplied onto everything beneath (the map art;
    the route, pins and marker lie above it and keep their colours). Hidden by full daylight."""

    def __init__(self):
        super().__init__()
        self.setZValue(1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.color = QColor("white")
        self.hide()

    def boundingRect(self) -> QRectF:
        return QRectF(-W, -H, 3 * W, 3 * H)

    def set_light(self, rgb) -> None:
        color = QColor.fromRgbF(*(clamp(c) for c in rgb))
        if color.rgb() != self.color.rgb():
            self.color = color
            self.setVisible(min(color.red(), color.green(), color.blue()) < 254)
            self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.fillRect(option.exposedRect, self.color)


# -- view ---------------------------------------------------------------------------------------------------

class CinemaView(QGraphicsView):
    """The map view. grey (0..1) drains the colour from everything on it in a cold blue light, like the game's
    spirit world while the player is dead (a colorize effect: grey tones tinted with SPIRIT_TINT; only switched
    on while needed, since it draws the view once more)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grey = 0.0
        self.spirit = QGraphicsColorizeEffect(self)
        self.spirit.setColor(SPIRIT_TINT)
        self.spirit.setStrength(0.0)
        self.spirit.setEnabled(False)
        self.setGraphicsEffect(self.spirit)

    def set_grey(self, grey: float) -> None:
        grey = clamp(grey)
        if abs(grey - self.grey) > 1e-4:
            self.grey = grey
            self.spirit.setStrength(grey)
            self.spirit.setEnabled(grey > 0.001)


# -- window overlays ----------------------------------------------------------------------------------------

class _Overlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self.area = QRectF()            # the picture between the letterbox bars, where an overlay uses it

    def picture(self) -> QRectF:
        """The picture between the letterbox bars (the whole overlay until it is known)."""
        return self.area if not self.area.isEmpty() else QRectF(self.rect())


class _TimedOverlay(_Overlay):
    """An overlay shown for life seconds; advance() counts its age up."""

    def __init__(self, parent, life: float = 0.0):
        super().__init__(parent)
        self.age, self.life = 0.0, life

    def restart(self) -> None:
        """Shows it from the start, on top."""
        self.age = 0.0
        self.show()
        self.raise_()
        self.update()

    def advance(self, dt: float) -> bool:
        """False once its life is over."""
        self.age += dt
        self.update()
        return self.age < self.life

    def leaving(self, seconds: float = FADE_SECONDS) -> float:
        """0 until the last `seconds` of its life, then eased up to 1."""
        return ease_in((self.age - (self.life - seconds)) / seconds)

    def envelope(self, fade_in: float, fade_out: float) -> float:
        """Opacity over its life: in over the first fade_in seconds, out over the last fade_out (both linear)."""
        return clamp(self.age / fade_in) * clamp((self.life - self.age) / fade_out)


class CinemaFrame(_Overlay):
    """Vignette over the map and letterbox bars that slide in when the replay starts."""

    def __init__(self, parent):
        super().__init__(parent)
        self.progress = 0.0
        self._vignette: tuple[tuple, QPixmap] | None = None   # drawn once per size

    @staticmethod
    def target_bar(w: int, h: int) -> int:
        return int(max(56, min(h * 0.12, (h - w / LETTERBOX) / 2)))

    def bar(self) -> int:
        """Current height of each bar."""
        return int(self.target_bar(self.width(), self.height()) * ease_out(self.progress))

    def advance(self, dt: float) -> bool:
        """Moves the bars in; True while they are moving."""
        if self.progress >= 1:
            return False
        self.progress = min(1.0, self.progress + dt / BARS_SECONDS)
        self.update()
        return True

    def _vignette_picture(self, w: int, h: int, dpr: float) -> QPixmap:
        key = (w, h, dpr)
        if self._vignette is None or self._vignette[0] != key:
            pixmap = QPixmap(math.ceil(w * dpr), math.ceil(h * dpr))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.translate(w / 2, h / 2)
            painter.scale(w / 2, h / 2)
            vignette = QRadialGradient(QPointF(0, 0), 1.42)
            vignette.setColorAt(0, QColor(0, 0, 0, 0))
            vignette.setColorAt(0.5, QColor(0, 0, 0, 0))
            vignette.setColorAt(0.78, QColor(0, 0, 0, 90))
            vignette.setColorAt(1, QColor(0, 0, 0, 215))
            painter.fillRect(QRectF(-1, -1, 2, 2), vignette)
            painter.end()
            self._vignette = (key, pixmap)
        return self._vignette[1]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.drawPixmap(0, 0, self._vignette_picture(w, h, painter.device().devicePixelRatioF()))
        bar = self.bar()
        if bar > 0:
            painter.fillRect(0, 0, w, bar, QColor("black"))
            painter.fillRect(0, h - bar, w, bar, QColor("black"))
            for y in (bar, h - bar - 1):
                edge = QLinearGradient(0, 0, w, 0)
                edge.setColorAt(0, QColor(201, 162, 74, 0))
                edge.setColorAt(0.5, QColor(201, 162, 74, 110))
                edge.setColorAt(1, QColor(201, 162, 74, 0))
                painter.fillRect(QRectF(0, y, w, 1), edge)
        painter.end()


class CloudCover(_Overlay):
    """Clouds over the whole picture, for trips to and from an island in the sky (maps.SKY_ISLANDS): amount 1
    hides the map completely (the trip changes maps under it). The clouds close in from the edges of the picture
    towards the middle, and part from the middle outward, showing the middle first: a front of puffs, lit from
    the upper left with grey-blue undersides, with misty cloud behind it. Its inner edge is an ellipse the shape
    of the picture, so it reaches the corners last. Lit by the time of day like the map (set_light)."""

    PUFFS = 90
    FAR = 1.5                      # the front's inner edge at amount 0, in half picture sizes (corners: 1.41)
    SOFT = 0.2                     # depth of the mist's soft edge behind the front, in half picture sizes

    def __init__(self, parent):
        super().__init__(parent)
        self.amount = 0.0
        self.clock = 0.0
        self.light = (1.0, 1.0, 1.0)
        rng = random.Random(7)
        # (angle, depth behind the front, radius, shade, drift): a sunflower spiral spreads them evenly all round.
        self.puffs = [(k * 2.39996 + rng.uniform(-0.15, 0.15), (k + 0.5) / self.PUFFS * 1.6,
                       rng.uniform(0.15, 0.27), rng.uniform(0.9, 1.0), rng.uniform(-1, 1))
                      for k in range(self.PUFFS)]
        self.hide()

    def set_amount(self, amount: float) -> None:
        amount = clamp(amount)
        if amount != self.amount:
            self.amount = amount
            self.setVisible(amount > 0.001)
            self.update()

    def set_light(self, rgb) -> None:
        self.light = tuple(clamp(c) for c in rgb)

    def advance(self, dt: float) -> None:
        self.clock += dt
        if self.isVisible():
            self.update()

    def _color(self, shade: float, alpha: float) -> QColor:
        r, g, b = self.light
        return QColor.fromRgbF(clamp(shade * r), clamp(shade * g), clamp(shade * (0.96 + 0.04 * b) * b),
                               clamp(alpha))

    def paintEvent(self, event) -> None:
        a = self.amount
        if a <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # Distances in half picture sizes from the middle: 1 is the edge of the picture, the corners lie at 1.41.
        # The front's inner edge (below 0 at a = 1): slow out at the edges, quick across the middle, so the
        # middle is covered late on the way in and shows early on the way out.
        edge = (1 - a) ** 0.6 * (self.FAR + self.SOFT) - self.SOFT
        painter.save()
        painter.translate(w / 2, h / 2)
        painter.scale(w / 2, h / 2)
        # The mist behind the front: clear inside the edge, thickening over SOFT, solid beyond.
        reach = 2.0
        mist = QRadialGradient(QPointF(0, 0), reach)
        stops = [(0.0, clamp(-edge / self.SOFT))]
        if edge > 0:
            stops.append((edge, 0.0))
        if edge + self.SOFT > 0:
            stops.append((edge + self.SOFT, 1.0))
        for rho, alpha in stops + [(reach, 1.0)]:
            at = min(1.0, rho / reach)
            mist.setColorAt(at, self._color(0.98 - 0.12 * at, alpha))
        painter.fillRect(QRectF(-1, -1, 2, 2), mist)
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        size = (w + h) / 4
        turn = self.clock * 0.012
        for angle, depth, radius, shade, drift in self.puffs:
            # The front is puffy; further back the puffs grow and fade into the mist.
            back = clamp((depth - 0.3) / 0.7)
            alpha = 1 - 0.8 * back
            r = radius * size * (1 + 0.8 * back)
            # Set back by half their size: the front puffs reach only a little past the mist's edge.
            rho = edge + 0.5 * r / (h / 2) + depth + 0.02 * math.sin(self.clock * 0.7 + drift * 3)
            if rho - r / (h / 2) > 1.45:
                continue                                       # beyond the corners
            angle += turn * drift
            cx, cy = w / 2 * (1 + rho * math.cos(angle)), h / 2 * (1 + rho * math.sin(angle))
            shadow = QRadialGradient(QPointF(cx + 0.12 * r, cy + 0.2 * r), r)
            shadow.setColorAt(0, self._color(0.72 * shade, 0.35 * alpha))
            shadow.setColorAt(1, self._color(0.72 * shade, 0))
            painter.setBrush(shadow)
            painter.drawEllipse(QPointF(cx + 0.12 * r, cy + 0.2 * r), r, r)
            puff = QRadialGradient(QPointF(cx, cy), r, QPointF(cx - 0.3 * r, cy - 0.35 * r))
            puff.setColorAt(0, self._color(1.04 * shade, alpha))
            puff.setColorAt(0.5, self._color(0.95 * shade, 0.85 * alpha))
            puff.setColorAt(1, self._color(0.86 * shade, 0))
            painter.setBrush(puff)
            painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.end()


class TitleCard(_TimedOverlay):
    """A large centred title: a small heading between gold lines, the title in gold with a glow and a passing
    shine, and a subtitle. It scales in and fades out. The "level" tone is the game's level-up display: its gold
    lines above and below, growing from the middle, and its golden glow flaring up behind the title."""

    INTRO = 0.45
    SHINE = (0.35, 1.25)          # when the shine passes, in seconds of its life
    # Colours per tone: glow, top/middle/bottom of the letters' fill, heading and its lines.
    TONES = {
        "gold": (GOLD_GLOW, GOLD_LETTERS, BANNER_HEADING, TRIM),
        "death": (QColor(220, 40, 30), ("#ffd9d2", "#d8352b", "#6e0f0c"), QColor("#e8a39b"), QColor("#a8433a")),
        "level": (GOLD_GLOW, GOLD_LETTERS, BANNER_HEADING, TRIM),
    }
    LINES = (0.1, 0.5)            # the level-up's lines grow from the middle: start and duration, in seconds

    def __init__(self, parent):
        super().__init__(parent)
        self.heading = self.text = self.subtitle = ""
        self.tone = "gold"
        self._still: tuple[tuple, QPixmap] | None = None     # the settled title, drawn once
        self.hide()

    def show_text(self, text: str, life: float, heading: str = "", subtitle: str = "", tone: str = "gold") -> None:
        self.text, self.heading, self.subtitle = text, heading, subtitle
        self.tone = tone if tone in self.TONES else "gold"
        self.life = life
        self.restart()

    def advance(self, dt: float) -> None:
        if self.isVisible() and not super().advance(dt):
            self.hide()

    def paintEvent(self, event) -> None:
        if not self.text:
            return
        painter = QPainter(self)
        painter.setOpacity(self.envelope(FADE_SECONDS, FADE_SECONDS))
        w, h = self.width(), self.height()
        settled = max(self.INTRO, self.SHINE[1], 0.9, sum(self.LINES))     # nothing moves after this
        if self.age < settled:
            self._paint_title(painter, w, h)
            painter.end()
            return
        dpr = painter.device().devicePixelRatioF()
        key = (self.text, self.heading, self.subtitle, self.tone, w, h, dpr)
        if self._still is None or self._still[0] != key:
            pixmap = QPixmap(math.ceil(w * dpr), math.ceil(h * dpr))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            still = QPainter(pixmap)
            self._paint_title(still, w, h)
            still.end()
            self._still = (key, pixmap)
        painter.drawPixmap(0, 0, self._still[1])
        painter.end()

    def _paint_title(self, painter: QPainter, w: int, h: int) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        intro = ease_out(self.age / self.INTRO)
        # A soft dark band behind the text keeps it readable on bright maps.
        band = QRadialGradient(QPointF(0, 0), 1)
        band.setColorAt(0, QColor(0, 0, 0, 150))
        band.setColorAt(0.6, QColor(0, 0, 0, 90))
        band.setColorAt(1, QColor(0, 0, 0, 0))
        painter.save()
        painter.translate(w / 2, h / 2)
        painter.scale(w * 0.45, h * 0.5)
        painter.fillRect(QRectF(-1, -1, 2, 2), band)
        painter.restore()
        painter.translate(w / 2, h * 0.5)
        painter.scale(1 + 0.3 * (1 - intro), 1 + 0.3 * (1 - intro))

        font = pixel_font(h * 0.36, True)
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, self.text)
        box = path.boundingRect()
        fit = min(1.0, w * 0.86 / max(1.0, box.width()))
        painter.save()
        painter.scale(fit, fit)
        path.translate(-box.center().x(), -box.center().y())
        box = path.boundingRect()
        glow, letters, heading_color, trim = self.TONES[self.tone]
        level = self.tone == "level"
        if level:
            self._level_glow(painter, box)
        _gold_letters(painter, path, glow, [(width, alpha * intro) for width, alpha in ((26, 22), (14, 40), (7, 70))],
                      5, letters, (self.age - self.SHINE[0]) / (self.SHINE[1] - self.SHINE[0]))
        half = box.width() * fit / 2
        top, bottom = box.top() * fit, box.bottom() * fit
        painter.restore()

        if level:
            self._level_lines(painter, w, h, top - h * 0.2, bottom + h * 0.04, half)
            if self.heading:
                font = pixel_font(h * 0.085)
                font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 135)
                painter.setFont(font)
                draw_shadowed_text(painter, QRectF(-w / 2, top - h * 0.16, w, h * 0.12), self.heading.upper(),
                                   heading_color, offset=1.5)
        elif self.heading:
            draw_flourish_heading(painter, QPointF(0, top - h * 0.1), self.heading, h * 0.085, heading_color, trim,
                                  reach=40 + 70 * intro, least=half + 70 * intro)
        if self.subtitle:
            painter.setFont(pixel_font(h * 0.08))
            draw_shadowed_text(painter, QRectF(-w / 2, bottom + h * (0.075 if level else 0.05), w, h * 0.12),
                               self.subtitle, QColor("#d9c9a3"), offset=1.5)

    def _level_glow(self, painter: QPainter, box: QRectF) -> None:
        """The game's golden glow behind the title: flaring up, then settling."""
        light = skin_pixmap("levelup_glow.png")
        if light.isNull():
            return
        flare = 0.6 + 0.4 * (1 - ease_out(self.age / 0.9))
        width, height = box.width() * 1.9, box.height() * 1.9
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setOpacity(painter.opacity() * flare)
        for _ in range(2):                                # added twice: the texture alone is faint on the map
            painter.drawPixmap(QRectF(box.center().x() - width / 2, box.bottom() + box.height() * 0.25 - height,
                                      width, height), light, QRectF(light.rect()))
        painter.restore()

    def _level_lines(self, painter: QPainter, w: float, h: float, above: float, below: float, half: float) -> None:
        """The game's gold lines above the heading and below the title, growing from the middle."""
        line = skin_pixmap("levelup_line.png")
        if line.isNull():
            return
        grow = ease_out((self.age - self.LINES[0]) / self.LINES[1])
        length = max(2.4 * half, w * 0.42) * grow
        thick = max(4.0, h * 0.03)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for mode in (QPainter.CompositionMode.CompositionMode_SourceOver, QPainter.CompositionMode.CompositionMode_Plus):
            painter.setCompositionMode(mode)              # laid on, then added once more: it shines
            for y in (above, below):
                painter.drawPixmap(QRectF(-length / 2, y - thick / 2, length, thick), line, QRectF(line.rect()))
        painter.restore()


# -- achievement banner -------------------------------------------------------------------------------------

def banner_parts(cue: Cue, with_time: bool = True) -> tuple[str, str, str, str, QColor, QPixmap | None]:
    """(heading, title, place, badge, badge colour, badge icon) of a cue's achievement banner. The level reached
    is shown as a number; otherwise the event's game icon, or its symbol where the icon is missing."""
    title = cue.title or cue.text
    where = cue.place if cue.place != title else ""       # a discovered zone would name itself twice
    place = "  ·  ".join(p for p in (where, format_datetime(cue.time) if with_time else "") if p)
    badge = str(cue.level) if cue.level is not None else (cue.glyph or "📷")
    color = QColor(theme.GOLD if cue.level is not None else cue.color)
    icon = icons.of_event(cue.icon, cue.event_type) if cue.level is None else None
    return cue.heading, title, place, badge, color, icon


def draw_round_icon(painter: QPainter, center: QPointF, radius: float, icon: QPixmap) -> None:
    """A game icon cut to a circle (without the dark frame drawn into each icon)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(center, radius, radius)
    painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    cut = icons.CROP * icon.width()
    painter.drawPixmap(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius), icon,
                       QRectF(cut, cut, icon.width() - 2 * cut, icon.height() - 2 * cut))
    painter.restore()


def draw_banner(painter: QPainter, rect: QRectF, heading: str, title: str, place: str, badge: str,
                badge_color: QColor, badge_icon: QPixmap | None = None) -> None:
    """The game's achievement alert: a dark plate with gold trim, a round medallion with the event's icon
    (or symbol, or the level reached) and the heading, name and place."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = rect.adjusted(3, 3, -3, -3)
    h = r.height()
    radius = h / 2 - 2
    center = QPointF(r.left() + h / 2, r.center().y())

    # Plate, starting behind the medallion, with a soft shadow.
    body = QRectF(center.x(), r.top() + h * 0.12, r.right() - center.x(), h * 0.76)
    _plate(painter, body, ((0, QColor(58, 44, 26, 245)), (1, QColor(14, 10, 6, 245))), radius=10)

    # Medallion.
    painter.setPen(QPen(TRIM, 3))
    painter.setBrush(bronze(center, radius))
    painter.drawEllipse(center, radius, radius)
    if badge_icon is not None:
        draw_round_icon(painter, center, radius - 6, badge_icon)
    painter.setPen(QPen(TRIM_DARK, 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius - 6, radius - 6)
    if badge_icon is None:
        families = None if badge.isdigit() else SYMBOL_FONTS
        painter.setFont(pixel_font(h * (0.42 if len(badge) < 3 else 0.3), True, families))
        painter.setPen(badge_color)
        painter.drawText(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
                         Qt.AlignmentFlag.AlignCenter, badge)

    # Heading, name (large, gold, with a shadow) and place, centred on the plate right of the medallion.
    left = center.x() + radius + 12
    area = QRectF(left, body.top() + body.height() * 0.06, body.right() - 18 - left, body.height() * 0.88)
    if place:
        rows = ((heading, 0.15, False, BANNER_HEADING, 0.24), (title, 0.3, True, QColor(theme.GOLD), 0.48),
                (place, 0.13, False, QColor(theme.MUTED), 0.28))
    else:
        rows = ((heading, 0.16, False, BANNER_HEADING, 0.36), (title, 0.32, True, QColor(theme.GOLD), 0.64))
    y = area.top()
    for text, share, bold, color, height in rows:
        row = QRectF(area.left(), y, area.width(), area.height() * height)
        y += row.height()
        if not text:
            continue
        font = pixel_font(max(11.0, h * share), bold)
        painter.setFont(font)
        text = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(row.width()))
        if bold:
            draw_shadowed_text(painter, row, text, color, alpha=220)
        else:
            painter.setPen(color)
            painter.drawText(row, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


def draw_ribbon(painter: QPainter, rect: QRectF, text: str, shine: float = -1.0) -> None:
    """A gold-trimmed ribbon with one word in large gold letters, its notched tails folded behind (a level-up's
    screenshot: the title before it already named the level). shine: where a passing light crosses the letters
    (0 to 1; none outside)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    h = rect.height() * 0.66
    tail, drop, notch = h * 0.9, h * 0.24, h * 0.34
    font = pixel_font(h * 0.52, True)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    path = QPainterPath()
    path.addText(QPointF(0, 0), font, text.upper())
    box = path.boundingRect()
    pad = h * 0.8
    w = min(rect.width() - 1.6 * tail, box.width() + 2 * pad)
    fit = min(1.0, (w - 2 * pad) / max(1.0, box.width()))
    cx, cy = rect.center().x(), rect.center().y()
    plate = QRectF(cx - w / 2, cy - h / 2, w, h)

    # Tails behind the plate, a little lower, with a notched end and a dark fold where they turn.
    for sign in (-1, 1):
        edge = cx + sign * w / 2
        inner, outer = edge - sign * h * 0.4, edge + sign * tail
        top, bottom = plate.top() + drop, plate.bottom() + drop
        shape = QPainterPath(QPointF(inner, top))
        for x, y in ((outer, top), (outer - sign * notch, (top + bottom) / 2), (outer, bottom), (inner, bottom)):
            shape.lineTo(x, y)
        shape.closeSubpath()
        fill = QLinearGradient(0, top, 0, bottom)
        fill.setColorAt(0, QColor(46, 34, 20, 245))
        fill.setColorAt(1, QColor(10, 7, 4, 245))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 80))
        painter.drawPath(shape.translated(3, 4))
        painter.setPen(QPen(TRIM, 1.5))
        painter.setBrush(fill)
        painter.drawPath(shape)
        fold = QPainterPath(QPointF(inner, plate.bottom()))
        fold.lineTo(edge, plate.bottom())
        fold.lineTo(edge, bottom)
        fold.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.drawPath(fold)

    # The plate, with a soft shadow, gold trim and a fine inner line.
    _plate(painter, plate, ((0, QColor(78, 58, 30, 250)), (0.5, QColor(40, 29, 16, 250)), (1, QColor(16, 11, 6, 250))))
    for sign in (-1, 1):
        _diamond(painter, QPointF(cx + sign * (w / 2 - pad * 0.5), cy), 8, TRIM)

    # The word: gold letters with a warm glow, a dark outline and a passing shine.
    painter.translate(cx, cy)
    painter.scale(fit, fit)
    path.translate(-box.center().x(), -box.center().y())
    _gold_letters(painter, path, GOLD_GLOW, ((16, 26), (8, 50)), 4, GOLD_LETTERS, shine)
    painter.restore()


class AchievementToast(_TimedOverlay):
    """An event as a small achievement alert: slides in from the right, moves up when older ones go, and
    fades out."""

    SLIDE = 0.45

    def __init__(self, parent, cue: Cue, life: float):
        super().__init__(parent, life)
        self.parts = banner_parts(cue, with_time=False)
        self.right = 0.0                # where its right edge rests
        self.centred = False            # at the top centre: drops in instead of sliding in from the right
        self.y: float | None = None     # current top, eased towards target_y
        self.target_y = 0.0

    def place_at(self, right: float, top: float, centred: bool = False) -> None:
        """Rests with its right edge at right (centred: drops in from above instead of sliding in)."""
        self.right, self.target_y, self.centred = right, top, centred
        if self.y is None:
            self.y = top
        self._move()

    def advance(self, dt: float) -> bool:
        """False once it is gone."""
        alive = super().advance(dt)
        if self.y is not None:
            self.y += (self.target_y - self.y) * min(1.0, dt * 10)
        self._move()
        return alive

    def _move(self) -> None:
        enter = ease_out(self.age / self.SLIDE)
        leave = self.leaving()
        # A short slide only: a child reaching past the window's edge breaks full screen on Windows.
        if self.centred:
            self.move(int(self.right - self.width()), int((self.y or 0) - 18 * max(1 - enter, leave)))
            return
        x = self.right - self.width() + 24 * max(1 - enter, leave)     # right rests 24 px from the edge
        self.move(int(x), int(self.y or 0))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setOpacity(min(1.0, self.age / 0.2) * (1 - self.leaving()))
        draw_banner(painter, QRectF(self.rect()), *self.parts)
        painter.end()


# -- screenshots --------------------------------------------------------------------------------------------

@dataclass
class _Shot:
    cue: Cue
    pixmap: QPixmap
    origin: QPointF
    tilt: float
    drift: QPointF = field(default_factory=QPointF)


class PhotoOverlay(_TimedOverlay):
    """A screenshot as a polaroid: a white flash, then the picture flies out from the marker to the centre,
    turning to a slight tilt; an achievement banner drops in above it. While it is shown the picture zooms in
    and pans slowly; at the end it flies back to the marker, where its pin stays."""

    FLY = 0.6
    FLASH = 0.3

    def __init__(self, parent, life: float):
        super().__init__(parent, life)
        self.shot: _Shot | None = None
        self.hide()

    def show_cue(self, cue: Cue, pixmap: QPixmap, origin: QPointF, area: QRectF) -> None:
        seed = scatter(cue.time)                           # the same tilt and pan for the same picture
        tilt = (1 if seed & 4 else -1) * (1.5 + 2.5 * (seed >> 3) / (0xFFFF >> 3))   # always a little crooked
        drift = QPointF(1 if seed & 1 else -1, -0.6 if seed & 2 else 0.6)
        self.area = area
        self.shot = _Shot(cue, pixmap, QPointF(origin), tilt, drift)
        self.restart()

    def layout(self) -> tuple[QRectF, QRectF, QRectF]:
        """Paper, picture (both centred on 0, 0) and banner (in widget coordinates)."""
        area = self.picture()
        pm = self.shot.pixmap
        aspect = pm.width() / max(1, pm.height())
        banner_h = clamp(area.height() * 0.14, 68, 118)
        above = banner_h * 0.62       # the banner's part above the paper
        # Paper: the picture with a margin of 3.5 % of its width, four times that below (for the caption).
        pw = min(area.width() * 0.6, (area.height() * 0.86 - above) / (1 / aspect + 0.035 * 5))
        ph = pw / aspect
        m = pw * 0.035
        paper_h = ph + 5 * m
        top = -(above + paper_h) / 2 + above
        paper = QRectF(-pw / 2 - m, top, pw + 2 * m, paper_h)
        photo = QRectF(-pw / 2, top + m, pw, ph)
        bw = clamp(paper.width() * 0.84, min(460.0, area.width() * 0.9), area.width() * 0.9)
        center = area.center()
        banner = QRectF(center.x() - bw / 2, center.y() + top - above, bw, banner_h)
        return paper, photo, banner

    def paintEvent(self, event) -> None:
        if self.shot is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        shot, age, life = self.shot, self.age, self.life
        fly_in = ease_out(age / self.FLY)
        fly_out = self.leaving(self.FLY)
        presence = fly_in * (1 - fly_out)

        painter.fillRect(self.rect(), QColor(0, 0, 0, int(150 * presence)))
        if age < self.FLASH:
            painter.fillRect(self.rect(), QColor(255, 255, 255, int(200 * (1 - age / self.FLASH) ** 2)))

        paper, photo, banner = self.layout()
        center = self.picture().center()
        start = shot.origin
        pos = start + (center - start) * fly_in
        pos = pos + (start - pos) * fly_out
        scale = 0.06 + 0.94 * presence
        painter.save()
        painter.translate(pos)
        painter.rotate(shot.tilt * fly_in - 22 * (1 - fly_in) + 18 * fly_out)
        painter.scale(scale, scale)
        painter.setOpacity(self.envelope(0.12, 0.12))
        # Shadow, softened by a few widening layers.
        painter.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((14, 18), (8, 30), (3, 60)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(paper.translated(8, 12).adjusted(-grow, -grow, grow, grow), grow, grow)
        paper_fill = QLinearGradient(paper.topLeft(), paper.bottomRight())
        paper_fill.setColorAt(0, PAPER)
        paper_fill.setColorAt(1, QColor("#e4dbc6"))
        painter.setPen(QPen(PAPER_EDGE, 1))
        painter.setBrush(paper_fill)
        painter.drawRect(paper)
        hold = clamp(age / life)
        source = cropped(shot.pixmap, photo.width() / photo.height(), 1.0 + 0.08 * hold,
                         QPointF(shot.drift.x() * hold, shot.drift.y() * hold))
        painter.drawPixmap(photo, shot.pixmap, source)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(photo)
        # The strip under the picture: where and when, as if written on it.
        strip = QRectF(photo.left(), photo.bottom(), photo.width(), paper.bottom() - photo.bottom())
        caption = "  ·  ".join(p for p in (shot.cue.place, format_datetime(shot.cue.time)) if p)
        font = pixel_font(clamp(strip.height() * 0.27, 11, 24))
        font.setItalic(True)
        painter.setFont(font)
        painter.setPen(INK)
        caption = QFontMetrics(font).elidedText(caption, Qt.TextElideMode.ElideRight, int(strip.width()))
        painter.drawText(strip, Qt.AlignmentFlag.AlignCenter, caption)
        painter.restore()

        # The banner drops in once the picture has landed and leaves before it flies back.
        drop = ease_out((age - self.FLY * 0.8) / 0.35) * (1 - ease_in((age - (life - self.FLY * 1.4)) / 0.3))
        if drop > 0:
            heading, title, _, badge, color, icon = banner_parts(shot.cue, with_time=False)
            painter.setOpacity(drop)
            if shot.cue.level is not None:     # the level-up title before it already named the level
                draw_ribbon(painter, banner.translated(0, -18 * (1 - drop)), heading,
                            (age - self.FLY * 0.8 - 0.3) / 0.9)
            else:
                draw_banner(painter, banner.translated(0, -18 * (1 - drop)), heading, title, "", badge, color, icon)
        painter.end()


# -- screenshots at the side ------------------------------------------------------------------------------

SIDE_WIDTH = 0.22          # a side picture's paper, share of the window's width
SIDE_MARGIN = 24           # pixels between the pile and the window's edge
SIDE_FLY = 0.7             # seconds a picture takes to fly from where it was taken to the pile
SIDE_FLASH = 0.35          # the small flash at the spot it was taken
SIDE_LIFE = 25.0           # real seconds a picture stays (unless newer ones push it off) ...
SIDE_LEAVE = 0.8           # ... and then fades out
SIDE_DEPTH_SECONDS = 0.18  # time constant of a picture going under a newer one
SIDE_STACK = 5             # pictures the pile shows at once
SIDE_STEP_DOWN = 0.16      # each one further under peeks out this much lower (share of its paper's height) ...
SIDE_STEP_IN = 0.05        # ... this much further in (share of its width) ...
SIDE_STEP_SCALE = 0.04     # ... and this much smaller


@dataclass
class _Card:
    cue: Cue
    pixmap: QPixmap
    origin: QPointF             # where it flies from: the spot it was taken, on the screen
    tilt: float
    age: float = 0.0
    slot: int = 0               # 0 on top, 1 under the newer one, ... SIDE_STACK and more: pushed off
    depth: float = 0.0          # slot, eased
    drawn: dict = field(default_factory=dict)   # its paper and banner, drawn once (SideShots._drawn)


class SideShots(_Overlay):
    """Screenshots in a pile over the right edge of the map, while the replay goes on. Each one flashes where
    it was taken and flies from there to the top of the pile, under a small achievement banner, with the place
    and date on the polaroid's strip. The ones before go under it (their banners fade away), each a little
    lower, further in and smaller so its strip peeks out; past SIDE_STACK the oldest falls off, and each
    picture fades out SIDE_LIFE seconds after it came. hit() finds the picture under the mouse (a click shows
    it large)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.cards: list[_Card] = []
        self.hide()

    # -- the pile ----------------------------------------------------------------------------------

    def add(self, cue: Cue, pixmap: QPixmap, origin: QPointF) -> _Card:
        for card in self.cards:
            card.slot += 1
        seed = scatter(cue.time)
        tilt = (1 if seed & 4 else -1) * (1.2 + 2.0 * (seed >> 3) / (0xFFFF >> 3))   # always a little crooked
        card = _Card(cue, pixmap, QPointF(origin), tilt)
        self.cards.append(card)
        self.show()
        self.update()
        return card

    def advance(self, dt: float) -> None:
        if not self.cards:
            return
        k = smooth(dt, SIDE_DEPTH_SECONDS)
        for card in self.cards:
            card.age += dt
            card.depth += (card.slot - card.depth) * k
        self.cards = [c for c in self.cards if not self._gone(c)]
        if not self.cards:
            self.hide()
        self.update()

    def clear(self) -> None:
        self.cards = []
        self.hide()

    def fade_all(self) -> None:
        """All pictures fade out now (the end credits show their own)."""
        for card in self.cards:
            card.age = max(card.age, SIDE_LIFE)

    def occupied(self) -> bool:
        """True while a picture stands in the pile (the camera keeps the marker away from it)."""
        return any(c.slot < SIDE_STACK and c.age < SIDE_LIFE for c in self.cards)

    def hit(self, pos: QPointF) -> _Card | None:
        """The picture on top at pos (window coordinates), if any."""
        for card in sorted(self.cards, key=lambda c: c.depth):
            if card.age < SIDE_FLY or card.slot >= SIDE_STACK or card.age >= SIDE_LIFE:
                continue
            paper, _, banner, center, scale, tilt = self.layout(card)
            local = QPointF(pos - center) / scale
            angle = math.radians(-tilt)
            local = QPointF(local.x() * math.cos(angle) - local.y() * math.sin(angle),
                            local.x() * math.sin(angle) + local.y() * math.cos(angle))
            if paper.contains(local) or (card.slot == 0 and banner.contains(local)):
                return card
        return None

    def screen_rect(self, card: _Card) -> QRectF:
        """Where the card's picture is on the screen (roughly, without its tilt)."""
        _, photo, _, center, scale, _ = self.layout(card)
        return QRectF(center + photo.topLeft() * scale, center + photo.bottomRight() * scale)

    @staticmethod
    def _gone(card: _Card) -> bool:
        # Pushed off: gone once it has faded on its way down (its depth only nears its slot).
        return card.age >= SIDE_LIFE + SIDE_LEAVE or card.depth >= SIDE_STACK - 0.03

    # -- layout ----------------------------------------------------------------------------------------

    def card_size(self, aspect: float) -> tuple[float, float]:
        """(paper width, banner height) for a picture of this aspect ratio: SIDE_WIDTH of the window, smaller
        where the picture between the bars is too low for the banner and the full pile under it."""
        area = self.picture()
        pw = self.width() * SIDE_WIDTH
        banner_h = 50.0
        for _ in range(2):
            banner_h = clamp(pw * 0.19, 50.0, 84.0)
            photo_w = pw / 1.07
            paper_h = photo_w / aspect + photo_w * 0.035 * 5
            height = banner_h * 0.62 + paper_h * (1 + SIDE_STEP_DOWN * (SIDE_STACK - 1))
            if height <= area.height() * 0.92:
                break
            pw *= area.height() * 0.92 / height
        return pw, banner_h

    def layout(self, card: _Card) -> tuple[QRectF, QRectF, QRectF, QPointF, float, float]:
        """Paper, picture and banner around the card's centre, then the centre on the screen, scale and tilt:
        flying in from its spot, on top of the pile, or under newer ones."""
        pm = card.pixmap
        aspect = pm.width() / max(1, pm.height())
        pw, banner_h = self.card_size(aspect)
        photo_w = pw / 1.07
        m = photo_w * 0.035
        photo_h = photo_w / aspect
        paper_h = photo_h + 5 * m
        above = banner_h * 0.62
        top = -(above + paper_h) / 2 + above
        paper = QRectF(-pw / 2, top, pw, paper_h)
        photo = QRectF(-photo_w / 2, top + m, photo_w, photo_h)
        banner = QRectF(-pw / 2, top - above, pw, banner_h)

        area = self.picture()
        # The whole pile (the newest on top, the ones under it stepping down) stands in the middle.
        rest = QPointF(self.width() - SIDE_MARGIN - pw / 2,
                       area.center().y() - paper_h * SIDE_STEP_DOWN * (SIDE_STACK - 1) / 2)
        # Under newer ones: lower and further in, a little smaller, the first one under turned the other way;
        # past the last place it falls off.
        d = min(card.depth, SIDE_STACK - 1.0)
        rest += QPointF(-pw * SIDE_STEP_IN * d, paper_h * SIDE_STEP_DOWN * d)
        tilt = card.tilt * (1 - 2 * min(d, 1.0))
        scale = 1 - SIDE_STEP_SCALE * d
        fall = max(0.0, card.depth - (SIDE_STACK - 1))
        rest += QPointF(0, paper_h * 0.35 * fall)
        f = ease_out(card.age / SIDE_FLY)
        center = card.origin + (rest - card.origin) * f
        scale *= 0.08 + 0.92 * f
        tilt = tilt * f + 20 * (1 - f)
        return paper, photo, banner, center, scale, tilt

    # -- painting --------------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        if not self.cards:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for card in sorted(self.cards, key=lambda c: -c.depth):     # the ones underneath first
            self._paint_card(painter, card)
        painter.end()

    def _paint_card(self, painter: QPainter, card: _Card) -> None:
        age = card.age
        if age < SIDE_FLASH:                                         # where it was taken
            r = 46 * (0.6 + 0.4 * age / SIDE_FLASH)
            glow = QRadialGradient(card.origin, r)
            glow.setColorAt(0, QColor(255, 255, 255, int(230 * (1 - age / SIDE_FLASH) ** 2)))
            glow.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(card.origin, r, r)
        opacity = (clamp(age / 0.12) * (1 - clamp((age - SIDE_LIFE) / SIDE_LEAVE))
                   * (1 - clamp(card.depth - (SIDE_STACK - 1))))
        if opacity <= 0:
            return
        paper, photo, banner, center, scale, tilt = self.layout(card)
        painter.save()
        painter.translate(center)
        painter.rotate(tilt)
        painter.scale(scale, scale)
        painter.setOpacity(opacity)
        dpr = painter.device().devicePixelRatioF()
        # The paper with its shadow and caption, then the picture (it zooms slowly while it stands).
        self._blit(painter, self._drawn(card, "paper", paper, dpr, lambda p: self._paint_paper(p, card, paper,
                                                                                            photo)), paper)
        drift = clamp(age / SIDE_LIFE)
        source = cropped(card.pixmap, photo.width() / photo.height(), 1.0 + 0.05 * drift)
        painter.drawPixmap(photo, card.pixmap, source)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(photo)
        if card.depth > 0.02:                                        # under newer ones: in their shade
            shade = 60 * min(1.0, card.depth) + 18 * max(0.0, card.depth - 1)
            painter.fillRect(paper, QColor(0, 0, 0, int(min(140.0, shade))))
        # The banner drops in once the picture has landed and fades as a newer one covers it.
        drop = ease_out((age - SIDE_FLY * 0.8) / 0.35) * (1 - clamp(card.depth * 1.5))
        if drop > 0:
            heading, title, _, badge, color, icon = banner_parts(card.cue, with_time=False)
            painter.setOpacity(opacity * drop)
            shown = banner.translated(0, -12 * (1 - drop))
            shine = (age - SIDE_FLY * 0.8 - 0.3) / 0.9
            if card.cue.level is not None and 0 < shine < 1:      # its light passing: drawn as it moves
                draw_ribbon(painter, shown, heading, shine)
            elif card.cue.level is not None:   # the level-up title in the middle names the level
                self._blit(painter, self._drawn(card, "banner", shown, dpr,
                                                lambda p, r=shown: draw_ribbon(p, r, heading)), shown)
            else:
                self._blit(painter, self._drawn(card, "banner", shown, dpr, lambda p, r=shown: draw_banner(
                    p, r, heading, title, "", badge, color, icon)), shown)
        painter.restore()

    @staticmethod
    def _paint_paper(painter: QPainter, card: _Card, paper: QRectF, photo: QRectF) -> None:
        # Shadow, softened by a few widening layers.
        painter.setPen(Qt.PenStyle.NoPen)
        for grow, alpha in ((10, 16), (5, 28), (2, 55)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(paper.translated(5, 8).adjusted(-grow, -grow, grow, grow), grow, grow)
        fill = QLinearGradient(paper.topLeft(), paper.bottomRight())
        fill.setColorAt(0, PAPER)
        fill.setColorAt(1, QColor("#e4dbc6"))
        painter.setPen(QPen(PAPER_EDGE, 1))
        painter.setBrush(fill)
        painter.drawRect(paper)
        strip = QRectF(photo.left(), photo.bottom(), photo.width(), paper.bottom() - photo.bottom())
        caption = "  ·  ".join(p for p in (card.cue.place, format_datetime(card.cue.time)) if p)
        font = pixel_font(clamp(strip.height() * 0.3, 10, 18))
        font.setItalic(True)
        painter.setFont(font)
        painter.setPen(INK)
        caption = QFontMetrics(font).elidedText(caption, Qt.TextElideMode.ElideRight, int(strip.width()))
        painter.drawText(strip, Qt.AlignmentFlag.AlignCenter, caption)

    @staticmethod
    def _drawn(card: _Card, part: str, rect: QRectF, dpr: float, paint) -> tuple[QPixmap, QRectF]:
        """A part of the card (paint draws it round rect, in card units) drawn once into a picture with room
        round it for shadows and flourishes; drawn again only when the window's size changes it."""
        key = (round(rect.width(), 1), round(rect.height(), 1), dpr)
        kept = card.drawn.get(part)
        if kept is not None and kept[0] == key:
            return kept[1], kept[2]
        room = max(24.0, rect.height() * 0.6)
        area = rect.adjusted(-room, -room, room, room)
        ratio = dpr * CARD_DETAIL
        pixmap = QPixmap(math.ceil(area.width() * ratio), math.ceil(area.height() * ratio))
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.scale(ratio, ratio)
        p.translate(-area.left(), -area.top())
        paint(p)
        p.end()
        card.drawn[part] = (key, pixmap, area.translated(-rect.left(), -rect.top()))
        return pixmap, card.drawn[part][2]

    @staticmethod
    def _blit(painter: QPainter, drawn: tuple[QPixmap, QRectF], at: QRectF) -> None:
        """A part drawn by _drawn, placed round at."""
        pixmap, area = drawn
        target = area.translated(at.left(), at.top())
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
