"""Route model for the map: projection onto zone/continent maps, segments and time lookup (spec F-005).

Rules from the spec:
- Lines only connect consecutive recorded points; a time gap, a map change, a teleport or an instance point
  ends a segment. No route is ever invented between points that are not connected.
- Scrubbing selects the nearest recorded point (a stationary point covers its whole time..until span).
- A replay marker moves along the line between two connected points (glide), as in the addon.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

from ..storage.repository import PositionPoint
from . import maps

GAP_SECONDS = 120  # longer gaps between two points split the route
ENTRY_SECONDS = 60  # an outdoor point at most this long before entering an instance marks its entrance
# Teleports (hearthstone, portals) are recognised by a step faster than any mount or flight path, measured in
# continent widths so cities and zones compare alike (same values as the addon's Core/Route.lua).
TELEPORT_SPEED = 0.004      # continent widths per second
TELEPORT_DISTANCE = 0.01    # shorter steps never count as a teleport
UNKNOWN_ZONE_SCALE = 0.1    # assumed size of a zone without continent geometry
CONTINENT_TYPE = 2          # Enum.UIMapType.Continent


@dataclass
class Segment:
    points: list[tuple[int, float, float]] = field(default_factory=list)  # (time, x, y) normalized on the view
    taxi: bool = False


class Route:
    def __init__(self, points: list[PositionPoint], map_infos: dict | None = None,
                 instance_names: dict[int, str] | None = None,
                 entrances: dict[int, tuple[int, float, float]] | None = None):
        self.points = sorted(points, key=lambda p: p.time)
        self.times = [p.time for p in self.points]
        self.map_infos = map_infos or {}
        self.instance_names = instance_names or {}
        self.recorded_entrances = entrances or {}
        self._derived_entrances: dict[int, tuple[int, float, float]] | None = None

    def __bool__(self) -> bool:
        return bool(self.points)

    @property
    def start(self) -> int | None:
        return self.points[0].time if self.points else None

    @property
    def end(self) -> int | None:
        return max(p.end for p in self.points) if self.points else None

    # -- projection --------------------------------------------------------------------

    def continent(self, map_id: int) -> int | None:
        return maps.continent_of(map_id, self.map_infos)

    def project(self, map_id: int | None, x: float | None, y: float | None, view: int) -> tuple[float, float] | None:
        """Normalized position of (map_id, x, y) on the view map, or None if it is not on that map.
        Zone points can be shown on their continent, and continent points on a zone that contains them."""
        if map_id is None or x is None:
            return None
        if map_id == view:
            return x, y
        info = self.map_infos.get(map_id)
        if info is not None and info["continent_id"] == view and info["min_x"] is not None:
            return (info["min_x"] + x * (info["max_x"] - info["min_x"]),
                    info["min_y"] + y * (info["max_y"] - info["min_y"]))
        zone = self.map_infos.get(view)
        if (zone is not None and zone["continent_id"] == map_id and zone["min_x"] is not None
                and zone["max_x"] > zone["min_x"] and zone["max_y"] > zone["min_y"]):
            zx = (x - zone["min_x"]) / (zone["max_x"] - zone["min_x"])
            zy = (y - zone["min_y"]) / (zone["max_y"] - zone["min_y"])
            if 0 <= zx <= 1 and 0 <= zy <= 1:
                return zx, zy
        return None

    # -- dungeon entrances -------------------------------------------------------------

    def entrance(self, instance_id: int | None) -> tuple[int, float, float] | None:
        """(map, x, y) of a dungeon entrance: recorded by the addon (journal or where the player walked in),
        else derived from the route (last outdoor point shortly before entering)."""
        if instance_id is None:
            return None
        if instance_id in self.recorded_entrances:
            return self.recorded_entrances[instance_id]
        if self._derived_entrances is None:
            self._derived_entrances = {}
            prev = None
            for p in self.points:
                if (p.instance_id is not None and prev is not None and prev.instance_id is None
                        and prev.map_id is not None and prev.x is not None and not prev.taxi
                        and p.time - prev.end <= ENTRY_SECONDS):
                    self._derived_entrances[p.instance_id] = (prev.map_id, prev.x, prev.y)
                prev = p
        return self._derived_entrances.get(instance_id)

    def locate(self, map_id: int | None, x: float | None, y: float | None,
               instance_id: int | None = None) -> tuple[int, float, float] | None:
        """Where something is shown: its own position, or inside an instance the dungeon entrance."""
        if map_id is not None and x is not None:
            return map_id, x, y
        return self.entrance(instance_id)

    def view_for(self, point: PositionPoint | None) -> int | None:
        """The map to show for a point: its zone. The client sometimes reports only the continent (between
        zones, on boats and zeppelins); then the smallest known zone containing the point is used.
        Points inside instances use the zone of the dungeon entrance."""
        if point is None:
            return None
        spot = self.locate(point.map_id, point.x, point.y, point.instance_id)
        if spot is None:
            return point.map_id
        map_id, x, y = spot
        best, best_area = None, None
        for zone_id, info in self.map_infos.items():
            if zone_id == map_id or info["continent_id"] != map_id or info["min_x"] is None:
                continue
            if info["min_x"] <= x <= info["max_x"] and info["min_y"] <= y <= info["max_y"]:
                area = (info["max_x"] - info["min_x"]) * (info["max_y"] - info["min_y"])
                if best_area is None or area < best_area:
                    best, best_area = zone_id, area
        return best if best is not None else map_id

    def available_views(self) -> list[int]:
        """Zone maps with points, then the continents that contain them (if their geometry is known)."""
        zones, continents = [], []
        for p in self.points:
            if p.map_id is not None and p.map_id not in zones:
                zones.append(p.map_id)
        for z in zones:
            info = self.map_infos.get(z)
            c = info["continent_id"] if info is not None and info["min_x"] is not None else None
            if c and c not in continents and c not in zones:
                continents.append(c)
        return zones + continents

    # -- connections -------------------------------------------------------------------

    def _continent_scale(self, map_id: int | None) -> float:
        """Size of one map unit in continent widths."""
        info = self.map_infos.get(map_id)
        if info is None:
            return UNKNOWN_ZONE_SCALE
        if "map_type" in info.keys() and info["map_type"] == CONTINENT_TYPE:
            return 1.0
        if info["min_x"] is not None and info["max_x"] > info["min_x"]:
            return info["max_x"] - info["min_x"]
        return UNKNOWN_ZONE_SCALE

    def is_jump(self, prev: PositionPoint, p: PositionPoint) -> bool:
        """True when the step from prev to p (same map) is a teleport."""
        if prev.taxi or p.taxi or prev.x is None or p.x is None:
            return False
        d = math.hypot(p.x - prev.x, p.y - prev.y) * self._continent_scale(p.map_id)
        return d >= TELEPORT_DISTANCE and d / max(1, p.time - prev.end) > TELEPORT_SPEED

    def connected(self, prev: PositionPoint, p: PositionPoint) -> bool:
        """True when a route line joins prev and p."""
        return (p.time - prev.end <= GAP_SECONDS and prev.map_id == p.map_id and prev.taxi == p.taxi
                and not self.is_jump(prev, p))

    # -- segments ----------------------------------------------------------------------

    def segments(self, view: int, start: int | None = None, end: int | None = None) -> list[Segment]:
        result: list[Segment] = []
        current: Segment | None = None
        prev: PositionPoint | None = None
        for p in self.points:
            if (start is not None and p.end < start) or (end is not None and p.time > end):
                prev = None
                current = None
                continue
            xy = self.project(p.map_id, p.x, p.y, view)
            if xy is None:
                current, prev = None, p
                continue
            if current is None or prev is None or not self.connected(prev, p):
                current = Segment(taxi=p.taxi)
                result.append(current)
            current.points.append((p.time, xy[0], xy[1]))
            prev = p
        return result

    # -- time lookup --------------------------------------------------------------------

    def point_at(self, t: int) -> PositionPoint | None:
        """The point covering t, else the nearest recorded point."""
        if not self.points:
            return None
        i = bisect.bisect_right(self.times, t) - 1
        if i >= 0 and self.points[i].time <= t <= self.points[i].end:
            return self.points[i]
        candidates = [self.points[j] for j in (i, i + 1) if 0 <= j < len(self.points)]
        return min(candidates, key=lambda p: min(abs(t - p.time), abs(t - p.end)))

    def glide(self, t: float) -> tuple[int, float, float] | None:
        """Where a replay shows the player at time t: between two connected points on the line joining them,
        else the nearest point (inside a dungeon its entrance). None if unknown."""
        i = bisect.bisect_right(self.times, t) - 1
        if 0 <= i < len(self.points) - 1:
            a, b = self.points[i], self.points[i + 1]
            if a.x is not None and b.x is not None and a.end < t < b.time and self.connected(a, b):
                f = (t - a.end) / (b.time - a.end)
                return a.map_id, a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f
        p = self.point_at(int(t))
        return self.locate(p.map_id, p.x, p.y, p.instance_id) if p else None

    def next_time_after(self, t: int) -> int | None:
        """Start time of the first point after t (used to skip gaps during playback)."""
        i = bisect.bisect_right(self.times, t)
        return self.points[i].time if i < len(self.points) else None

    def instance_name(self, point: PositionPoint) -> str | None:
        if point.instance_id is None:
            return None
        return self.instance_names.get(point.instance_id) or f"#{point.instance_id}"
