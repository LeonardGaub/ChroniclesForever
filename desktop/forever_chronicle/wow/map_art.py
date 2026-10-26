"""Map artwork: ``forever_chronicle/maps/<uiMapID>.jpg``, the one place the app takes map images from.

The images come from the game client itself (tools/extract_maps.py draws each map fully explored, as the game
does) and ship with the code in the private repo.
Rerun the tool after a client patch. Forever reworked several Classic zones, so Classic images do not fit.

The seamless world map (tools/build_world_map.py, from OpenMap's stitched zone art) lies in ``maps/world/``:
a base picture of the whole world and sharp detail tiles where there is land. Its unit is the world unit of
domain/maps.py (a pixel of the world map 947).
"""

from __future__ import annotations

from pathlib import Path

BASE_PX = 4            # pixels per world unit of world/base.jpg
TILE_PX = 16           # ... and of the detail tiles (OpenMap bakes its zones at 16)
TILE_UNITS = 32        # world units a detail tile covers (each way) ...
TILE_MARGIN = 2        # ... plus this many pixels of its neighbours on every side


def maps_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "maps"


def find_art(map_id: int | None) -> Path | None:
    if map_id is None:
        return None
    path = maps_dir() / f"{map_id}.jpg"
    return path if path.is_file() else None


def world_base() -> Path | None:
    path = maps_dir() / "world" / "base.jpg"
    return path if path.is_file() else None


def world_tile(i: int, j: int) -> Path | None:
    path = maps_dir() / "world" / f"{i}_{j}.jpg"
    return path if path.is_file() else None
