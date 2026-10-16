"""Chronicle: all events of a character with type filter and search, as a card list like the addon's Chronik:
a gold heading per day, then per entry the game icon, the event in gold, time and place in grey, and on the right
the screenshot taken for it. Milestones carry a gold bar, deaths a red one. Data gaps appear as red entries.

Clicking a thumbnail (or double-clicking the entry) opens the picture in the viewer (ui/screenshots.py).
Screenshots without an entry (test screenshots) are entries of their own. The filter "With screenshot" shows only
entries with a screenshot. Selecting an entry moves the map to that moment.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from ...domain import event_types
from ...i18n import format_day, tr
from .. import icons, theme
from ..cards import DATA, ICON_SIZE, CardList, placeholder_pixmap
from ..screenshots import ScreenshotViewer, Shot, ThumbnailLoader, file_exists, make_shot
from ..widgets import Page, muted

SHOTS = "__screenshots__"  # type filter entry: only entries with a screenshot


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
        self.open_folder = QPushButton()
        self.open_folder.clicked.connect(self._open_folder)
        bar.addWidget(self.type_filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        bar.addWidget(self.open_folder)
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
        self.open_folder.setText(tr("screenshot.open_folder"))
        client = self.ctx.client()
        self.open_folder.setEnabled(bool(client and client.screenshots_dir.is_dir()))
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
        """Selecting an event moves the map to that moment (spec F-010)."""
        item = self.list.item(row) if row >= 0 else None
        data = item.data(DATA) if item else None
        if data and data[0] and self.character_id:
            self.ctx.focus_time.emit(self.character_id, int(data[0]))

    def open_screenshot(self, row: int) -> ScreenshotViewer | None:
        item = self.list.item(row)
        data = item.data(DATA) if item else None
        index = data[1] if data else None
        if index is None:
            return None
        viewer = ScreenshotViewer(self.shots, index, self, self.ctx)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.show()
        return viewer

    def _open_folder(self) -> None:
        client = self.ctx.client()
        if client:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(client.screenshots_dir)))

