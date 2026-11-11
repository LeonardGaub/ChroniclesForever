"""Cinematic replay script: the moments a cinematic replay announces or stops at (map page, cinematic mode).

- An event cue is shown as a short toast while the replay goes on; a level-up gets a large title instead.
  An event whose screenshot is shown gets no toast: the picture's banner names it.
  Toasts and screenshots carry a banner like the game's achievement alert (heading, title, place).
- A screenshot cue shows the picture taken at that moment: at the sides while the replay goes on, or in the
  middle while it pauses (option). Only screenshots whose file was found are used. Big moments (is_big:
  level-ups, dungeons and bosses, the player's own screenshots and moments) slow the replay down at the sides.
- Deaths (death_spans): when the character lay dead, ran back as a ghost and came back to life. Since addon
  0.16.0 the death's event says so (releasedAt, revivedAt, how and by whom); older deaths are read from the route.
- Companions (Companions): who the player was grouped with, from the addon's group stream (since 0.16.0).
- Battlegrounds and arenas (match_spans): the replay jumps over a match and shows only its result (the
  battleground event, addon Modules/PvP.lua) and its screenshot; deaths inside a match are no death scenes.
- Standstills (still_spans): stretches in which the character did not move at all (AFK, waiting), which the
  replay can run through faster or skip.
- Teleports (teleports): hearthstone, portals and the ghost's release to the graveyard, which the replay shows as a
  flight across the world map. A jump to the other continent counts only after the player stood still before it
  (casting); otherwise it was a boat or zeppelin, which the replay shows as a crossing of the sea. Since addon
  0.16.0 a teleport the player cast is marked on the route (hearthstone or another spell) and always counts.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..i18n import tr
from ..storage.repository import EventRow, PositionPoint
from . import event_types, maps
from .route import WORLD_PER_CONTINENT, Route, too_fast

# Event types the replay announces. Quests are left out: there are too many for a replay at speed.
CUE_EVENT_TYPES = ("level_up", "player_died", "zone_discovered", "achievement_earned", "rare_killed",
                   "boss_killed", "dungeon_completed", "profession_learned", "profession_rank", "mount_learned",
                   "hearth_set", "item_obtained", "moment", "pvp_kill", "duel", "battleground")
# Cues that name the companions the player was grouped with.
WITH_COMPANIONS = ("boss_killed", "dungeon_completed", "rare_killed", "pvp_kill", "battleground")
# Screenshots the replay slows down for while it shows them at the sides: these events, and the ones the player
# took (manual) or marked (/fj moment).
BIG_EVENT_TYPES = ("level_up", "dungeon_completed", "boss_killed", "moment")
BIG_TRIGGERS = ("manual", "moment")
MATCH_AFTER = 120          # a match without a later route point outside it ends this long after its result
MATCH_AFTER_MAX = 600      # a later point is looked for at most this long after the result
GAP_SKIP = 30              # breaks without points longer than this are skipped by the replay: no playing time


def played_time(route: Route, start: float, end: float) -> float:
    """Playing time in [start, end], breaks longer than GAP_SKIP left out (as the replay skips them)."""
    return route.timeline(start, end, GAP_SKIP).total


@dataclass(frozen=True)
class Cue:
    time: int
    kind: str                   # "event" | "level" | "screenshot"
    text: str
    glyph: str = ""
    color: str = "#ffd100"
    icon: int | str = ""        # game icon (event_types.icon_of; the screenshot icon for a screenshot alone)
    path: str | None = None     # screenshot file
    level: int | None = None    # level reached (kind "level"; also on a level-up's screenshot)
    heading: str = ""           # banner (toast, screenshot): what happened ("Achievement earned") ...
    title: str = ""             # ... its name, shown large ...
    place: str = ""             # ... and where
    event_type: str = ""        # the event's type ("" for a screenshot without its event)
    has_screenshot: bool = False  # an event whose screenshot is shown too (its banner says the same)
    cause: str = ""             # a death's cause ("Killed by Hogger"), "" if unknown
    trigger: str = ""           # a screenshot's trigger type ("level", "zone", "manual", ...)


def is_big(cue: Cue) -> bool:
    """A screenshot of a big moment (BIG_EVENT_TYPES, BIG_TRIGGERS): the replay slows down for it."""
    return cue.kind == "screenshot" and (cue.level is not None or cue.event_type in BIG_EVENT_TYPES
                                         or cue.trigger in BIG_TRIGGERS)


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
    "profession_learned": lambda e: e.payload.get("name"),
    "profession_rank": lambda e: event_types.describe(e),
    "mount_learned": lambda e: e.payload.get("name"),
    "hearth_set": lambda e: e.payload.get("place"),
    "item_obtained": event_types.item_name,
    "moment": lambda e: e.payload.get("text") or tr("cine.moment_untitled"),
    "player_revived": lambda e: e.payload.get("reviver"),
    "pvp_kill": lambda e: e.payload.get("name"),
    "duel": lambda e: e.payload.get("name"),
    "battleground": lambda e: e.payload.get("name"),
}


def _heading_key(event: EventRow) -> str:
    """The banner's heading: per type, a first mount, worn gear and epic loot have their own."""
    p = event.payload
    if event.event_type == "mount_learned" and p.get("first"):
        return "cine.banner.first_mount"
    if event.event_type == "item_obtained":
        if p.get("equipped"):
            return "cine.banner.item_equipped"
        if isinstance(p.get("quality"), int) and p["quality"] >= 4:
            return "cine.banner.item_epic"
    if event.event_type == "duel":
        return "cine.banner.duel.won" if p.get("won") else "cine.banner.duel.lost"
    if event.event_type == "battleground" and p.get("result") in event_types.MATCH_RESULTS:
        return f"cine.banner.battleground.{p['result']}"
    return f"cine.banner.{event.event_type}"


