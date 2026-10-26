"""What the cinematic mode (ui/cinematic.py) draws on top of the map art.

On the map (scene items):
- RouteItem: the route up to the current moment. Older parts are thin and dim; the last TRAIL_SECONDS grow
  brighter and wider in small steps towards the marker, the newest minutes glow. Flight paths are dashed, and
  their dashes move along the line; corpse runs are pale and dotted.
- MarkerItem: the player, at screen size: a disc in the class colour with a pulsing halo and an arrow in the
  direction of travel; a flapping gryphon on flight paths and a swirling portal inside dungeons. Dead it is a
  dim grave mark, released a floating wisp (the ghost). Flying to a teleport's destination it is a bright arcane
  comet.
- PinsItem: a pin where each event of the replay happened, once it has happened (screenshots as small
  polaroids), and short bursts on the map at the moment something happens (a teleport: an arcane swirl where the
  player vanishes and a flash where they arrive).
- SkyItem: the time of day over the map (domain/daylight.py), multiplied onto the map art.
- CinemaView: the view showing the map; while the player is dead it drains the colour like the game's spirit
  world (grey with a cold blue light).

Over the window (widgets, all transparent for the mouse):
- CinemaFrame: a vignette and letterbox bars that slide in when the replay starts.
- TitleCard: the large title of a level-up (and of the end): it scales in with a glow and a passing shine. A
  death gets the same card in dark red.
- AchievementToast: an event, as a small achievement alert that slides in from the right.
- CloudCover: clouds that close over the picture and part again, for trips to and from an island in the sky.
- PhotoOverlay: a screenshot as a polaroid that flies out from the marker after a white flash, drifts slowly
  under an achievement banner while it is shown, and flies back to its pin. A level-up's picture gets a
  ribbon saying "Level up" instead (its title has just named the level).
"""

from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
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
BURST_LIFE = {"level": 1.7, "death": 1.5, "event": 1.1, "revive": 1.8, "spirit": 1.6, "teleport": 1.5, "arrive": 1.4}
BURST_REACH = {"level": 110, "death": 70, "event": 55, "revive": 90, "spirit": 60, "teleport": 80, "arrive": 95}
GHOST_COLOR = QColor("#b9d3ea")   # the corpse run on the map, and the ghost
ARCANE_COLOR = QColor("#8fc4ff")  # teleports: the swirl, the comet and its trail
GHOST_DOTS = (0.1, 2.2)    # dotted line of the corpse run, in pen widths
SPIRIT_TINT = QColor(96, 116, 142)    # the spirit world's light: grey tones in this colour
LETTERBOX = 2.2            # aspect ratio of the picture between the bars
BARS_SECONDS = 1.2         # time the bars take to slide in


# -- helpers ------------------------------------------------------------------------------------------------

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

