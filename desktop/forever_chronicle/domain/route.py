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
from typing import Iterator

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
WORLD_PER_CONTINENT = 0.78  # a continent map's width as a share of the world map's (maps.CONTINENT_IN_WORLD)


def too_fast(d: float, seconds: float, least: float = TELEPORT_DISTANCE) -> bool:
    """True when a step of d continent widths in seconds is a teleport: at least `least` long and faster than
    any mount or flight path."""
    return d >= least and d / max(1, seconds) > TELEPORT_SPEED


@dataclass
class Segment:
    points: list[tuple[int, float, float]] = field(default_factory=list)  # (time, x, y) normalized on the view
    taxi: bool = False


@dataclass
class ZoneRun:
    start: float
    to: float
    map_id: int | None          # None inside dungeons
    instance_id: int | None


class Timeline:
    """Maps time to a position on a timeline of active time (value = seconds since the start, breaks left out)."""

    def __init__(self, intervals: list[tuple[float, float]]):
        self.starts = [a for a, _ in intervals]
        self.ends = [b for _, b in intervals]
        self.offsets: list[float] = []
        total = 0.0
        for a, b in intervals:
            self.offsets.append(total)
            total += b - a
        self.total = max(1.0, total)

    def to_value(self, t: float) -> float:
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        return self.offsets[i] + max(0.0, min(self.ends[i], t) - self.starts[i])

    def to_time(self, v: float) -> float:
        i = max(0, bisect.bisect_right(self.offsets, v) - 1)
        return min(self.ends[i], self.starts[i] + max(0.0, v - self.offsets[i]))

    def breaks(self) -> list[float]:
        """Values where a collapsed break lies."""
        return self.offsets[1:]


SEGMENT_MEMO = 24          # Route.segments results kept per route (the whole journey, a few chosen chapters)

# Fingerprint of what Route.load reads: changes whenever a point is added or changed, or the map data changes.
_FINGERPRINT_POINTS = """SELECT COUNT(*), MAX(occurred_at), TOTAL(until_at), TOTAL(jump), TOTAL(on_taxi), TOTAL(mounted),
                                TOTAL(map_id), TOTAL(x) FROM positions WHERE character_id = ?"""
_FINGERPRINT_MAPS = """SELECT (SELECT COUNT(*) || ':' || TOTAL(min_x) || ':' || TOTAL(max_y) FROM map_info),
                              (SELECT COUNT(*) FROM instances), (SELECT COUNT(*) FROM instance_entrances)"""
_loaded: dict[str, tuple[tuple, "Route"]] = {}     # character ID -> (fingerprint, route), for Route.cached


