"""Map artwork: ``forever_chronicle/maps/<uiMapID>.jpg``, the one place the app takes map images from.

The images come from the game client itself (tools/extract_maps.py draws each map fully explored, as the game
does) and ship with the code: in the private repo and in the friend package (tools/package_for_friend.py).
Rerun the tool after a client patch. Forever reworked several Classic zones, so Classic images do not fit.
"""

from __future__ import annotations

from pathlib import Path


def maps_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "maps"


def find_art(map_id: int | None) -> Path | None:
    if map_id is None:
        return None
    path = maps_dir() / f"{map_id}.jpg"
    return path if path.is_file() else None
