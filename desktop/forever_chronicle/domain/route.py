"""Route model for the map: projection onto zone/continent maps, segments and time lookup (spec F-005).

Rules from the spec:
- Coordinates are never interpolated. Lines only connect consecutive recorded points; a time gap,
  a map change or an instance point ends a segment.
- Scrubbing selects the nearest recorded point (a stationary point covers its whole time..until span).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from ..storage.repository import PositionPoint
from . import maps

GAP_SECONDS = 120  # longer gaps between two points split the route


@dataclass
class Segment:
    points: list[tuple[int, float, float]] = field(default_factory=list)  # (time, x, y) normalized on the view
    taxi: bool = False


class Route:
    def __init__(self, points: list[PositionPoint], map_infos: dict | None = None,
                 instance_names: dict[int, str] | None = None):
        self.points = sorted(points, key=lambda p: p.time)
        self.times = [p.time for p in self.points]
        self.map_infos = map_infos or {}
        self.instance_names = instance_names or {}

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

    def view_for(self, point: PositionPoint | None) -> int | None:
        """The map to show for a point: its zone. The client sometimes reports only the continent (between
        zones, on boats and zeppelins); then the smallest known zone containing the point is used."""
        if point is None or point.map_id is None:
            return None
        if point.x is None:
            return point.map_id
        best, best_area = None, None
        for map_id, info in self.map_infos.items():
            if map_id == point.map_id or info["continent_id"] != point.map_id or info["min_x"] is None:
                continue
            if info["min_x"] <= point.x <= info["max_x"] and info["min_y"] <= point.y <= info["max_y"]:
                area = (info["max_x"] - info["min_x"]) * (info["max_y"] - info["min_y"])
                if best_area is None or area < best_area:
                    best, best_area = map_id, area
        return best if best is not None else point.map_id

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
            breaks = (current is None or prev is None or p.time - prev.end > GAP_SECONDS
                      or prev.map_id != p.map_id or prev.taxi != p.taxi)
            if breaks:
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

    def next_time_after(self, t: int) -> int | None:
        """Start time of the first point after t (used to skip gaps during playback)."""
        i = bisect.bisect_right(self.times, t)
        return self.points[i].time if i < len(self.points) else None

    def instance_name(self, point: PositionPoint) -> str | None:
        if point.instance_id is None:
            return None
        return self.instance_names.get(point.instance_id) or f"#{point.instance_id}"
