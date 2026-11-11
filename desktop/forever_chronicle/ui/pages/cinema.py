"""Kino: the way into the cinematic mode. It replaced the map page on 2026-11-02 (user decision): the addon's own
map is the place to browse the route, the desktop app plays it back.

- The banner: the whole journey on the world map in the route colours (ui/journey_art.py), where it stands now
  glowing softly, and over it the character's title, what the journey adds up to, "▶ Die ganze Reise" and
  "⤓ Video".
- Kapitel: every session with route points is a chapter, newest first: its number, main zone, day and time, length,
  levels, quests and deaths, and its first screenshot. Selecting chapters lights their route up on the banner
  (the rest stays dim); a double-click or Enter plays them. Several chosen together (Ctrl/Shift) play as one,
  from the first one's start to the last one's end.
- The cinematic mode itself opens in full screen and starts with its own title over the world (ui/cinematic.py).
"""

from __future__ import annotations

import bisect
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ...domain import event_types
from ...domain.route import Route
from ...domain.route_colors import RouteColors
from ...i18n import format_day, format_duration, tr
from ...wow import map_art
from .. import icons, journey_art, motion, theme
from ..cards import DATA, ICON_SIZE, CardList
from ..screenshots import ThumbnailLoader, shots_on_disk
from ..widgets import Page, muted
from .home import session_range, zone_times

BANNER_H = 320
PULSE_MS = 40            # the marker's glow, while the page shows
PULSE_SECONDS = 2.6
HIGHLIGHT_MS = 420       # the lit-up route crossfades when the chosen chapters change
REBUILD_MS = 120         # after resizing, the picture is painted again at the new size


@dataclass
class Chapter:
    number: int
    start: int
    end: int
    zone: str | None
    start_level: int | None
    end_level: int | None
    quests: int
    deaths: int
    level_ups: int
    shot: str | None      # its first screenshot on this computer


def chapters(repo, character_id: str, route: Route, shot_rows: list | None = None) -> list[Chapter]:
    """The character's sessions with route points, oldest first, numbered from 1. shot_rows: shots_on_disk(),
    if already at hand."""
    events = repo.events(character_id, types=("quest_completed", "player_died", "level_up"), limit=1_000_000)
    events.sort(key=lambda e: e.occurred_at)
    times = [e.occurred_at for e in events]
    if shot_rows is None:
        shot_rows = shots_on_disk(repo, character_id)
    shots = sorted(((r["captured_at"] or r["requested_at"] or 0, r["file_path"]) for r in shot_rows))
    shot_times = [t for t, _ in shots]
    out: list[Chapter] = []
    for session in reversed(repo.sessions(character_id)):
        start, end = session_range(session, route)
        if next(route.points_in(start, end), None) is None:
            continue
        inside = events[bisect.bisect_left(times, start):bisect.bisect_right(times, end)]
        kinds = [e.event_type for e in inside]
        i = bisect.bisect_left(shot_times, start)
        zones = zone_times(route, start, end)
        out.append(Chapter(len(out) + 1, start, end, zones[0][0] if zones else None, session["start_level"],
                           session["end_level"], kinds.count("quest_completed"), kinds.count("player_died"),
                           kinds.count("level_up"), shots[i][1] if i < len(shots) and shots[i][0] <= end else None))
    return out


def chapter_detail(c: Chapter) -> str:
    clock = f"{time.strftime('%H:%M', time.localtime(c.start))}–{time.strftime('%H:%M', time.localtime(c.end))}"
    parts = [format_day(c.start), clock, format_duration(c.end - c.start)]
    if c.start_level and c.end_level and c.end_level != c.start_level:
        parts.append(tr("home.levels", start=c.start_level, end=c.end_level))
    elif c.end_level or c.start_level:
        parts.append(tr("cine.level", level=c.end_level or c.start_level))
    if c.quests:
        parts.append(tr("cinema.quest_one") if c.quests == 1 else tr("cinema.quests", n=c.quests))
    if c.deaths:
        parts.append(tr("cinema.death_one") if c.deaths == 1 else tr("cinema.deaths", n=c.deaths))
    return "  ·  ".join(parts)


