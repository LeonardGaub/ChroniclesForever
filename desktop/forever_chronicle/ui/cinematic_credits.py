"""End credits of the cinematic mode (option "cine_credits"): when the replay reaches its end, the map dims and
credits roll up as in the game's own: the character's name in large letters, then what the journey added up to
(domain/credits.py), each as a small gold role above a larger name, while the range's screenshots drift by as
polaroids on both sides. A last card ("Journey Forever") stops in the middle and stays.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap

from ..domain.credits import Section
from ..i18n import tr
from . import theme
from .cinematic_fx import (BANNER_HEADING, PAPER, PAPER_EDGE, TRIM, _Overlay, clamp, cropped, ease_out, load_thumbnail,
                           pixel_font, with_alpha)

SPEED = 0.07               # scrolling, in window heights per second
DIM_SECONDS = 2.5          # the map dims behind the credits
DIM = 185                  # how dark it gets (alpha)
START_DELAY = 1.2          # seconds before the first line comes up
HOLD = 4.0                 # seconds the last card stands before the credits count as finished
MAX_PHOTOS = 12
PARALLAX = 0.8             # the polaroids move slower than the text
TEXT = QColor(theme.TEXT)


class CreditsOverlay(_Overlay):
    def __init__(self, parent, title: list[str], sections: list[Section], photos: list[str] = ()):
        super().__init__(parent)
        self.title, self.sections = title, sections
        self.photos: list[QPixmap] = [p for p in (load_thumbnail(path, QSize(360, 240))
                                                  for path in list(photos)[:MAX_PHOTOS]) if p is not None]
        self.age = 0.0
        self.area = QRectF()            # the picture between the letterbox bars
        self.hide()

    def start(self, area: QRectF) -> None:
        self.area = area
        self.age = 0.0
        self.show()
        self.raise_()

    def advance(self, dt: float) -> None:
        if self.isVisible():
            self.age += dt
            self.update()

    # -- layout -----------------------------------------------------------------------------------------------

    def _rows(self, h: float) -> list[tuple[float, str, str, float]]:
        """(height, kind, text, font size) of every row from the top of the credits."""
        rows = [(h * 0.11, "name", self.title[0], h * 0.085)]
        for text in self.title[1:]:
            rows.append((h * 0.05, "sub", text, h * 0.03))
        rows.append((h * 0.16, "gap", "", 0))
        for section in self.sections:
            rows.append((h * 0.07, "heading", section.heading, h * 0.026))
            for line in section.lines:
                rows.append((h * 0.034, "role", line.role, h * 0.022))
                rows.append((h * 0.07, "line", line.name, h * 0.036))
            rows.append((h * 0.1, "gap", "", 0))
        rows.append((h * 0.06, "gap", "", 0))
        rows.append((h * 0.1, "end", "Journey Forever", h * 0.075))
        rows.append((h * 0.05, "thanks", tr("credits.thanks"), h * 0.028))
        return rows

    def _scroll(self, h: float) -> tuple[float, float]:
        """(how far the credits have moved up, how far they move before the last card stands in the middle)."""
        rows = self._rows(h)
        end_center = sum(r[0] for r in rows[:-2]) + rows[-2][0] / 2
        area = self.area if not self.area.isEmpty() else QRectF(self.rect())
        stop = area.bottom() + end_center - area.center().y()
        return min(stop, max(0.0, self.age - START_DELAY) * SPEED * h), stop

    def duration(self) -> float:
        """Seconds from the start until the last card has stood for HOLD seconds."""
        h = max(1, self.height())
        _, stop = self._scroll(h)
        return START_DELAY + stop / (SPEED * h) + HOLD

    @property
    def finished(self) -> bool:
        return self.age >= self.duration()

    # -- painting ---------------------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor(0, 0, 0, int(DIM * ease_out(self.age / DIM_SECONDS))))
        area = self.area if not self.area.isEmpty() else QRectF(self.rect())
        painter.setClipRect(area)                  # nothing over the letterbox bars
        offset, _ = self._scroll(h)
        top = area.bottom() - offset
        rows = self._rows(h)
        total = sum(r[0] for r in rows)
        self._photos(painter, area, top, total, offset)
        y = top
        for height, kind, text, size in rows:
            if kind != "gap" and y + height > area.top() and y < area.bottom():
                fade = clamp((y + height / 2 - area.top()) / (h * 0.08)) * clamp((area.bottom() - y) / (h * 0.08))
                painter.setOpacity(fade)
                self._row(painter, QRectF(0, y, w, height), kind, text, size)
            y += height
        painter.end()

    def _row(self, painter: QPainter, row: QRectF, kind: str, text: str, size: float) -> None:
        if kind in ("name", "end"):
            font = pixel_font(size, families=theme.TITLE_FONTS)
            painter.setFont(font)
            painter.setPen(QColor(0, 0, 0, 220))
            painter.drawText(row.translated(3, 3), Qt.AlignmentFlag.AlignCenter, text)
            fill = QLinearGradient(0, row.top(), 0, row.bottom())
            for at, color in zip((0.2, 0.55, 0.9), ("#fff6c8", theme.GOLD, "#b07a10")):
                fill.setColorAt(at, QColor(color))
            painter.setPen(QPen(QBrush(fill), 1))
            painter.drawText(row, Qt.AlignmentFlag.AlignCenter, text)
        elif kind == "heading":
            font = pixel_font(size)
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 135)
            painter.setFont(font)
            painter.setPen(BANNER_HEADING)
            label = text.upper()
            painter.drawText(row, Qt.AlignmentFlag.AlignCenter, label)
            tw = QFontMetrics(font).horizontalAdvance(label)
            cx, cy = row.center().x(), row.center().y()
            for sign in (-1, 1):
                x0, x1 = cx + sign * (tw / 2 + 18), cx + sign * (tw / 2 + 140)
                line = QLinearGradient(x0, 0, x1, 0)
                line.setColorAt(0, TRIM)
                line.setColorAt(1, with_alpha(TRIM, 0))
                painter.fillRect(QRectF(min(x0, x1), cy - 0.75, abs(x1 - x0), 1.5), line)
                painter.save()
                painter.translate(x0, cy)
                painter.rotate(45)
                painter.fillRect(QRectF(-3, -3, 6, 6), TRIM)
                painter.restore()
        else:
            color = {"sub": BANNER_HEADING, "role": QColor(theme.GOLD), "line": TEXT,
                     "thanks": QColor(theme.MUTED)}[kind]
            painter.setFont(pixel_font(size, bold=kind == "line"))
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(row.translated(2, 2), Qt.AlignmentFlag.AlignCenter, text)
            painter.setPen(color)
            painter.drawText(row, Qt.AlignmentFlag.AlignCenter, text)

    def _photos(self, painter: QPainter, area: QRectF, top: float, total: float, offset: float) -> None:
        """The screenshots as polaroids drifting up on both sides, a little slower than the text."""
        if not self.photos:
            return
        w = self.width()
        pw = clamp(w * 0.15, 120, 300)
        step = max(pw * 0.9, total / len(self.photos))
        for i, pixmap in enumerate(self.photos):
            x = w * (0.14 if i % 2 == 0 else 0.86)
            y = area.bottom() + i * step + pw * 0.4 - offset * PARALLAX
            if y < area.top() - pw or y > area.bottom() + pw:
                continue
            fade = clamp((y - area.top()) / (pw * 0.9)) * clamp((area.bottom() - y) / (pw * 0.9))
            painter.save()
            painter.setOpacity(0.8 * fade)
            painter.translate(QPointF(x, y))
            painter.rotate((-1 if i % 2 == 0 else 1) * (3 + (i * 7) % 5))
            ph = pw * 0.62
            m = pw * 0.04
            paper = QRectF(-pw / 2 - m, -ph / 2 - m, pw + 2 * m, ph + 4 * m)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRect(paper.translated(5, 7))
            painter.setPen(QPen(PAPER_EDGE, 1))
            painter.setBrush(PAPER)
            painter.drawRect(paper)
            photo = QRectF(-pw / 2, -ph / 2, pw, ph)
            painter.drawPixmap(photo, pixmap, cropped(pixmap, pw / ph))
            painter.restore()