def banner(event: EventRow | None, trigger: str | None) -> tuple[str, str, str]:
    """(heading, title, place) for a screenshot taken for event (None: a test screenshot or a lost event)."""
    if event is None:
        return tr("cine.banner.screenshot"), tr(f"trigger.{trigger}"), ""
    make = BANNER_TITLES.get(event.event_type)
    try:
        title = make(event) if make else None
    except Exception:  # a malformed payload must never break the replay
        title = None
    heading = tr(_heading_key(event)) if make else tr(event_types.get(event.event_type).label_key)
    place = event.payload.get("instance") if event.event_type == "boss_killed" else None
    return heading, str(title or event_types.describe(event)), place or event_types.location_text(event)


def build_cues(events: Iterable[EventRow], screenshots: Iterable[Any], start: int, end: int,
               companions: "Companions | None" = None) -> list[Cue]:
    """Cues within [start, end] in time order. events: may include other types (their screenshots get a
    banner); only CUE_EVENT_TYPES become cues, and a toast for each time another player brought the character
    back to life. screenshots: rows with captured_at/requested_at, file_path, trigger_type and first_event_id
    (Repository.screenshots). companions: named on boss, dungeon and rare cues ("with Gigel")."""
    events = list(events)
    by_id = {e.event_id: e for e in events}
    shots = [r for r in screenshots if _shown(r, start, end)]
    with_shot = {r["first_event_id"] for r in shots}
    cues: list[Cue] = []
    for e in events:
        if e.event_type not in CUE_EVENT_TYPES or not start <= e.occurred_at <= end or in_match(e):
            continue
        et = event_types.get(e.event_type)
        level = e.payload.get("level") if e.event_type == "level_up" else None
        heading, title, place = banner(e, None)
        if companions and e.event_type in WITH_COMPANIONS:
            place = companions.with_text(e.occurred_at, place)
        cues.append(Cue(e.occurred_at, "level" if isinstance(level, int) else "event", event_types.describe(e),
                        et.glyph, et.color, event_types.icon_of(e), level=level if isinstance(level, int) else None,
                        heading=heading, title=title, place=place, event_type=e.event_type,
                        has_screenshot=e.event_id in with_shot,
                        cause=event_types.death_cause(e) if e.event_type == "player_died" else ""))
    for e in events:
        revived = e.payload.get("revivedAt") if e.event_type == "player_died" else None
        if e.payload.get("revive") == "player" and isinstance(revived, int) and start <= revived <= end:
            rev = EventRow(e.character_id, e.event_id + ":revived", "player_revived", revived, e.zone_name,
                           e.subzone_name, e.map_id, e.x, e.y, e.payload, e.instance_id)
            et = event_types.get(rev.event_type)
            heading, title, place = banner(rev, None)
            cues.append(Cue(revived, "event", event_types.describe(rev), et.glyph, et.color, et.icon,
                            heading=heading, title=title, place=place, event_type=rev.event_type))
    for row in shots:
        t = row["captured_at"] or row["requested_at"]
        path = row["file_path"]
        event = by_id.get(row["first_event_id"])
        text = event_types.describe(event) if event else tr(f"trigger.{row['trigger_type']}")
        heading, title, place = banner(event, row["trigger_type"])
        et = event_types.get(event.event_type) if event else None
        level = event.payload.get("level") if event and event.event_type == "level_up" else None
        cues.append(Cue(t, "screenshot", text, et.glyph if et else "", et.color if et else "#ffd100",
                        event_types.icon_of(event) if event else event_types.SCREENSHOT_ICON, path=path,
                        level=level if isinstance(level, int) else None, heading=heading, title=title, place=place,
                        event_type=event.event_type if event else "", trigger=row["trigger_type"] or ""))
    # At the same second the event comes first, then its screenshot.
    order = {"level": 0, "event": 0, "screenshot": 1}
    cues.sort(key=lambda c: (c.time, order[c.kind]))
    return cues


