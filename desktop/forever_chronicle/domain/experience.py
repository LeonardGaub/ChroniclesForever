"""How full the experience bar is at a recorded moment (the cinematic's XP bar).

- With the addon's minute samples (Modules/Metrics.lua: experience earned in total), the bar is exact: the
  experience earned since reaching the level, out of what the level took. A level's size is the experience
  earned between its level-up and the next. The bar as the addon last saw it (anchor: xp of xp_max at a moment)
  starts and sizes the level the character was in then, even when it began before tracking; other levels without
  both ends take their size from the Classic experience table (XP_TO_NEXT).
- Without samples (older data, friends' characters), the bar fills with the playing time between two level-ups;
  in the level the character is still in it stays unknown (None).
"""

from __future__ import annotations

import bisect
from typing import Callable

from .cinematic import Levels

MAX_LEVEL = 60
# Experience from each level to the next (Classic Era); Forever's own values come from the samples where known.
XP_TO_NEXT = {
    1: 400, 2: 900, 3: 1400, 4: 2100, 5: 2800, 6: 3600, 7: 4500, 8: 5400, 9: 6500, 10: 7600,
    11: 8800, 12: 10100, 13: 11400, 14: 12900, 15: 14400, 16: 16000, 17: 17700, 18: 19400, 19: 21300, 20: 23200,
    21: 25200, 22: 27300, 23: 29400, 24: 31700, 25: 34000, 26: 36400, 27: 38900, 28: 41400, 29: 44300, 30: 47400,
    31: 50800, 32: 54500, 33: 58600, 34: 62800, 35: 67100, 36: 71600, 37: 76100, 38: 80800, 39: 85700, 40: 90700,
    41: 95800, 42: 101000, 43: 106300, 44: 111800, 45: 117500, 46: 123200, 47: 129100, 48: 135100, 49: 141200,
    50: 147500, 51: 153900, 52: 160400, 53: 167100, 54: 173900, 55: 180800, 56: 187900, 57: 195000, 58: 202300,
    59: 209800,
}


class Experience:
    def __init__(self, levels: Levels, samples: list[tuple[int, int, int | None]] = (),
                 played: Callable[[float, float], float] | None = None,
                 anchor: tuple[int, int, int] | None = None):
        """samples: (time, experience earned in total, level) in time order (Repository.metrics).
        played(a, b): playing time between two moments (breaks left out), for the fallback without samples.
        anchor: (when, xp, xp to the next level) as the addon last saw the bar (Character.xp)."""
        self.levels = levels
        self.times = [s[0] for s in samples]
        self.xp = [s[1] for s in samples]
        self.played = played or (lambda a, b: b - a)
        self.start: dict[int, float] = {}            # level -> experience earned in total on reaching it
        for t, level in zip(levels.times, levels.levels):
            value = self.xp_at(t)
            if value is not None:
                self.start[level] = value
        self.sizes: dict[int, float] = {}             # level -> its size as the game said (the anchor)
        if anchor is not None:
            when, xp, xp_max = anchor
            total, level = self.xp_at(when), levels.at(when)
            if total is not None and level is not None and xp_max > 0:
                self.start[level] = total - xp
                self.sizes[level] = xp_max

    def xp_at(self, t: float) -> float | None:
        """Experience earned in total at t, between the samples around it (None before the first; after the last
        nothing changed, since the addon writes a sample whenever something did)."""
        if not self.times or t < self.times[0]:
            return None
        i = bisect.bisect_right(self.times, t) - 1
        if i >= len(self.times) - 1:
            return float(self.xp[-1])
        t0, t1 = self.times[i], self.times[i + 1]
        return self.xp[i] + (self.xp[i + 1] - self.xp[i]) * (t - t0) / max(1, t1 - t0)

    def size(self, level: int) -> float | None:
        """Experience the level took: from the samples between its level-up and the next, else as the game said
        (the anchor), else the table."""
        if level in self.sizes:
            return self.sizes[level]
        if level in self.start and level + 1 in self.start and self.start[level + 1] > self.start[level]:
            return self.start[level + 1] - self.start[level]
        return XP_TO_NEXT.get(level)

    def at(self, t: float) -> tuple[int | None, float | None]:
        """(level, share of the bar 0..1) at t; the share is None when unknown, the level None too without any."""
        level, share, _ = self.values(t)
        return level, share

    def values(self, t: float) -> tuple[int | None, float | None, float | None]:
        """(level, share of the bar 0..1, the level's size in experience points) at t. The size is None where only
        the playing time places the bar (no samples): then there are no experience points to show."""
        level = self.levels.at(t)
        if level is None:
            return None, None, None
        if level >= MAX_LEVEL:
            return level, None, None
        now = self.xp_at(t)
        if now is not None:
            begin = self.start.get(level)
            size = self.size(level)
            if begin is None and level + 1 in self.start and size:
                begin = self.start[level + 1] - size       # tracking began within the level
            if begin is not None and size:
                return level, max(0.0, min(1.0, (now - begin) / size)), size
        return level, self._by_time(level, t), None

    def _by_time(self, level: int, t: float) -> float | None:
        """The share by playing time between the level-up and the next (both must be known)."""
        i = bisect.bisect_right(self.levels.times, t) - 1
        if i < 0 or i + 1 >= len(self.levels.times) or self.levels.levels[i] != level:
            return None
        a, b = self.levels.times[i], self.levels.times[i + 1]
        total = self.played(a, b)
        return max(0.0, min(1.0, self.played(a, t) / total)) if total > 0 else None
