"""Home: the start page, four cards instead of a wall of tabs.

- Letzte Sitzung: when the character last played, how long, what happened (levels, and a game icon with a count
  per kind of moment), its screenshots, and "▶ Rückblick" (the session in the cinematic mode) or "⤓ Video".
- Galerie: the newest pictures (favourites first) and how many there are; opens the gallery.
- Karte & Wiedergabe: the last session's route on its zone map, "Karte öffnen" and "▶ Kino-Modus" for everything.
- Charaktere: my characters (class colour, level, last played) and the friends' ones; a click shows that
  character.
The cards navigate through AppContext.navigate / select_character; the main window does the rest.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ...domain import event_types, maps
from ...domain.route import Route
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
MAX_CHARACTERS = 7


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
        grid = QGridLayout()
        grid.setSpacing(14)
        self.session_card = Card()
        self.gallery_card = Card(clickable=True)
        self.gallery_card.clicked.connect(lambda: ctx.navigate.emit("tab.gallery"))
        self.map_card = Card()
        self.characters_card = Card()
        grid.addWidget(self.session_card, 0, 0)
        grid.addWidget(self.gallery_card, 0, 1)
        grid.addWidget(self.map_card, 1, 0)
        grid.addWidget(self.characters_card, 1, 1)
        for column in (0, 1):
            grid.setColumnStretch(column, 1)
        root.addLayout(grid)
        root.addStretch(1)
        self.bodies = {}
        for name, card in (("session", self.session_card), ("gallery", self.gallery_card), ("map", self.map_card),
                           ("characters", self.characters_card)):
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
        self.session_card.title.setText(tr("home.session"))
        self.gallery_card.title.setText(tr("home.gallery"))
        self.map_card.title.setText(tr("home.map"))
        self.characters_card.title.setText(tr("home.characters"))
        for body in self.bodies.values():
            clear(body)
        route = (Route(repo.positions(self.character_id), repo.map_infos(), repo.instance_names(), repo.entrances())
                 if self.character_id else None)
        sessions = repo.sessions(self.character_id) if self.character_id else []
        self._fill_session(sessions[0] if sessions else None, route)
        self._fill_gallery()
        self._fill_map(sessions[0] if sessions else None, route)
        self._fill_characters()

    # -- last session ----------------------------------------------------------------------

    def _fill_session(self, session, route: Route | None) -> None:
        body = self.bodies["session"]
        if session is None:
            body.addWidget(muted(tr("home.no_session")))
            return
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

        shots = [r for r in self.ctx.repo.screenshots(self.character_id, only_files=True)
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

    # -- characters ------------------------------------------------------------------------

    def _fill_characters(self) -> None:
        body = self.bodies["characters"]
        chars = self.ctx.repo.list_characters()
        if not chars:
            body.addWidget(muted(tr("sidebar.empty")))
            return
        mine = [c for c in chars if not c.is_friend]
        friends = [c for c in chars if c.is_friend]
        for char in (mine + friends)[:MAX_CHARACTERS]:
            row = QPushButton()
            row.setObjectName("CharacterRow")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setCheckable(True)
            row.setChecked(char.character_id == self.character_id)
            row.clicked.connect(lambda _=False, cid=char.character_id: self._show_character(cid))
            layout = QHBoxLayout(row)
            layout.setContentsMargins(10, 4, 10, 4)
            name = QLabel(char.full_name)
            name.setStyleSheet(theme.font_css(12, theme.class_color(char.class_file)))
            level = QLabel(tr("cine.level", level=char.level or "?"))
            level.setStyleSheet("color: #ffffff; background: transparent;")
            detail = (tr("char.friend", name=char.owner_name or "?") if char.is_friend
                      else tr("home.last_played", when=format_datetime(char.last_seen_at)) if char.last_seen_at else "")
            seen = QLabel(detail)
            seen.setStyleSheet(f"color: {theme.MUTED}; background: transparent; font-size: 8pt;")
            for w in (name, level):
                layout.addWidget(w)
            layout.addStretch(1)
            layout.addWidget(seen)
            row.setMinimumHeight(38)
            body.addWidget(row)
        rest = len(chars) - MAX_CHARACTERS
        if rest > 0:
            body.addWidget(muted(tr("home.more_characters", n=rest)))
        if friends:
            body.addWidget(muted(tr("home.friends", n=len({c.owner_id for c in friends}), chars=len(friends))))

    def _show_character(self, character_id: str) -> None:
        self.ctx.select_character.emit(character_id)
        self.ctx.navigate.emit("tab.overview")

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
