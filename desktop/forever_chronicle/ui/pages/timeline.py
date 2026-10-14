"""Chronicle: all events of a character with type filter and search. Data gaps appear as rows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QTableWidgetItem, QVBoxLayout

from ...domain import event_types
from ...i18n import format_datetime, tr
from .. import theme
from ..widgets import Page, muted, table


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
        bar.addWidget(self.type_filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        root.addLayout(bar)

        self.table = table(3, 1)
        self.table.cellDoubleClicked.connect(self._open_screenshot)
        self.table.currentCellChanged.connect(self._row_selected)
        root.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.search.setPlaceholderText(tr("timeline.search"))
        self.table.setHorizontalHeaderLabels([tr("timeline.col.time"), tr("timeline.col.event"),
                                              tr("timeline.col.location")])
        current = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem(tr("timeline.filter_all"), None)
        if self.character_id:
            for key in self.ctx.repo.event_types_for(self.character_id):
                self.type_filter.addItem(tr(event_types.get(key).label_key), key)
        index = self.type_filter.findData(current)
        self.type_filter.setCurrentIndex(max(index, 0))
        self.type_filter.blockSignals(False)
        self._reload()

    def _reload(self) -> None:
        self.table.setRowCount(0)
        if not self.character_id:
            self.count.setText("")
            return
        selected = self.type_filter.currentData()
        events = self.ctx.repo.events(self.character_id, types=[selected] if selected else None,
                                      search=self.search.text().strip() or None)
        rows = [(e.occurred_at, "event", e) for e in events]
        if not selected and not self.search.text().strip():
            for gap in self.ctx.repo.gaps(self.character_id):
                if gap["stream"] == "events":
                    rows.append((gap["before_time"] or 0, "gap", gap))
        rows.sort(key=lambda r: r[0], reverse=True)
        shots = self.ctx.repo.screenshot_files_by_event(self.character_id)

        self.table.setRowCount(len(rows))
        for i, (ts, kind, obj) in enumerate(rows):
            if kind == "gap":
                n = obj["to_seq"] - obj["from_seq"] + 1
                cells = ["", tr("timeline.gap", n=n), ""]
                color = QColor(theme.RED)
            else:
                et = event_types.get(obj.event_type)
                text = f"{et.glyph}  {event_types.describe(obj)}"
                shot = shots.get(obj.event_id)
                if shot:
                    text += "   📷"
                cells = [format_datetime(ts), text, event_types.location_text(obj)]
                color = None
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QColor(theme.MUTED))
                    item.setData(Qt.ItemDataRole.UserRole, ts if kind == "event" else None)
                if color is not None:
                    item.setForeground(color)
                    font = QFont()
                    font.setItalic(True)
                    item.setFont(font)
                elif col == 1:
                    item.setData(Qt.ItemDataRole.UserRole, shot)
                    if shot:
                        item.setToolTip(tr("timeline.screenshot_tip"))
                self.table.setItem(i, col, item)
        self.count.setText(tr("timeline.count", n=len(events)))

    def _row_selected(self, row: int, *_args) -> None:
        """Selecting an event moves the map to that moment (spec F-010)."""
        item = self.table.item(row, 0) if row >= 0 else None
        ts = item.data(Qt.ItemDataRole.UserRole) if item else None
        if ts and self.character_id:
            self.ctx.focus_time.emit(self.character_id, int(ts))

    def _open_screenshot(self, row: int, _column: int) -> None:
        item = self.table.item(row, 1)
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
