"""Music from the game for the cinematic mode: the adventure music (the outdoor themes of some zones, a new one
every few levels) and the music files themselves.

- forever_chronicle/zone_music.json (kept in git, written by tools/extract_zone_music.py): per uiMapID ("zones")
  and per instance map ID ("instances") the fileDataIDs of the day and the night music.
- Adventure music: chapter by chapter (CHAPTER_LEVELS) the day music of the zones in ADVENTURE, in that order;
  after the last theme they start again. Chapters are long in the first levels and get shorter later, where a
  level takes much longer to play.
- The MP3 files come out of the player's own install when needed (extract_missing) into
  %APPDATA%\\ForeverChronicle\\music\\<fileDataID>.mp3. Needs numpy (wow/casc.py); without it, or without the
  game, the cinematic mode plays the built-in theme instead.
"""

from __future__ import annotations

import bisect
import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from ..config import app_home
from .paths import ClientInstall

TABLE = Path(__file__).resolve().parents[1] / "zone_music.json"
# The adventure themes (uiMapIDs whose music plays): Elwynn Forest (forest), Mulgore (plains), Dun Morogh
# (mountains), the Barrens, Stranglethorn Vale (jungle), Ashenvale (night elf forest), Tanaris (desert), Stormwind.
ADVENTURE = (1429, 1412, 1426, 1413, 1434, 1440, 1446, 1453)
# The levels a new chapter (the next theme) begins at: every 7 levels at first, every 3 at the end.
CHAPTER_LEVELS = (1, 8, 15, 21, 27, 32, 37, 41, 45, 49, 52, 55, 58)

_failed: set[int] = set()         # not readable from the game files (this session): not tried again


def cache_dir() -> Path:
    return app_home() / "music"


@lru_cache(maxsize=1)
def table() -> dict:
    try:
        return json.loads(TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"zones": {}, "instances": {}}


def entry(map_id: int | None, instance_id: int | None = None) -> dict | None:
    """The music entry of a dungeon, else of a zone (None: no music of its own)."""
    data = table()
    if instance_id is not None and str(instance_id) in data.get("instances", {}):
        return data["instances"][str(instance_id)]
    if map_id is not None:
        return data.get("zones", {}).get(str(map_id))
    return None


def chapter(level: int | None) -> int:
    """The adventure chapter of a level (0 while the level is unknown)."""
    return max(0, bisect.bisect_right(CHAPTER_LEVELS, level) - 1) if level is not None else 0


def adventure_file_ids(chapter_index: int) -> tuple[int, ...]:
    """The music files of an adventure chapter: the day music of its theme (the themes repeat)."""
    found = entry(ADVENTURE[chapter_index % len(ADVENTURE)])
    return tuple(found["day"]) if found else ()


def find(fdid: int) -> Path | None:
    for suffix in (".mp3", ".ogg"):
        path = cache_dir() / f"{fdid}{suffix}"
        if path.is_file():
            return path
    return None


def paths(fdids: Iterable[int]) -> list[Path]:
    """The files that are there, in the given order."""
    return [p for p in map(find, fdids) if p is not None]


def missing(fdids: Iterable[int]) -> list[int]:
    return [f for f in dict.fromkeys(fdids) if f not in _failed and find(f) is None]


def extract_missing(client: ClientInstall | None, fdids: Iterable[int]) -> int:
    """Takes the music files that are not in the cache yet out of the local game. Returns how many were added.
    Each file is written under a temporary name first, so a player never sees half a file."""
    todo = missing(fdids)
    if not todo or client is None:
        return 0
    from . import casc
    storage = casc.open_client(client)
    if storage is None:  # no numpy, or the game files cannot be read: not tried again this session
        _failed.update(todo)
        return 0
    written = 0
    for fdid in todo:
        try:
            data = storage.read_fdid(fdid)
        except Exception:
            _failed.add(fdid)
            continue
        suffix = ".ogg" if data[:4] == b"OggS" else ".mp3"
        casc.write_atomic(cache_dir() / f"{fdid}{suffix}", data)
        written += 1
    return written
