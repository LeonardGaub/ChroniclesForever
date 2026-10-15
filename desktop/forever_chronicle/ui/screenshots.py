"""Screenshots in the chronicle: thumbnails (loaded in small batches so large folders do not freeze the window)
and a viewer that shows the full picture, with buttons to step through the other screenshots of the list."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImageReader, QKeySequence, QPainter, QPixmap, \
    QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ..i18n import tr
from . import theme
from .widgets import muted

THUMB = QSize(112, 70)
BATCH = 6


def placeholder(text: str, size: QSize = THUMB) -> QIcon:
    pix = QPixmap(size)
    pix.fill(QColor(theme.PANEL_ALT))
    painter = QPainter(pix)
    painter.setPen(QColor(theme.BORDER))
    painter.drawRect(0, 0, size.width() - 1, size.height() - 1)
    painter.setPen(QColor(theme.MUTED))
    font = QFont()
    font.setPointSize(8)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    painter.end()
    return QIcon(pix)


def load_thumbnail(path: str, size: QSize = THUMB) -> QIcon | None:
    reader = QImageReader(path)
    full = reader.size()
    if not full.isValid():
        return None
    reader.setScaledSize(full.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    return QIcon(QPixmap.fromImage(image)) if not image.isNull() else None


def file_exists(path: str | None) -> bool:
    return bool(path) and Path(path).is_file()


class ThumbnailLoader:
    """Loads thumbnails on a timer and hands each one to its callback. Thumbnails are cached by path."""

    def __init__(self, parent):
        self.cache: dict[str, QIcon] = {}
        self._pending: list[tuple[str, Callable[[QIcon], None]]] = []
        self._timer = QTimer(parent)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self.load_batch)

    def clear(self) -> None:
        self._timer.stop()
        self._pending = []

    def request(self, path: str, apply: Callable[[QIcon], None]) -> None:
        """Calls apply now if the thumbnail is cached, else later once it is loaded."""
        if path in self.cache:
            apply(self.cache[path])
            return
        self._pending.append((path, apply))
        if not self._timer.isActive():
            self._timer.start()

    def load_batch(self) -> None:
        for _ in range(BATCH):
            if not self._pending:
                self._timer.stop()
                return
            path, apply = self._pending.pop(0)
            icon = self.cache.get(path) or load_thumbnail(path)
            if icon:
                self.cache[path] = icon
                apply(icon)


@dataclass
class Shot:
    path: str
    caption: str


class ScreenshotViewer(QDialog):
    """The full picture, scaled to the window, with its entry as caption. Arrow keys step through the list."""

    def __init__(self, shots: list[Shot], index: int, parent=None):
        super().__init__(parent)
        self.shots, self.index = shots, index
        self.resize(1100, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(320, 200)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image.setStyleSheet(f"background: {theme.BG};")
        root.addWidget(self.image, 1)

        self.caption = QLabel()
        self.caption.setFont(theme.heading_font(12))
        self.caption.setStyleSheet(f"color: {theme.GOLD};")
        self.caption.setWordWrap(True)
        root.addWidget(self.caption)

        bar = QHBoxLayout()
        self.prev_button = QPushButton(tr("screenshot.prev"))
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.next_button = QPushButton(tr("screenshot.next"))
        self.next_button.clicked.connect(lambda: self.step(1))
        self.position = muted()
        self.position.setWordWrap(False)
        self.position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.external = QPushButton(tr("screenshot.open_external"))
        self.external.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.current.path)))
        close = QPushButton(tr("screenshot.close"))
        close.clicked.connect(self.accept)
        bar.addWidget(self.prev_button)
        bar.addWidget(self.next_button)
        bar.addWidget(self.position, 1)
        bar.addWidget(self.external)
        bar.addWidget(close)
        root.addLayout(bar)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step(1))
        self._pixmap = QPixmap()
        self.show_current()

    @property
    def current(self) -> Shot:
        return self.shots[self.index]

    def step(self, delta: int) -> None:
        index = self.index + delta
        if 0 <= index < len(self.shots):
            self.index = index
            self.show_current()

    def show_current(self) -> None:
        shot = self.current
        self.setWindowTitle(Path(shot.path).name)
        self._pixmap = QPixmap(shot.path)
        self.caption.setText(shot.caption)
        self.position.setText(tr("screenshot.position", i=self.index + 1, n=len(self.shots)))
        self.prev_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.shots) - 1)
        self._scale()

    def _scale(self) -> None:
        if self._pixmap.isNull():
            self.image.setPixmap(QPixmap())
            self.image.setText(tr("screenshot.missing"))
            return
        self.image.setPixmap(self._pixmap.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale()
