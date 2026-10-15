"""Chronicle: all events of a character with type filter and search. Data gaps appear as rows.

Screenshots are shown with the entry that triggered them: a thumbnail in the last column that opens the full
picture (click on it, or double-click the row). Screenshots without an entry (test screenshots) are entries of
their own. The filter "With screenshot" shows only entries with a screenshot.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QTableWidgetItem, \
    QVBoxLayout

from ...domain import event_types
from ...i18n import format_datetime, tr
from .. import theme
from ..screenshots import THUMB, ScreenshotViewer, Shot, ThumbnailLoader, file_exists, placeholder
from ..widgets import Page, muted, table

SHOTS = "__screenshots__"  # type filter entry: only entries with a screenshot
SHOT_COLUMN = 3
SHOT_GLYPH = "\U0001F4F7"


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
        self.open_folder = QPushButton()
        self.open_folder.clicked.connect(self._open_folder)
        bar.addWidget(self.type_filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        bar.addWidget(self.open_folder)
        root.addLayout(bar)

        self.table = table(4, 1)
        self.table.setIconSize(THUMB)
        self.table.horizontalHeader().setSectionResizeMode(SHOT_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.table.cellClicked.connect(self._cell_clicked)
        self.table.cellDoubleClicked.connect(lambda row, _col: self.open_screenshot(row))
        self.table.currentCellChanged.connect(self._row_selected)
        root.addWidget(self.table, 1)

        self.thumbnails = ThumbnailLoader(self)
        self.shots: list[Shot] = []  # screenshots with a file, in list order (the viewer steps through them)

    def refresh(self) -> None:
        self.search.setPlaceholderText(tr("timeline.search"))
        self.open_folder.setText(tr("screenshot.open_folder"))
        client = self.ctx.client()
        self.open_folder.setEnabled(bool(client and client.screenshots_dir.is_dir()))
        self.table.setHorizontalHeaderLabels([tr("timeline.col.time"), tr("timeline.col.event"),
                                              tr("timeline.col.location"), tr("timeline.col.screenshot")])
        self.table.setColumnWidth(SHOT_COLUMN, max(THUMB.width() + 16,
                                                   self.table.horizontalHeader().sectionSizeHint(SHOT_COLUMN)))
        current = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem(tr("timeline.filter_all"), None)
        self.type_filter.addItem(f"{SHOT_GLYPH}  {tr('timeline.filter_shots')}", SHOTS)
        if self.character_id:
            for key in self.ctx.repo.event_types_for(self.character_id):
                self.type_filter.addItem(tr(event_types.get(key).label_key), key)
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
        self.table.setRowCount(0)
        if not self.character_id:
            self.count.setText("")
            return
        rows = self._rows()
        loading, missing = placeholder(tr("screenshot.loading")), placeholder(tr("screenshot.missing"))

        self.table.setRowCount(len(rows))
        for i, (ts, kind, obj, shot) in enumerate(rows):
            if kind == "gap":
                n = obj["to_seq"] - obj["from_seq"] + 1
                cells = ["", tr("timeline.gap", n=n), ""]
                color = QColor(theme.RED)
            elif kind == "shot":
                cells = [format_datetime(ts), f"{SHOT_GLYPH}  {obj}", ""]
                color = None
            else:
                et = event_types.get(obj.event_type)
                cells = [format_datetime(ts), f"{et.glyph}  {event_types.describe(obj)}",
                         event_types.location_text(obj)]
                color = None
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QColor(theme.MUTED))
                    item.setData(Qt.ItemDataRole.UserRole, ts if kind != "gap" else None)
                if color is not None:
                    item.setForeground(color)
                    font = QFont()
                    font.setItalic(True)
                    item.setFont(font)
                self.table.setItem(i, col, item)
            if shot is not None:
                self._add_thumbnail(i, ts, cells, shot, loading, missing)
        n_entries = sum(1 for r in rows if r[1] != "gap")
        n_shots = sum(1 for r in rows if r[3] is not None)
        self.count.setText(tr("timeline.count_shots", n=n_entries, shots=n_shots) if n_shots
                           else tr("timeline.count", n=n_entries))

    def _add_thumbnail(self, row: int, ts: int, cells: list[str], shot, loading, missing) -> None:
        item = QTableWidgetItem()
        path = shot["file_path"]
        if file_exists(path):
            caption = "  ·  ".join(c for c in (cells[1], format_datetime(ts), cells[2]) if c)
            item.setData(Qt.ItemDataRole.UserRole, len(self.shots))
            self.shots.append(Shot(path, caption))
            item.setIcon(loading)
            item.setToolTip(tr("timeline.screenshot_tip"))
            self.thumbnails.request(path, item.setIcon)
        else:
            item.setIcon(missing)
            item.setToolTip(tr("screenshot.missing_tip", stamp=shot["file_stamp"] or "?"))
        self.table.setItem(row, SHOT_COLUMN, item)
        self.table.setRowHeight(row, THUMB.height() + 8)

    def _row_selected(self, row: int, *_args) -> None:
        """Selecting an event moves the map to that moment (spec F-010)."""
        item = self.table.item(row, 0) if row >= 0 else None
        ts = item.data(Qt.ItemDataRole.UserRole) if item else None
        if ts and self.character_id:
            self.ctx.focus_time.emit(self.character_id, int(ts))

    def _cell_clicked(self, row: int, column: int) -> None:
        if column == SHOT_COLUMN:
            self.open_screenshot(row)

    def open_screenshot(self, row: int) -> ScreenshotViewer | None:
        item = self.table.item(row, SHOT_COLUMN)
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        if index is None:
            return None
        viewer = ScreenshotViewer(self.shots, index, self)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.show()
        return viewer

    def _open_folder(self) -> None:
        client = self.ctx.client()
        if client:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(client.screenshots_dir)))