def in_match(e: EventRow) -> bool:
    """A death inside a battleground or arena (addon 0.16.0): no death scene, no death toast."""
    return e.event_type == "player_died" and e.payload.get("battleground") in ("pvp", "arena")


def match_spans(events: Iterable[EventRow], route: Route, start: float, end: float) -> list[tuple[float, float, str]]:
    """(from, to, name) of the battleground and arena matches within [start, end], in time order: from entering
    the match to the first route point outside it after its end (the score board stays open a while), else
    MATCH_AFTER seconds after the end. The replay jumps over them; the moments inside are still shown."""
    spans: list[tuple[float, float, str]] = []
    for e in sorted((e for e in events if e.event_type == "battleground"), key=lambda e: e.occurred_at):
        p = e.payload
        began = p.get("startedAt")
        if not isinstance(began, int) or began > e.occurred_at:
            duration = p.get("duration")
            began = e.occurred_at - duration if isinstance(duration, int) and duration > 0 else e.occurred_at
        map_id, instance_id = p.get("mapID"), p.get("instanceID")
        until = e.occurred_at + MATCH_AFTER
        for pt in route.points[bisect.bisect_right(route.times, e.occurred_at):]:
            inside = (map_id is not None and pt.map_id == map_id) or (
                instance_id is not None and pt.instance_id == instance_id)
            if not inside:
                until = pt.time
                break
            if pt.time > e.occurred_at + MATCH_AFTER_MAX:
                break
        a, b = max(float(began), start), min(float(until), end)
        if b > a:
            spans.append((a, b, str(p.get("name") or e.zone_name or "")))
    return spans


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


# -- companions -----------------------------------------------------------------------------------------------

class Companions:
    """Who the player was grouped with: the addon's group stretches (from, until, members), a member being
    {"name", "class", "guid"}."""

    def __init__(self, stretches: Iterable[tuple[int, int, list[dict[str, str]]]]):
        self.stretches = sorted(stretches, key=lambda s: s[0])

    def at(self, t: float) -> list[dict[str, str]]:
        """The members of the group at time t (a few seconds of slack at both ends)."""
        for a, b, members in self.stretches:
            if a - 5 <= t <= b + 5:
                return members
        return []

    def with_text(self, t: float, place: str) -> str:
        """The place with "with Gigel, Thrall" added when the player was in a group at t."""
        names = [m.get("name") for m in self.at(t) if m.get("name")]
        if not names:
            return place
        shown = ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "")
        return "  ·  ".join(p for p in (place, tr("cine.with", names=shown)) if p)


# -- deaths ---------------------------------------------------------------------------------------------------

RELEASE_WITHIN = 6 * 60    # a teleport this soon after dying is the release to the graveyard
GHOST_WITHIN = 15 * 60     # longest corpse run looked for
CORPSE_REACH = 0.004       # continent widths (~60 yards): close enough to the body to come back to life
SPIRIT_HEALER = 30         # seconds at the graveyard when the ghost never walks back (the spirit healer)
MOVED_ON = 0.001           # continent widths: brought back where the body lay once the player moves this far
NO_ROUTE_DEATH = 20        # seconds shown as dead when the route says nothing about it


