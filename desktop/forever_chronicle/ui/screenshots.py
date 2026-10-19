"""Screenshots: thumbnails (loaded in small batches so large folders do not freeze the window), the Shot model and
a viewer for the full picture.

The viewer shows the picture on black, under an achievement banner as in the cinematic mode (heading, name,
place; the event's game icon or the level reached). It steps through the other screenshots of its list (arrow
keys), stars favourites (F; kept in the database, the gallery shows them) and plays the replay from that moment in
the cinematic mode ("Wiedergabe ab hier", Enter). Esc closes it, F11 switches between window and full screen.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImageReader, QKeySequence, QPainter, QPixmap, \
    QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..domain import event_types
from ..domain.cinematic import Cue, banner
from ..i18n import format_datetime, tr
from . import theme
from .cards import THUMB_SIZE

BATCH = 6
REPLAY_BEFORE = 120        # the replay from a screenshot starts this many seconds of play before it


def load_thumbnail(path: str | None, size: QSize = THUMB_SIZE, fill: bool = False) -> QPixmap | None:
    """The picture scaled to fit inside size, or with fill to cover it (for cropping)."""
    if not path:
        return None
    reader = QImageReader(path)
    full = reader.size()
    if not full.isValid():
        return None
    mode = Qt.AspectRatioMode.KeepAspectRatioByExpanding if fill else Qt.AspectRatioMode.KeepAspectRatio
    reader.setScaledSize(full.scaled(size, mode))
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else None


def file_exists(path: str | None) -> bool:
    return bool(path) and Path(path).is_file()


class ThumbnailLoader:
    """Loads thumbnails on a timer and hands each one to its callback. Thumbnails are cached by path."""

    def __init__(self, parent, size: QSize = THUMB_SIZE):
        self.size = size
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
            icon = self.cache.get(path)
            if icon is None:
                pix = load_thumbnail(path, self.size)
                icon = QIcon(pix) if pix is not None else None
            if icon:
                self.cache[path] = icon
                apply(icon)


@dataclass
class Shot:
    path: str
    caption: str                        # one line: what, when, where
    cue: Cue | None = None              # the banner (as in the cinematic mode)
    character_id: str | None = None
    screenshot_id: str | None = None
    extra: dict = field(default_factory=dict)   # what a list knows about it (gallery: zone, level ...)

    @property
    def time(self) -> int | None:
        return self.cue.time if self.cue else None


def make_shot(row, event=None, level: int | None = None) -> Shot:
    """A screenshot row (Repository.screenshots) with the event it was taken for (None: a test screenshot)."""
    t = row["captured_at"] or row["requested_at"] or 0
    heading, title, place = banner(event, row["trigger_type"])
    et = event_types.get(event.event_type) if event else None
    if event is not None and event.event_type == "level_up" and isinstance(event.payload.get("level"), int):
        level = event.payload["level"]
    cue = Cue(t, "screenshot", event_types.describe(event) if event else tr(f"trigger.{row['trigger_type']}"),
              et.glyph if et else "", et.color if et else theme.GOLD,
              event_types.icon_of(event) if event else event_types.SCREENSHOT_ICON, path=row["file_path"],
              level=level if event is not None and event.event_type == "level_up" else None,
              heading=heading, title=title, place=place, event_type=event.event_type if event else "")
    caption = "  ·  ".join(p for p in (cue.text, format_datetime(t), place) if p)
    return Shot(row["file_path"], caption, cue, row["character_id"], row["screenshot_id"])


def replay_range(ctx, character_id: str, t: int) -> tuple[int, int]:
    """The replay "from here": shortly before the moment, to the end of its session."""
    sessions = sorted(ctx.repo.sessions(character_id), key=lambda s: s["started_at"])
    starts = [s["started_at"] for s in sessions]
    i = bisect.bisect_right(starts, t) - 1
    if i >= 0:
        session = sessions[i]
        end = session["ended_at"] or max(t + 60, session["started_at"])
        return max(session["started_at"], t - REPLAY_BEFORE), max(end, t + 60)
    return t - REPLAY_BEFORE, t + 30 * 60


class Picture(QWidget):
    """The picture fitted into the widget, under the achievement banner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap()
        self.cue: Cue | None = None
        self.setMinimumSize(320, 200)

    def paintEvent(self, event) -> None:
        from .cinematic_fx import banner_parts, draw_banner
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.pixmap.isNull():
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("screenshot.missing"))
            painter.end()
            return
        size = self.pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2, size.width(),
                        size.height())
        painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        if self.cue is not None:
            w = min(560.0, max(360.0, self.width() * 0.42))
            h = max(80.0, min(104.0, self.height() * 0.11))
            rect = QRectF((self.width() - w) / 2, max(14.0, target.top() + 14), w, h)
            draw_banner(painter, rect, *banner_parts(self.cue))
        painter.end()


