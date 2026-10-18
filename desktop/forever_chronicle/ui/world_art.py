"""The seamless world map in a graphics scene (cinematic mode): every zone on one picture of Azeroth, so the
camera glides from one zone into the next instead of switching maps (wow/map_art.py, tools/build_world_map.py).

The scene's unit is the world unit (the world map 947 at ART_WIDTH x ART_HEIGHT, as every map of the replay).
Under everything lies the whole world at BASE_PX; where the camera is close, the sharp detail tiles come in, loaded
when they first come near the view and let go when the view has moved on. City maps (much finer than their zone's
painting of them) fade in where they belong while the player is inside the city, and out on leaving it: they
do not fit the zone art round them, so they show only where the replay is.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from ..domain import maps
from ..wow import map_art
from .cinematic_fx import clamp

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
DETAIL_FROM = map_art.BASE_PX * 1.1   # screen px per world unit where the detail tiles come in
KEEP = 1.5                            # tiles stay loaded this many tile widths past the view
CITY_FADE = 0.8                       # seconds a city's map takes to fade in or out
Z_BASE, Z_TILES, Z_CITIES = -3.0, -2.0, -1.0


def available() -> bool:
    return map_art.world_base() is not None


class WorldArt:
    def __init__(self, scene: QGraphicsScene):
        self.scene = scene
        self.base = None
        path = map_art.world_base()
        if path is not None:
            pixmap = QPixmap(str(path))
            self.base = scene.addPixmap(pixmap)
            self.base.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.base.setScale(W / pixmap.width())
            self.base.setZValue(Z_BASE)
        folder = map_art.maps_dir() / "world"
        self.known = set()
        for f in folder.glob("*_*.jpg"):
            i, _, j = f.stem.partition("_")
            if i.isdigit() and j.isdigit():
                self.known.add((int(i), int(j)))
        self.tiles: dict[tuple[int, int], QGraphicsPixmapItem] = {}
        self.cities: dict[int, QGraphicsPixmapItem] = {}

    def add_city(self, map_id: int, pixmap: QPixmap, rect: QRectF) -> None:
        """A city's map (soft edges) lying at rect (world units)."""
        item = self.scene.addPixmap(pixmap)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setPos(rect.topLeft())
        item.setScale(rect.width() / pixmap.width())
        item.setZValue(Z_CITIES)
        item.setOpacity(0.0)
        item.hide()
        self.cities[map_id] = item

    def update(self, visible: QRectF, scale: float, zone: int | None = None, dt: float = 0.0) -> None:
        """Brings in the detail near the view (visible: the view's rectangle in world units; scale: screen pixels
        per world unit) and fades the city the player is in (zone) in, the others out (dt: real seconds since the
        last update; 0 sets them at once)."""
        unit = map_art.TILE_UNITS
        wanted: set[tuple[int, int]] = set()
        if scale >= DETAIL_FROM:
            near = visible.adjusted(-unit * 0.5, -unit * 0.5, unit * 0.5, unit * 0.5)
            for i in range(math.floor(near.left() / unit), math.floor(near.right() / unit) + 1):
                for j in range(math.floor(near.top() / unit), math.floor(near.bottom() / unit) + 1):
                    if (i, j) in self.known:
                        wanted.add((i, j))
        for key in wanted - self.tiles.keys():
            path = map_art.world_tile(*key)
            pixmap = QPixmap(str(path)) if path else QPixmap()
            if pixmap.isNull():
                self.known.discard(key)
                continue
            item = self.scene.addPixmap(pixmap)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setScale(1 / map_art.TILE_PX)
            margin = map_art.TILE_MARGIN / map_art.TILE_PX
            item.setPos(key[0] * unit - margin, key[1] * unit - margin)
            item.setZValue(Z_TILES)
            self.tiles[key] = item
        keep = visible.adjusted(-unit * KEEP, -unit * KEEP, unit * KEEP, unit * KEEP)
        for key in [k for k in self.tiles if k not in wanted]:
            i, j = key
            if scale < DETAIL_FROM or not keep.intersects(QRectF(i * unit, j * unit, unit, unit)):
                self.scene.removeItem(self.tiles.pop(key))
        for map_id, item in self.cities.items():
            target = 1.0 if map_id == zone else 0.0
            step = dt / CITY_FADE if dt > 0 else 1.0
            now = item.opacity()
            alpha = target if abs(now - target) <= step else now + math.copysign(step, target - now)
            item.setOpacity(clamp(alpha))
            item.setVisible(alpha > 0.003)
