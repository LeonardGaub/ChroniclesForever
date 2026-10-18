"""Dungeon maps on the map page and in cinematic mode (domain/dungeons.py; the addon's map page does the same).

- FloorBar: [<] Floor 2/4 - Library [>] for dungeons with several floors.
- VisitPanel: the visit at the shown moment and every event of it (bosses numbered), the time since entering, grey
  until it happens; a click on an entry jumps there.
- DungeonOverlay: cinematic mode's picture while the player is inside a dungeon with a map: the floor fades in
  over the map, with the visit list growing as the replay goes on (later moments are not shown in advance).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsColorizeEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..domain import dungeons, event_types
from ..domain.dungeons import DungeonMap, Visit, VisitEntry
from ..i18n import format_datetime, format_duration, tr
from . import icons, theme

ROWS = 16                  # entries listed at most (as in the addon)
PANEL_WIDTH = 290
ICON = 16
FUTURE_ALPHA = 0.4         # entries after the shown moment


def entry_text(entry: VisitEntry) -> str:
    if entry.boss is not None:
        return f"{entry.boss}. {entry.event.payload.get('name') or event_types.describe(entry.event)}"
    return event_types.describe(entry.event)


def entry_icon(entry: VisitEntry) -> QPixmap | None:
    return icons.of_event(event_types.icon_of(entry.event), entry.event.event_type)


def visit_line(found: list[Visit], index: int) -> str:
    """"date · duration · visit 2 of 3"."""
    visit = found[index]
    parts = [format_datetime(int(visit.start)), format_duration(visit.end - visit.start)]
    if len(found) > 1:
        parts.append(tr("map.visit_of", n=index + 1, count=len(found)))
    return "  ·  ".join(parts)


def dungeon_name(dungeon: DungeonMap, client_names: dict[int, str]) -> str:
    """The name the client gave this instance (recorded on entering), else the map table's."""
    return client_names.get(dungeon.instance_id) or dungeon.name()


_BOX = "background: rgba(0,0,0,190); border: 1px solid rgba(90,70,48,200); border-radius: 3px;"
_PLAIN = "QLabel { border: none; }"   # the map view's own border style would reach the labels


class FloorBar(QFrame):
    stepped = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("floorBar")
        self.setStyleSheet(f"#floorBar {{ {_BOX} }} QPushButton {{ padding: 0 6px; }} {_PLAIN}")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 3, 4, 3)
        self.prev, self.next = QPushButton("◀"), QPushButton("▶")
        self.label = QLabel()
        self.label.setStyleSheet(theme.font_css(10, theme.GOLD))
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for button, step in ((self.prev, -1), (self.next, 1)):
            button.setFixedWidth(30)
            button.clicked.connect(lambda _=False, s=step: self.stepped.emit(s))
        row.addWidget(self.prev)
        row.addWidget(self.label, 1)
        row.addWidget(self.next)
        self.setFixedWidth(PANEL_WIDTH)

    def show_floor(self, dungeon: DungeonMap, floor: int) -> None:
        text = tr("map.floor", n=floor, count=dungeon.floors)
        name = dungeon.floor_name(floor)
        self.label.setText(f"{text} – {name}" if name else text)
        self.label.setToolTip(self.label.text())
        for button in (self.prev, self.next):
            button.setToolTip(tr("map.floor_tip"))


class _Row(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.setObjectName("visitRow")
        self.setStyleSheet("#visitRow { background: transparent; border: none; border-radius: 2px; }"
                           "#visitRow:hover { background: rgba(255,209,0,40); }")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.on_click = on_click
        self.at: int | None = None
        self.full = ""                  # the entry's whole text (the label may be shortened)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 1, 3, 1)
        row.setSpacing(6)
        self.icon = QLabel()
        self.icon.setFixedSize(ICON, ICON)
        self.text = QLabel()
        self.text.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        self.when = QLabel()
        self.when.setStyleSheet(f"color: {theme.MUTED}; background: transparent;")
        row.addWidget(self.icon)
        row.addWidget(self.text, 1)
        row.addWidget(self.when)
        self.fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade)

    def mousePressEvent(self, event) -> None:
        if self.at is not None and event.button() == Qt.MouseButton.LeftButton:
            self.on_click(self.at)
        super().mousePressEvent(event)


