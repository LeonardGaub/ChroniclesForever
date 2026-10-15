"""Cinematic replay script: the moments a cinematic replay announces or stops at (map page, cinematic mode).

- An event cue is shown as a short toast while the replay goes on; a level-up gets a large title instead.
  An event whose screenshot is shown gets no toast: the picture's banner names it.
  Toasts and screenshots carry a banner like the game's achievement alert (heading, title, place).
- A screenshot cue pauses the replay and shows the picture taken at that moment. Only screenshots whose file
  was found are used.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

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
    level: int | None = None    # level reached (kind "level"; also on a level-up's screenshot)
    heading: str = ""           # banner (toast, screenshot): what happened ("Achievement earned") ...
    title: str = ""             # ... its name, shown large ...
    place: str = ""             # ... and where
    event_type: str = ""        # the event's type ("" for a screenshot without its event)
    has_screenshot: bool = False  # an event whose screenshot is shown too (its banner says the same)


# Screenshot banner, like the game's achievement alert: a short heading and the name of what happened.
BANNER_TITLES: dict[str, Callable[[EventRow], Any]] = {
    "level_up": lambda e: tr("cine.level", level=e.payload.get("level", "?")),
    "achievement_earned": lambda e: e.payload.get("name"),
    "rare_killed": lambda e: e.payload.get("name"),
    "boss_killed": lambda e: e.payload.get("name"),
    "dungeon_completed": lambda e: e.payload.get("instance"),
    "zone_discovered": lambda e: e.payload.get("zone") or e.zone_name,
    "quest_completed": lambda e: e.payload.get("title"),
    "player_died": lambda e: e.subzone_name or e.zone_name,
}


def banner(event: EventRow | None, trigger: str | None) -> tuple[str, str, str]:
    """(heading, title, place) for a screenshot taken for event (None: a test screenshot or a lost event)."""
    if event is None:
        return tr("cine.banner.screenshot"), tr(f"trigger.{trigger}"), ""
    make = BANNER_TITLES.get(event.event_type)
    try:
        title = make(event) if make else None
    except Exception:  # a malformed payload must never break the replay
        title = None
    heading = tr(f"cine.banner.{event.event_type}") if make else tr(event_types.get(event.event_type).label_key)
    place = event.payload.get("instance") if event.event_type == "boss_killed" else None
    return heading, str(title or event_types.describe(event)), place or event_types.location_text(event)


def build_cues(events: Iterable[EventRow], screenshots: Iterable[Any], start: int, end: int) -> list[Cue]:
    """Cues within [start, end] in time order. events: may include other types (their screenshots get a
    banner); only CUE_EVENT_TYPES become cues. screenshots: rows with captured_at/requested_at, file_path,
    trigger_type and first_event_id (Repository.screenshots)."""
    events = list(events)
    by_id = {e.event_id: e for e in events}
    shots = [r for r in screenshots if _shown(r, start, end)]
    with_shot = {r["first_event_id"] for r in shots}
    cues: list[Cue] = []
    for e in events:
        if e.event_type not in CUE_EVENT_TYPES or not start <= e.occurred_at <= end:
            continue
        et = event_types.get(e.event_type)
        level = e.payload.get("level") if e.event_type == "level_up" else None
        heading, title, place = banner(e, None)
        cues.append(Cue(e.occurred_at, "level" if isinstance(level, int) else "event", event_types.describe(e),
                        et.glyph, et.color, level=level if isinstance(level, int) else None, heading=heading,
                        title=title, place=place, event_type=e.event_type,
                        has_screenshot=e.event_id in with_shot))
    for row in shots:
        t = row["captured_at"] or row["requested_at"]
        path = row["file_path"]
        event = by_id.get(row["first_event_id"])
        text = event_types.describe(event) if event else tr(f"trigger.{row['trigger_type']}")
        heading, title, place = banner(event, row["trigger_type"])
        et = event_types.get(event.event_type) if event else None
        level = event.payload.get("level") if event and event.event_type == "level_up" else None
        cues.append(Cue(t, "screenshot", text, et.glyph if et else "", et.color if et else "#ffd100", path=path,
                        level=level if isinstance(level, int) else None, heading=heading, title=title, place=place,
                        event_type=event.event_type if event else ""))
    # At the same second the event comes first, then its screenshot.
    order = {"level": 0, "event": 0, "screenshot": 1}
    cues.sort(key=lambda c: (c.time, order[c.kind]))
    return cues


def _shown(row, start: int, end: int) -> bool:
    """A screenshot the replay stops at: taken within the range, its file found."""
    t = row["captured_at"] or row["requested_at"]
    path = row["file_path"]
    return t is not None and start <= t <= end and bool(path) and Path(path).is_file()


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