@dataclass(frozen=True)
class Death:
    time: int                  # died
    released: int | None       # the ghost appears at the graveyard (None: brought back where the body lay)
    revived: int               # alive again
    revive: str | None = None  # how, as the addon recorded it: "corpse" | "spirit_healer" | "player" | "self"
    reviver: str | None = None # who, when another player brought the character back

    def dead(self, t: float) -> bool:
        return self.time <= t < self.revived

    def ghost(self, t: float) -> bool:
        return self.released is not None and self.released <= t < self.revived


def death_spans(events: Iterable[EventRow], route: Route) -> list[Death]:
    """Each death of the events (player_died), with its ghost run read from the route: the release is the first
    teleport (or the step out of a dungeon) within RELEASE_WITHIN; the ghost comes back to life on reaching the
    body, or after SPIRIT_HEALER seconds at the graveyard when it never walks back. Without a release the player
    was brought back where the body lay and is alive again on moving on."""
    result: list[Death] = []
    for e in sorted((e for e in events if e.event_type == "player_died" and not in_match(e)),
                    key=lambda e: e.occurred_at):
        t = e.occurred_at
        p = e.payload
        revived, released = p.get("revivedAt"), p.get("releasedAt")
        if isinstance(revived, int) and revived >= t:
            # Recorded by the addon: no need to read it from the route.
            released = released if isinstance(released, int) and t <= released <= revived else None
            result.append(Death(t, released, revived, p.get("revive"),
                                p.get("reviver") if isinstance(p.get("reviver"), str) else None))
            continue
        body = route.point_at(t)
        if body is None or abs(_gap(body, t)) > RELEASE_WITHIN:
            result.append(Death(t, None, t + NO_ROUTE_DEATH))
            continue
        later = route.points[bisect.bisect_right(route.times, t):]
        released, rest = _release(route, body, later, t)
        if released is not None:
            revived = next((p.time for p in rest if p.time - released <= GHOST_WITHIN and _at_body(route, body, p)),
                           None)
            result.append(Death(t, released, revived if revived is not None else released + SPIRIT_HEALER))
            continue
        moved = next((p.time for p in later if p.time - t <= RELEASE_WITHIN and _moved_on(route, body, p)), None)
        result.append(Death(t, None, moved if moved is not None else t + NO_ROUTE_DEATH))
    return result


def _gap(p: PositionPoint, t: float) -> float:
    return 0 if p.time <= t <= p.end else (p.time - t if p.time > t else t - p.end)


def _release(route: Route, body: PositionPoint, later: list[PositionPoint], t: int):
    """(time of the release, the points after it) or (None, [])."""
    prev = body
    for k, p in enumerate(later):
        if p.time - t > RELEASE_WITHIN:
            break
        if body.instance_id is not None:
            if p.instance_id is None:              # out of the dungeon: the graveyard outside
                return p.time, later[k + 1:]
        elif p.instance_id is None:
            # A step faster than any mount (as Route.is_jump, across maps too), or onto a map that cannot be
            # measured against the body's.
            d = route.distance(prev, p)
            fast = d is not None and too_fast(d, p.time - prev.end)
            if fast or (d is None and p.map_id != prev.map_id):
                return p.time, later[k + 1:]
        prev = p
    return None, []


def _at_body(route: Route, body: PositionPoint, p: PositionPoint) -> bool:
    if body.instance_id is not None:
        return p.instance_id == body.instance_id   # ran back into the dungeon
    d = route.distance(body, p)
    return d is not None and d <= CORPSE_REACH


def _moved_on(route: Route, body: PositionPoint, p: PositionPoint) -> bool:
    if body.instance_id is not None or p.instance_id is not None:
        return p.instance_id != body.instance_id
    d = route.distance(body, p)
    return d is None or d > MOVED_ON


# -- standstills ----------------------------------------------------------------------------------------------

STILL_SECONDS = 90         # not moving a single step at least this long is a standstill
STILL_EDGE = 6             # seconds at both ends that play normally (stopping and setting off)


