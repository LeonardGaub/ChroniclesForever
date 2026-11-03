"""Bakes the terrain of the local WoW Forever install into the data pack of the cinematic's 3D map
(docs/3D_Map_Viewer.md): per tile the heights and the minimap picture, per continent a small overview, and the
map tables that place route points on the terrain.

    desktop\\.venv\\Scripts\\python tools\\build_terrain.py [--continents kalimdor,azeroth,zephras] [--out FOLDER]
                                                         [--install WOW_FOLDER]

Default output: desktop/forever_chronicle/terrain/. Reads only the game files (forever_chronicle/wow/casc.py) and
their map tables (tools/db2.py); nothing in the game folder is changed. Files whose content did not change are
left alone, so a rebuild after a client patch only touches the tiles the patch changed.

Pack layout (format 1, read by forever_chronicle/domain/terrain.py):
- index.json: format, client build, per continent its tiles (with height range) and offset in the shared world,
  per uiMapID its UiMapAssignment rows (map uv -> world yards).
- <continent>/h_<tx>_<ty>.bin: "FCH1", grid size (uint16), 0, base height (float32), then zlib of grid x grid
  uint16 heights in 0.1 yd over the base. Rows run north to south, columns west to east (the tile's outer
  MCVT vertices, 129 x 129).
- <continent>/m_<tx>_<ty>.jpg: the tile's minimap picture, as the client has it (512 px).
- <continent>/overview.jpg: all tiles at OVERVIEW_PX each, in the 64 x 64 tile grid (missing tiles black).
- <continent>/overview_h.bin: "FCO1", then zlib of 64 x 64 x 17 x 17 float16 heights (every 8th vertex; NaN where
  no tile is).
- <continent>/w_<tx>_<ty>.bin, only for tiles with liquids: "FCW1", then zlib of 129 x 129 float16 surface heights
  (NaN where no liquid) and 128 x 128 uint8 liquid kinds per cell (0 none, 1 water, 2 ocean, 3 magma, 4 slime),
  from the root ADT's MH2O (the first layer of a chunk).
- <continent>/overview_w.bin: "FCV1", then zlib of 64 x 64 x 17 x 17 float16 liquid heights (NaN where none) and
  64 x 64 x 16 x 16 uint8 kinds, for the far view.
Worlds that the world map does not show (Zephras Isle) are placed far from the continents in the shared world.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "tools")]
from db2 import UI_MAP_ASSIGNMENT, find_install, open_install, table  # noqa: E402
from forever_chronicle.wow import casc  # noqa: E402

FORMAT = 1
TILE_YARDS = 1600 / 3
GRID = 129                       # outer vertices per tile side (16 chunks x 8 + 1)
OVERVIEW_PX = 32
OVERVIEW_STEP = 8                # every 8th vertex: 17 x 17 per tile
HEIGHT_STEP = 0.1
WORLD_MAP, WORLD_W, WORLD_H = 947, 1002, 668
MAP_DB2, LIQUID_TYPE = 1349477, 1371380   # Map: [21] WdtFileDataID; LiquidType: [3] SoundBank (water, ocean, ...)
# The worlds (Map.db2 ID) baked by default.
CONTINENTS = {"kalimdor": 1, "azeroth": 0, "zephras": 2991}
APART = 60000.0            # yards between a world the world map does not show and the continents

# MAID: eight fileDataIDs per tile.
ROOT_ADT, MINIMAP = 0, 7


def chunks(data: bytes):
    """(tag, payload) of the chunks in a WoW chunked file (tags are stored reversed)."""
    i = 0
    while i + 8 <= len(data):
        size = struct.unpack_from("<I", data, i + 4)[0]
        yield data[i:i + 4][::-1].decode("latin1"), data[i + 8:i + 8 + size]
        i += 8 + size


def tile_ids(storage: casc.Casc, wdt_fdid: int) -> np.ndarray:
    """MAID as [ty, tx, kind]."""
    maid = dict(chunks(storage.read_fdid(wdt_fdid)))["MAID"]
    return np.frombuffer(maid, "<u4").reshape(64, 64, 8)


def tile_heights(adt: bytes) -> np.ndarray:
    """The tile's outer vertex heights (GRID x GRID, world z in yards)."""
    out = np.zeros((GRID, GRID), np.float32)
    for tag, d in chunks(adt):
        if tag != "MCNK":
            continue
        ix, iy = struct.unpack_from("<II", d, 4)
        base_z = struct.unpack_from("<f", d, 0x68 + 8)[0]
        mcvt = dict(chunks(d[128:])).get("MCVT")
        if mcvt is None:
            continue
        v = np.frombuffer(mcvt, "<f4")
        outer = np.stack([v[r * 17:r * 17 + 9] for r in range(9)]) + base_z
        out[iy * 8:iy * 8 + 9, ix * 8:ix * 8 + 9] = outer
    return out


