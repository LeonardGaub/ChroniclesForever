"""Bakes the terrain of the local WoW Forever install into the data pack of the cinematic's 3D map
(docs/3D_Map_Viewer.md): per tile the heights and the minimap picture, per continent a small overview, and the
map tables that place route points on the terrain.

    desktop\\.venv\\Scripts\\python tools\\build_terrain.py [--continents kalimdor,azeroth] [--out FOLDER]
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
# The continents' worlds (Map.db2 ID) and their WDT files.
CONTINENTS = {"kalimdor": (1, 782779), "azeroth": (0, 775971)}

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


def bake_continent(storage: casc.Casc, name: str, wdt: int, out: Path) -> dict:
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    ids = tile_ids(storage, wdt)
    over_h = np.full((64, 64, 17, 17), np.nan, np.float16)
    overview = Image.new("RGB", (64 * OVERVIEW_PX, 64 * OVERVIEW_PX))
    tiles, changed, started = [], 0, time.time()
    present = [(ty, tx) for ty in range(64) for tx in range(64) if ids[ty, tx, ROOT_ADT]]
    for n, (ty, tx) in enumerate(present, 1):
        h = tile_heights(storage.read_fdid(int(ids[ty, tx, ROOT_ADT])))
        data, low, high = encode_heights(h)
        changed += write_if_changed(folder / f"h_{tx}_{ty}.bin", data)
        over_h[ty, tx] = h[::OVERVIEW_STEP, ::OVERVIEW_STEP]
        if ids[ty, tx, MINIMAP]:
            pic = Image.open(io.BytesIO(storage.read_fdid(int(ids[ty, tx, MINIMAP])))).convert("RGB")
            buf = io.BytesIO()
            pic.save(buf, "JPEG", quality=85)
            changed += write_if_changed(folder / f"m_{tx}_{ty}.jpg", buf.getvalue())
            overview.paste(pic.resize((OVERVIEW_PX, OVERVIEW_PX), Image.LANCZOS), (tx * OVERVIEW_PX, ty * OVERVIEW_PX))
        tiles.append([tx, ty, round(low, 1), round(high, 1)])
        if n % 100 == 0:
            print(f"  {name}: {n}/{len(present)} tiles, {time.time() - started:.0f} s", flush=True)
    buf = io.BytesIO()
    overview.save(buf, "JPEG", quality=88)
    changed += write_if_changed(folder / "overview.jpg", buf.getvalue())
    changed += write_if_changed(folder / "overview_h.bin", b"FCO1" + zlib.compress(over_h.astype("<f2").tobytes(), 9))
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
    offsets, scales = shared_offsets(ui_maps, [m for m, _ in CONTINENTS.values()])
    index["shared_scale"] = scales
    for name in args.continents.split(","):
        world, wdt = CONTINENTS[name]
        continents[name] = {"map_id": world, "offset": offsets.get(world, [0.0, 0.0]),
                            **bake_continent(storage, name, wdt, args.out)}
    for name, c in continents.items():
        c["offset"] = offsets.get(c["map_id"], c["offset"])
    write_if_changed(index_path, json.dumps(index, separators=(",", ":")).encode("utf-8"))
    print(f"shared world: {scales}")
    total = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"{args.out}: {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
