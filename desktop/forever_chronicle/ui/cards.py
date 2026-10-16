"""Cards in the Classic look, instead of plain tables.

- Card: a framed panel with a gold title (Morpheus) for the home screen; clickable cards light up on hover and
  emit clicked.
- CardList: a list like the addon's Chronik. Each row has a game icon, a gold title, a grey detail line and, on
  the right, an optional thumbnail; gold heading rows (a day, a category) sit between them. A coloured bar on the
  left marks milestones (gold) and deaths (red). Rows are drawn by a delegate, so thousands stay quick.
  thumb_clicked(row) fires when a thumbnail is clicked.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QLabel, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate, QVBoxLayout)

from . import theme

KIND, TITLE, DETAIL, ICON, THUMB, ACCENT, TITLE_COLOR, DATA = (Qt.ItemDataRole.UserRole + i for i in range(8))
ROW_H, HEADER_H = 46, 32
ICON_SIZE = 32
THUMB_SIZE = QSize(112, 70)
ACCENTS = {"milestone": theme.GOLD, "danger": theme.RED}


class Card(QFrame):
    """A home-screen card: title, then whatever the caller adds to body (a QVBoxLayout)."""

    clicked = Signal()

    def __init__(self, title: str = "", clickable: bool = False):
        super().__init__()
        self.setObjectName("Card")
        self.setProperty("clickable", clickable)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 14, 18, 16)
        self.body.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.body.addWidget(self.title)

    def mouseReleaseEvent(self, event) -> None:
        if self.property("clickable") and event.button() == Qt.MouseButton.LeftButton \
                and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CardList(QListWidget):
    thumb_clicked = Signal(int)

    def __init__(self, thumbs: bool = False):
        """thumbs: rows leave room on the right for a thumbnail (rows without one stay low)."""
        super().__init__()
        self.thumbs = thumbs
        self.setItemDelegate(CardDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setUniformItemSizes(False)
        self.setMouseTracking(True)
        self.setSpacing(0)

    def add_header(self, text: str) -> QListWidgetItem:
        item = QListWidgetItem(text)
        item.setData(KIND, "header")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(QSize(100, HEADER_H))
        self.addItem(item)
        return item

    def add_entry(self, title: str, detail: str = "", icon: QPixmap | None = None, accent: str | None = None,
                  title_color: str | None = None, data: Any = None, thumb: bool = False,
                  tooltip: str = "") -> QListWidgetItem:
        """A row; thumb=True reserves the thumbnail's place (set_thumb fills it in later)."""
        item = QListWidgetItem(title)
        item.setData(KIND, "entry")
        item.setData(TITLE, title)
        item.setData(DETAIL, detail)
        item.setData(ICON, icon)
        item.setData(ACCENT, ACCENTS.get(accent or "", accent))
        item.setData(TITLE_COLOR, title_color)
        item.setData(DATA, data)
        if tooltip:
            item.setToolTip(tooltip)
        item.setSizeHint(QSize(100, THUMB_SIZE.height() + 10 if thumb else ROW_H))
        if thumb:
            item.setData(THUMB, placeholder_pixmap())
        self.addItem(item)
        return item

    @staticmethod
    def set_thumb(item: QListWidgetItem, thumb: QPixmap | QIcon | None) -> None:
        if isinstance(thumb, QIcon):
            thumb = thumb.pixmap(THUMB_SIZE)
        item.setData(THUMB, thumb)

    def entries(self) -> list[QListWidgetItem]:
        return [self.item(i) for i in range(self.count()) if self.item(i).data(KIND) == "entry"]

    def thumb_rect(self, row: int) -> QRect | None:
        item = self.item(row)
        if item is None or item.data(THUMB) is None:
            return None
        return CardDelegate.thumb_rect(self.visualItemRect(item))

    def mouseReleaseEvent(self, event) -> None:
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        rect = self.thumb_rect(index.row()) if index.isValid() else None
        super().mouseReleaseEvent(event)
        if rect is not None and rect.contains(pos) and event.button() == Qt.MouseButton.LeftButton:
            self.thumb_clicked.emit(index.row())


