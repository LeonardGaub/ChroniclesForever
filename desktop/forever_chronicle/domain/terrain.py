"""The terrain pack of the cinematic's 3D map (written by tools/build_terrain.py, docs/3D_Map_Viewer.md): where a
route point lies in the world and how high the ground is there.

Coordinates, from the addon's record to the 3D world:
- map position: a uiMapID with x, y across its map (0..1), as the addon records it;
- world position: a world (Map.db2 ID: 1 Kalimdor, 0 Eastern Kingdoms) with the game's yards x (north), y (west),
  through the map's UiMapAssignment rows, as C_Map.GetWorldPosFromMapPos does;
- shared position: east, north in yards in one 3D world holding both continents, each moved by its offset so the
  layout matches the world map 947 (true yards inside a continent; the oceans between them follow the world map).

Tiles: a world is 64 x 64 tiles of 533 1/3 yd; tile (tx, ty) is column tx (from the west) and row ty (from the
north). A tile's heights are a 129 x 129 grid, rows north to south, columns west to east.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

FORMAT = 1
TILE_YARDS = 1600 / 3
HEIGHT_STEP = 0.1


def pack_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "terrain"


@dataclass(frozen=True)
class Continent:
    name: str
    map_id: int
    offset: tuple[float, float]                      # east, north added to true yards
    tiles: dict[tuple[int, int], tuple[float, float]]  # (tx, ty) -> (lowest, highest) ground


def tile_of(wx: float, wy: float) -> tuple[int, int, float, float]:
    """The tile under a world position and where in it (0..1 east, 0..1 south)."""
    fx, fy = 32 - wy / TILE_YARDS, 32 - wx / TILE_YARDS
    tx, ty = int(np.floor(fx)), int(np.floor(fy))
    return tx, ty, fx - tx, fy - ty


def tile_origin(tx: int, ty: int) -> tuple[float, float]:
    """True (east, north) yards of a tile's north-west corner."""
    return (tx - 32) * TILE_YARDS, (32 - ty) * TILE_YARDS


def decode_heights(data: bytes) -> np.ndarray:
    if data[:4] != b"FCH1":
        raise ValueError("not a terrain height file")
    grid, _, base = struct.unpack_from("<HHf", data, 4)
    q = np.frombuffer(zlib.decompress(data[12:]), "<u2").reshape(grid, grid)
    return q.astype(np.float32) * HEIGHT_STEP + base


def map_to_world(rows: list[list[float]], x: float, y: float) -> tuple[int, float, float] | None:
    """A map position through its UiMapAssignment rows (the first whose UI rectangle holds it)."""
    for u0, v0, u1, v1, x0, y0, x1, y1, world, _order in rows:
        if u0 - 1e-6 <= x <= u1 + 1e-6 and v0 - 1e-6 <= y <= v1 + 1e-6:
            return int(world), x1 - (y - v0) / (v1 - v0) * (x1 - x0), y1 - (x - u0) / (u1 - u0) * (y1 - y0)
    return None


class TerrainPack:
    def __init__(self, root: Path | None = None):
        self.root = root or pack_dir()
        index = json.loads((self.root / "index.json").read_text("utf-8"))
        if index.get("format") != FORMAT:
            raise ValueError(f"terrain pack format {index.get('format')}, expected {FORMAT}")
        self.build = index.get("build")
        self.ui_maps = {int(k): v for k, v in index["ui_maps"].items()}
        self.continents: dict[int, Continent] = {}
        for name, c in index["continents"].items():
            tiles = {(t[0], t[1]): (t[2], t[3]) for t in c["tiles"]}
            self.continents[c["map_id"]] = Continent(name, c["map_id"], tuple(c["offset"]), tiles)
        self._heights = lru_cache(maxsize=96)(self._load_heights)

    @classmethod
    def available(cls, root: Path | None = None) -> bool:
        return ((root or pack_dir()) / "index.json").exists()

    # -- coordinates ----------------------------------------------------------------------------------------

    def world_pos(self, ui_map: int, x: float, y: float) -> tuple[int, float, float] | None:
        rows = self.ui_maps.get(ui_map)
        return map_to_world(rows, x, y) if rows else None

    def shared(self, world: int, wx: float, wy: float) -> tuple[float, float] | None:
        c = self.continents.get(world)
        if c is None:
            return None
        return -wy + c.offset[0], wx + c.offset[1]

    def unshared(self, world: int, east: float, north: float) -> tuple[float, float]:
        c = self.continents[world]
        return north - c.offset[1], -(east - c.offset[0])

    def place(self, ui_map: int, x: float, y: float) -> tuple[float, float, float] | None:
        """A map position in the shared world: (east, north, ground height)."""
        pos = self.world_pos(ui_map, x, y)
        if pos is None or pos[0] not in self.continents:
            return None
        east, north = self.shared(*pos)
        return east, north, self.height_at(*pos)

    # -- heights --------------------------------------------------------------------------------------------

    def tile_path(self, world: int, kind: str, tx: int, ty: int) -> Path:
        return self.root / self.continents[world].name / f"{kind}_{tx}_{ty}.{'bin' if kind == 'h' else 'jpg'}"

    def _load_heights(self, world: int, tx: int, ty: int) -> np.ndarray | None:
        c = self.continents.get(world)
        if c is None or (tx, ty) not in c.tiles:
            return None
        return decode_heights(self.tile_path(world, "h", tx, ty).read_bytes())

    def heights(self, world: int, tx: int, ty: int) -> np.ndarray | None:
        return self._heights(world, tx, ty)

    def height_at(self, world: int, wx: float, wy: float) -> float:
        """Ground height at a world position, bilinear between the grid's vertices; 0 (sea level) off the tiles."""
        tx, ty, fx, fy = tile_of(wx, wy)
        h = self.heights(world, tx, ty)
        if h is None:
            return 0.0
        n = h.shape[0] - 1
        c, r = fx * n, fy * n
        c0, r0 = min(int(c), n - 1), min(int(r), n - 1)
        a, b = c - c0, r - r0
        top = h[r0, c0] * (1 - a) + h[r0, c0 + 1] * a
        bottom = h[r0 + 1, c0] * (1 - a) + h[r0 + 1, c0 + 1] * a
        return float(top * (1 - b) + bottom * b)

    def overview(self, world: int) -> tuple[np.ndarray, Path]:
        """The continent's far view: 64 x 64 x 17 x 17 heights (NaN off the tiles) and its overview picture."""
        folder = self.root / self.continents[world].name
        data = (folder / "overview_h.bin").read_bytes()
        if data[:4] != b"FCO1":
            raise ValueError("not a terrain overview file")
        h = np.frombuffer(zlib.decompress(data[4:]), "<f2").reshape(64, 64, 17, 17).astype(np.float32)
        return h, folder / "overview.jpg"