def liquid_kinds(storage: casc.Casc) -> dict[int, int]:
    """LiquidType ID -> kind (1 water, 2 ocean, 3 magma, 4 slime) from its SoundBank."""
    return {r["id"]: min(4, max(0, r["fields"][3]) + 1) for r in table(storage, LIQUID_TYPE)}


def tile_liquids(adt: bytes, kinds: dict[int, int]) -> tuple[np.ndarray, np.ndarray] | None:
    """The tile's liquid surface (GRID x GRID heights, NaN where none) and kind per cell (128 x 128), from MH2O.
    The vertex format comes from the size of each instance's vertex block (1 byte a vertex: depth only, the
    surface flat at the instance's height; 5: height + depth; 8: height + uv; 9: height + uv + depth)."""
    d = dict(chunks(adt)).get("MH2O")
    if not d:
        return None
    instances, offsets = [], {len(d)}
    for i in range(256):
        oi, layers, oa = struct.unpack_from("<III", d, i * 12)
        offsets.update(o for o in (oi, oa) if o)
        if layers:
            lt, _obj, low, _high, xo, yo, w, h, oe, ov = struct.unpack_from("<HHffBBBBII", d, oi)
            offsets.update(o for o in (oe, ov) if o)
            instances.append((i, lt, low, xo, yo, w, h, oe, ov))
    if not instances:
        return None
    offsets = sorted(offsets)
    heights = np.full((GRID, GRID), np.nan, np.float32)
    cells = np.zeros((GRID - 1, GRID - 1), np.uint8)
    for i, lt, low, xo, yo, w, h, oe, ov in instances:
        if w == 0 or h == 0 or xo + w > 8 or yo + h > 8:
            continue
        iy, ix = divmod(i, 16)
        verts = (w + 1) * (h + 1)
        surface = np.full((h + 1, w + 1), low, np.float32)
        if ov:
            size = next(o for o in offsets if o > ov) - ov
            if size >= 4 * verts and size // verts in (5, 8, 9):
                surface = np.frombuffer(d, "<f4", verts, ov).reshape(h + 1, w + 1).copy()
        exists = np.ones((h, w), bool)
        if oe:
            bits = np.unpackbits(np.frombuffer(d, np.uint8, (w * h + 7) // 8, oe), bitorder="little")
            exists = bits[:w * h].reshape(h, w).astype(bool)
        r0, c0 = iy * 8 + yo, ix * 8 + xo
        block = cells[r0:r0 + h, c0:c0 + w]
        block[exists & (block == 0)] = kinds.get(lt, 1)
        here = heights[r0:r0 + h + 1, c0:c0 + w + 1]
        heights[r0:r0 + h + 1, c0:c0 + w + 1] = np.where(np.isnan(here), surface, here)
    # a vertex counts only if a liquid cell touches it
    touched = np.zeros((GRID, GRID), bool)
    wet = cells > 0
    for dr in (0, 1):
        for dc in (0, 1):
            touched[dr:dr + GRID - 1, dc:dc + GRID - 1] |= wet
    heights[~touched] = np.nan
    return (heights, cells) if wet.any() else None


def encode_liquids(heights: np.ndarray, cells: np.ndarray) -> bytes:
    return b"FCW1" + zlib.compress(heights.astype("<f2").tobytes() + cells.astype(np.uint8).tobytes(), 9)


def coarse_liquids(heights: np.ndarray, cells: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """17 x 17 surface heights and 16 x 16 kinds of a tile's liquids for the far view: a coarse cell is wet when
    most of its 8 x 8 fine cells are."""
    blocks = cells.reshape(16, 8, 16, 8).transpose(0, 2, 1, 3).reshape(16, 16, 64)
    kind = np.zeros((16, 16), np.uint8)
    for k in (1, 2, 3, 4):
        kind[((blocks == k).sum(-1) > 32) & (kind == 0)] = k
    with np.errstate(all="ignore"):
        win = np.full((17, 17), np.nan, np.float32)
        for r in range(17):
            for c in range(17):
                patch = heights[max(0, r * 8 - 4):r * 8 + 5, max(0, c * 8 - 4):c * 8 + 5]
                if np.isfinite(patch).any():
                    win[r, c] = np.nanmean(patch)
    touched = np.zeros((17, 17), bool)
    for dr in (0, 1):
        for dc in (0, 1):
            touched[dr:dr + 16, dc:dc + 16] |= kind > 0
    win[~touched] = np.nan
    return win, kind


def encode_heights(h: np.ndarray) -> tuple[bytes, float, float]:
    base = float(np.floor(h.min()))
    q = np.round((h - base) / HEIGHT_STEP)
    if q.max() > 65535:
        raise ValueError(f"height range {h.max() - base:.0f} yd too large for one tile")
    data = b"FCH1" + struct.pack("<HHf", GRID, 0, base) + zlib.compress(q.astype("<u2").tobytes(), 9)
    return data, base, float(h.max())


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and hashlib.sha1(path.read_bytes()).digest() == hashlib.sha1(data).digest():
        return False
    casc.write_atomic(path, data)
    return True


def assignments(storage: casc.Casc) -> dict[int, list[list[float]]]:
    """Per uiMapID its UiMapAssignment rows: [u0, v0, u1, v1, x0, y0, x1, y1, map_id, order] (world yards)."""
    real = lambda bits: struct.unpack("<f", struct.pack("<I", bits))[0]  # noqa: E731
    out: dict[int, list] = {}
    for r in table(storage, UI_MAP_ASSIGNMENT):   # UiMin[2], UiMax[2], Region[6], ID, UiMapID, OrderIndex, MapID
        f = r["fields"]
        (u0, v0), (u1, v1) = [real(v) for v in f[0]], [real(v) for v in f[1]]
        x0, y0, _, x1, y1, _ = [real(v) for v in f[2]]
        if u1 <= u0 or v1 <= v0 or x1 <= x0 or y1 <= y0:
            continue
        out.setdefault(f[4], []).append([round(u0, 6), round(v0, 6), round(u1, 6), round(v1, 6),
                                         round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3), f[6], f[5]])
    for rows in out.values():
        rows.sort(key=lambda a: a[9])
    return out


def shared_offsets(ui_maps: dict, worlds: list[int]) -> tuple[dict[int, list[float]], dict[int, tuple]]:
    """Each world's offset (east, north) in the shared 3D world, in true yards: placed so that its middle lands
    where the world map 947 shows it, at one common scale (yards per world map pixel, the mean of the worlds').
    Also returns each world's own scale (yards per world map pixel, across and down) to see how common it is."""
    rows = {a[8]: a for a in ui_maps.get(WORLD_MAP, [])}
    scales, k = {}, []
    for m in worlds:
        if m not in rows:
            continue
        u0, v0, u1, v1, x0, y0, x1, y1, *_ = rows[m]
        scales[m] = ((y1 - y0) / ((u1 - u0) * WORLD_W), (x1 - x0) / ((v1 - v0) * WORLD_H))
        k.extend(scales[m])
    k = sum(k) / len(k) if k else 1.0
    out = {}
    for m, (u0, v0, u1, v1, x0, y0, x1, y1, *_) in ((m, rows[m]) for m in scales):
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
        u = u0 + (u1 - u0) * (y1 - yc) / (y1 - y0)
        v = v0 + (v1 - v0) * (x1 - xc) / (x1 - x0)
        east, north = u * WORLD_W * k, -v * WORLD_H * k
        out[m] = [round(east - (-yc), 3), round(north - xc, 3)]
    return out, {"yards_per_px": k, **{str(m): s for m, s in scales.items()}}


def wdt_ids(storage: casc.Casc) -> dict[int, int]:
    """Map ID -> its WDT's fileDataID (Map.db2)."""
    return {r["id"]: r["fields"][21] for r in table(storage, MAP_DB2) if r["fields"][21]}


def bake_continent(storage: casc.Casc, name: str, wdt: int, out: Path, kinds: dict[int, int]) -> dict:
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    ids = tile_ids(storage, wdt)
    over_h = np.full((64, 64, 17, 17), np.nan, np.float16)
    over_wh = np.full((64, 64, 17, 17), np.nan, np.float16)
    over_wk = np.zeros((64, 64, 16, 16), np.uint8)
    overview = Image.new("RGB", (64 * OVERVIEW_PX, 64 * OVERVIEW_PX))
    tiles, changed, started = [], 0, time.time()
    present = [(ty, tx) for ty in range(64) for tx in range(64) if ids[ty, tx, ROOT_ADT]]
    for n, (ty, tx) in enumerate(present, 1):
        adt = storage.read_fdid(int(ids[ty, tx, ROOT_ADT]))
        h = tile_heights(adt)
        data, low, high = encode_heights(h)
        changed += write_if_changed(folder / f"h_{tx}_{ty}.bin", data)
        over_h[ty, tx] = h[::OVERVIEW_STEP, ::OVERVIEW_STEP]
        liquids = tile_liquids(adt, kinds)
        water = folder / f"w_{tx}_{ty}.bin"
        if liquids is not None:
            changed += write_if_changed(water, encode_liquids(*liquids))
            over_wh[ty, tx], over_wk[ty, tx] = coarse_liquids(*liquids)
        elif water.exists():
            water.unlink()
            changed += 1
        if ids[ty, tx, MINIMAP]:
            pic = Image.open(io.BytesIO(storage.read_fdid(int(ids[ty, tx, MINIMAP])))).convert("RGB")
            buf = io.BytesIO()
            pic.save(buf, "JPEG", quality=85)
            changed += write_if_changed(folder / f"m_{tx}_{ty}.jpg", buf.getvalue())
            overview.paste(pic.resize((OVERVIEW_PX, OVERVIEW_PX), Image.LANCZOS), (tx * OVERVIEW_PX, ty * OVERVIEW_PX))
        tiles.append([tx, ty, round(low, 1), round(high, 1), int(liquids is not None)])
        if n % 100 == 0:
            print(f"  {name}: {n}/{len(present)} tiles, {time.time() - started:.0f} s", flush=True)
    buf = io.BytesIO()
    overview.save(buf, "JPEG", quality=88)
    changed += write_if_changed(folder / "overview.jpg", buf.getvalue())
    changed += write_if_changed(folder / "overview_h.bin", b"FCO1" + zlib.compress(over_h.astype("<f2").tobytes(), 9))
    changed += write_if_changed(folder / "overview_w.bin", b"FCV1" + zlib.compress(
        over_wh.astype("<f2").tobytes() + over_wk.tobytes(), 9))
    print(f"  {name}: {len(tiles)} tiles, {changed} files written, {time.time() - started:.0f} s")
    return {"tiles": tiles}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "desktop" / "forever_chronicle" / "terrain")
    ap.add_argument("--continents", default=",".join(CONTINENTS))
    ap.add_argument("--install", type=Path, help="the World of Warcraft folder (default: found automatically)")
    args = ap.parse_args()
    install = find_install(args.install)
    storage = open_install(install)
    ui_maps = assignments(storage)
    index_path = args.out / "index.json"
    index = json.loads(index_path.read_text("utf-8")) if index_path.exists() else {}
    if index.get("format") != FORMAT:
        index = {}
    index["format"] = FORMAT
    index["build"] = storage.build.get("Version")
    index["tile_yards"] = TILE_YARDS
    index["grid"] = GRID
    index["ui_maps"] = {str(k): v for k, v in sorted(ui_maps.items())}
    continents = index.setdefault("continents", {})
    offsets, scales = shared_offsets(ui_maps, list(CONTINENTS.values()))
    apart = [m for m in CONTINENTS.values() if m not in offsets]
    for i, m in enumerate(apart, 1):
        offsets[m] = [APART * i, APART]
    index["shared_scale"] = scales
    wdts, kinds = wdt_ids(storage), liquid_kinds(storage)
    for name in args.continents.split(","):
        world = CONTINENTS[name]
        continents[name] = {"map_id": world, "offset": offsets[world],
                            **bake_continent(storage, name, wdts[world], args.out, kinds)}
    for name, c in continents.items():
        c["offset"] = offsets.get(c["map_id"], c["offset"])
    write_if_changed(index_path, json.dumps(index, separators=(",", ":")).encode("utf-8"))
    print(f"shared world: {scales}")
    total = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"{args.out}: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
