"""Music and ambience from the game for the cinematic mode: the adventure music (the outdoor themes of some zones,
a new one every few levels), the zones' ambience (wind, birds, insects: one loop by day, one by night) and the
files themselves.

- forever_chronicle/zone_music.json (kept in git, written by tools/extract_zone_music.py): per uiMapID ("zones")
  and per instance map ID ("instances") the fileDataIDs of the day and the night music; the same for the ambience
  under "ambience".
- Adventure music: chapter by chapter (CHAPTER_LEVELS) the day music of the zones in ADVENTURE, in that order;
  after the last theme they start again. Chapters are long in the first levels and get shorter later, where a
  level takes much longer to play. With a known race every other chapter is a theme of its people's lands
  (RACE_THEMES: the undead get Tirisfal, the Plaguelands and Felwood), starting with the first chapter.
- The files (MP3 music, OGG ambience) come out of the player's own install when needed (extract_missing) into
  %APPDATA%\\ForeverChronicle\\music\\<fileDataID>.mp3 (or .ogg). Needs numpy (wow/casc.py); without it, or
  without the game, the cinematic mode plays the built-in theme instead, and no ambience.
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
# Per race (the game's race token) the themes of its lands, in order: start zone, then others.
RACE_THEMES = {
    "Human": (1429, 1453),             # Elwynn Forest, Stormwind
    "Dwarf": (1426,),                  # Dun Morogh
    "Gnome": (1426,),
    "NightElf": (1438, 1439, 1457),    # Teldrassil, Darkshore, Darnassus
    "Orc": (1411, 1454),               # Durotar, Orgrimmar
    "Troll": (1411, 1434),             # Durotar, Stranglethorn Vale
    "Tauren": (1412, 1456),            # Mulgore, Thunder Bluff
    "Scourge": (1420, 1422, 1448),     # Tirisfal Glades, the Plaguelands, Felwood
}
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


def ambience_file_ids(map_id: int | None, instance_id: int | None = None, night: bool = False) -> tuple[int, ...]:
    """The ambience of a dungeon, else of a zone, by day or night (() for none)."""
    data = table().get("ambience", {})
    found = data.get("instances", {}).get(str(instance_id)) if instance_id is not None else None
    if found is None and map_id is not None:
        found = data.get("zones", {}).get(str(map_id))
    return tuple(found["night" if night else "day"]) if found else ()


def chapter(level: int | None) -> int:
    """The adventure chapter of a level (0 while the level is unknown)."""
    return max(0, bisect.bisect_right(CHAPTER_LEVELS, level) - 1) if level is not None else 0


def _themes(map_ids: Iterable[int]) -> list[tuple[int, ...]]:
    """The day music of these zones, each music once (Durotar and Mulgore share theirs)."""
    found = (entry(m) for m in map_ids)
    return list(dict.fromkeys(tuple(e["day"]) for e in found if e and e["day"]))


def adventure_file_ids(chapter_index: int, race: str | None = None) -> tuple[int, ...]:
    """The music files of an adventure chapter: the day music of its theme (the themes repeat). With a known race,
    the even chapters play its own themes and the odd ones the others."""
    common = _themes(ADVENTURE)
    own = _themes(RACE_THEMES.get(race or "", ()))
    if not own:
        return common[chapter_index % len(common)] if common else ()
    others = [m for m in common if m not in own] or common
    pool = own if chapter_index % 2 == 0 else others
    return pool[chapter_index // 2 % len(pool)]


_found: dict[tuple[Path, int], Path] = {}     # files once found (the replay asks every frame)


def find(fdid: int) -> Path | None:
    folder = cache_dir()
    known = _found.get((folder, fdid))
    if known is not None:
        return known
    for suffix in (".mp3", ".ogg"):
        path = folder / f"{fdid}{suffix}"
        if path.is_file():
            _found[(folder, fdid)] = path
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