class RouteItem(QGraphicsItem):
    """The route on one map, painted up to time t; the last part up to the moving marker (head). Lines within a
    ghost span (from the release to coming back to life) are the corpse run."""

    def __init__(self, segments, colors: RouteColors, ghost_spans=()):
        super().__init__()
        self.setZValue(2)                        # above the map art and the light
        self.segs = []
        self.has_taxi = False
        for seg in segments:
            times = [p[0] for p in seg.points]
            # Colour of the line from point i-1 to point i: the route's colour where it ends, or the corpse run's.
            line_colors = [None] + [QColor(colors.at(t, seg.taxi)) for t in times[1:]]
            if ghost_spans and not seg.taxi:
                for i in range(1, len(times)):
                    if any(a < times[i] <= b for a, b in ghost_spans):
                        line_colors[i] = GHOST_COLOR
            self.segs.append((times, [QPointF(x * W, y * H) for _, x, y in seg.points], seg.taxi,
                              self._runs(line_colors), line_colors))
            self.has_taxi = self.has_taxi or seg.taxi
        self.t = 0.0
        self.head: QPointF | None = None
        self.phase = 0.0

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

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        old, trail, glow = [], [], []        # (taxi, colour, points), (taxi, step, colour, points), ...
        for times, pts, taxi, runs, line_colors in self.segs:
            n = bisect.bisect_right(times, self.t)
            if n == 0:
                continue
            first = max(0, bisect.bisect_right(times, self.t - TRAIL_SECONDS) - 1)
            for a, b, color in runs:
                if a >= first:
                    break
                line = pts[a:min(b, first) + 1]
                if len(line) >= 2:
                    old.append((taxi, color, line))
            lines = self._trail_lines(times, pts, line_colors, first, n)
            for (step, color), line in self._group(
                    lines, lambda ln: (min(TRAIL_STEPS - 1, int(ln[0] / TRAIL_SECONDS * TRAIL_STEPS)), ln[1])):
                trail.append((taxi, step, color, line))
            for (step, color), line in self._group(
                    [ln for ln in lines if ln[0] < GLOW_SECONDS],
                    lambda ln: (min(3, int(ln[0] / GLOW_SECONDS * 4)), ln[1])):
                glow.append((step, color, line))

        # Glow under everything (added light), then all outlines, then the lines, so joints stay clean.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for step, color, line in glow:
            k = 1 - step / 4
            for width, alpha in ((18, 26), (10, 46)):
                painter.setPen(self._pen(color, width, alpha * k, False))
                painter.drawPolyline(line)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # A dark outline keeps the line readable on bright maps (the Barrens are gold too).
        for taxi, color, line in old:
            painter.setPen(self._pen(OUTLINE, 5, 90, False))
            painter.drawPolyline(line)
        for taxi, step, color, line in trail:
            k = 1 - (step + 0.5) / TRAIL_STEPS          # 1: newest
            painter.setPen(self._pen(OUTLINE, 5 + 3 * k, 90 + 120 * k, False))
            painter.drawPolyline(line)
        for taxi, color, line in old:
            painter.setPen(self._pen(color, 3, 120, taxi))
            painter.drawPolyline(line)
        for taxi, step, color, line in trail:
            k = 1 - (step + 0.5) / TRAIL_STEPS
            painter.setPen(self._pen(color, 3 + 1.8 * k, 130 + 125 * k, taxi))
            painter.drawPolyline(line)


# -- marker -------------------------------------------------------------------------------------------------

class MarkerItem(QGraphicsItem):
    """The player on the map, drawn at screen size: walking (disc, halo, arrow), on a flight path (gryphon)
    or inside a dungeon (portal at its entrance)."""

    TAXI_COLOR = QColor(hex_color(TAXI))      # the flight paths' blue
    PORTAL_COLOR = QColor("#a87bff")

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setZValue(10)
        self.color = QColor(theme.GOLD)
        self.mode = "walk"           # "walk" | "taxi" | "dungeon" | "dead" | "ghost" | "flight"
        self.angle = 0.0             # direction of travel in degrees, as on screen (0: right, 90: down)
        self.motion = 0.0            # 0..1: how visible the arrow is (only while moving)
        self.moving = False
        self.clock = 0.0

    def boundingRect(self) -> QRectF:
        return QRectF(-34, -34, 68, 68)

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

    def tick(self, dt: float) -> None:
        self.clock += dt
        self.motion = clamp(self.motion + (dt * 4 if self.moving else -dt * 2))
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
        self._halo(painter, self.TAXI_COLOR, 26 + 4 * pulse, 170)
        painter.save()
        painter.rotate(self.angle)
        painter.scale(1.45, 1.45)
        s = 0.55 + 0.45 * math.sin(self.clock * 9)      # wing beat
        bird = QPainterPath()
        bird.moveTo(9, 0)
        bird.lineTo(5, -2.5)
        bird.cubicTo(2, -6 * s, -3, -12 * s, -8, -17 * s)
        bird.lineTo(-5, -7 * s)
        bird.lineTo(-7, -3)
        bird.lineTo(-14, -4)
        bird.lineTo(-11, 0)
        bird.lineTo(-14, 4)
        bird.lineTo(-7, 3)
        bird.lineTo(-5, 7 * s)
        bird.lineTo(-8, 17 * s)
        bird.cubicTo(-3, 12 * s, 2, 6 * s, 5, 2.5)
        bird.closeSubpath()
        painter.setPen(QPen(QColor(20, 14, 6, 230), 1.6))
        painter.setBrush(QColor("#f1dca6"))
        painter.drawPath(bird)
        painter.setBrush(QColor("#fff7e0"))
        painter.drawEllipse(QPointF(8, 0), 3.2, 3.2)       # head
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


