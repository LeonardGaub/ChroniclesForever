"""Cinematic replay script: the moments a cinematic replay announces or stops at (map page, cinematic mode).

- An event cue is shown as a short toast while the replay goes on; a level-up gets a large title instead.
- A screenshot cue pauses the replay and shows the picture taken at that moment. Only screenshots whose file
  was found are used.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..i18n import tr
from ..storage.repository import EventRow
from . import event_types

# Event types the replay announces. Quests are left out: there are too many for a replay at speed.
CUE_EVENT_TYPES = ("level_up", "player_died", "zone_discovered", "achievement_earned", "rare_killed",
                   "boss_killed", "dungeon_completed")


@dataclass(frozen=True)
class Cue:
    time: int
    kind: str                   # "event" | "level" | "screenshot"
    text: str
    glyph: str = ""
    color: str = "#ffd100"
    path: str | None = None     # screenshot file
    level: int | None = None    # level reached (kind "level")


def build_cues(events: Iterable[EventRow], screenshots: Iterable[Any], start: int, end: int) -> list[Cue]:
    """Cues within [start, end] in time order. screenshots: rows with captured_at/requested_at, file_path,
    trigger_type and first_event_id (Repository.screenshots)."""
    events = list(events)
    by_id = {e.event_id: e for e in events}
    cues: list[Cue] = []
    for e in events:
        if e.event_type not in CUE_EVENT_TYPES or not start <= e.occurred_at <= end:
            continue
        et = event_types.get(e.event_type)
        level = e.payload.get("level") if e.event_type == "level_up" else None
        cues.append(Cue(e.occurred_at, "level" if isinstance(level, int) else "event", event_types.describe(e),
                        et.glyph, et.color, level=level if isinstance(level, int) else None))
    for row in screenshots:
        t = row["captured_at"] or row["requested_at"]
        path = row["file_path"]
        if t is None or not start <= t <= end or not path or not Path(path).is_file():
            continue
        event = by_id.get(row["first_event_id"])
        text = event_types.describe(event) if event else tr(f"trigger.{row['trigger_type']}")
        cues.append(Cue(t, "screenshot", text, path=path))
    # At the same second the event comes first, then its screenshot.
    order = {"level": 0, "event": 0, "screenshot": 1}
    cues.sort(key=lambda c: (c.time, order[c.kind]))
    return cues


class Levels:
    """The character's level at any time, from its level-up events."""

    def __init__(self, events: Iterable[EventRow], current: int | None = None):
        changes = sorted((e.occurred_at, e.payload.get("level")) for e in events
                         if e.event_type == "level_up" and isinstance(e.payload.get("level"), int))
        self.times = [t for t, _ in changes]
        self.levels = [lv for _, lv in changes]
        self.current = current

    def at(self, t: float) -> int | None:
        i = bisect.bisect_right(self.times, t) - 1
        if i >= 0:
            return self.levels[i]
        if self.levels:
            return self.levels[0] - 1
        return self.current
