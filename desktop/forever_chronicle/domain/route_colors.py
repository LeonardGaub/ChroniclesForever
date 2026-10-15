"""Route and timeline colours, the same as in the addon's map (UI/Pages/Map.lua, UI/MapCanvas.lua).

- The route is coloured by level (default), by session or in one colour; flight paths are always blue.
  A line takes the colour of the moment it ends at.
- The timeline shows one muted band per zone (in order of first visit) and a dark one inside dungeons.
Values are kept as the addon's 0..1 floats so both sides can be compared at a glance.
"""

from __future__ import annotations

import bisect
from typing import Callable, Iterable, Sequence

from ..i18n import format_datetime, tr
from .cinematic import Levels

MODES = ("level", "session", "plain")
LEGEND_ROWS = 10

ROUTE = (1, 0.82, 0)
TAXI = (0.41, 0.8, 0.94)
# Neighbouring levels and sessions get different colours; blue stays reserved for flight paths.
PALETTE = ((1, 0.82, 0), (0.45, 1, 0.35), (1, 0.42, 0.3), (0.85, 0.5, 1), (1, 1, 1), (1, 0.62, 0.1))
ZONES = ((0.62, 0.47, 0.25), (0.33, 0.52, 0.3), (0.3, 0.43, 0.6), (0.6, 0.33, 0.33),
         (0.52, 0.52, 0.28), (0.45, 0.35, 0.6), (0.28, 0.52, 0.52), (0.65, 0.42, 0.3))
INSTANCE = (0.22, 0.18, 0.28)
SEGMENT_END = (0.62, 0.62, 0.62)   # the addon's grey dots where recorded data starts or stops


def hex_color(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{int(v * 255 + 0.5):02x}" for v in rgb)


def palette_color(n: int) -> str:
    return hex_color(PALETTE[(n - 1) % len(PALETTE)])


class RouteColors:
    """Colour of the route at a time, for one character."""

    def __init__(self, mode: str, levels: Levels, session_starts: Iterable[int]):
        self.mode = mode if mode in MODES else MODES[0]
        self.levels = levels
        self.session_starts = sorted(session_starts)

    def key_at(self, t: float) -> int | None:
        """Level or session number (1 = oldest) at t; None in one-colour mode."""
        if self.mode == "level":
            return self.levels.at(t) or 1
        if self.mode == "session":
            return max(1, bisect.bisect_right(self.session_starts, t))
        return None

    def at(self, t: float, taxi: bool = False) -> str:
        if taxi:
            return hex_color(TAXI)
        key = self.key_at(t)
        return palette_color(key) if key is not None else hex_color(ROUTE)

    def runs(self, times: Sequence[int], taxi: bool = False) -> list[tuple[int, int, str]]:
        """Same-coloured stretches of a segment: (first point, last point, colour); the line from point i-1 to
        point i has the colour at times[i]."""
        runs: list[list] = []
        for i in range(1, len(times)):
            color = self.at(times[i], taxi)
            if runs and runs[-1][2] == color:
                runs[-1][1] = i
            else:
                runs.append([i - 1, i, color])
        return [tuple(r) for r in runs]

    def legend(self, segments) -> list[tuple[str, str]]:
        """(colour, label) for the levels or sessions the drawn segments touch (newest LEGEND_ROWS)."""
        if self.mode == "plain":
            return []
        keys = set()
        for seg in segments:
            if not seg.taxi and seg.points:
                for t, _, _ in (seg.points[0], seg.points[-1]):
                    keys.add(self.key_at(t))
        items = []
        for key in sorted(keys)[-LEGEND_ROWS:]:
            if self.mode == "level":
                label = tr("cine.level", level=key)
            else:
                start = self.session_starts[key - 1] if key <= len(self.session_starts) else None
                label = format_datetime(start) if start is not None else str(key)
            items.append((palette_color(key), label))
        return items


def zone_colors(runs) -> Callable[[object], str]:
    """Band colour per zone run (Route.zone_runs): zones in order of first visit, dungeons dark."""
    assigned: dict[int | None, str] = {}

    def color(run) -> str:
        if run.instance_id is not None:
            return hex_color(INSTANCE)
        if run.map_id not in assigned:
            assigned[run.map_id] = hex_color(ZONES[len(assigned) % len(ZONES)])
        return assigned[run.map_id]

    for run in runs:
        color(run)
    return color
