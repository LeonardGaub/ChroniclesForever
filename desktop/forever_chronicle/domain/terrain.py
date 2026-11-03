"""The terrain pack of the cinematic's 3D map (written by tools/build_terrain.py, docs/3D_Map_Viewer.md): where a
route point lies in the world and how high the ground is there.

Coordinates, from the addon's record to the 3D world:
- map position: a uiMapID with x, y across its map (0..1), as the addon records it;
- world position: a world (Map.db2 ID: 1 Kalimdor, 0 Eastern Kingdoms) with the game's yards x (north), y (west),
  through the map's UiMapAssignment rows, as C_Map.GetWorldPosFromMapPos does;
- shared position: east, north in yards in one 3D world holding both continents, each moved by its offset so the
  layout matches the world map 947 (true yards inside a continent; the oceans between them follow the world map).

Tiles: a world is 64 x 64 tiles of 533 1/3 yd; tile (tx, ty) is column tx (from the west) and row ty (from the
north). A tile's heights are a 129 x 129 grid, rows north to south, columns west to east. Liquids (lakes, rivers,
the sea along the coasts, lava) come from the game per tile; off the tiles is open sea at sea level.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

FORMAT = 1
TILE_YARDS = 1600 / 3
HEIGHT_STEP = 0.1
SEA_LEVEL = 0.0
WORLD_MAP = 947
NONE, WATER, OCEAN, MAGMA, SLIME = 0, 1, 2, 3, 4      # liquid kinds per cell


def pack_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "terrain"


@dataclass(frozen=True)
class Continent:
    name: str
    map_id: int
    offset: tuple[float, float]                      # east, north added to true yards
    tiles: dict[tuple[int, int], tuple[float, float]]  # (tx, ty) -> (lowest, highest) ground
    wet: frozenset = frozenset()                       # tiles with liquids
    floors: frozenset = frozenset()                    # tiles under buildings (their floors)
    roofs: frozenset = frozenset()                     # the same tiles (their roofs)


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


def decode_liquids(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """(129 x 129 surface heights, NaN where dry; 128 x 128 kinds per cell)."""
    if data[:4] != b"FCW1":
        raise ValueError("not a terrain liquid file")
    raw = zlib.decompress(data[4:])
    n = 129 * 129 * 2
    heights = np.frombuffer(raw[:n], "<f2").reshape(129, 129).astype(np.float32)
    return heights, np.frombuffer(raw[n:], np.uint8).reshape(128, 128)


def sample_floor(grid: np.ndarray, col: np.ndarray, row: np.ndarray) -> np.ndarray:
    """Floor heights at grid positions (columns, rows in vertices): between four floor points bilinear, at a
    floor's edge the nearest point's, NaN off the floors (no smearing over the edge of a bridge or a wall)."""
    n = grid.shape[0] - 1
    c0, r0 = np.clip(col.astype(np.int64), 0, n - 1), np.clip(row.astype(np.int64), 0, n - 1)
    a, b = col - c0, row - r0
    q = np.stack([grid[r0, c0], grid[r0, c0 + 1], grid[r0 + 1, c0], grid[r0 + 1, c0 + 1]])
    w = np.stack([(1 - a) * (1 - b), a * (1 - b), (1 - a) * b, a * b])
    full = np.isfinite(q).all(axis=0)
    blend = (np.nan_to_num(q) * w).sum(axis=0)
    nearest = q[np.argmax(w, axis=0), np.arange(q.shape[1])]
    return np.where(full, blend, nearest)


def decode_mesh(data: bytes):
    """A building mesh file (tools/wmo.py encode_mesh): positions (model space), normals, shade (0..1), triangle
    indices, texture coordinates and the batches (first index, index count, texture fileDataID, blend mode)."""
    if data[:4] != b"FCB2":
        raise ValueError("not a building mesh file (format 2)")
    low, size = np.array(struct.unpack_from("<3f", data, 4)), np.array(struct.unpack_from("<3f", data, 16))
    n, m, nb = struct.unpack_from("<III", data, 28)
    raw = zlib.decompress(data[40:])
    pos = np.frombuffer(raw, "<u2", 3 * n).reshape(n, 3).astype(np.float32) / 65535 * size + low
    at = 6 * n
    nrm = np.frombuffer(raw, np.int8, 3 * n, at).reshape(n, 3).astype(np.float32) / 127
    shade = np.frombuffer(raw, np.uint8, n, at + 3 * n).astype(np.float32) / 255
    uv = np.frombuffer(raw, "<f2", 2 * n, at + 4 * n).reshape(n, 2).astype(np.float32)
    at += 8 * n
    wide = n >= 65536
    idx = np.frombuffer(raw, "<u4" if wide else "<u2", m, at).astype(np.uint32)
    at += m * (4 if wide else 2)
    batches = np.frombuffer(raw, "<u4", 4 * nb, at).reshape(nb, 4).astype(np.int64)
    return pos.astype(np.float32), nrm, shade, idx, uv, batches


@dataclass
class Buildings:
    """A world's building placements: mesh fileDataIDs, model -> shared transforms (3 x 3 and shift) and boxes
    (low, high corners) in the shared world."""
    fdids: np.ndarray
    linear: np.ndarray
    shift: np.ndarray
    low: np.ndarray
    high: np.ndarray

    def __init__(self, rows: list, offset: tuple[float, float]):
        a = np.array(rows, np.float64).reshape(-1, 19)
        move = np.array([offset[0], offset[1], 0.0])
        self.fdids = a[:, 0].astype(np.int64)
        self.linear = a[:, 1:10].reshape(-1, 3, 3)
        self.shift = a[:, 10:13] + move
        self.low, self.high = a[:, 13:16] + move, a[:, 16:19] + move

    def __len__(self) -> int:
        return len(self.fdids)

    def near(self, east: float, north: float, reach: float, big: float = 0.0, big_reach: float = 0.0) -> np.ndarray:
        """Indices of the buildings whose box comes within reach of (east, north); those at least big yards across
        also from big_reach."""
        dx = np.maximum(0, np.maximum(self.low[:, 0] - east, east - self.high[:, 0]))
        dy = np.maximum(0, np.maximum(self.low[:, 1] - north, north - self.high[:, 1]))
        d = np.hypot(dx, dy)
        size = np.maximum(self.high[:, 0] - self.low[:, 0], self.high[:, 1] - self.low[:, 1])
        return np.nonzero((d <= reach) | ((size >= big) & (d <= big_reach) if big else False))[0]


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
            wet = frozenset((t[0], t[1]) for t in c["tiles"] if len(t) > 4 and t[4])
            floors = frozenset(tuple(f) for f in c.get("floors", ()))
            roofs = frozenset(tuple(f) for f in c.get("roofs", ()))
            self.continents[c["map_id"]] = Continent(name, c["map_id"], tuple(c["offset"]), tiles, wet, floors,
                                                     roofs)
        self._heights = lru_cache(maxsize=96)(self._load_heights)
        self._liquids = lru_cache(maxsize=96)(self._load_liquids)
        self._floors = lru_cache(maxsize=96)(self._load_floors)
        self._roofs = lru_cache(maxsize=96)(lambda w, x, y: self._load_floors(w, x, y, "r"))
        self._buildings: dict[int, Buildings] = {}

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

    def sky_island(self, world: int) -> bool:
        """True for a world the world map does not show (Forever's islands in the sky)."""
        rows = self.ui_maps.get(WORLD_MAP)
        return bool(rows) and all(row[8] != world for row in rows)

    def unshared(self, world: int, east: float, north: float) -> tuple[float, float]:
        c = self.continents[world]
        return north - c.offset[1], -(east - c.offset[0])

    def map_to_shared(self, ui_map: int, x: float, y: float) -> tuple[float, float] | None:
        """Any position on a map (world map 947, a continent, a zone) in the shared world, also between its
        rectangles: there it is carried on from the nearest one (the sea between the continents on the world
        map, crossed by boats and teleports). None for a map without UiMapAssignment rows or worlds."""
        rows = [r for r in self.ui_maps.get(ui_map, ()) if int(r[8]) in self.continents]
        if not rows:
            return None
        inside = next((r for r in rows if r[0] - 1e-6 <= x <= r[2] + 1e-6 and r[1] - 1e-6 <= y <= r[3] + 1e-6), None)
        row = inside or min(rows, key=lambda r: math.hypot(max(r[0] - x, 0, x - r[2]), max(r[1] - y, 0, y - r[3])))
        u0, v0, u1, v1, x0, y0, x1, y1, world, _ = row
        wx = x1 - (y - v0) / (v1 - v0) * (x1 - x0)
        wy = y1 - (x - u0) / (u1 - u0) * (y1 - y0)
        return self.shared(int(world), wx, wy)

    def place(self, ui_map: int, x: float, y: float) -> tuple[float, float, float] | None:
        """A map position in the shared world: (east, north, height of what the player stands or swims on)."""
        pos = self.world_pos(ui_map, x, y)
        if pos is None or pos[0] not in self.continents:
            return None
        east, north = self.shared(*pos)
        return east, north, self.surface_at(*pos)

    # -- heights --------------------------------------------------------------------------------------------

    def tile_path(self, world: int, kind: str, tx: int, ty: int) -> Path:
        return self.root / self.continents[world].name / f"{kind}_{tx}_{ty}.{'bin' if kind == 'h' else 'jpg'}"

    def _load_heights(self, world: int, tx: int, ty: int) -> np.ndarray | None:
        c = self.continents.get(world)
        if c is None or (tx, ty) not in c.tiles:
            return None
        return decode_heights(self.tile_path(world, "h", tx, ty).read_bytes())

    def _load_liquids(self, world: int, tx: int, ty: int) -> tuple[np.ndarray, np.ndarray] | None:
        c = self.continents.get(world)
        if c is None or (tx, ty) not in c.wet:
            return None
        return decode_liquids((self.root / c.name / f"w_{tx}_{ty}.bin").read_bytes())

    def liquids(self, world: int, tx: int, ty: int) -> tuple[np.ndarray, np.ndarray] | None:
        return self._liquids(world, tx, ty)

    def _load_floors(self, world: int, tx: int, ty: int, kind: str = "f") -> np.ndarray | None:
        c = self.continents.get(world)
        if c is None or (tx, ty) not in (c.floors if kind == "f" else c.roofs):
            return None
        data = (self.root / c.name / f"{kind}_{tx}_{ty}.bin").read_bytes()
        if data[:4] != b"FCF1":
            raise ValueError("not a terrain floor file")
        return np.frombuffer(zlib.decompress(data[4:]), "<f2").reshape(129, 129).astype(np.float32)

    def floors(self, world: int, tx: int, ty: int) -> np.ndarray | None:
        """The tile's building floors (129 x 129 heights, NaN where no building is), None without any."""
        return self._floors(world, tx, ty)

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

    def water_at(self, world: int, wx: float, wy: float) -> float | None:
        """The liquid surface at a world position, None where dry (sea level off the tiles)."""
        tx, ty, fx, fy = tile_of(wx, wy)
        c = self.continents.get(world)
        if c is not None and (tx, ty) not in c.tiles:
            return SEA_LEVEL
        found = self.liquids(world, tx, ty)
        if found is None:
            return None
        heights, kinds = found
        col, row = min(int(fx * 128), 127), min(int(fy * 128), 127)
        if not kinds[row, col]:
            return None
        corners = heights[row:row + 2, col:col + 2]
        return float(np.nanmean(corners)) if np.isfinite(corners).any() else None

    def surface_at(self, world: int, wx: float, wy: float) -> float:
        """What a player at this spot stands or swims on: a building's floor, else the ground, or a liquid's
        surface above it."""
        tx, ty, fx, fy = tile_of(wx, wy)
        ground = self.height_at(world, wx, wy)
        found = self.floors(world, tx, ty)
        if found is not None:
            level = sample_floor(found, np.array([fx * 128]), np.array([fy * 128]))[0]
            if np.isfinite(level) and level >= ground - 1.0:
                ground = float(level)
        water = self.water_at(world, wx, wy)
        return ground if water is None else max(ground, water)

    def world_at(self, east: float, north: float) -> int | None:
        """The world whose tiles hold a shared position, None over the open sea."""
        for world in self.continents:
            wx, wy = self.unshared(world, east, north)
            tx, ty, _, _ = tile_of(wx, wy)
            if (tx, ty) in self.continents[world].tiles:
                return world
        return None

    def ground_shared(self, east: float, north: float) -> float:
        """The ground under a shared position (sea level over the open sea)."""
        world = self.world_at(east, north)
        return SEA_LEVEL if world is None else self.height_at(world, *self.unshared(world, east, north))

    def surface_shared(self, east: float, north: float) -> float:
        """What a player at a shared position stands or swims on (the sea's surface over the open sea)."""
        world = self.world_at(east, north)
        return SEA_LEVEL if world is None else self.surface_at(world, *self.unshared(world, east, north))

    def surface_many(self, east: np.ndarray, north: np.ndarray, water: bool = True) -> np.ndarray:
        """surface_shared (water=False: ground_shared) for many shared positions at once."""
        east, north = np.asarray(east, np.float64), np.asarray(north, np.float64)
        out = np.full(east.shape, SEA_LEVEL, np.float64)
        for world, c in self.continents.items():
            wx, wy = north - c.offset[1], -(east - c.offset[0])
            fx, fy = 32 - wy / TILE_YARDS, 32 - wx / TILE_YARDS
            tx, ty = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
            keys = tx * 64 + ty
            for key in np.unique(keys):
                tile = (int(key // 64), int(key % 64))
                if tile not in c.tiles:
                    continue
                sel = keys == key
                h = self.heights(world, *tile)
                n = h.shape[0] - 1
                col, row = (fx[sel] - tile[0]) * n, (fy[sel] - tile[1]) * n
                c0 = np.clip(col.astype(np.int64), 0, n - 1)
                r0 = np.clip(row.astype(np.int64), 0, n - 1)
                a, b = col - c0, row - r0
                top = h[r0, c0] * (1 - a) + h[r0, c0 + 1] * a
                bottom = h[r0 + 1, c0] * (1 - a) + h[r0 + 1, c0 + 1] * a
                ground = top * (1 - b) + bottom * b
                if water:
                    found = self.floors(world, *tile)
                    if found is not None:
                        level = sample_floor(found, col, row)
                        ground = np.where(np.isfinite(level) & (level >= ground - 1.0), level, ground)
                    found = self.liquids(world, *tile)
                    if found is not None:
                        lh, kinds = found
                        cc, rr = np.clip((col / n * 128).astype(np.int64), 0, 127), np.clip((row / n * 128).astype(np.int64), 0, 127)
                        wet = kinds[rr, cc] > 0
                        corners = np.stack([lh[rr, cc], lh[rr, cc + 1], lh[rr + 1, cc], lh[rr + 1, cc + 1]])
                        count = np.isfinite(corners).sum(axis=0)
                        level = np.nansum(corners, axis=0) / np.maximum(count, 1)
                        wet &= count > 0
                        ground = np.where(wet, np.maximum(ground, level), ground)
                out[sel] = ground
        return out

    def buildings(self, world: int) -> "Buildings":
        """The buildings placed in a world (empty without the pack's buildings)."""
        if world not in self._buildings:
            path = self.root / self.continents[world].name / "buildings.json"
            rows = json.loads(path.read_text("utf-8"))["placements"] if path.exists() else []
            self._buildings[world] = Buildings(rows, self.continents[world].offset)
        return self._buildings[world]

    def building_mesh(self, fdid: int):
        """A building's mesh (decode_mesh): positions, normals, shade, indices, texture coordinates, batches."""
        return decode_mesh((self.root / "buildings" / f"{fdid}.bin").read_bytes())

    def obstacles_many(self, east: np.ndarray, north: np.ndarray) -> np.ndarray:
        """The highest of the ground and the buildings' roofs at many shared positions: what a line of sight must
        pass over."""
        east, north = np.asarray(east, np.float64), np.asarray(north, np.float64)
        out = self.surface_many(east, north, water=False)
        for world, c in self.continents.items():
            if not c.roofs:
                continue
            wx, wy = north - c.offset[1], -(east - c.offset[0])
            fx, fy = 32 - wy / TILE_YARDS, 32 - wx / TILE_YARDS
            tx, ty = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
            keys = tx * 64 + ty
            for key in np.unique(keys):
                tile = (int(key // 64), int(key % 64))
                if tile not in c.roofs:
                    continue
                sel = keys == key
                level = sample_floor(self._roofs(world, *tile), (fx[sel] - tile[0]) * 128, (fy[sel] - tile[1]) * 128)
                out[sel] = np.where(np.isfinite(level), np.maximum(out[sel], level), out[sel])
        return out

    def overview(self, world: int) -> tuple[np.ndarray, Path]:
        """The continent's far view: 64 x 64 x 17 x 17 heights (NaN off the tiles) and its overview picture."""
        folder = self.root / self.continents[world].name
        data = (folder / "overview_h.bin").read_bytes()
        if data[:4] != b"FCO1":
            raise ValueError("not a terrain overview file")
        h = np.frombuffer(zlib.decompress(data[4:]), "<f2").reshape(64, 64, 17, 17).astype(np.float32)
        return h, folder / "overview.jpg"

    def overview_liquids(self, world: int) -> tuple[np.ndarray, np.ndarray]:
        """The far view's liquids: 64 x 64 x 17 x 17 surface heights (NaN where dry) and 64 x 64 x 16 x 16 kinds."""
        path = self.root / self.continents[world].name / "overview_w.bin"
        if not path.exists():
            return np.full((64, 64, 17, 17), np.nan, np.float32), np.zeros((64, 64, 16, 16), np.uint8)
        data = path.read_bytes()
        if data[:4] != b"FCV1":
            raise ValueError("not a terrain overview liquid file")
        raw = zlib.decompress(data[4:])
        n = 64 * 64 * 17 * 17 * 2
        heights = np.frombuffer(raw[:n], "<f2").reshape(64, 64, 17, 17).astype(np.float32)
        return heights, np.frombuffer(raw[n:], np.uint8).reshape(64, 64, 16, 16)
