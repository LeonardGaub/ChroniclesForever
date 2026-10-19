"""Home: the start page, three cards instead of a wall of tabs.

- Letzte Sitzung (the whole left column): when the character last played, how long, what happened (levels, and
  a game icon with a count per kind of moment), its statistics (quests per hour, time on flight paths, time at
  the level, total played, the average session), the zones it was spent in, its screenshots, and "▶ Rückblick"
  (the session in the cinematic mode) or "⤓ Video".
- Galerie: the newest pictures (favourites first) and how many there are; opens the gallery.
- Karte & Wiedergabe: the last session's route on its zone map, "Karte öffnen" and "▶ Kino-Modus" for everything.
The characters are in the sidebar, so the page has no card for them.
The cards navigate through AppContext.navigate; the main window does the rest.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ...domain import event_types, maps
from ...domain.route import GAP_SECONDS, Route
from ...domain.stats import session_durations
from ...i18n import format_datetime, format_day, format_duration, tr
from ...wow.map_art import find_art
from .. import icons, theme
from ..cards import Card
from ..screenshots import ScreenshotViewer, file_exists, keep_open, load_thumbnail, make_shot
from ..widgets import Page, muted

# Moments counted for the last session, in this order (the type's game icon and the count).
SESSION_TYPES = ("level_up", "quest_completed", "zone_discovered", "achievement_earned", "rare_killed",
                 "boss_killed", "dungeon_completed", "player_died", "recipe_learned")
THUMB = QSize(132, 82)
MAP_PREVIEW = QSize(420, 280)
MAX_ZONES = 4
MIN_RATE_SECONDS = 15 * 60      # shorter sessions show no quests per hour


def clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.setParent(None)          # gone from the card at once, not only after the event loop
            widget.deleteLater()
        elif item.layout():
            clear(item.layout())


def session_range(session, route: Route | None) -> tuple[int, int]:
    """Start and end of a session; a session still open (or closed without its end) ends at its last point."""
    start = session["started_at"]
    end = session["ended_at"]
    if not end and route and route.points:
        end = max((p.end for p in route.points if p.time >= start), default=start)
    return start, max(end or start, start + 1)


def taxi_seconds(route: Route | None, start: int, end: int) -> int:
    """Time of [start, end] spent on flight paths: the taxi points, and the steps between two of them."""
    if not route:
        return 0
    total = 0
    points = route.points
    for i, p in enumerate(points):
        if not p.taxi or p.end < start or p.time > end:
            continue
        to = p.end
        nxt = points[i + 1] if i + 1 < len(points) else None
        if nxt is not None and nxt.taxi and nxt.time - p.end <= GAP_SECONDS:
            to = nxt.time
        total += max(0, min(to, end) - max(p.time, start))
    return total


def zone_times(route: Route | None, start: int, end: int) -> list[tuple[str, int]]:
    """The zones and dungeons of [start, end] with the time spent in each, longest first."""
    if not route:
        return []
    seconds: dict[tuple[int | None, int | None], int] = {}
    for run in route.zone_runs(start, end):
        key = (run.map_id, run.instance_id)
        seconds[key] = seconds.get(key, 0) + int(run.to - run.start)
    out = []
    for (map_id, instance_id), n in seconds.items():
        if instance_id is not None:
            name = route.instance_names.get(instance_id) or f"#{instance_id}"
        else:
            info = route.map_infos.get(map_id)
            name = maps.display_name(map_id, info["name"] if info is not None else None)
        out.append((name, n))
    return sorted(out, key=lambda z: -z[1])


def session_stats(session, count: int, durations: list[int], events, route: Route | None, start: int,
                  end: int) -> list[tuple[str, str]]:
    """The last session's statistics as (label, value) rows; those without data are left out. count: all the
    character's sessions, durations: the lengths of those that have one."""
    rows = []
    quests = sum(1 for e in events if e.event_type == "quest_completed")
    if quests and end - start >= MIN_RATE_SECONDS:
        rate = f"{quests / ((end - start) / 3600):.1f}".replace(".", tr("common.decimal_sep"))
        rows.append((tr("stats.quests_per_hour"), rate))
    taxi = taxi_seconds(route, start, end)
    if taxi >= 60:
        rows.append((tr("home.stat.taxi"), format_duration(taxi)))
    if session["played_level_seconds"] is not None:
        rows.append((tr("home.stat.level_time", level=session["end_level"] or session["start_level"] or "?"),
                     format_duration(session["played_level_seconds"])))
    if session["played_total_seconds"] is not None:
        rows.append((tr("stats.played_total"), format_duration(session["played_total_seconds"])))
    if len(durations) > 1:
        rows.append((tr("home.stat.average"), format_duration(sum(durations) / len(durations))))
    rows.append((tr("stats.sessions"), str(count)))
    return rows


