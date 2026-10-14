"""Screenshots: thumbnails of the character's screenshots with the event they belong to (spec F-010).

Thumbnails load in small batches on a timer so large folders do not freeze the window.
Missing files show a placeholder. Double-click opens the image in the system viewer.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from ...domain import event_types
from ...i18n import format_datetime, tr
from .. import theme
from ..widgets import Page, muted

THUMB = QSize(256, 160)
BATCH = 6


def placeholder(text: str) -> QIcon:
    pix = QPixmap(THUMB)
    pix.fill(QColor(theme.PANEL_ALT))
    painter = QPainter(pix)
    painter.setPen(QColor(theme.BORDER))
    painter.drawRect(0, 0, THUMB.width() - 1, THUMB.height() - 1)
    painter.setPen(QColor(theme.MUTED))
    font = QFont()
    font.setPointSize(10)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pix)


def load_thumbnail(path: str) -> QIcon | None:
    reader = QImageReader(path)
    size = reader.size()
    if not size.isValid():
        return None
    reader.setScaledSize(size.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    return QIcon(QPixmap.fromImage(image)) if not image.isNull() else None


class GalleryPage(Page):
    title_key = "tab.gallery"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        self.count = muted()
        self.open_folder = QPushButton()
        self.open_folder.clicked.connect(self._open_folder)
        bar.addWidget(self.count, 1)
        bar.addWidget(self.open_folder)
        root.addLayout(bar)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 24, THUMB.height() + 58))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(6)
        self.grid.itemDoubleClicked.connect(self._open_item)
        root.addWidget(self.grid, 1)

        self._cache: dict[str, QIcon] = {}
        self._pending: list[QListWidgetItem] = []
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._load_batch)

    def refresh(self) -> None:
        self.open_folder.setText(tr("gallery.open_folder"))
        client = self.ctx.client()
        self.open_folder.setEnabled(bool(client and client.screenshots_dir.is_dir()))
        self._timer.stop()
        self._pending = []
        self.grid.clear()
        if not self.character_id:
            self.count.setText("")
            return
        loading, missing = placeholder(tr("gallery.loading")), placeholder(tr("gallery.missing"))
        rows = self.ctx.repo.screenshots(self.character_id, only_files=True)
        for row in rows:
            caption = tr(f"trigger.{row['trigger_type']}")
            if row["first_event_id"]:
                event = self.ctx.repo.event(self.character_id, row["first_event_id"])
                if event:
                    caption = event_types.describe(event)
            if row["event_count"] > 1:
                caption += tr("gallery.more", n=row["event_count"] - 1)
            item = QListWidgetItem(f"{caption}\n{format_datetime(row['captured_at'])}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            path = row["file_path"]
            item.setData(Qt.ItemDataRole.UserRole, path)
            if path and Path(path).is_file():
                item.setIcon(self._cache.get(path, loading))
                item.setToolTip(path)
                if path not in self._cache:
                    self._pending.append(item)
            else:
                item.setIcon(missing)
                item.setToolTip(tr("gallery.missing_tip", stamp=row["file_stamp"] or "?"))
            self.grid.addItem(item)
        self.count.setText(tr("gallery.count", n=len(rows)) if rows else tr("gallery.empty"))
        if self._pending:
            self._timer.start()

    def _load_batch(self) -> None:
        for _ in range(BATCH):
            if not self._pending:
                self._timer.stop()
                return
            item = self._pending.pop(0)
            path = item.data(Qt.ItemDataRole.UserRole)
            icon = self._cache.get(path) or load_thumbnail(path)
            if icon:
                self._cache[path] = icon
                item.setIcon(icon)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_folder(self) -> None:
        client = self.ctx.client()
        if client:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(client.screenshots_dir)))