def still_spans(route: Route, start: float, end: float) -> list[tuple[float, float]]:
    """(from, to) of the standstills within [start, end], in time order: stretches in which the player did not
    move at all (AFK, waiting). The addon keeps them as one sample whose end time it extends, and any step starts
    a new one, so a fight round one camp is never a standstill. Inside dungeons there are no positions, so nothing
    there counts."""
    spans: list[tuple[float, float]] = []
    anchor: PositionPoint | None = None
    prev: PositionPoint | None = None
    began = until = 0.0

    def close() -> None:
        a, b = max(began, start) + STILL_EDGE, min(until, end) - STILL_EDGE
        if anchor is not None and until - began >= STILL_SECONDS and b > a:
            spans.append((a, b))

    for p in route.points_in(start, end):
        if (anchor is not None and prev is not None and route.connected(prev, p)
                and (p.map_id, p.x, p.y) == (anchor.map_id, anchor.x, anchor.y)):
            until = p.end           # the same spot again (a new sample after a reload or a loading screen)
        else:
            close()
            anchor = p if p.x is not None and not p.taxi else None
            began, until = p.time, p.end
        prev = p
    close()
    return spans


# -- teleports ------------------------------------------------------------------------------------------------

TELEPORT_GAP = 120         # seconds between vanishing and arriving at most (a loading screen); longer: a logout
TELEPORT_MIN = 0.03        # continent widths (~450 yards): shorter jumps are not flown
CAST_SECONDS = 5           # standing this long before a jump to the other continent: a hearthstone or a portal
CAST_REACH = 0.0015        # continent widths (~25 yards) the player may shift while casting


@dataclass(frozen=True)
class Teleport:
    depart: int                        # the player vanishes (the end of the last point before) ...
    arrive: int                        # ... and appears (the first point after)
    origin: tuple[float, float]        # on the world map (normalized)
    target: tuple[float, float]
    spirit: bool = False               # the ghost's release to the graveyard
    cause: str | None = None           # recorded by the addon: "hearth" (hearthstone) or "spell" (another teleport)


def teleports(route: Route, deaths: Iterable[Death], start: float, end: float) -> list[Teleport]:
    """The teleports within [start, end], in time order: a step much faster than any mount or flight path, far
    enough to be worth a flight, with a loading screen at most in between. Inside a dungeon the player counts as
    standing at its entrance."""
    releases = {d.released for d in deaths if d.released is not None}
    result: list[Teleport] = []
    i = max(1, bisect.bisect_right(route.times, start))
    for k in range(i, len(route.points)):
        a, b = route.points[k - 1], route.points[k]
        if b.time > end:
            break
        gap = b.time - a.end
        if a.end < start or a.taxi or b.taxi or not 0 <= gap <= TELEPORT_GAP:
            continue
        wa, wb = _world(route, a), _world(route, b)
        if wa is None or wb is None:
            continue
        d = math.hypot(wb[0] - wa[0], wb[1] - wa[1]) / WORLD_PER_CONTINENT      # continent widths
        if not too_fast(d, gap, TELEPORT_MIN):
            continue
        if b.cause is None and _continent(route, a) != _continent(route, b) and not _cast(route, k - 1):
            continue                                                         # a boat or a zeppelin
        result.append(Teleport(a.end, b.time, wa, wb, b.time in releases, b.cause))
    return result


def _spot(route: Route, p: PositionPoint):
    return route.locate(p.map_id, p.x, p.y, p.instance_id)


def _world(route: Route, p: PositionPoint) -> tuple[float, float] | None:
    spot = _spot(route, p)
    return maps.world_xy(*spot, route.map_infos) if spot else None


def _continent(route: Route, p: PositionPoint) -> int | None:
    spot = _spot(route, p)
    return route.continent_or_self(spot[0]) if spot else None


def _cast(route: Route, k: int) -> bool:
    """True when the player stood still for CAST_SECONDS before leaving point k (casting a hearthstone)."""
    last = route.points[k]
    began = last.time
    for j in range(k - 1, -1, -1):
        p = route.points[j]
        d = route.distance(p, last)
        if d is None or d > CAST_REACH or last.end - p.end > CAST_SECONDS * 4:
            break
        began = p.time
    return last.end - began >= CAST_SECONDS
