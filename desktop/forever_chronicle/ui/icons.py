"""Qt pictures of the game icons (wow/game_icons.py): plain for lists and tables, framed squares for stat tiles,
round with a ring for map pins.

Every function returns None when the icon has no file; the caller then shows the event type's symbol. The
event_* functions fall back to the type's icon where the icon recorded with an event is missing.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from ..domain import event_types
from ..storage.repository import EventRow
from ..wow import game_icons

# Map pins as the addon draws them (UI/MapCanvas.lua PIN_LOOKS): icon and ring size, ring and back colour.
PIN_LOOKS = {
    "": (14, 19, QColor(217, 179, 107), QColor(20, 15, 10)),
    "milestone": (20, 26, QColor(255, 209, 0), QColor(31, 20, 5)),
    "danger": (15, 21, QColor(242, 56, 38), QColor(77, 8, 5)),
}
PIN_ORDER = {"": 0, "danger": 1, "milestone": 2}  # the addon's PIN_LEVEL: milestones on top
CROP = 0.07   # the dark frame inside each icon, cut off where the icon is round (the addon's 0.07 ... 0.93)
SCALE = 2     # drawn at twice their size, for sharp edges on high-DPI screens
LIST_SIZE = 20  # icons in lists and tables
TILE_SIZE = 34  # the overview's stat tiles (the addon's)

_pixmaps: dict[object, QPixmap | None] = {}
_generation = -1


def _cached(key, make):
    global _generation
    if _generation != game_icons.generation:  # new icons were taken from the game: look again
        _pixmaps.clear()
        _generation = game_icons.generation
    if key not in _pixmaps:
        _pixmaps[key] = make()
    return _pixmaps[key]


def pixmap(icon: game_icons.Icon | None) -> QPixmap | None:
    def load():
        path = game_icons.find(icon)
        pm = QPixmap(str(path)) if path else None
        return pm if pm is not None and not pm.isNull() else None
    return _cached(("plain", game_icons.name_of(icon)), load)


def small(icon: game_icons.Icon | None, size: int = LIST_SIZE) -> QPixmap | None:
    """The icon for list and table rows. Set it as the item's DecorationRole: a pixmap keeps its own size there,
    also in views whose icon size is larger (the chronicle's screenshot column); a QIcon would be stretched."""
    def make():
        source = pixmap(icon)
        if source is None:
            return None
        pm = source.scaled(size * SCALE, size * SCALE, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(SCALE)
        return pm
    return _cached(("list", game_icons.name_of(icon), size), make)


def tile(icon: game_icons.Icon | None, size: int = TILE_SIZE) -> QPixmap | None:
    """The icon of a stat tile as the addon draws it (UI:IconSquare): cut frame, 2 px inset on a dark square."""
    def make():
        source = pixmap(icon)
        if source is None:
            return None
        out = QPixmap(size * SCALE, size * SCALE)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.scale(SCALE, SCALE)
        p.fillRect(QRectF(0, 0, size, size), QColor(0, 0, 0, 178))
        cut = CROP * source.width()
        p.drawPixmap(QRectF(2, 2, size - 4, size - 4), source,
                     QRectF(cut, cut, source.width() - 2 * cut, source.height() - 2 * cut))
        p.end()
        out.setDevicePixelRatio(SCALE)
        return out
    return _cached(("tile", game_icons.name_of(icon), size), make)


def of_event(icon: game_icons.Icon | None, event_type: str) -> QPixmap | None:
    """An event's icon; the type's icon where the one recorded with the event was not found in the game."""
    return pixmap(icon) or pixmap(event_types.get(event_type).icon)


def event_file(event: EventRow) -> Path | None:
    """The PNG of an event's icon (for rich text such as tooltips), with the same fallback as of_event."""
    return game_icons.find(event_types.icon_of(event)) or game_icons.find(event_types.get(event.event_type).icon)


def event_small(event: EventRow) -> QPixmap | None:
    return small(event_types.icon_of(event)) or small(event_types.get(event.event_type).icon)


def medallion(icon: game_icons.Icon | None, look: str = "", crop: bool = True) -> QPixmap | None:
    """A round map pin: the icon in a coloured ring on a dark back (look: an event type's highlight)."""
    def make():
        source = pixmap(icon)
        if source is None:
            return None
        size, ring, color, back = PIN_LOOKS.get(look, PIN_LOOKS[""])
        out = QPixmap(ring * SCALE, ring * SCALE)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.scale(SCALE, SCALE)
        c = QPointF(ring / 2, ring / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(back)
        p.drawEllipse(c, ring / 2 - 0.5, ring / 2 - 0.5)
        clip = QPainterPath()
        clip.addEllipse(c, size / 2, size / 2)
        p.setClipPath(clip)
        cut = CROP * source.width() if crop else 0
        p.drawPixmap(QRectF(c.x() - size / 2, c.y() - size / 2, size, size), source,
                     QRectF(cut, cut, source.width() - 2 * cut, source.height() - 2 * cut))
        p.setClipping(False)
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, (size + ring) / 4, (size + ring) / 4)
        p.end()
        out.setDevicePixelRatio(SCALE)
        return out
    return _cached(("pin", game_icons.name_of(icon), look, crop), make)


def event_pin(event: EventRow) -> QPixmap | None:
    """The event's map pin as in the addon (the death skull is drawn whole, without a cut frame)."""
    et = event_types.get(event.event_type)
    if et.pin_icon:
        pin = medallion(et.pin_icon, et.highlight, crop=False)
        if pin:
            return pin
    return medallion(event_types.icon_of(event), et.highlight) or medallion(et.icon, et.highlight)