class Route:
    """A character's route. Read-only once made (pages share one through Route.cached), so the segments of a view
    are worked out once and kept."""

    def __init__(self, points: list[PositionPoint], map_infos: dict | None = None,
                 instance_names: dict[int, str] | None = None,
                 entrances: dict[int, tuple[int, float, float]] | None = None):
        self.points = sorted(points, key=lambda p: p.time)
        self.times = [p.time for p in self.points]
        self.map_infos = map_infos or {}
        self.instance_names = instance_names or {}
        self.recorded_entrances = entrances or {}
        self._derived_entrances: dict[int, tuple[int, float, float]] | None = None
        self._segments: dict[tuple, list[Segment]] = {}
        self._end: int | None = None

    @classmethod
    def load(cls, repo, character_id: str) -> "Route":
        """A character's whole route with the map, instance and entrance data (repo: storage.repository)."""
        return cls(repo.positions(character_id), repo.map_infos(), repo.instance_names(), repo.entrances())

    @classmethod
    def cached(cls, repo, character_id: str) -> "Route":
        """Route.load, but the same Route again while the character's points and the map data are unchanged (a
        quick count instead of reading tens of thousands of points on every page refresh). Treat it as read-only."""
        conn = repo.conn
        key = (id(conn), conn.execute("PRAGMA database_list").fetchone()[2],
               tuple(conn.execute(_FINGERPRINT_POINTS, (character_id,)).fetchone()),
               tuple(conn.execute(_FINGERPRINT_MAPS).fetchone()))
        hit = _loaded.get(character_id)
        if hit is not None and hit[0] == key:
            return hit[1]
        route = cls.load(repo, character_id)
        _loaded[character_id] = (key, route)
        return route

    def __bool__(self) -> bool:
        return bool(self.points)

    @property
    def start(self) -> int | None:
        return self.points[0].time if self.points else None

    @property
    def end(self) -> int | None:
        if self._end is None and self.points:
            self._end = max(p.end for p in self.points)
        return self._end

    # -- projection --------------------------------------------------------------------

    def continent(self, map_id: int) -> int | None:
        return maps.continent_of(map_id, self.map_infos)

    def continent_or_self(self, map_id: int | None) -> int | None:
        """The continent a map lies on, or the map itself if it is one."""
        return map_id if map_id in maps.CONTINENT_IN_WORLD else self.continent(map_id)

    def project(self, map_id: int | None, x: float | None, y: float | None, view: int) -> tuple[float, float] | None:
        """Normalized position of (map_id, x, y) on the view map, or None if it is not on that map.
        Zone points can be shown on their continent, and continent points on a zone that contains them."""
        if map_id is None or x is None:
            return None
        if map_id == view:
            return x, y
        if view == maps.WORLD:
            return maps.world_xy(map_id, x, y, self.map_infos)
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

    def distance(self, a: PositionPoint, b: PositionPoint) -> float | None:
        """Distance between two points in continent widths, or None when it cannot be measured (no position, or
        not on one map: b is projected onto a's map when that map contains it)."""
        if a.x is None or b.x is None or a.map_id is None:
            return None
        xy = self.project(b.map_id, b.x, b.y, a.map_id)
        if xy is None:
            return None
        return math.hypot(xy[0] - a.x, xy[1] - a.y) * self._continent_scale(a.map_id)

    def is_jump(self, prev: PositionPoint, p: PositionPoint) -> bool:
        """True when the step from prev to p (same map) is a teleport."""
        if p.jump:
            return True
        if prev.taxi or p.taxi or prev.x is None or p.x is None:
            return False
        d = math.hypot(p.x - prev.x, p.y - prev.y) * self._continent_scale(p.map_id)
        return too_fast(d, p.time - prev.end)

    def connected(self, prev: PositionPoint, p: PositionPoint, view: int | None = None) -> bool:
        """True when a route line joins prev and p. On the world map (the seamless one) lines also cross from
        one zone into the next, unless the step is a teleport."""
        if p.time - prev.end > GAP_SECONDS or prev.taxi != p.taxi or p.jump:
            return False
        if prev.map_id == p.map_id:
            return not self.is_jump(prev, p)
        return view == maps.WORLD and self._walked_across(prev, p)

    def _walked_across(self, prev: PositionPoint, p: PositionPoint) -> bool:
        """True when prev and p lie on different maps of one continent, close enough to be one walk."""
        if prev.instance_id is not None or p.instance_id is not None:
            return False
        if self.continent_or_self(prev.map_id) != self.continent_or_self(p.map_id):
            return False
        a = maps.world_xy(prev.map_id, prev.x, prev.y, self.map_infos)
        b = maps.world_xy(p.map_id, p.x, p.y, self.map_infos)
        if a is None or b is None:
            return False
        d = math.hypot(b[0] - a[0], b[1] - a[1]) / WORLD_PER_CONTINENT    # continent widths
        return not too_fast(d, p.time - prev.end)

    # -- segments ----------------------------------------------------------------------

    def segments(self, view: int, start: int | None = None, end: int | None = None) -> list[Segment]:
        """The route's lines on the view map within [start, end]. Kept per (view, start, end): the segments are
        shared, read them only."""
        key = (view, start, end)
        cached = self._segments.get(key)
        if cached is None:
            cached = self._segments[key] = self._make_segments(view, start, end)
            while len(self._segments) > SEGMENT_MEMO:
                self._segments.pop(next(iter(self._segments)))
        return list(cached)

    def _make_segments(self, view: int, start: int | None, end: int | None) -> list[Segment]:
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
            if current is None or prev is None or not self.connected(prev, p, view):
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

    def glide(self, t: float, view: int | None = None) -> tuple[int, float, float] | None:
        """Where a replay shows the player at time t: between two connected points on the line joining them,
        else the nearest point (inside a dungeon its entrance). None if unknown. view=WORLD (the seamless map)
        also glides from one zone into the next; the point is then on the world map."""
        i = bisect.bisect_right(self.times, t) - 1
        if 0 <= i < len(self.points) - 1:
            a, b = self.points[i], self.points[i + 1]
            if a.x is not None and b.x is not None and a.end < t < b.time and self.connected(a, b, view):
                f = (t - a.end) / (b.time - a.end)
                if a.map_id != b.map_id:
                    wa = maps.world_xy(a.map_id, a.x, a.y, self.map_infos)
                    wb = maps.world_xy(b.map_id, b.x, b.y, self.map_infos)
                    return maps.WORLD, wa[0] + (wb[0] - wa[0]) * f, wa[1] + (wb[1] - wa[1]) * f
                return a.map_id, a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f
        p = self.point_at(int(t))
        return self.locate(p.map_id, p.x, p.y, p.instance_id) if p else None

    def points_in(self, start: float, end: float) -> Iterator[PositionPoint]:
        """The points overlapping [start, end], in time order (from the last one starting at or before start)."""
        for p in self.points[max(0, bisect.bisect_right(self.times, start) - 1):]:
            if p.time > end:
                break
            if p.end >= start:
                yield p

    def timeline(self, start: float, end: float, gap: float = 300) -> "Timeline":
        """Active time within [start, end]: breaks without points longer than gap are collapsed (as on the
        addon's slider), so a timeline over many sessions is not mostly empty."""
        intervals: list[list[float]] = []
        for p in self.points_in(start, end):
            a, b = max(p.time, start), min(p.end, end)
            if intervals and a - intervals[-1][1] <= gap:
                intervals[-1][1] = max(intervals[-1][1], b)
            else:
                intervals.append([a, b])
        if not intervals:
            intervals = [[start, end]]
        return Timeline([(a, b) for a, b in intervals])

    def zone_runs(self, start: float, end: float) -> list[ZoneRun]:
        """Stretches of [start, end] spent in one zone or one dungeon, in time order (the addon's
        Route.ZoneRuns, used for the timeline's zone bands)."""
        runs: list[ZoneRun] = []
        current: ZoneRun | None = None
        for p in self.points_in(start, end):
            map_id = p.map_id if p.instance_id is None else None
            if current and current.map_id == map_id and current.instance_id == p.instance_id:
                current.to = min(p.end, end)
            else:
                begin = max(p.time, start)
                if current:
                    current.to = max(current.to, begin)
                current = ZoneRun(begin, min(p.end, end), map_id, p.instance_id)
                runs.append(current)
        return runs

    def next_time_after(self, t: int) -> int | None:
        """Start time of the first point after t (used to skip gaps during playback)."""
        i = bisect.bisect_right(self.times, t)
        return self.points[i].time if i < len(self.points) else None

    def instance_name(self, point: PositionPoint | int | None) -> str | None:
        """The name of the instance a point lies in (or of an instance ID); None outside instances."""
        instance_id = point if point is None or isinstance(point, int) else point.instance_id
        if instance_id is None:
            return None
        return self.instance_names.get(instance_id) or f"#{instance_id}"
