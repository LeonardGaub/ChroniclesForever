"""Map: route replay on the game's map images (spec F-005).

- Map selector (zones with route points and their continents), session filter, route/event toggles.
- Route colours as in the addon: by level (default), by session or one colour, with a legend; flight paths blue
  (domain/route_colors.py). The choice is kept in the app settings and used by cinematic mode too.
- Time slider and playback (1x = one minute of play time per second; gaps are skipped).
- The marker shows the nearest recorded point; inside dungeons there is no position, so a notice is shown.
- Selecting an event in the Chronicle moves the map to that moment (AppContext.focus_time).
- Without artwork for a map a schematic grid is drawn instead.
- Cinematic mode plays the selected range full screen with events and screenshots (ui/cinematic.py).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

from ...domain import event_types, maps
from ...domain.cinematic import Levels
from ...domain.route import Route
from ...domain.route_colors import MODES, SEGMENT_END, RouteColors, hex_color
from ...i18n import format_datetime, format_duration, tr
from ...wow.map_art import find_art
from .. import theme
from ..cinematic import CinematicWindow
from ..widgets import Page, muted

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
BASE_SPEED = 60          # game seconds per real second at 1x
TICK_MS = 50
SPEEDS = (1, 2, 4, 10)


def _marker(radius: float, fill: str, outline: str = "#000000") -> QGraphicsEllipseItem:
    item = QGraphicsEllipseItem(-radius, -radius, 2 * radius, 2 * radius)
    item.setBrush(QBrush(QColor(fill)))
    item.setPen(QPen(QColor(outline), 1.5))
    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
    return item


class MapView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(theme.PANEL_ALT))
        self.setStyleSheet(f"border: 1px solid {theme.BORDER};")
        self.zoomed = False

    def fit(self) -> None:
        self.zoomed = False
        self.fitInView(QRectF(0, 0, W, H), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        fit_scale = min(self.viewport().width() / W, self.viewport().height() / H)
        if scale < fit_scale:
            self.fit()
            return
        if scale > fit_scale * 10:
            return
        self.zoomed = True
        self.scale(factor, factor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.zoomed:
            self.fit()


class MapPage(Page):
    title_key = "tab.map"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.route: Route | None = None
        self.view_map: int | None = None
        self._last_zone: int | None = None  # zone of the last shown point (map follow)
        self.range: tuple[int, int] | None = None
        self.current_t: int | None = None
        self.pending_focus: int | None = None
        self._updating = False
        self._art_notice: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.map_select = QComboBox()
        self.map_select.setMinimumWidth(200)
        self.map_select.currentIndexChanged.connect(self._map_selected)
        self.session_select = QComboBox()
        self.session_select.setMinimumWidth(220)
        self.session_select.currentIndexChanged.connect(self._session_selected)
        self.show_trail = QCheckBox()
        self.show_trail.setChecked(True)
        self.show_trail.toggled.connect(lambda _: self._draw())
        self.show_events = QCheckBox()
        self.show_events.setChecked(True)
        self.show_events.toggled.connect(lambda _: self._draw())
        self.follow = QCheckBox()
        self.follow.setChecked(True)
        self.color_select = QComboBox()
        self.color_select.currentIndexChanged.connect(self._colors_selected)
        for w in (self.map_select, self.session_select):
            top.addWidget(w)
        top.addSpacing(8)
        for w in (self.show_trail, self.show_events, self.follow):
            top.addWidget(w)
        top.addSpacing(8)
        top.addWidget(self.color_select)
        top.addStretch(1)
        root.addLayout(top)

        self.view = MapView()
        root.addWidget(self.view, 1)
        self.notice = QLabel(self.view)
        self.notice.setStyleSheet(f"background: rgba(9,8,7,200); color: {theme.GOLD}; padding: 6px 10px;"
                                  f"border: 1px solid {theme.BORDER}; border-radius: 3px;")
        self.notice.move(10, 10)
        self.notice.hide()
        self.legend = QLabel(self.view)
        self.legend.setStyleSheet(f"background: rgba(0,0,0,166); color: {theme.TEXT}; padding: 6px 10px;")
        self.legend.hide()
        self.colors: RouteColors | None = None

        bottom = QHBoxLayout()
        self.play = QPushButton()
        self.play.setFixedWidth(110)
        self.play.clicked.connect(self._toggle_play)
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s}×", s)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._slider_moved)
        self.time_label = muted()
        self.time_label.setMinimumWidth(150)
        self.cinematic = QPushButton()
        self.cinematic.clicked.connect(self._open_cinematic)
        bottom.addWidget(self.play)
        bottom.addWidget(self.speed)
        bottom.addWidget(self.slider, 1)
        bottom.addWidget(self.time_label)
        bottom.addWidget(self.cinematic)
        root.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.marker = None
        ctx.focus_time.connect(self._focus)

    # -- data ------------------------------------------------------------------------------

    def refresh(self) -> None:
        self._texts()
        self.timer.stop()
        self._set_play_text()
        if not self.character_id:
            self.route = None
            self._clear("")
            return
        repo = self.ctx.repo
        self.route = Route(repo.positions(self.character_id), repo.map_infos(), repo.instance_names(),
                           repo.entrances())
        char = next((c for c in repo.list_characters() if c.character_id == self.character_id), None)
        self.colors = RouteColors(self._color_mode(),
                                  Levels(repo.events(self.character_id, types=("level_up",)), char.level if char else None),
                                  [s["started_at"] for s in repo.sessions(self.character_id)])
        self._fill_sessions()
        self._fill_maps()
        if not self.route:
            self._clear(tr("map.no_points"))
            return
        if self.pending_focus is not None:
            focus, self.pending_focus = self.pending_focus, None
            self._jump_to(focus)
        else:
            self._apply_range()

    def _texts(self) -> None:
        self.show_trail.setText(tr("map.trail"))
        self.show_events.setText(tr("map.events"))
        self.follow.setText(tr("map.follow"))
        self.speed.setToolTip(tr("map.speed_tip"))
        self.cinematic.setText(tr("map.cinematic"))
        self.cinematic.setToolTip(tr("map.cinematic_tip"))
        self.color_select.blockSignals(True)
        self.color_select.clear()
        for mode in MODES:
            self.color_select.addItem(tr(f"map.colors_{mode}"), mode)
        self.color_select.setCurrentIndex(MODES.index(self._color_mode()))
        self.color_select.setToolTip(tr("map.colors_tip"))
        self.color_select.blockSignals(False)

    def _color_mode(self) -> str:
        mode = self.ctx.config.extra.get("map_colors")
        return mode if mode in MODES else MODES[0]

    def _colors_selected(self) -> None:
        mode = self.color_select.currentData()
        if mode is None or mode == self._color_mode():
            return
        self.ctx.config.extra["map_colors"] = mode
        self.ctx.config.save()
        if self.colors:
            self.colors = RouteColors(mode, self.colors.levels, self.colors.session_starts)
            self._draw()
            self._update_marker()

    def _fill_sessions(self) -> None:
        self.session_select.blockSignals(True)
        self.session_select.clear()
        self.session_select.addItem(tr("map.session_all"), None)
        for s in self.ctx.repo.sessions(self.character_id):
            end = s["ended_at"] or int(time.time())
            label = tr("map.session_item", date=format_datetime(s["started_at"]),
                       duration=format_duration(end - s["started_at"]))
            self.session_select.addItem(label, (s["started_at"], end))
        self.session_select.blockSignals(False)

    def _fill_maps(self) -> None:
        self.map_select.blockSignals(True)
        self.map_select.clear()
        infos = self.route.map_infos if self.route else {}
        for map_id in (self.route.available_views() if self.route else []):
            info = infos.get(map_id)
            self.map_select.addItem(maps.display_name(map_id, info["name"] if info is not None else None), map_id)
        self.map_select.blockSignals(False)

    def _clear(self, notice: str) -> None:
        self.view.scene().clear()
        self.marker = None
        self.view_map = None
        self.legend.hide()
        self.slider.setEnabled(False)
        self.play.setEnabled(False)
        self.cinematic.setEnabled(False)
        self.time_label.setText("")
        self._show_notice(notice)

    # -- range, map and time -------------------------------------------------------------

    def _apply_range(self) -> None:
        data = self.session_select.currentData()
        start, end = data if data else (self.route.start, self.route.end)
        self.range = (start, max(end, start + 1))
        self._updating = True
        self.slider.setRange(0, self.range[1] - self.range[0])
        self.slider.setEnabled(True)
        self.play.setEnabled(True)
        self.cinematic.setEnabled(True)
        self._updating = False
        self._last_zone = None
        self._set_view(self.route.view_for(self.route.point_at(start)) or self._first_view(), redraw=True)
        self._set_time(start)

    def _first_view(self) -> int | None:
        views = self.route.available_views()
        return views[0] if views else None

    def _session_selected(self) -> None:
        if self.route:
            self.timer.stop()
            self._set_play_text()
            self._apply_range()

    def _map_selected(self) -> None:
        map_id = self.map_select.currentData()
        if map_id is not None and map_id != self.view_map:
            self._set_view(map_id, redraw=True)
            if self.current_t is not None:
                self._set_time(self.current_t)

    def _set_view(self, map_id: int | None, redraw: bool) -> None:
        self.view_map = map_id
        index = self.map_select.findData(map_id)
        if index >= 0 and index != self.map_select.currentIndex():
            self.map_select.blockSignals(True)
            self.map_select.setCurrentIndex(index)
            self.map_select.blockSignals(False)
        if redraw:
            self._draw()
            self.view.fit()

    def _slider_moved(self, value: int) -> None:
        if not self._updating and self.range:
            self._set_time(self.range[0] + value)

    def _set_time(self, t: int) -> None:
        self.current_t = t
        if self.range:
            self._updating = True
            self.slider.setValue(max(0, min(t - self.range[0], self.slider.maximum())))
            self._updating = False
        self.time_label.setText(format_datetime(t))
        self._update_marker()

    def _update_marker(self) -> None:
        if not self.route or self.current_t is None:
            return
        point = self.route.point_at(self.current_t)
        if point is None:
            return
        # Inside a dungeon there is no position: the dungeon entrance is shown instead, if known.
        spot = self.route.locate(point.map_id, point.x, point.y, point.instance_id)
        if spot is None:
            if self.marker:
                self.marker.hide()
            self._show_notice(tr("map.instance", name=self.route.instance_name(point))
                              if point.instance_id is not None else None)
            return
        # Follow the player's zone. A map picked by hand stays until the zone changes or the point is not on it.
        zone = self.route.view_for(point)
        moved_zone = zone != self._last_zone
        self._last_zone = zone
        xy = self.route.project(*spot, self.view_map) if self.view_map else None
        if self.follow.isChecked() and zone is not None and zone != self.view_map and (moved_zone or xy is None):
            self._set_view(zone, redraw=True)
            xy = self.route.project(*spot, self.view_map)
        if xy is None:
            if self.marker:
                self.marker.hide()
            self._show_notice(tr("map.elsewhere", name=maps.display_name(spot[0])))
            return
        self._show_notice(tr("map.instance_entrance", name=self.route.instance_name(point))
                          if point.instance_id is not None else self._art_notice)
        if self.marker:
            self.marker.setPos(QPointF(xy[0] * W, xy[1] * H))
            self.marker.show()

    def _show_notice(self, text: str | None) -> None:
        self.notice.setText(text or "")
        self.notice.adjustSize()
        self.notice.setVisible(bool(text))

    # -- drawing ---------------------------------------------------------------------------

    def _draw(self) -> None:
        scene = self.view.scene()
        scene.clear()
        self.marker = None
        if not self.route or self.view_map is None:
            return
        scene.setSceneRect(QRectF(0, 0, W, H))
        art = find_art(self.view_map)
        pixmap = QPixmap(str(art)) if art else QPixmap()
        if not pixmap.isNull():
            if pixmap.width() != W or pixmap.height() != H:
                pixmap = pixmap.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            scene.addPixmap(pixmap)
            self._art_notice = None
        else:
            self._draw_schematic(scene)
            self._art_notice = tr("map.no_art")

        start, end = self.range or (None, None)
        segments = self.route.segments(self.view_map, start, end) if self.show_trail.isChecked() else []
        for seg in segments:
            self._draw_segment(scene, seg)
        self._show_legend(self.colors.legend(segments) if self.colors else [])
        if self.show_events.isChecked():
            self._draw_events(scene, start, end)
        self.marker = _marker(7, theme.GOLD)
        self.marker.setZValue(10)
        scene.addItem(self.marker)
        self._show_notice(self._art_notice)

    def _draw_schematic(self, scene: QGraphicsScene) -> None:
        scene.addRect(QRectF(0, 0, W, H), QPen(QColor(theme.BORDER)), QBrush(QColor(theme.PANEL)))
        grid = QPen(QColor("#2a2018"))
        for x in range(0, W, 100):
            scene.addLine(x, 0, x, H, grid)
        for y in range(0, H, 100):
            scene.addLine(0, y, W, y, grid)
        label = scene.addSimpleText(maps.display_name(self.view_map))
        font = theme.heading_font(28)
        label.setFont(font)
        label.setBrush(QBrush(QColor(theme.MUTED)))
        r = label.boundingRect()
        label.setPos((W - r.width()) / 2, (H - r.height()) / 2)

    def _draw_segment(self, scene: QGraphicsScene, seg) -> None:
        times = [t for t, _, _ in seg.points]
        for a, b, color in self.colors.runs(times, seg.taxi):
            path = QPainterPath()
            for i in range(a, b + 1):
                pt = QPointF(seg.points[i][1] * W, seg.points[i][2] * H)
                if i == a:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
            pen = QPen(QColor(color), 3)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if seg.taxi:
                pen.setStyle(Qt.PenStyle.DashLine)
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setOpacity(0.9)
            scene.addItem(item)
        # Grey dots mark where recorded data starts and ends (gaps are never bridged), as in the addon.
        for _, x, y in (seg.points[0], seg.points[-1]):
            end = _marker(2.5, hex_color(SEGMENT_END), "#000000")
            end.setPos(QPointF(x * W, y * H))
            scene.addItem(end)

    def _show_legend(self, items: list[tuple[str, str]]) -> None:
        self.legend.setText("<br>".join(f"<span style='color:{c}'>▬</span>&nbsp; {label}" for c, label in items))
        self.legend.adjustSize()
        self._place_legend()
        self.legend.setVisible(bool(items))

    def _place_legend(self) -> None:
        self.legend.move(10, self.view.height() - self.legend.height() - 10)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_legend()

    def _draw_events(self, scene: QGraphicsScene, start: int | None, end: int | None) -> None:
        for e in self.ctx.repo.events(self.character_id):
            if (start is not None and e.occurred_at < start) or (end is not None and e.occurred_at > end):
                continue
            spot = self.route.locate(e.map_id, e.x, e.y, e.instance_id)  # dungeon events: at the entrance
            xy = self.route.project(*spot, self.view_map) if spot else None
            if xy is None:
                continue
            et = event_types.get(e.event_type)
            dot = _marker(5, et.color)
            dot.setPos(QPointF(xy[0] * W, xy[1] * H))
            dot.setToolTip(f"{et.glyph} {event_types.describe(e)}\n{format_datetime(e.occurred_at)}")
            dot.setZValue(5)
            scene.addItem(dot)

    # -- playback --------------------------------------------------------------------------

    def _open_cinematic(self) -> None:
        if not self.route or not self.range or not self.character_id:
            return
        self.timer.stop()
        self._set_play_text()
        self._cinematic_window = CinematicWindow(self.ctx, self.character_id, self.range[0], self.range[1],
                                                 self.speed.currentData(), self._color_mode())
        self._cinematic_window.showFullScreen()

    def _set_play_text(self) -> None:
        self.play.setText(tr("map.pause") if self.timer.isActive() else tr("map.play"))

    def _toggle_play(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
        elif self.range:
            if self.current_t is None or self.current_t >= self.range[1]:
                self._set_time(self.range[0])
            self.timer.start()
        self._set_play_text()

    def _tick(self) -> None:
        if not self.route or self.current_t is None or not self.range:
            self.timer.stop()
            return
        step = max(1, int(self.speed.currentData() * BASE_SPEED * TICK_MS / 1000))
        t = self.current_t + step
        point = self.route.point_at(t)
        if point is None or not (point.time - step <= t <= point.end + step):
            nxt = self.route.next_time_after(self.current_t)
            if nxt is not None:
                t = max(t, nxt)  # skip time without recorded points
        if t >= self.range[1]:
            t = self.range[1]
            self.timer.stop()
            self._set_play_text()
        self._set_time(t)

    # -- timeline sync ---------------------------------------------------------------------

    def _focus(self, character_id: str, t: int) -> None:
        if character_id != self.character_id:
            return
        if not self.isVisible() or not self.route:
            self.pending_focus = t
            return
        self._jump_to(t)

    def _jump_to(self, t: int) -> None:
        index = 0
        for i in range(1, self.session_select.count()):
            start, end = self.session_select.itemData(i)
            if start <= t <= end:
                index = i
                break
        self.session_select.blockSignals(True)
        self.session_select.setCurrentIndex(index)
        self.session_select.blockSignals(False)
        self._apply_range()
        zone = self.route.view_for(self.route.point_at(t))
        if zone is not None and zone != self.view_map:
            self._set_view(zone, redraw=True)
        self._set_time(t)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.pending_focus is not None and self.route:
            focus, self.pending_focus = self.pending_focus, None
            self._jump_to(focus)

    def hideEvent(self, event) -> None:
        self.timer.stop()
        self._set_play_text()
        super().hideEvent(event)