def route_preview(route: Route, view: int, start: int, end: int, size: QSize = MAP_PREVIEW) -> QPixmap:
    """The zone's map with the route of [start, end] drawn on it, as the map page does."""
    pix = QPixmap(size)
    pix.fill(QColor(theme.PANEL_ALT))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    art = find_art(view)
    if art:
        painter.drawPixmap(pix.rect(), QPixmap(str(art)))
    w, h = size.width(), size.height()
    last = None
    for seg in route.segments(view, start, end):
        if len(seg.points) < 2:
            continue
        path = QPainterPath(QPointF(seg.points[0][1] * w, seg.points[0][2] * h))
        for _, x, y in seg.points[1:]:
            path.lineTo(x * w, y * h)
        for width, color in ((5, QColor(26, 15, 5, 200)), (2.5, QColor("#69ccf0" if seg.taxi else theme.GOLD))):
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
        last = QPointF(seg.points[-1][1] * w, seg.points[-1][2] * h)
    if last is not None:
        painter.setPen(QPen(QColor("black"), 2))
        painter.setBrush(QColor(theme.GOLD))
        painter.drawEllipse(last, 6, 6)
    painter.setPen(QPen(QColor(theme.BORDER), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(pix.rect().adjusted(0, 0, -1, -1))
    painter.end()
    return pix


class Thumb(QLabel):
    """A clickable screenshot thumbnail on photo paper."""

    def __init__(self, path: str, on_click, size: QSize = THUMB):
        super().__init__()
        self.on_click = on_click
        self.setFixedSize(size + QSize(8, 8))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #f3eee2; border: 1px solid #c9bea6;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        icon = load_thumbnail(path, size)
        if icon is not None:
            self.setPixmap(icon.pixmap(size))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()


class HomePage(Page):
    title_key = "tab.home"
    needs_character = False

    def __init__(self, ctx):
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)
        self.welcome = QLabel()
        self.welcome.setStyleSheet(theme.font_css(24, theme.GOLD, title=True))
        root.addWidget(self.welcome)
        # First start: what to do to see anything here (opens the wizard).
        self.start_card = Card()
        self.start_text = muted()
        self.start_button = QPushButton()
        self.start_button.clicked.connect(ctx.setup_requested.emit)
        self.start_card.body.addWidget(self.start_text)
        self.start_card.body.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.start_card)
        grid = QGridLayout()
        grid.setSpacing(14)
        self.session_card = Card()
        self.gallery_card = Card(clickable=True)
        self.gallery_card.clicked.connect(lambda: ctx.navigate.emit("tab.gallery"))
        self.map_card = Card()
        grid.addWidget(self.session_card, 0, 0, 2, 1)
        grid.addWidget(self.gallery_card, 0, 1)
        grid.addWidget(self.map_card, 1, 1)
        for column in (0, 1):
            grid.setColumnStretch(column, 1)
        root.addLayout(grid)
        root.addStretch(1)
        self.bodies = {}
        for name, card in (("session", self.session_card), ("gallery", self.gallery_card), ("map", self.map_card)):
            body = QVBoxLayout()
            body.setSpacing(8)
            card.body.addLayout(body)
            card.body.addStretch(1)
            self.bodies[name] = body
        self.windows = []          # cinematic windows and viewers opened from here

    def refresh(self) -> None:
        repo = self.ctx.repo
        char = next((c for c in repo.list_characters() if c.character_id == self.character_id), None)
        self.welcome.setText(tr("home.welcome", name=char.name) if char else tr("home.welcome_none"))
        self.start_card.setVisible(not repo.list_characters())
        self.start_card.title.setText(tr("home.start"))
        self.start_text.setText(tr("home.start_text"))
        self.start_button.setText(tr("home.start_button"))
        self.session_card.title.setText(tr("home.session"))
        self.gallery_card.title.setText(tr("home.gallery"))
        self.map_card.title.setText(tr("home.map"))
        for body in self.bodies.values():
            clear(body)
        route = (Route(repo.positions(self.character_id), repo.map_infos(), repo.instance_names(), repo.entrances())
                 if self.character_id else None)
        sessions = repo.sessions(self.character_id) if self.character_id else []
        self._fill_session(sessions, route)
        self._fill_gallery()
        self._fill_map(sessions[0] if sessions else None, route)

    # -- last session ----------------------------------------------------------------------

    def _fill_session(self, sessions, route: Route | None) -> None:
        body = self.bodies["session"]
        if not sessions:
            body.addWidget(muted(tr("home.no_session")))
            return
        session = sessions[0]
        start, end = session_range(session, route)
        when = QLabel(f"{format_day(start)}  ·  {time.strftime('%H:%M', time.localtime(start))}"
                      f"–{time.strftime('%H:%M', time.localtime(end))}")
        when.setObjectName("CardBig")
        body.addWidget(when)
        played = format_duration(end - start)
        levels = (tr("home.levels", start=session["start_level"], end=session["end_level"])
                  if session["start_level"] and session["end_level"] and session["end_level"] != session["start_level"]
                  else tr("cine.level", level=session["end_level"] or session["start_level"] or "?"))
        body.addWidget(muted(f"{played}  ·  {levels}"))

        events = [e for e in self.ctx.repo.events(self.character_id, types=SESSION_TYPES, limit=100_000)
                  if start <= e.occurred_at <= end]
        chips = QHBoxLayout()
        chips.setSpacing(12)
        for key in SESSION_TYPES:
            n = sum(1 for e in events if e.event_type == key)
            if not n:
                continue
            et = event_types.get(key)
            chip = QHBoxLayout()
            chip.setSpacing(4)
            icon = QLabel()
            pix = icons.small(et.icon, 22)
            if pix is not None:
                icon.setPixmap(pix)
            else:
                icon.setText(et.glyph)
            count = QLabel(str(n))
            count.setStyleSheet(theme.font_css(12, theme.RED if key == 'player_died' else '#ffffff'))
            for w in (icon, count):
                w.setToolTip(tr(et.label_key))
                chip.addWidget(w)
            chips.addLayout(chip)
        chips.addStretch(1)
        if events:
            body.addLayout(chips)
        else:
            body.addWidget(muted(tr("home.quiet_session")))

        stats = QGridLayout()
        stats.setHorizontalSpacing(16)
        stats.setVerticalSpacing(4)
        durations = session_durations(self.ctx.repo, self.character_id)
        for i, (label, value) in enumerate(session_stats(session, len(sessions), durations, events, route, start,
                                                         end)):
            name = muted(label)
            name.setWordWrap(False)
            stats.addWidget(name, i, 0)
            text = QLabel(value)
            text.setStyleSheet(theme.font_css(12, "#ffffff"))
            stats.addWidget(text, i, 1)
        stats.setColumnStretch(2, 1)
        body.addWidget(self._heading(tr("home.stats")))
        body.addLayout(stats)
        self.stats_grid = stats

        zones = zone_times(route, start, end)
        if zones:
            body.addWidget(self._heading(tr("home.zones")))
            for name, seconds in zones[:MAX_ZONES]:
                row = QHBoxLayout()
                label = QLabel(name)
                label.setStyleSheet(theme.font_css(12, "#ffffff"))
                row.addWidget(label)
                row.addStretch(1)
                row.addWidget(muted(format_duration(seconds)))
                body.addLayout(row)
            if len(zones) > MAX_ZONES:
                body.addWidget(muted(tr("home.more_zones", n=len(zones) - MAX_ZONES)))

        shots =[r for r in self.ctx.repo.screenshots(self.character_id, only_files=True)
                 if file_exists(r["file_path"]) and start <= (r["captured_at"] or r["requested_at"] or 0) <= end]
        if shots:
            row = QHBoxLayout()
            row.setSpacing(8)
            by_id = {e.event_id: e for e in events}
            all_shots = [make_shot(r, by_id.get(r["first_event_id"]) or self.ctx.repo.event(self.character_id,
                                                                                           r["first_event_id"] or ""))
                         for r in reversed(shots)]
            for i, shot in enumerate(all_shots[:4]):
                row.addWidget(Thumb(shot.path, lambda i=i, s=all_shots: self._view(s, i)))
            row.addStretch(1)
            body.addLayout(row)
        buttons = QHBoxLayout()
        recap = QPushButton(tr("home.recap"))
        recap.setToolTip(tr("home.recap_tip"))
        recap.clicked.connect(lambda: self.play(start, end))
        video = QPushButton(tr("cine.export"))
        video.setToolTip(tr("cine.export_tip"))
        video.clicked.connect(lambda: self._export(start, end))
        buttons.addWidget(recap)
        buttons.addWidget(video)
        buttons.addStretch(1)
        body.addLayout(buttons)
        self.recap_button = recap

    # -- gallery ---------------------------------------------------------------------------

    def _fill_gallery(self) -> None:
        body = self.bodies["gallery"]
        rows = ([r for r in self.ctx.repo.screenshots(self.character_id, only_files=True) if file_exists(r["file_path"])]
                if self.character_id else [])
        if not rows:
            body.addWidget(muted(tr("gallery.empty")))
            return
        favorites = self.ctx.repo.favorite_screenshots(self.character_id)
        picks = sorted(rows, key=lambda r: (r["screenshot_id"] in favorites,
                                            r["captured_at"] or r["requested_at"] or 0), reverse=True)[:3]
        collage = QHBoxLayout()
        collage.setSpacing(8)
        big = Thumb(picks[0]["file_path"], lambda: self.ctx.navigate.emit("tab.gallery"), QSize(260, 162))
        collage.addWidget(big)
        side = QVBoxLayout()
        side.setSpacing(8)
        for r in picks[1:]:
            side.addWidget(Thumb(r["file_path"], lambda: self.ctx.navigate.emit("tab.gallery"), QSize(122, 75)))
        side.addStretch(1)
        collage.addLayout(side)
        collage.addStretch(1)
        body.addLayout(collage)
        n_fav = sum(1 for r in rows if r["screenshot_id"] in favorites)
        text = QLabel(tr("gallery.count", n=len(rows), fav=n_fav))
        text.setObjectName("CardBig")
        body.addWidget(text)
        body.addWidget(muted(tr("home.gallery_hint")))

    # -- map -------------------------------------------------------------------------------

    def _fill_map(self, session, route: Route | None) -> None:
        body = self.bodies["map"]
        if not route:
            body.addWidget(muted(tr("map.no_points")))
            return
        start, end = session_range(session, route) if session else (route.start, route.end)
        last = route.point_at(end)
        view = route.view_for(last)
        if view is not None:
            preview = QLabel()
            preview.setPixmap(route_preview(route, view, start, end))
            preview.setCursor(Qt.CursorShape.PointingHandCursor)
            preview.mouseReleaseEvent = lambda _e: self.ctx.navigate.emit("tab.map")
            body.addWidget(preview)
            info = route.map_infos.get(view)
            zones = {p.map_id for p in route.points if p.map_id is not None}
            text = QLabel(tr("home.map_last", zone=maps.display_name(view, info["name"] if info is not None else None)))
            text.setObjectName("CardBig")
            body.addWidget(text)
            body.addWidget(muted(tr("home.map_stats", zones=len(zones), since=format_datetime(route.start))))
        buttons = QHBoxLayout()
        open_map = QPushButton(tr("home.open_map"))
        open_map.clicked.connect(lambda: self.ctx.navigate.emit("tab.map"))
        everything = QPushButton(tr("home.cinematic_all"))
        everything.clicked.connect(lambda: self.play(route.start, route.end))
        buttons.addWidget(open_map)
        buttons.addWidget(everything)
        buttons.addStretch(1)
        body.addLayout(buttons)

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(theme.font_css(12, theme.GOLD) + " padding-top: 6px;")
        return label

    # -- actions ---------------------------------------------------------------------------

    def play(self, start: int, end: int):
        """The cinematic mode for [start, end] (the last session's recap, or everything)."""
        from ..cinematic import CinematicWindow
        if not self.character_id:
            return None
        colors = self.ctx.config.extra.get("map_colors") or "level"
        window = keep_open(CinematicWindow(self.ctx, self.character_id, start, end, 4, colors))
        window.showFullScreen()
        return window

    def _export(self, start: int, end: int) -> None:
        from ..cinematic_export import ExportDialog
        colors = self.ctx.config.extra.get("map_colors") or "level"
        ExportDialog(self, self.ctx, self.character_id, start, end, 4, colors).exec()

    def _view(self, shots, index: int) -> None:
        viewer = ScreenshotViewer(shots, index, self, self.ctx)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.showFullScreen()
