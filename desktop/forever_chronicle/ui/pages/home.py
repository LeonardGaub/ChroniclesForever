"""Home: the start page, three cards instead of a wall of tabs.

- Letzte Sitzung (the whole left column): when the character last played, how long, what happened (levels, and
  a game icon with a count per kind of moment), its statistics (quests per hour, time on flight paths, time at
  the level, total played, the average session), the zones it was spent in, its screenshots, and "▶ Rückblick"
  (the session in the cinematic mode) or "⤓ Video".
- Galerie: the newest pictures (favourites first) and how many there are; opens the gallery.
- Kino: the whole journey on the world map (as on the Kino page, ui/journey_art.py), "▶ Die ganze Reise" and
  "Alle Kapitel" (the Kino page).
The characters are in the sidebar, so the page has no card for them.
The cards navigate through AppContext.navigate; the main window does the rest.
The page refreshes often (every start, import and tab change), so the route comes from Route.cached, the journey
picture is painted again only when the route changed (journey_art.cached_picture) and the photos are read in the
background (ui/image_loader.py) and kept.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ...domain import event_types, maps
from ...domain.route import GAP_SECONDS, Route
from ...domain.stats import session_durations
from ...i18n import format_datetime, format_day, format_duration, tr
from .. import icons, journey_art, theme
from ..cards import Card
from ..image_loader import ImageLoader
from ..screenshots import make_shot, open_viewer, shots_on_disk
from ..widgets import Page, muted

# Moments counted for the last session, in this order (the type's game icon and the count).
SESSION_TYPES = ("level_up", "quest_completed", "zone_discovered", "achievement_earned", "rare_killed",
                 "boss_killed", "dungeon_completed", "player_died")
THUMB = QSize(132, 82)
JOURNEY = QSize(420, 236)
MAX_ZONES = 4
MIN_RATE_SECONDS = 15 * 60      # shorter sessions show no quests per hour
PHOTO_CACHE = 48                # photos kept (path and size)


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
            name = maps.zone_name(map_id, route.map_infos)
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


class Photos:
    """Screenshots for the cards, read in worker threads and kept by path and size. clear() (each refresh) drops
    the callbacks still waiting; pictures being read still arrive in the cache."""

    def __init__(self, parent):
        self.loader = ImageLoader(parent)
        self.cache: dict[tuple[str, int, int], QPixmap] = {}
        self.waiting: dict[tuple[str, int, int], list[Callable[[QPixmap], None]]] = {}

    def clear(self) -> None:
        for applies in self.waiting.values():
            applies.clear()

    def request(self, path: str, size: QSize, apply: Callable[[QPixmap], None]) -> None:
        """Calls apply with the picture now if it is kept, else once it is read (not at all if it cannot be)."""
        key = (path, size.width(), size.height())
        pix = self.cache.get(key)
        if pix is not None:
            apply(pix)
        elif key in self.waiting:
            self.waiting[key].append(apply)
        else:
            self.waiting[key] = [apply]
            self.loader.request(path, lambda image, k=key: self._loaded(k, image), size)

    def _loaded(self, key: tuple[str, int, int], image) -> None:
        applies = self.waiting.pop(key, [])
        if image is None:
            return
        pix = self.cache[key] = QPixmap.fromImage(image)
        while len(self.cache) > PHOTO_CACHE:
            self.cache.pop(next(iter(self.cache)))
        for apply in applies:
            apply(pix)


class Thumb(QLabel):
    """A clickable screenshot thumbnail on photo paper; the picture comes in when photos has read it."""

    def __init__(self, path: str, on_click, size: QSize = THUMB, photos: Photos | None = None):
        super().__init__()
        self.on_click = on_click
        self.setFixedSize(size + QSize(8, 8))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #f3eee2; border: 1px solid #c9bea6;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if photos is not None and path:
            photos.request(path, size, self._show)

    def _show(self, pix: QPixmap) -> None:
        try:
            self.setPixmap(pix)
        except RuntimeError:  # the card was filled again meanwhile
            pass

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()


class HomePage(Page):
    title_key = "tab.home"

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
        self.photos = Photos(self)

    def refresh(self) -> None:
        repo = self.ctx.repo
        char = repo.character(self.character_id)
        self.welcome.setText(tr("home.welcome", name=char.name) if char else tr("home.welcome_none"))
        self.start_card.setVisible(not repo.list_characters())
        self.start_card.title.setText(tr("home.start"))
        self.start_text.setText(tr("home.start_text"))
        self.start_button.setText(tr("home.start_button"))
        self.session_card.title.setText(tr("home.session"))
        self.gallery_card.title.setText(tr("home.gallery"))
        self.map_card.title.setText(tr("home.map"))
        self.photos.clear()
        for body in self.bodies.values():
            clear(body)
        route = Route.cached(repo, self.character_id) if self.character_id else None
        sessions = repo.sessions(self.character_id) if self.character_id else []
        shots = shots_on_disk(repo, self.character_id) if self.character_id else []
        self._fill_session(sessions, route, shots)
        self._fill_gallery(shots)
        self._fill_map(sessions, route, char)

    # -- last session ----------------------------------------------------------------------

    def _fill_session(self, sessions, route: Route | None, shots: list) -> None:
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

        shots = [r for r in shots if start <= (r["captured_at"] or r["requested_at"] or 0) <= end]
        if shots:
            row = QHBoxLayout()
            row.setSpacing(8)
            by_id = {e.event_id: e for e in events}
            all_shots = [make_shot(r, by_id.get(r["first_event_id"]) or self.ctx.repo.event(self.character_id,
                                                                                           r["first_event_id"] or ""))
                         for r in reversed(shots)]
            for i, shot in enumerate(all_shots[:4]):
                row.addWidget(Thumb(shot.path, lambda i=i, s=all_shots: open_viewer(self, self.ctx, s, i),
                                    photos=self.photos))
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

    def _fill_gallery(self, rows: list) -> None:
        body = self.bodies["gallery"]
        if not rows:
            body.addWidget(muted(tr("gallery.empty")))
            return
        favorites = self.ctx.repo.favorite_screenshots(self.character_id)
        picks = sorted(rows, key=lambda r: (r["screenshot_id"] in favorites,
                                            r["captured_at"] or r["requested_at"] or 0), reverse=True)[:3]
        collage = QHBoxLayout()
        collage.setSpacing(8)
        big = Thumb(picks[0]["file_path"], lambda: self.ctx.navigate.emit("tab.gallery"), QSize(260, 162),
                    self.photos)
        collage.addWidget(big)
        side = QVBoxLayout()
        side.setSpacing(8)
        for r in picks[1:]:
            side.addWidget(Thumb(r["file_path"], lambda: self.ctx.navigate.emit("tab.gallery"), QSize(122, 75),
                                 self.photos))
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

    def _fill_map(self, sessions, route: Route | None, char) -> None:
        body = self.bodies["map"]
        if not route:
            body.addWidget(muted(tr("map.no_points")))
            return
        session = sessions[0] if sessions else None
        colors, colors_key = journey_art.journey_colors(self.ctx, self.character_id, char, sessions)
        pixmap = journey_art.cached_picture(self.character_id, route, colors, colors_key, JOURNEY)
        if pixmap is not None:
            preview = QLabel()
            preview.setPixmap(pixmap)
            preview.setCursor(Qt.CursorShape.PointingHandCursor)
            preview.setToolTip(tr("cinema.play_all_tip"))
            preview.mouseReleaseEvent = lambda _e: self.ctx.navigate.emit("tab.cinema")
            body.addWidget(preview)
        start, end = session_range(session, route) if session else (route.start, route.end)
        view = route.view_for(route.point_at(end))
        if view is not None:
            text = QLabel(tr("home.map_last", zone=maps.zone_name(view, route.map_infos)))
            text.setObjectName("CardBig")
            body.addWidget(text)
        zones = {p.map_id for p in route.points if p.map_id is not None}
        body.addWidget(muted(tr("home.map_stats", zones=len(zones), since=format_datetime(route.start))))
        buttons = QHBoxLayout()
        everything = QPushButton(tr("cinema.play_all"))
        everything.setToolTip(tr("cinema.play_all_tip"))
        everything.clicked.connect(lambda: self.play(route.start, route.end))
        chapters = QPushButton(tr("cinema.all_chapters"))
        chapters.clicked.connect(lambda: self.ctx.navigate.emit("tab.cinema"))
        buttons.addWidget(everything)
        buttons.addWidget(chapters)
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
        from ..cinematic import open_cinematic
        if not self.character_id:
            return None
        return open_cinematic(self.ctx, self.character_id, start, end)

    def _export(self, start: int, end: int) -> None:
        from ..cinematic_export import ExportDialog
        ExportDialog(self, self.ctx, self.character_id, start, end, 4, self.ctx.map_colors).exec()