class VisitPanel(QFrame):
    """The visit list of the map page."""
    jump = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("visitPanel")
        self.setStyleSheet(f"#visitPanel {{ {_BOX} }} {_PLAIN}")
        self.setFixedWidth(PANEL_WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 8)
        box.setSpacing(1)
        self.title = QLabel()
        self.title.setStyleSheet(theme.font_css(12, theme.GOLD))
        self.sub = QLabel()
        self.sub.setStyleSheet(f"color: {theme.MUTED}; background: transparent;")
        box.addWidget(self.title)
        box.addWidget(self.sub)
        box.addSpacing(4)
        self.rows = [_Row(self.jump.emit) for _ in range(ROWS)]
        for row in self.rows:
            box.addWidget(row)
        self.more = QLabel()
        self.more.setStyleSheet(f"color: {theme.MUTED}; background: transparent;")
        box.addWidget(self.more)
        self.key = None

    def show_visit(self, title: str, found: list[Visit], index: int | None, entries: list[VisitEntry],
                   now: float) -> None:
        """Fills the list for the moment now; entries after it are greyed out."""
        done = sum(1 for e in entries if e.event.occurred_at <= now)
        key = (title, len(found), index, found[index].end if index is not None else None, len(entries), done)
        if key == self.key:
            return
        self.key = key
        self.title.setText(title)
        self.sub.setText(visit_line(found, index) if index is not None else tr("map.visit_none"))
        visit = found[index] if index is not None else None
        for row, entry in zip(self.rows, entries + [None] * ROWS):
            row.setVisible(entry is not None)
            if entry is None:
                row.at = None
                continue
            row.at = entry.event.occurred_at
            when = dungeons.since_entering(entry.offset)
            row.when.setText(when)
            room = PANEL_WIDTH - 40 - ICON - row.when.fontMetrics().horizontalAdvance(when)
            row.full = entry_text(entry)
            row.text.setText(row.text.fontMetrics().elidedText(row.full, Qt.TextElideMode.ElideRight, room))
            icon = entry_icon(entry)
            row.icon.setPixmap(icon.scaled(ICON, ICON, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation) if icon else QPixmap())
            row.setToolTip(f"{event_types.describe(entry.event)}\n{format_datetime(entry.event.occurred_at)}\n"
                           f"{tr('map.visit_tip')}")
            row.fade.setOpacity(FUTURE_ALPHA if entry.event.occurred_at > now else 1.0)
        more = (tr("map.visit_more", n=len(entries) - ROWS) if len(entries) > ROWS
                else tr("map.visit_empty") if visit is not None and not entries else "")
        self.more.setText(more)
        self.more.setVisible(bool(more))
        self.adjustSize()


# -- cinematic mode ------------------------------------------------------------------------------------------------

FADE_IN, FADE_OUT = 0.8, 0.6          # seconds
NEW_SECONDS = 2.5                     # a new entry glows this long


