"""Cinematic mode: a full-screen replay of the selected time range on the map.

- The route is painted up to the current moment: the last 15 minutes bright, older parts dimmed.
- The camera follows the player at a fixed zoom; on a zone change the new map fades in from black.
- Events appear as short toasts, level-ups as a large title. At each screenshot the replay pauses and shows
  the picture for a few seconds (domain/cinematic.py decides which moments).
- Breaks without route points (logouts, long pauses) are skipped.
- Keys: Space pause/continue (at the end: start again), 1-4 speed, Right: next moment, Left: 5 minutes back,
  Esc: close.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsOpacityEffect, QGraphicsScene,
                               QGraphicsView, QLabel, QVBoxLayout, QWidget)

from ..domain import maps
from ..domain.cinematic import Cue, Levels, build_cues, CUE_EVENT_TYPES
from ..domain.route import Route
from ..i18n import format_datetime, tr
from ..wow.map_art import find_art
from . import theme

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
TICK_MS = 33
BASE_SPEED = 60            # game seconds per real second at 1x (as on the map page)
SPEEDS = (1, 2, 4, 10)
ZOOM = 2.4                 # camera zoom relative to the whole map
CAMERA_EASE = 0.12         # share of the way the camera moves towards the marker per tick
TRAIL_SECONDS = 15 * 60
GAP_SKIP = 30              # breaks without points longer than this are skipped
TOAST_SECONDS = 3.5
LEVEL_SECONDS = 2.8
PHOTO_SECONDS = 4.5
FADE_SECONDS = 0.45
HINT_SECONDS = 5
MAX_TOASTS = 3
ROUTE_COLOR, TAXI_COLOR, OUTLINE = QColor(theme.GOLD), QColor("#69ccf0"), QColor("#1a0f05")


class RouteItem(QGraphicsItem):
    """The route on one map, painted up to time t; the last part up to the moving marker (head)."""

    def __init__(self, segments):
        super().__init__()
        self.segs = [([p[0] for p in seg.points], [QPointF(x * W, y * H) for _, x, y in seg.points], seg.taxi)
                     for seg in segments]
        self.t = 0.0
        self.head: QPointF | None = None

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -10, W + 20, H + 20)

    def set_time(self, t: float, head: QPointF | None) -> None:
        self.t, self.head = t, head
        self.update()

    @staticmethod
    def _pen(color: QColor, width: float, alpha: int, taxi: bool) -> QPen:
        c = QColor(color)
        c.setAlpha(alpha)
        pen = QPen(c, width)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if taxi:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def painted(self) -> int:
        """Number of route points painted at the current time (for tests)."""
        return sum(bisect.bisect_right(times, self.t) for times, _, _ in self.segs)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for times, pts, taxi in self.segs:
            n = bisect.bisect_right(times, self.t)
            if n == 0:
                continue
            drawn = pts[:n]
            if n < len(pts) and self.head is not None:
                drawn = drawn + [self.head]   # the marker is between two points of this segment
            if len(drawn) < 2:
                continue
            # A dark outline keeps the line readable on bright maps (the Barrens are gold too).
            color = TAXI_COLOR if taxi else ROUTE_COLOR
            painter.setPen(self._pen(OUTLINE, 5, 90, False))
            painter.drawPolyline(drawn)
            painter.setPen(self._pen(color, 3, 120, taxi))
            painter.drawPolyline(drawn)
            first = max(0, bisect.bisect_right(times, self.t - TRAIL_SECONDS) - 1)
            if first < n:
                trail = drawn[first:]
                painter.setPen(self._pen(OUTLINE, 8, 200, False))
                painter.drawPolyline(trail)
                painter.setPen(self._pen(color, 4.5, 255, taxi))
                painter.drawPolyline(trail)


@dataclass
class _Toast:
    label: QLabel
    effect: QGraphicsOpacityEffect
    age: float = 0.0


def _faded(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    return effect


def _fade_curve(age: float, life: float) -> float:
    """Opacity over a lifetime: fade in, hold, fade out."""
    if age < FADE_SECONDS:
        return age / FADE_SECONDS
    if age > life - FADE_SECONDS:
        return max(0.0, (life - age) / FADE_SECONDS)
    return 1.0


class CinematicWindow(QWidget):
    def __init__(self, ctx, character_id: str, start: int, end: int, speed: int = 4):
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(tr("cine.title"))
        self.setStyleSheet(f"background: black; color: {theme.TEXT};")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        repo = ctx.repo
        self.route = Route(repo.positions(character_id), repo.map_infos(), repo.instance_names(), repo.entrances())
        events = repo.events(character_id, types=CUE_EVENT_TYPES)
        self.cues: list[Cue] = build_cues(events, repo.screenshots(character_id, only_files=True), start, end)
        self.cue_times = [c.time for c in self.cues]
        char = next((c for c in repo.list_characters() if c.character_id == character_id), None)
        self.char_name = char.name if char else ""
        self.char_color = theme.class_color(char.class_file if char else None)
        self.levels = Levels(events, char.level if char else None)
        self.start, self.end = start, max(end, start + 1)
        self.speed = speed if speed in SPEEDS else 4
        self.t = float(self.route.next_time_after(start - 1) or start)
        self.cue_index = bisect.bisect_left(self.cue_times, self.t)
        self.paused = False
        self.ended = False
        self.view_map: int | None = None
        self.route_item: RouteItem | None = None
        self.camera: QPointF | None = None
        self._art: dict[int, QPixmap] = {}

        self.view = QGraphicsView(self)
        self.view.setScene(QGraphicsScene(self.view))
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setInteractive(False)
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setBackgroundBrush(QColor("black"))
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.marker = QGraphicsEllipseItem(-8, -8, 16, 16)
        self.marker.setBrush(QBrush(QColor(theme.GOLD)))
        self.marker.setPen(QPen(QColor("black"), 2))
        self.marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.marker.setZValue(10)

        # Black cover for map changes (fades out).
        self.cover = QWidget(self)
        self.cover.setStyleSheet("background: black;")
        self.cover_effect = _faded(self.cover)
        self.cover_age = FADE_SECONDS * 2

        self.caption = QLabel(self)
        self.caption.setStyleSheet("background: rgba(0,0,0,170); padding: 12px 18px; border-radius: 4px;"
                                   f"border: 1px solid {theme.BORDER}; font-size: 14pt;")
        self.hint = QLabel(self)
        self.hint.setStyleSheet(f"background: rgba(0,0,0,150); color: {theme.MUTED}; padding: 6px 10px;"
                                "border-radius: 3px; font-size: 10pt;")
        self.hint_effect = _faded(self.hint)
        self.hint_age = 0.0
        self.notice = QLabel(self)
        self.notice.setStyleSheet(f"background: rgba(0,0,0,170); color: {theme.GOLD}; padding: 6px 12px;"
                                  "border-radius: 3px; font-size: 12pt;")
        self.notice.hide()

        self.title = QLabel(self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet(f"background: transparent; color: {theme.GOLD}; font-size: 54pt; font-weight: bold;")
        self.title_effect = _faded(self.title)
        self.title_age, self.title_life = 0.0, 0.0

        self.photo = QWidget(self)
        self.photo.setStyleSheet(f"background: rgba(10,8,6,235); border: 2px solid {theme.BORDER};")
        layout = QVBoxLayout(self.photo)
        layout.setContentsMargins(10, 10, 10, 10)
        self.photo_image = QLabel()
        self.photo_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_image.setStyleSheet("border: none;")
        self.photo_text = QLabel()
        self.photo_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_text.setStyleSheet(f"border: none; color: {theme.GOLD}; font-size: 15pt; padding-top: 6px;")
        layout.addWidget(self.photo_image, 1)
        layout.addWidget(self.photo_text)
        self.photo_effect = _faded(self.photo)
        self.photo_age, self.photo_on = 0.0, False
        self.photo.hide()

        self.toasts: list[_Toast] = []
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self._set_hint()
        self._render()

    # -- lifecycle -----------------------------------------------------------------------

    def start_playback(self) -> None:
        self.clock.start()
        self.timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._layout()
        self._apply_zoom()
        if not self.timer.isActive():
            self.start_playback()

    def closeEvent(self, event) -> None:
        self.timer.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout()
        self._apply_zoom()

    def _layout(self) -> None:
        r = self.rect()
        self.view.setGeometry(r)
        self.cover.setGeometry(r)
        self.caption.adjustSize()
        self.caption.move(24, r.height() - self.caption.height() - 24)
        self.hint.adjustSize()
        self.hint.move(r.width() - self.hint.width() - 24, 24)
        self.notice.adjustSize()
        self.notice.move(24, 24)
        self.title.setGeometry(0, r.height() // 2 - 120, r.width(), 120)
        pw, ph = int(r.width() * 0.72), int(r.height() * 0.78)
        self.photo.setGeometry((r.width() - pw) // 2, (r.height() - ph) // 2, pw, ph)
        y = 70
        for toast in self.toasts:
            toast.label.adjustSize()
            toast.label.move((r.width() - toast.label.width()) // 2, y)
            y += toast.label.height() + 8

    # -- keys ------------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Space:
            if self.ended:
                self.seek(self.start)
            else:
                self.paused = not self.paused
            self._set_hint()
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_4:
            self.speed = SPEEDS[key - Qt.Key.Key_1]
            self._set_hint()
        elif key == Qt.Key.Key_Right:
            if self.cue_index < len(self.cues):
                self.seek(self.cues[self.cue_index].time - 1)
        elif key == Qt.Key.Key_Left:
            self.seek(max(self.start, self.t - 300))
        else:
            super().keyPressEvent(event)

    def seek(self, t: float) -> None:
        self.t = float(max(self.start, min(self.end, t)))
        self.cue_index = bisect.bisect_left(self.cue_times, self.t)
        self.ended = False
        self.title.hide()
        self._hide_photo()
        self._render()

    def _set_hint(self) -> None:
        text = tr("cine.hint", speed=self.speed)
        if self.paused:
            text = tr("cine.paused") + "  ·  " + text
        self.hint.setText(text)
        self.hint_age = 0.0
        self._layout()

    # -- playback --------------------------------------------------------------------------

    def _tick(self) -> None:
        dt = min(0.1, self.clock.restart() / 1000) if self.clock.isValid() else TICK_MS / 1000
        self.advance(dt)

    def advance(self, dt: float) -> None:
        """One step of real time dt (seconds): overlays, then the replay unless a picture is shown."""
        self._age_overlays(dt)
        if self.photo_on:
            self.photo_age += dt
            self.photo_effect.setOpacity(_fade_curve(self.photo_age, PHOTO_SECONDS))
            if self.photo_age >= PHOTO_SECONDS:
                self._hide_photo()
            return
        if self.paused or self.ended:
            return
        t = self.t + self.speed * BASE_SPEED * dt
        t = self._skip_gap(t)
        while self.cue_index < len(self.cues) and self.cues[self.cue_index].time <= t:
            cue = self.cues[self.cue_index]
            self.cue_index += 1
            if cue.kind == "screenshot":
                t = cue.time               # stop exactly there while the picture is shown
                self._show_photo(cue)
                break
            self._show_cue(cue)
        if t >= self.end:
            t, self.ended = self.end, True
            self._show_title(tr("cine.end"), life=10**9)
            self._set_hint()
        self.t = t
        self._render()

    def _skip_gap(self, t: float) -> float:
        """Time without points (logout, a long break) is skipped."""
        times = self.route.times
        i = bisect.bisect_right(times, self.t) - 1
        if 0 <= i < len(times) - 1:
            a, b = self.route.points[i], self.route.points[i + 1]
            if t > a.end and b.time - a.end > GAP_SKIP:
                return max(t, float(b.time)) if t < b.time else t
        return t

    # -- scene -----------------------------------------------------------------------------

    def _render(self) -> None:
        point = self.route.point_at(int(self.t))
        if point is None:
            return
        zone = self.route.view_for(point)
        if zone is not None and zone != self.view_map:
            self._switch_map(zone)
        spot = self.route.glide(self.t)
        xy = self.route.project(*spot, self.view_map) if spot and self.view_map is not None else None
        head = QPointF(xy[0] * W, xy[1] * H) if xy else None
        if self.route_item:
            self.route_item.set_time(self.t, head if point.instance_id is None else None)
        if head is not None:
            self.marker.setPos(head)
            self.marker.show()
            self.camera = head if self.camera is None else QPointF(
                self.camera.x() + (head.x() - self.camera.x()) * CAMERA_EASE,
                self.camera.y() + (head.y() - self.camera.y()) * CAMERA_EASE)
            self.view.centerOn(self.camera)
        else:
            self.marker.hide()
        dungeon = self.route.instance_name(point)
        self.notice.setText(tr("cine.in_dungeon", name=dungeon) if dungeon else "")
        self.notice.setVisible(bool(dungeon))
        self._set_caption(zone)

    def _switch_map(self, view: int) -> None:
        scene = self.view.scene()
        if self.marker.scene() is scene:
            scene.removeItem(self.marker)   # kept across maps; clear() would delete it
        scene.clear()
        self.view_map = view
        scene.setSceneRect(QRectF(0, 0, W, H))
        pixmap = self._pixmap(view)
        if pixmap is not None:
            scene.addPixmap(pixmap)
        else:
            scene.addRect(QRectF(0, 0, W, H), QPen(QColor(theme.BORDER)), QBrush(QColor(theme.PANEL)))
        self.route_item = RouteItem(self.route.segments(view, self.start, self.end))
        scene.addItem(self.route_item)
        scene.addItem(self.marker)
        self.camera = None
        self._apply_zoom()
        self.cover_age = 0.0
        self.cover_effect.setOpacity(1.0)

    def _pixmap(self, view: int) -> QPixmap | None:
        if view not in self._art:
            art = find_art(view)
            pixmap = QPixmap(str(art)) if art else QPixmap()
            if not pixmap.isNull() and (pixmap.width() != W or pixmap.height() != H):
                pixmap = pixmap.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            self._art[view] = pixmap
        pixmap = self._art[view]
        return None if pixmap.isNull() else pixmap

    def _apply_zoom(self) -> None:
        vw, vh = self.view.viewport().width(), self.view.viewport().height()
        if vw <= 0 or vh <= 0:
            return
        scale = min(vw / W, vh / H) * ZOOM
        self.view.resetTransform()
        self.view.scale(scale, scale)
        if self.camera is not None:
            self.view.centerOn(self.camera)

    def _set_caption(self, zone: int | None) -> None:
        info = self.route.map_infos.get(zone) if zone is not None else None
        zone_name = maps.display_name(zone, info["name"] if info is not None else None) if zone is not None else ""
        level = self.levels.at(self.t)
        parts = [f"<span style='color:{self.char_color}; font-weight:bold'>{self.char_name}</span>"]
        if level:
            parts.append(tr("cine.level", level=level))
        text = ("  ·  ".join(parts) + f"<br><span style='color:{theme.MUTED}; font-size:11pt'>"
                f"{zone_name}  ·  {format_datetime(int(self.t))}</span>")
        if text != self.caption.text():
            self.caption.setText(text)
            self._layout()

    # -- overlays --------------------------------------------------------------------------

    def _show_cue(self, cue: Cue) -> None:
        if cue.kind == "level" and cue.level is not None:
            self._show_title(tr("cine.level", level=cue.level), LEVEL_SECONDS)
            return
        label = QLabel(f"<span style='color:{cue.color}'>{cue.glyph}</span>  {cue.text}", self)
        label.setStyleSheet(f"background: rgba(0,0,0,185); color: {theme.TEXT}; padding: 8px 16px;"
                            f"border: 1px solid {theme.BORDER}; border-radius: 4px; font-size: 13pt;")
        toast = _Toast(label, _faded(label))
        label.show()
        self.toasts.append(toast)
        while len(self.toasts) > MAX_TOASTS:
            self.toasts.pop(0).label.deleteLater()
        self._layout()

    def _show_title(self, text: str, life: float) -> None:
        self.title.setText(text)
        self.title_age, self.title_life = 0.0, life
        self.title.show()

    def _show_photo(self, cue: Cue) -> None:
        pixmap = QPixmap(cue.path)
        if pixmap.isNull():
            return
        self._layout()
        box = self.photo.contentsRect()
        self.photo_image.setPixmap(pixmap.scaled(max(1, box.width() - 20), max(1, box.height() - 70),
                                                 Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        self.photo_text.setText(f"{cue.text}  ·  {format_datetime(cue.time)}")
        self.photo_age, self.photo_on = 0.0, True
        self.photo_effect.setOpacity(0.0)
        self.photo.show()
        self.photo.raise_()

    def _hide_photo(self) -> None:
        self.photo_on = False
        self.photo.hide()

    def _age_overlays(self, dt: float) -> None:
        for toast in list(self.toasts):
            toast.age += dt
            toast.effect.setOpacity(_fade_curve(toast.age, TOAST_SECONDS))
            if toast.age >= TOAST_SECONDS:
                self.toasts.remove(toast)
                toast.label.deleteLater()
                self._layout()
        if self.title.isVisible():
            self.title_age += dt
            self.title_effect.setOpacity(_fade_curve(self.title_age, self.title_life))
            if self.title_age >= self.title_life:
                self.title.hide()
        if self.cover_age < FADE_SECONDS * 2:
            self.cover_age += dt
            self.cover_effect.setOpacity(max(0.0, 1 - self.cover_age / FADE_SECONDS))
        self.hint_age += dt
        self.hint_effect.setOpacity(1.0 if self.paused or self.ended else _fade_curve(self.hint_age + FADE_SECONDS,
                                                                                    HINT_SECONDS))