def chapter_icon(c: Chapter):
    """The chapter's mark: a level-up, else a death, else the map."""
    key = "level_up" if c.level_ups else "player_died" if c.deaths else "zone_discovered"
    return icons.small(event_types.get(key).icon, ICON_SIZE)


def _font(families: list[str], size: int, spacing: float | None = None) -> QFont:
    font = QFont()
    font.setFamilies(families)
    font.setPointSize(size)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    return font


class JourneyBanner(QWidget):
    """The journey on the world map with the character's title over it (see the module notes).

    The pictures are painted when the banner is first painted after new data (not while it is hidden) and kept:
    set_journey() with the same key (same route and colours) keeps them, and the whole journey's bright route is
    kept for going back to it. The marker's pulse runs only while the banner shows in the active window (a
    full-screen cinematic over the main window stops it)."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setFixedHeight(BANNER_H)
        self.route: Route | None = None
        self.colors: RouteColors | None = None
        self.key: tuple | None = None                 # what the pictures were painted for (set_journey)
        self.texts = ("", "", "", theme.TEXT, "")     # heading, title, subtitle, subtitle colour, stats
        self.span: tuple[int, int] | None = None      # the chosen chapters; None: the whole journey
        self.frame: journey_art.Frame | None = None
        self.layer: QImage | None = None              # the map with the whole route dim
        self.lit: QImage | None = None                # the chosen part bright
        self.old_lit: QImage | None = None            # ... and the one it fades from
        self.whole: tuple[QImage, QPointF | None] | None = None   # the whole journey bright, and where it ends
        self.stale = False                            # new data: the pictures are painted before the next paint
        self.blend = 1.0
        self.marker: QPointF | None = None
        self.glow = 0.5
        self._lines: tuple[tuple, list] | None = None  # ((texts, width), [(font, colour, text, ascent, height)])

        self.play_all = QPushButton()
        self.play_all.setObjectName("HeroPlay")
        self.video = QPushButton()
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 0, 34, 28)
        root.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.play_all)
        row.addWidget(self.video)
        row.addStretch(1)
        root.addLayout(row)

        self.rebuild_timer = QTimer(self)
        self.rebuild_timer.setSingleShot(True)
        self.rebuild_timer.setInterval(REBUILD_MS)
        self.rebuild_timer.timeout.connect(self._rebuild)
        self.clock = QElapsedTimer()
        self.pulse = QTimer(self)
        self.pulse.setTimerType(Qt.TimerType.PreciseTimer)
        self.pulse.setInterval(PULSE_MS)
        self.pulse.timeout.connect(self._pulse)
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(HIGHLIGHT_MS)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.valueChanged.connect(self._blend)
        QApplication.instance().applicationStateChanged.connect(self._update_pulse)

    # -- data ------------------------------------------------------------------------------

    def set_journey(self, route: Route | None, colors: RouteColors | None, texts: tuple,
                    key: tuple | None = None) -> None:
        """key: what the route and colours stand for; the same key again (and the same route) keeps the pictures."""
        same = key is not None and key == self.key and route is self.route and self.layer is not None
        self.route, self.colors, self.texts, self.key = route, colors, texts, key
        self.span = None
        self.fade.stop()
        self.old_lit, self.blend = None, 1.0
        if same and not self.stale:
            self.lit = self._paint_lit()            # the whole journey's, kept
            self.update()
            return
        self.layer = self.lit = self.whole = None
        self.frame = self.marker = None
        self.stale = True
        self.update()

    def set_span(self, span: tuple[int, int] | None) -> None:
        if span == self.span:
            return
        self.span = span
        if self.stale:              # painted with the next paint anyway
            return
        self.old_lit = self.lit
        self.lit = self._paint_lit()
        if self.old_lit is not None and motion.enabled(self.config) and self.isVisible():
            self.blend = 0.0
            self.fade.stop()
            self.fade.start()
        else:
            self.blend = 1.0
            self.old_lit = None
        self.update()

    def _rebuild(self) -> None:
        self._build()
        self.update()

    def _build(self) -> None:
        self.stale = False
        self.layer = self.lit = self.old_lit = self.whole = None
        self.frame = self.marker = None
        size = self.size()
        if self.route and self.colors and size.width() > 0:
            area = journey_art.bounds(self.route)
            if area is not None:
                w, h = size.width(), size.height()
                self.frame = journey_art.frame(area, size, QRectF(w * 0.4, 22, w * 0.58, h - 44))
                self.layer = journey_art.background(self.frame, self.devicePixelRatioF())
                painter = QPainter(self.layer)
                journey_art.draw_route(painter, self.frame, self.route, self.colors, bright=False)
                painter.end()
                self.lit = self._paint_lit()
        self._update_pulse()

    def _paint_lit(self) -> QImage | None:
        if self.frame is None or self.route is None:
            return None
        if self.span is None and self.whole is not None:
            self.marker = self.whole[1]
            return self.whole[0]
        image = QImage(self.frame.size * self.devicePixelRatioF(), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.devicePixelRatioF())
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        start, end = self.span or (None, None)
        self.marker = journey_art.draw_route(painter, self.frame, self.route, self.colors, start, end)
        painter.end()
        if self.span is None:
            self.whole = (image, self.marker)
        return image

    # -- motion ----------------------------------------------------------------------------

    def _blend(self, value) -> None:
        self.blend = float(value)
        if self.blend >= 1.0:
            self.old_lit = None
        self.update()

    def _pulse(self) -> None:
        f = (self.clock.elapsed() / 1000.0) % PULSE_SECONDS / PULSE_SECONDS
        self.glow = 0.5 - 0.5 * math.cos(f * 2 * math.pi)
        if self.marker is not None:
            self.update(int(self.marker.x()) - 24, int(self.marker.y()) - 24, 48, 48)

    def _update_pulse(self, *_args) -> None:
        """The pulse runs while the banner shows a marker in the active window (not under a full-screen
        cinematic, not while the app is in the background)."""
        try:
            run = (motion.enabled(self.config) and self.isVisible() and self.isActiveWindow()
                   and self.marker is not None)
        except RuntimeError:  # the banner is gone (the application's signal outlives it)
            return
        if run and not self.pulse.isActive():
            if not self.clock.isValid():
                self.clock.start()
            self.pulse.start()
        elif not run and self.pulse.isActive():
            self.pulse.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_pulse()

    def hideEvent(self, event) -> None:
        self.pulse.stop()
        super().hideEvent(event)

    def event(self, event) -> bool:
        handled = super().event(event)
        # The window's (de)activation reaches its visible widgets as WindowActivate / WindowDeactivate.
        if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate,
                            QEvent.Type.ActivationChange):
            self._update_pulse()
        return handled

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.layer is None:
            return                          # painted at the right size when first painted
        if self.isVisible():
            self.rebuild_timer.start()      # meanwhile the old pictures stretch
        else:
            self.stale = True

    # -- painting --------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        if self.stale:
            self._build()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        w, h = rect.width(), rect.height()
        painter.fillRect(rect, QColor(theme.BG))
        if self.layer is not None:
            painter.drawImage(rect, self.layer)
        if self.old_lit is not None:
            painter.setOpacity(1.0 - self.blend)
            painter.drawImage(rect, self.old_lit)
        if self.lit is not None:
            painter.setOpacity(self.blend)
            painter.drawImage(rect, self.lit)
        painter.setOpacity(1.0)
        if self.marker is not None:
            journey_art.draw_marker(painter, self.marker, self.glow)

        # The title's side darkens, the edges fade into the page, a vignette frames it.
        left = QLinearGradient(0, 0, w * 0.62, 0)
        left.setColorAt(0, QColor(9, 7, 5, 235))
        left.setColorAt(0.55, QColor(9, 7, 5, 150))
        left.setColorAt(1, QColor(9, 7, 5, 0))
        painter.fillRect(rect, left)
        bottom = QLinearGradient(0, h * 0.55, 0, h)
        bottom.setColorAt(0, QColor(9, 7, 5, 0))
        bottom.setColorAt(1, QColor(9, 7, 5, 200))
        painter.fillRect(rect, bottom)
        vignette = QRadialGradient(rect.center(), max(w, h) * 0.75)
        vignette.setColorAt(0.55, QColor(0, 0, 0, 0))
        vignette.setColorAt(1, QColor(0, 0, 0, 150))
        painter.fillRect(rect, vignette)
        for y, alpha in ((0.5, 255), (h - 0.5, 255)):          # bronze lines above and below, as a frame
            painter.setPen(QColor(201, 162, 74, alpha // 2))
            painter.drawLine(QPointF(0, y), QPointF(w, y))

        x, y = 36, 40
        for line, gap in zip(self._text_lines(max(100, int(w * 0.5))), (6, 2, 8, 0)):
            y = self._text(painter, line, x, y) + gap
        painter.end()

    def _text_lines(self, width: int) -> list[tuple[QFont, QColor, str, int, int]]:
        """The title's four lines as (font, colour, elided text, ascent, height); made again only when the texts or
        the width change (the pulse repaints many times a second)."""
        key = (self.texts, width)
        if self._lines is None or self._lines[0] != key:
            heading, title, subtitle, subtitle_color, stats = self.texts
            lines = []
            for text, font, color in ((heading, _font(theme.HEADING_FONTS, 10, 118), "#c9a24a"),
                                      (title, _font(theme.TITLE_FONTS, 30), theme.GOLD),
                                      (subtitle, _font(theme.HEADING_FONTS, 13), subtitle_color),
                                      (stats, _font(["Segoe UI", "Arial"], 10), theme.TEXT)):
                metrics = QFontMetrics(font)
                lines.append((font, QColor(color), metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)
                              if text else "", metrics.ascent(), metrics.height()))
            self._lines = (key, lines)
        return self._lines[1]

    @staticmethod
    def _text(painter: QPainter, line: tuple[QFont, QColor, str, int, int], x: int, y: int) -> int:
        """A line with a soft shadow; returns the y under it."""
        font, color, text, ascent, height = line
        if not text:
            return y
        painter.setFont(font)
        base = y + ascent
        painter.setPen(QColor(0, 0, 0, 200))
        for dx, dy in ((2, 2), (1, 1), (0, 2)):
            painter.drawText(x + dx, base + dy, text)
        painter.setPen(color)
        painter.drawText(x, base, text)
        return y + height


class CinemaPage(Page):
    title_key = "tab.cinema"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.route: Route | None = None
        self.chapters: list[Chapter] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.banner = JourneyBanner(ctx.config)
        self.banner.play_all.clicked.connect(self.play_all)
        self.banner.video.clicked.connect(lambda: self._export(self._whole()))
        root.addWidget(self.banner)

        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.heading = QLabel()
        self.heading.setObjectName("CardTitle")
        self.hint = muted()
        self.hint.setWordWrap(False)
        self.play_chosen = QPushButton()
        self.play_chosen.clicked.connect(self.play_selected)
        self.video_chosen = QPushButton()
        self.video_chosen.clicked.connect(lambda: self._export(self.selected_span()))
        bar.addWidget(self.heading)
        bar.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignBottom)
        bar.addStretch(1)
        bar.addWidget(self.play_chosen)
        bar.addWidget(self.video_chosen)
        body.addLayout(bar)
        self.empty = muted()
        body.addWidget(self.empty)
        self.list = CardList(thumbs=True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemActivated.connect(lambda _item: self.play_selected())
        body.addWidget(self.list, 1)
        root.addLayout(body, 1)
        self.thumbnails = ThumbnailLoader(self)

    # -- data ------------------------------------------------------------------------------

    def refresh(self) -> None:
        self.heading.setText(tr("cinema.chapters"))
        self.hint.setText(tr("cinema.chapters_hint"))
        self.banner.play_all.setText(tr("cinema.play_all"))
        self.banner.play_all.setToolTip(tr("cinema.play_all_tip"))
        self.banner.video.setText(tr("cine.export"))
        self.banner.video.setToolTip(tr("cine.export_tip"))
        self.video_chosen.setText(tr("cine.export"))
        self.video_chosen.setToolTip(tr("cine.export_tip"))
        self.thumbnails.clear()
        self.list.clear()
        repo = self.ctx.repo
        char = repo.character(self.character_id) if self.character_id else None
        self.route = Route.cached(repo, self.character_id) if self.character_id else None
        if not self.route:
            self.chapters = []
            self.banner.set_journey(None, None, (tr("cinema.heading"), char.name if char else tr("cinema.no_journey"),
                                                 "", theme.TEXT, tr("map.no_points") if char else ""))
            self._show_list()
            return
        sessions = repo.sessions(self.character_id)
        colors, colors_key = journey_art.journey_colors(self.ctx, self.character_id, char, sessions)
        shots = shots_on_disk(repo, self.character_id)
        self.chapters = chapters(repo, self.character_id, self.route, shots)
        self.banner.set_journey(self.route, colors, self._texts(char, sessions, len(shots)),
                                (self.character_id, colors_key, map_art.world_base()))
        for c in reversed(self.chapters):
            title = tr("cinema.chapter", n=c.number) + (f"  ·  {c.zone}" if c.zone else "")
            item = self.list.add_entry(title, chapter_detail(c), chapter_icon(c), thumb=c.shot is not None,
                                       data=(c.start, c.end), accent="milestone" if c.level_ups else None)
            if c.shot:
                self.thumbnails.request(c.shot, lambda icon, it=item: CardList.set_thumb(it, icon))
        self._show_list()

    def _texts(self, char, sessions, shots: int) -> tuple:
        details = tr("char.details", level=char.level or "?", race=char.race_name or "",
                     cls=char.class_name or "").strip() if char else ""
        played = next((s["played_total_seconds"] for s in sessions if s["played_total_seconds"] is not None), None)
        zones = {p.map_id for p in self.route.points if p.map_id is not None}
        parts = [tr("cinema.n_chapters", n=len(self.chapters))]
        if played:
            parts.append(tr("cinema.played", time=format_duration(played)))
        parts.append(tr("cinema.n_zone_one") if len(zones) == 1 else tr("cinema.n_zones", n=len(zones)))
        if shots:
            parts.append(tr("gallery.picture_one") if shots == 1 else tr("gallery.pictures", n=shots))
        return (tr("cinema.heading"), tr("cinema.title", name=char.name if char else "?"), details,
                theme.class_color(char.class_file if char else None), "  ·  ".join(parts))

    def _show_list(self) -> None:
        has = bool(self.chapters)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText(tr("cinema.no_chapters"))
        self.banner.play_all.setEnabled(bool(self.route))
        self.banner.video.setEnabled(bool(self.route))
        self._selection_changed()

    # -- choosing and playing ----------------------------------------------------------------

    def selected_span(self) -> tuple[int, int] | None:
        spans = [item.data(DATA) for item in self.list.selectedItems() if item.data(DATA)]
        if not spans:
            return None
        return min(s for s, _ in spans), max(e for _, e in spans)

    def _whole(self) -> tuple[int, int] | None:
        if not self.route:
            return None
        return self.route.start, max(self.route.end, self.route.start + 1)

    def _selection_changed(self) -> None:
        n = len(self.list.selectedItems())
        self.play_chosen.setText(tr("cinema.play_chapters", n=n) if n > 1 else tr("cinema.play_chapter"))
        self.play_chosen.setEnabled(n > 0)
        self.video_chosen.setEnabled(n > 0)
        self.banner.set_span(self.selected_span())

    def play_all(self):
        return self.play(self._whole())

    def play_selected(self):
        return self.play(self.selected_span())

    def play(self, span: tuple[int, int] | None):
        from ..cinematic import open_cinematic
        if span is None or not self.character_id:
            return None
        return open_cinematic(self.ctx, self.character_id, span[0], span[1])

    def _export(self, span: tuple[int, int] | None) -> None:
        from ..cinematic_export import ExportDialog
        if span is None or not self.character_id:
            return
        ExportDialog(self, self.ctx, self.character_id, span[0], span[1], 4, self.ctx.map_colors).exec()