def placeholder_pixmap(text: str = "") -> QPixmap:
    pix = QPixmap(THUMB_SIZE)
    pix.fill(QColor(theme.PANEL_ALT))
    painter = QPainter(pix)
    painter.setPen(QColor(theme.BORDER))
    painter.drawRect(0, 0, THUMB_SIZE.width() - 1, THUMB_SIZE.height() - 1)
    if text:
        painter.setPen(QColor(theme.MUTED))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    painter.end()
    return pix


class CardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index: QModelIndex) -> QSize:
        hint = index.data(Qt.ItemDataRole.SizeHintRole)
        return hint if isinstance(hint, QSize) else QSize(100, ROW_H)

    @staticmethod
    def thumb_rect(row: QRect) -> QRect:
        return QRect(row.right() - THUMB_SIZE.width() - 8, row.top() + (row.height() - THUMB_SIZE.height()) // 2,
                     THUMB_SIZE.width(), THUMB_SIZE.height())

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = option.rect
        if index.data(KIND) == "header":
            self._header(painter, r, index.data(Qt.ItemDataRole.DisplayRole) or "")
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.fillRect(r, QColor(theme.SELECT) if selected else QColor("#1d1712") if hover
                         else QColor(theme.PANEL_ALT) if index.row() % 2 else QColor(theme.PANEL))
        painter.fillRect(QRect(r.left(), r.bottom(), r.width(), 1), QColor("#241b12"))
        accent = index.data(ACCENT)
        if selected or accent:
            painter.fillRect(QRect(r.left(), r.top(), 3, r.height()), QColor(theme.GOLD if selected else accent))

        x = r.left() + 12
        icon = index.data(ICON)
        box = QRect(x, r.top() + (r.height() - ICON_SIZE) // 2, ICON_SIZE, ICON_SIZE)
        painter.fillRect(box.adjusted(-1, -1, 1, 1), QColor(0, 0, 0, 200))
        if isinstance(icon, QPixmap) and not icon.isNull():
            painter.drawPixmap(box, icon)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.drawRect(box.adjusted(-1, -1, 0, 0))
        x = box.right() + 12

        thumb = index.data(THUMB)
        right = (self.thumb_rect(r).left() - 12) if isinstance(thumb, QPixmap) else r.right() - 10
        title_font = theme.heading_font(11)
        detail_font = QFont()
        detail_font.setPointSize(9)
        title, detail = index.data(TITLE) or "", index.data(DETAIL) or ""
        th, dh = QFontMetrics(title_font).height(), QFontMetrics(detail_font).height()
        top = r.top() + (r.height() - th - (dh + 2 if detail else 0)) // 2
        painter.setFont(title_font)
        painter.setPen(QColor(index.data(TITLE_COLOR) or theme.GOLD))
        width = max(10, right - x)
        painter.drawText(QRect(x, top, width, th), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight, width))
        if detail:
            painter.setFont(detail_font)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(QRect(x, top + th + 2, width, dh), Qt.AlignmentFlag.AlignLeft,
                             QFontMetrics(detail_font).elidedText(detail, Qt.TextElideMode.ElideRight, width))
        if isinstance(thumb, QPixmap) and not thumb.isNull():
            rect = self.thumb_rect(r)
            scaled = thumb.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            at = QPoint(rect.left() + (rect.width() - scaled.width()) // 2,
                        rect.top() + (rect.height() - scaled.height()) // 2)
            painter.fillRect(QRect(at, scaled.size()).adjusted(-3, -3, 3, 3), QColor("#f3eee2"))   # photo paper
            painter.drawPixmap(at, scaled)
        painter.restore()

    @staticmethod
    def _header(painter: QPainter, r: QRect, text: str) -> None:
        painter.fillRect(r, QColor(theme.BG))
        font = theme.heading_font(11)
        painter.setFont(font)
        painter.setPen(QColor(theme.GOLD))
        width = QFontMetrics(font).horizontalAdvance(text)
        painter.drawText(QRect(r.left() + 10, r.top(), width + 4, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
        y = r.center().y() + 1
        line_x = r.left() + 22 + width
        if r.right() - 10 > line_x:
            painter.setPen(QPen(QColor(201, 162, 74, 110), 1))
            painter.drawLine(line_x, y, r.right() - 10, y)
