"""Chronicle: all events of a character with type filter and search, as a card list like the addon's Chronik:
a gold heading per day, then per entry the game icon, the event in gold, time and place in grey, and on the right
the screenshot taken for it. Milestones carry a gold bar, deaths a red one. Data gaps appear as red entries.

Clicking a thumbnail (or double-clicking the entry) opens the picture in the viewer (ui/screenshots.py).
Screenshots without an entry (test screenshots) are entries of their own. The filter "With screenshot" shows only
entries with a screenshot. "▶ Ab hier" (or Enter) plays the chosen moment in the cinematic mode, from shortly
before it to the end of its session.
"""

from __future__ import annotations

import time

from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from ...domain import event_types
from ...domain.route import Route
from ...i18n import format_day, tr
from .. import icons, theme
from ..cards import DATA, ICON_SIZE, CardList, placeholder_pixmap
from ..screenshots import (ScreenshotFolderButton, ScreenshotViewer, Shot, ThumbnailLoader, file_exists, make_shot,
                           open_viewer)
from ..widgets import Page, muted
from .home import session_range

SHOTS = "__screenshots__"  # type filter entry: only entries with a screenshot
LEAD = 30                  # seconds the replay starts before the chosen moment


class TimelinePage(Page):
    title_key = "tab.timeline"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        bar = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.setMinimumWidth(200)
        self.type_filter.currentIndexChanged.connect(self._reload)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._reload)
        self.count = muted()
        self.count.setWordWrap(False)
        self.open_folder = ScreenshotFolderButton(ctx)
        bar.addWidget(self.type_filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        bar.addWidget(self.open_folder)
        self.play_here = QPushButton()
        self.play_here.clicked.connect(self.play_selected)
        self.play_here.setEnabled(False)
        bar.addWidget(self.play_here)
        root.addLayout(bar)

        self.list = CardList(thumbs=True)
        self.list.thumb_clicked.connect(self.open_screenshot)
        self.list.itemDoubleClicked.connect(lambda item: self.open_screenshot(self.list.row(item)))
        self.list.currentRowChanged.connect(self._row_selected)
        root.addWidget(self.list, 1)

        self.thumbnails = ThumbnailLoader(self)
        self.shots: list[Shot] = []  # screenshots with a file, in list order (the viewer steps through them)

    def refresh(self) -> None:
        self.search.setPlaceholderText(tr("timeline.search"))
        self.play_here.setText(tr("timeline.play_here"))
        self.play_here.setToolTip(tr("timeline.play_here_tip"))
        self.open_folder.refresh()
        current = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem(tr("timeline.filter_all"), None)
        self.type_filter.addItem(tr("timeline.filter_shots"), SHOTS)
        shot_icon = icons.small(event_types.SCREENSHOT_ICON)
        if shot_icon is not None:
            self.type_filter.setItemIcon(1, QIcon(shot_icon))
        if self.character_id:
            for key in self.ctx.repo.event_types_for(self.character_id):
                index = self.type_filter.count()
                self.type_filter.addItem(tr(event_types.get(key).label_key), key)
                icon = icons.small(event_types.get(key).icon)
                if icon is not None:
                    self.type_filter.setItemIcon(index, QIcon(icon))
        index = self.type_filter.findData(current)
        self.type_filter.setCurrentIndex(max(index, 0))
        self.type_filter.blockSignals(False)
        self._reload()

    def _rows(self) -> list[tuple[int, str, object, object]]:
        """(time, kind, object, screenshot row or None), newest first. kind: event, shot (no entry) or gap."""
        cid = self.character_id
        selected = self.type_filter.currentData()
        search = self.search.text().strip()
        shots = self.ctx.repo.screenshots_by_event(cid)
        types = [selected] if selected and selected != SHOTS else None
        events = self.ctx.repo.events(cid, types=types, search=search or None)
        if selected == SHOTS:
            events = [e for e in events if e.event_id in shots]
        rows = [(e.occurred_at, "event", e, shots.get(e.event_id)) for e in events]
        if selected in (None, SHOTS):
            for shot in self.ctx.repo.screenshots(cid, only_files=True):
                caption = tr(f"trigger.{shot['trigger_type']}")
                if shot["first_event_id"] is None and (not search or search.lower() in caption.lower()):
                    rows.append((shot["captured_at"] or shot["requested_at"] or 0, "shot", caption, shot))
        if selected is None and not search:
            for gap in self.ctx.repo.gaps(cid):
                if gap["stream"] == "events":
                    rows.append((gap["before_time"] or 0, "gap", gap, None))
        rows.sort(key=lambda r: r[0], reverse=True)
        return rows

    def _reload(self) -> None:
        self.thumbnails.clear()
        self.shots = []
        self.list.clear()
        if not self.character_id:
            self.count.setText("")
            return
        rows = self._rows()
        day = None
        for ts, kind, obj, shot in rows:
            if kind != "gap" and ts and time.localtime(ts)[:3] != day:
                day = time.localtime(ts)[:3]
                self.list.add_header(format_day(ts))
            clock = time.strftime("%H:%M", time.localtime(ts)) if ts else ""
            if kind == "gap":
                n = obj["to_seq"] - obj["from_seq"] + 1
                self.list.add_entry(tr("timeline.gap", n=n), tr("timeline.gap_detail"), accent="danger",
                                    title_color=theme.RED, data=(None, None))
                continue
            if kind == "shot":
                title, detail = str(obj), clock
                icon = icons.small(event_types.SCREENSHOT_ICON, ICON_SIZE)
                accent = None
            else:
                et = event_types.get(obj.event_type)
                title = event_types.describe(obj)
                detail = "  ·  ".join(p for p in (clock, event_types.location_text(obj), event_types.detail(obj)) if p)
                icon = icons.small(event_types.icon_of(obj), ICON_SIZE)
                accent = et.highlight or None
            item = self.list.add_entry(title, detail, icon, accent=accent, thumb=shot is not None,
                                       data=(ts, None))
            if shot is not None:
                self._add_thumbnail(item, shot, obj if kind == "event" else None)
        n_entries = sum(1 for r in rows if r[1] != "gap")
        n_shots = sum(1 for r in rows if r[3] is not None)
        self.count.setText(tr("timeline.count_shots", n=n_entries, shots=n_shots) if n_shots
                           else tr("timeline.count", n=n_entries))

    def _add_thumbnail(self, item, shot, event) -> None:
        path = shot["file_path"]
        ts = item.data(DATA)[0]
        if file_exists(path):
            item.setData(DATA, (ts, len(self.shots)))
            self.shots.append(make_shot(shot, event))
            CardList.set_thumb(item, placeholder_pixmap(tr("screenshot.loading")))
            item.setToolTip(tr("timeline.screenshot_tip"))
            self.thumbnails.request(path, lambda icon, it=item: CardList.set_thumb(it, icon))
        else:
            CardList.set_thumb(item, placeholder_pixmap(tr("screenshot.missing")))
            item.setToolTip(tr("screenshot.missing_tip", stamp=shot["file_stamp"] or "?"))

    def _row_selected(self, row: int) -> None:
        self.play_here.setEnabled(self._selected_time() is not None)

    def _selected_time(self) -> int | None:
        item = self.list.currentItem()
        data = item.data(DATA) if item else None
        return int(data[0]) if data and data[0] else None

    def play_selected(self):
        """The chosen moment in the cinematic mode, from LEAD seconds before it to the end of its session."""
        from ..cinematic import open_cinematic
        t = self._selected_time()
        if t is None or not self.character_id:
            return None
        route = Route.cached(self.ctx.repo, self.character_id)
        start, end = t - LEAD, t + 3600
        session = next((s for s in self.ctx.repo.sessions(self.character_id) if s["started_at"] <= t), None)
        if session is not None:
            first, last = session_range(session, route)
            start, end = max(first, t - LEAD), max(last, t + 60)
        return open_cinematic(self.ctx, self.character_id, start, end)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.play_here.isEnabled():
            self.play_selected()
            return
        super().keyPressEvent(event)

    def open_screenshot(self, row: int) -> ScreenshotViewer | None:
        item = self.list.item(row)
        data = item.data(DATA) if item else None
        index = data[1] if data else None
        if index is None:
            return None
        return open_viewer(self, self.ctx, self.shots, index, full_screen=False)