# -- pins and bursts ----------------------------------------------------------------------------------------

@dataclass
class Pin:
    time: int
    pos: QPointF                 # on the map (scene)
    glyph: str
    color: QColor
    thumb: QPixmap | None = None  # screenshots: a small picture
    tilt: float = 0.0
    icon: QPixmap | None = None   # events: the game icon, shown instead of the glyph


@dataclass
class Burst:
    pos: QPointF
    color: QColor
    kind: str                     # a key of BURST_LIFE
    age: float = 0.0


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
        placed: list[QPointF] = []
        for i in sorted(self.shown):
            pin = self.pins[i]
            p = transform.map(pin.pos)
            same = sum(1 for q in placed if abs(q.x() - p.x()) + abs(q.y() - p.y()) < 6)
            placed.append(QPointF(p))
            if same:
                a = math.radians(same * 55 - 90)
                ring = 18 + 6 * (same // 6)
                p = QPointF(p.x() + math.cos(a) * ring, p.y() + math.sin(a) * ring)
            scale = ease_out_back(self.shown[i].age / PIN_POP)
            if scale <= 0.01:
                continue
            painter.save()
            painter.translate(p)
            painter.scale(scale, scale)
            if pin.thumb is not None:
                self._polaroid(painter, pin)
            else:
                self._medallion(painter, pin)
            painter.restore()
        for b in self.bursts:
            self._burst(painter, transform.map(b.pos), b)
        painter.restore()

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
        draw_polaroid(painter, QRectF(-14, -13, 28, 26), QRectF(-12, -11, 24, 17), pin.thumb, QPointF(1.5, 2.5))

    @staticmethod
    def _burst(painter: QPainter, p: QPointF, b: Burst) -> None:
        x = b.age / BURST_LIFE[b.kind]
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

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.save()
        painter.translate(w / 2, h / 2)
        painter.scale(w / 2, h / 2)
        vignette = QRadialGradient(QPointF(0, 0), 1.42)
        vignette.setColorAt(0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.5, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.78, QColor(0, 0, 0, 90))
        vignette.setColorAt(1, QColor(0, 0, 0, 215))
        painter.fillRect(QRectF(-1, -1, 2, 2), vignette)
        painter.restore()
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
    hides the map completely (the trip changes maps under it). Lower amounts part the clouds: banks of puffs,
    lit from the upper left with grey-blue undersides, rush outward from the middle and grow, as when the camera
    drops through them (and come together again on the way up). Lit by the time of day like the map
    (set_light)."""

    BANKS, PUFFS = 18, 9           # cloud banks, puffs per bank

    def __init__(self, parent):
        super().__init__(parent)
        self.amount = 0.0
        self.clock = 0.0
        self.light = (1.0, 1.0, 1.0)
        rng = random.Random(7)
        self.banks = []
        for k in range(self.BANKS):
            # Spread around the middle on a sunflower spiral, so every part of the picture is covered.
            reach = 0.62 * math.sqrt((k + 0.5) / self.BANKS)
            angle = k * 2.39996 + rng.uniform(-0.3, 0.3)
            x, y = 0.5 + reach * math.cos(angle) * 1.15, 0.5 + reach * math.sin(angle)
            away = math.atan2(y - 0.5, x - 0.5) if reach > 0.08 else rng.uniform(-math.pi, math.pi)
            puffs = [(rng.gauss(0, 0.075), rng.gauss(0, 0.035), rng.uniform(0.07, 0.13), rng.uniform(0.9, 1.0))
                     for _ in range(self.PUFFS)]
            self.banks.append((x, y, math.cos(away), math.sin(away), rng.uniform(0.8, 1.25), puffs))
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
        size = max(w, h)
        part = 1 - a
        # Deep inside the clouds: a misty fill, lighter in the middle; at 1 nothing of the map shows.
        veil = ease_in(clamp((a - 0.8) / 0.2))
        if veil > 0:
            mist = QRadialGradient(QPointF(w / 2, h / 2), size * 0.75)
            mist.setColorAt(0, self._color(1.0, veil))
            mist.setColorAt(1, self._color(0.86, veil))
            painter.fillRect(self.rect(), mist)
        painter.setPen(Qt.PenStyle.NoPen)
        alpha = clamp(a * 2.2)
        for x, y, dx, dy, speed, puffs in self.banks:
            reach = part * 1.25 * speed
            grow = 1 + 1.4 * part
            bx = (x + self.clock * 0.01 * speed + dx * reach) * w
            by = (y + dy * reach) * h
            for px, py, radius, shade in puffs:
                cx, cy, r = bx + px * size * grow, by + py * size * grow, radius * size * grow
                shadow = QRadialGradient(QPointF(cx + 0.12 * r, cy + 0.2 * r), r)
                shadow.setColorAt(0, self._color(0.72 * shade, alpha * 0.35))
                shadow.setColorAt(1, self._color(0.72 * shade, 0))
                painter.setBrush(shadow)
                painter.drawEllipse(QPointF(cx + 0.12 * r, cy + 0.2 * r), r, r)
                puff = QRadialGradient(QPointF(cx, cy), r, QPointF(cx - 0.3 * r, cy - 0.35 * r))
                puff.setColorAt(0, self._color(1.04 * shade, alpha))
                puff.setColorAt(0.5, self._color(0.95 * shade, alpha * 0.85))
                puff.setColorAt(1, self._color(0.86 * shade, 0))
                painter.setBrush(puff)
                painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.end()


class TitleCard(_TimedOverlay):
    """A large centred title: a small heading between gold lines, the title in gold with a glow and a passing
    shine, and a subtitle. It scales in and fades out."""

    INTRO = 0.45
    SHINE = (0.35, 1.25)          # when the shine passes, in seconds of its life
    # Colours per tone: glow, top/middle/bottom of the letters' fill, heading and its lines.
    TONES = {
        "gold": (GOLD_GLOW, GOLD_LETTERS, BANNER_HEADING, TRIM),
        "death": (QColor(220, 40, 30), ("#ffd9d2", "#d8352b", "#6e0f0c"), QColor("#e8a39b"), QColor("#a8433a")),
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.heading = self.text = self.subtitle = ""
        self.tone = "gold"
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self.envelope(FADE_SECONDS, FADE_SECONDS))
        w, h = self.width(), self.height()
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
        _gold_letters(painter, path, glow, [(width, alpha * intro) for width, alpha in ((26, 22), (14, 40), (7, 70))],
                      5, letters, (self.age - self.SHINE[0]) / (self.SHINE[1] - self.SHINE[0]))
        half = box.width() * fit / 2
        top, bottom = box.top() * fit, box.bottom() * fit
        painter.restore()

        if self.heading:
            draw_flourish_heading(painter, QPointF(0, top - h * 0.1), self.heading, h * 0.085, heading_color, trim,
                                  reach=40 + 70 * intro, least=half + 70 * intro)
        if self.subtitle:
            painter.setFont(pixel_font(h * 0.08))
            draw_shadowed_text(painter, QRectF(-w / 2, bottom + h * 0.05, w, h * 0.12), self.subtitle,
                               QColor("#d9c9a3"), offset=1.5)
        painter.end()


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
        self.y: float | None = None     # current top, eased towards target_y
        self.target_y = 0.0

    def place_at(self, right: float, top: float) -> None:
        self.right, self.target_y = right, top
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
