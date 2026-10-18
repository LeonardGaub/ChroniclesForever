"""Dungeon maps (docs/Dungeon_Maps.md, "Built"), as in the addon's map page.

The client gives no position inside dungeons, so a dungeon with a map is a view of its own ("dungeon:<instanceID>")
without a route: its map, a floor at a time, and the list of what happened during the visit (bosses numbered in
kill order, deaths, level-ups, ...) with the time since entering. The pictures and names come from
tools/build_dungeon_maps.py (``maps/dungeon_<instanceID>_<floor>.jpg`` and ``maps/dungeons.json``), the same
table the addon draws from the client's tiles (Data/DungeonMaps.lua). Dungeons without a map (Forever's own) keep
the old behaviour: shown at their entrance.
"""

from __future__ import annotations

import bisect
import functools
import json
from dataclasses import dataclass
from pathlib import Path

from ..i18n import language
from ..storage.repository import EventRow, PositionPoint
from ..wow import map_art

VISIT_GAP = 30 * 60      # time outside (a corpse run, a quick trip out) that still counts as the same visit
VIEW_PREFIX = "dungeon:"


@dataclass(frozen=True)
class DungeonMap:
    instance_id: int
    names: dict[str, str]                       # language -> name
    floor_names: tuple[dict[str, str] | None, ...]

    @property
    def floors(self) -> int:
        return len(self.floor_names)

    def name(self) -> str:
        return self.names.get(language()) or self.names.get("en") or f"#{self.instance_id}"

    def floor_name(self, floor: int) -> str | None:
        """The floor's name (floor counts from 1); None for single-floor dungeons."""
        names = self.floor_names[floor - 1] if 1 <= floor <= self.floors else None
        return (names.get(language()) or names.get("en")) if names else None

    def art(self, floor: int) -> Path | None:
        path = map_art.maps_dir() / f"dungeon_{self.instance_id}_{floor}.jpg"
        return path if path.is_file() else None


def table() -> dict[int, DungeonMap]:
    """Every dungeon with a map (empty if the tool has not written dungeons.json)."""
    path = map_art.maps_dir() / "dungeons.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return {}
    return _load(path, stamp)


@functools.lru_cache(maxsize=4)
def _load(path: Path, stamp: int) -> dict[int, DungeonMap]:
    """dungeons.json, read again when it changes (stamp: its modification time)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result = {}
    for key, d in data.get("dungeons", {}).items():
        floors = tuple(f.get("name") for f in d.get("floors", []))
        if floors:
            result[int(key)] = DungeonMap(int(key), d.get("name") or {}, floors)
    return result


def get(instance_id: int | None) -> DungeonMap | None:
    return table().get(instance_id) if instance_id is not None else None


def view_key(instance_id: int | None) -> str | None:
    """The view of a dungeon with a map, None for dungeons without one."""
    return f"{VIEW_PREFIX}{instance_id}" if get(instance_id) else None


def dungeon_of(view) -> int | None:
    """The instance ID of a dungeon view, None for map views."""
    if isinstance(view, str) and view.startswith(VIEW_PREFIX) and view[len(VIEW_PREFIX):].isdigit():
        return int(view[len(VIEW_PREFIX):])
    return None


def view_for(route, point: PositionPoint | None):
    """The view for a point: its dungeon's map if there is one, else its zone (Route.view_for)."""
    if point is None:
        return None
    return view_key(point.instance_id) or route.view_for(point)


def available_views(route) -> list:
    """Maps that have points (zones, and dungeons with a map) in the order they were first visited, followed by the
    continents that contain them (the addon's Route.Views)."""
    zones, continents = [], []
    for p in route.points:
        view = p.map_id if p.map_id is not None else view_key(p.instance_id)
        if view is not None and view not in zones:
            zones.append(view)
    for z in zones:
        info = route.map_infos.get(z) if dungeon_of(z) is None else None
        c = info["continent_id"] if info is not None and info["min_x"] is not None else None
        if c and c not in continents and c not in zones:
            continents.append(c)
    return zones + continents


# -- visits ---------------------------------------------------------------------------------------------------------

@dataclass
class Visit:
    start: float
    end: float


@dataclass
class VisitEntry:
    event: EventRow
    offset: float                # seconds since entering
    boss: int | None = None      # kill order of a boss within the visit


def visits(route, instance_id: int, start: float, end: float) -> list[Visit]:
    """Visits to a dungeon within [start, end], oldest first (the addon's Route.DungeonVisits)."""
    result: list[Visit] = []
    for run in route.zone_runs(start, end):
        if run.instance_id != instance_id:
            continue
        if result and run.start - result[-1].end <= VISIT_GAP:
            result[-1].end = run.to
        else:
            result.append(Visit(run.start, run.to))
    return result


def visit_at(found: list[Visit], t: float) -> int | None:
    """Index of the visit shown at t: the one at t, else the last one before it, else the first."""
    if not found:
        return None
    return max(0, bisect.bisect_right([v.start for v in found], t) - 1)


def visit_entries(events: list[EventRow], visit: Visit) -> list[VisitEntry]:
    """Every event of the visit in time order; bosses get their number in kill order."""
    entries, bosses = [], 0
    for e in sorted(events, key=lambda e: e.occurred_at):
        if not visit.start <= e.occurred_at <= visit.end:
            continue
        number = None
        if e.event_type == "boss_killed":
            bosses += 1
            number = bosses
        entries.append(VisitEntry(e, e.occurred_at - visit.start, number))
    return entries


def since_entering(seconds: float) -> str:
    """"+m:ss" (or "+h:mm:ss") since entering."""
    seconds = max(0, int(seconds))
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"+{h}:{m:02d}:{s:02d}" if h else f"+{m}:{s:02d}"
