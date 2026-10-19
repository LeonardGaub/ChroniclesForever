"""The cinematic mode's experience bar, as the game draws it at the bottom of the screen: its own frame with twenty
bubbles (UI-MainMenuBar-Dwarf) over the purple status bar (UI-StatusBar), and "EP: 11523 / 27300" on it, as the
game shows it under the mouse (tools/build_ui_skin.py builds xp_frame.png and xp_fill.png from the install).

The bar glides to the replay's experience (domain/experience.py) and the points count along with it; at a level-up
it fills up, flashes and starts again empty. Where only the playing time places the bar (no samples) it shows the
share; where nothing is known (the level still going, without samples) the frame stays empty.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from ..i18n import tr
from .cinematic_fx import _Overlay, clamp, pixel_font, with_alpha
from .theme import SKIN

FRAME_ROWS = 15                 # xp_frame.png: 1024 x 15 ...
FILL_TOP, FILL_BOTTOM = 4, 14   # ... the status bar lies in these rows, under the frame's lines
FILL_SECONDS = 0.25             # the fill gliding to the experience
WRAP_SPEED = 2.5                # bar widths per second while filling up at a level-up
FLASH_SECONDS = 0.9
TRACK = QColor(0, 0, 0, 150)    # the empty part (the game's bar background)


class XpBar(_Overlay):
    WIDTH = 1024                # the game's bar at UI scale 1

    def __init__(self, parent):
        super().__init__(parent)
        self.frame = QPixmap(str(SKIN / "xp_frame.png"))
        self.fill = QPixmap(str(SKIN / "xp_fill.png"))
        self.level: int | None = None          # what the bar shows ...
        self.share: float | None = None
        self.size: float | None = None
        self.target: tuple[int | None, float | None, float | None] = (None, None, None)   # ... where it goes
        self.flash = 0.0

    @staticmethod
    def height_for(width: int) -> int:
        """The bar's height at a width, in the game's proportions."""
        return max(10, round(width * FRAME_ROWS / XpBar.WIDTH))

    def set_target(self, level: int | None, share: float | None, size: float | None = None) -> None:
        self.target = (level, share, size)
        if self.level is None:
            self.snap()

    def snap(self) -> None:
        """Straight to the target (after a jump)."""
        self.level, self.share, self.size = self.target
        self.flash = 0.0
        self.update()

    def advance(self, dt: float) -> None:
        self.flash = max(0.0, self.flash - dt / FLASH_SECONDS)
        level, share, size = self.target
        if level is None or self.level is None or level < self.level or level > self.level + 1:
            self.level, self.share, self.size = level, share, size        # a jump: no animation
        elif level == self.level + 1:                                     # a level-up: fill up, flash, wrap
            self.share = min(1.0, (self.share or 0.0) + dt * WRAP_SPEED)
            if self.share >= 1.0:
                self.level, self.share, self.size, self.flash = level, 0.0, size, 1.0
        elif share is None:
            self.share, self.size = None, size
        else:
            now = self.share if self.share is not None else share
            self.share = now + (share - now) * (1 - math.exp(-dt / FILL_SECONDS))
            self.size = size
        self.update()

    def text(self) -> str:
        """As the game: the points in the level and the level's size; the share where the points are unknown."""
        if self.share is None:
            return ""
        if self.size:
            return tr("cine.xp_points", xp=int(round(clamp(self.share) * self.size)), max=int(round(self.size)))
        return tr("cine.xp", percent=round(clamp(self.share) * 100))

    def paintEvent(self, event) -> None:
        if self.level is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        k = h / FRAME_ROWS
        bar = QRectF(2 * k, FILL_TOP * k, w - 4 * k, (FILL_BOTTOM - FILL_TOP) * k)
        painter.fillRect(bar, TRACK)
        share = self.share
        if share is not None and share > 0 and not self.fill.isNull():
            painter.drawPixmap(QRectF(bar.left(), bar.top(), bar.width() * clamp(share), bar.height()), self.fill,
                               QRectF(self.fill.rect()))
        if self.flash > 0:
            painter.fillRect(bar, with_alpha(QColor(255, 225, 140), 200 * self.flash))
        if not self.frame.isNull():
            painter.drawPixmap(QRectF(0, 0, w, h), self.frame, QRectF(self.frame.rect()))
        text = self.text()
        if text:
            painter.setFont(pixel_font(max(9.0, bar.height() * 0.95)))
            painter.setPen(QColor(0, 0, 0, 230))
            painter.drawText(QRectF(0, 1, w, h).translated(1, 1), Qt.AlignmentFlag.AlignCenter, text)
            painter.setPen(QColor(255, 255, 255, 240))
            painter.drawText(QRectF(0, 1, w, h), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