class DungeonOverlay(QWidget):
    """Cinematic mode inside a dungeon with a map: its floor over the map (the client gives no position there,
    so there is no marker), and the visit so far as a list on the right, the newest entry glowing."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self.spirit = QGraphicsColorizeEffect(self)       # grey while the player is dead, like the map
        self.spirit.setColor(QColor(150, 175, 210))
        self.spirit.setStrength(0.0)
        self.spirit.setEnabled(False)
        self.setGraphicsEffect(self.spirit)
        self.opacity = 0.0
        self.wanted = False
        self.area = QRectF()
        self.title = ""
        self.sub = ""
        self.floor_text = ""
        self.pixmap: QPixmap | None = None
        self.entries: list[VisitEntry] = []
        self.ages: dict[str, float] = {}               # event_id -> seconds since it appeared
        self._art: dict[tuple[int, int], QPixmap | None] = {}
        self.hide()

    def show_visit(self, dungeon: DungeonMap | None, title: str = "", found: list[Visit] | None = None,
                   index: int | None = None, entries: list[VisitEntry] | None = None, now: float = 0.0,
                   jump: bool = False) -> None:
        """What to show at the moment now (dungeon None: nothing, fades out). jump: after a seek, at once and
        without the newest entry glowing. The first floor is shown: without a position the floor is unknown."""
        self.wanted = dungeon is not None
        if dungeon is None:
            if jump:
                self.opacity = 0.0
                self.hide()
            return
        self.pixmap = self._pixmap(dungeon.instance_id, 1)
        self.title = title
        self.floor_text = dungeon.floor_name(1) or ""
        self.sub = visit_line(found, index) if found and index is not None else ""
        shown = [e for e in (entries or []) if e.event.occurred_at <= now]
        if jump:
            self.ages = {e.event.event_id: NEW_SECONDS for e in shown}
        for e in shown:
            self.ages.setdefault(e.event.event_id, 0.0)
        self.entries = shown
        if jump:
            self.opacity = 1.0
        self.setVisible(self.opacity > 0)
        self.update()

    def set_grey(self, grey: float) -> None:
        self.spirit.setStrength(grey)
        self.spirit.setEnabled(grey > 0.001)

    def advance(self, dt: float) -> None:
        before = self.opacity
        if self.wanted:
            self.opacity = min(1.0, self.opacity + dt / FADE_IN)
        else:
            self.opacity = max(0.0, self.opacity - dt / FADE_OUT)
        for key in self.ages:
            self.ages[key] += dt
        self.setVisible(self.opacity > 0)
        if self.opacity > 0 and (self.opacity != before or any(a < NEW_SECONDS for a in self.ages.values())):
            self.update()

    def _pixmap(self, instance_id: int, floor: int) -> QPixmap | None:
        key = (instance_id, floor)
        if key not in self._art:
            dungeon = dungeons.get(instance_id)
            path = dungeon.art(floor) if dungeon else None
            pixmap = QPixmap(str(path)) if path else QPixmap()
            self._art[key] = None if pixmap.isNull() else pixmap
        return self._art[key]

    def paintEvent(self, event) -> None:
        if self.opacity <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self.opacity)
        area = self.area if not self.area.isEmpty() else QRectF(self.rect())
        painter.fillRect(area, QColor(0, 0, 0))
        # The list on the left: event alerts slide in on the right.
        list_w = min(380.0, max(260.0, area.width() * 0.24))
        art = area.adjusted(list_w + 56, 18, -24, -18)
        if self.pixmap is not None and art.width() > 0 and art.height() > 0:
            size = self.pixmap.size().scaled(int(art.width()), int(art.height()), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(art.center().x() - size.width() / 2, art.center().y() - size.height() / 2,
                            size.width(), size.height())
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        self._paint_list(painter, QRectF(area.left() + 32, area.top() + 24, list_w, area.height() - 48))
        painter.end()

    def _paint_list(self, painter: QPainter, rect: QRectF) -> None:
        line = max(20.0, min(28.0, rect.height() / 22))
        painter.setFont(_font(line * 0.95, title=True))
        painter.setPen(QColor(theme.GOLD))
        y = rect.top()
        painter.drawText(QRectF(rect.left(), y, rect.width(), line * 1.4), Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, self.title)
        y += line * 1.4
        painter.setFont(_font(line * 0.55))
        painter.setPen(QColor(theme.MUTED))
        for text in (self.floor_text, self.sub):
            if text:
                painter.drawText(QRectF(rect.left(), y, rect.width(), line * 0.8),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
                y += line * 0.8
        y += line * 0.4
        pen = QPen(QColor(theme.BORDER), 1)
        painter.setPen(pen)
        painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        y += line * 0.4
        rows = max(1, int((rect.bottom() - y) / line))
        shown = self.entries[-rows:]                    # the newest when the list is long
        painter.setFont(_font(line * 0.6))
        for entry in shown:
            age = self.ages.get(entry.event.event_id, NEW_SECONDS)
            glow = max(0.0, 1 - age / NEW_SECONDS)
            row = QRectF(rect.left(), y, rect.width(), line)
            if glow > 0:
                gradient = QLinearGradient(row.topLeft(), row.topRight())
                gradient.setColorAt(0, QColor(255, 209, 0, int(70 * glow)))
                gradient.setColorAt(1, QColor(255, 209, 0, 0))
                painter.fillRect(row, gradient)
            icon = entry_icon(entry)
            size = line * 0.75
            if icon is not None:
                painter.drawPixmap(QRectF(row.left() + 2, row.center().y() - size / 2, size, size), icon,
                                   QRectF(icon.rect()))
            text_rect = row.adjusted(size + 10, 0, -4, 0)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             dungeons.since_entering(entry.offset))
            painter.setPen(QColor(theme.GOLD) if entry.boss is not None else QColor(theme.TEXT))
            text = painter.fontMetrics().elidedText(entry_text(entry), Qt.TextElideMode.ElideRight,
                                                    int(text_rect.width() - line * 2.6))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            y += line


def _font(px: float, title: bool = False):
    font = theme.title_font(10) if title else theme.heading_font(10)
    font.setPixelSize(max(8, int(px)))
    return font
