"""Zone music from the game: which music files the game plays in a zone or dungeon, and the files themselves.

- forever_chronicle/zone_music.json (kept in git, written by tools/extract_zone_music.py): per uiMapID ("zones")
  and per instance map ID ("instances") the fileDataIDs of the day and the night music.
- The MP3 files come out of the player's own install when needed (extract_missing) into
  %APPDATA%\\ForeverChronicle\\music\\<fileDataID>.mp3. Needs numpy (wow/casc.py); without it, or without the
  game, the cinematic mode plays the built-in theme instead.
- Zones without music of their own (Ironforge, Undercity) have no entry; dungeons without one keep the music of
  the zone around them (the cinematic shows that zone too).
"""

from __future__ import annotations

import datetime
import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from ..config import app_home
from .paths import ClientInstall

TABLE = Path(__file__).resolve().parents[1] / "zone_music.json"
NIGHT_FROM, NIGHT_UNTIL = 21, 6   # local hours of the recorded moment counted as night

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


def is_night(t: float) -> bool:
    hour = datetime.datetime.fromtimestamp(t).hour
    return hour >= NIGHT_FROM or hour < NIGHT_UNTIL


def file_ids(map_id: int | None, instance_id: int | None, t: float) -> tuple[int, ...]:
    """The music files the game plays there at that moment (day or night by the recorded local time)."""
    found = entry(map_id, instance_id)
    if not found:
        return ()
    return tuple(found["night" if is_night(t) else "day"])


def all_file_ids(places: Iterable[tuple[int | None, int | None]]) -> list[int]:
    """Day and night music of the given (map_id, instance_id) places, without repeats."""
    result: list[int] = []
    for map_id, instance_id in places:
        found = entry(map_id, instance_id)
        for fdid in (found["day"] + found["night"]) if found else []:
            if fdid not in result:
                result.append(fdid)
    return result


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
    try:
        from . import casc
        storage = casc.Casc(client.path.parent, client.flavor)
    except Exception:  # no numpy, or the game files cannot be read: not tried again this session
        _failed.update(todo)
        return 0
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for fdid in todo:
        try:
            data = storage.read_fdid(fdid)
        except Exception:
            _failed.add(fdid)
            continue
        suffix = ".ogg" if data[:4] == b"OggS" else ".mp3"
        part = folder / f"{fdid}{suffix}.part"
        part.write_bytes(data)
        part.replace(folder / f"{fdid}{suffix}")
        written += 1
    return written