class ScreenshotViewer(QWidget):
    favorite_changed = Signal(str, bool)       # screenshot_id, favourite

    def __init__(self, shots: list[Shot], index: int, parent=None, ctx=None):
        """ctx: needed for favourites and the replay (without it those buttons are hidden)."""
        super().__init__(parent, Qt.WindowType.Window)
        self.shots, self.index, self.ctx = shots, index, ctx
        self.cinematic = None
        self.resize(1200, 800)
        self.setStyleSheet("ScreenshotViewer { background: black; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.picture = Picture()
        root.addWidget(self.picture, 1)

        bar_widget = QWidget()
        bar_widget.setStyleSheet(f"background: {theme.PANEL}; border-top: 1px solid {theme.BORDER};")
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(12, 8, 12, 8)
        self.prev_button = QPushButton("◀")
        self.prev_button.setToolTip(tr("screenshot.prev"))
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.next_button = QPushButton("▶")
        self.next_button.setToolTip(tr("screenshot.next"))
        self.next_button.clicked.connect(lambda: self.step(1))
        self.star = QPushButton("★")
        self.star.setObjectName("Star")
        self.star.setCheckable(True)
        self.star.setToolTip(tr("gallery.star_tip"))
        self.star.clicked.connect(self.toggle_favorite)
        self.caption = QLabel()
        self.caption.setStyleSheet(theme.font_css(11, theme.GOLD) + " border: 0;")
        self.position = QLabel()
        self.position.setStyleSheet(f"color: {theme.MUTED}; background: transparent; border: 0;")
        self.replay = QPushButton(tr("gallery.replay"))
        self.replay.setToolTip(tr("gallery.replay_tip"))
        self.replay.clicked.connect(self.play_replay)
        self.external = QPushButton(tr("screenshot.open_external"))
        self.external.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.current.path)))
        close = QPushButton(tr("screenshot.close"))
        close.clicked.connect(self.close)
        for widget in (self.prev_button, self.next_button, self.star):
            bar.addWidget(widget)
        bar.addSpacing(8)
        bar.addWidget(self.caption, 1)
        bar.addWidget(self.position)
        bar.addSpacing(8)
        for widget in (self.replay, self.external, close):
            bar.addWidget(widget)
        root.addWidget(bar_widget)
        for widget in (self.star, self.replay):
            widget.setVisible(ctx is not None)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step(-1))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self.toggle_full_screen)
        QShortcut(QKeySequence(Qt.Key.Key_F), self, lambda: (self.star.toggle(), self.toggle_favorite()))
        QShortcut(QKeySequence(Qt.Key.Key_Return), self, self.play_replay)
        self.show_current()

    @property
    def _pixmap(self) -> QPixmap:
        return self.picture.pixmap

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
        self.picture.pixmap = QPixmap(shot.path)
        self.picture.cue = shot.cue
        self.picture.update()
        self.caption.setText(shot.caption)
        self.position.setText(tr("screenshot.position", i=self.index + 1, n=len(self.shots)))
        self.prev_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(self.index < len(self.shots) - 1)
        favorite = bool(self.ctx and shot.character_id and shot.screenshot_id
                        and shot.screenshot_id in self.ctx.repo.favorite_screenshots(shot.character_id))
        self.star.setChecked(favorite)
        self.replay.setEnabled(bool(self.ctx and shot.character_id and shot.time))

    def toggle_favorite(self) -> None:
        shot = self.current
        if not (self.ctx and shot.character_id and shot.screenshot_id):
            return
        on = self.star.isChecked()
        self.ctx.repo.set_favorite(shot.character_id, shot.screenshot_id, on)
        self.favorite_changed.emit(shot.screenshot_id, on)

    def toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def play_replay(self):
        """Plays the cinematic mode from shortly before this picture to the end of its session."""
        shot = self.current
        if not (self.ctx and shot.character_id and shot.time):
            return None
        from .cinematic import open_cinematic
        start, end = replay_range(self.ctx, shot.character_id, shot.time)
        self.cinematic = open_cinematic(self.ctx, shot.character_id, start, end)
        self.close()
        return self.cinematic
