"""The cinematic replay's end credits: what the journey in the replayed range adds up to, as sections of credits
lines (a small gold role above a larger name, as in the game's credits). Lines without a value are left out.

Distances are estimates: the route's map coordinates are turned into yards with the size of each continent map
(CONTINENT_YARDS, the community's map data for Classic), and shown in kilometres.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from ..i18n import format_date, format_duration, tr
from ..storage.repository import EventRow
from . import event_types, maps
from .cinematic import Death, Levels, Teleport
from .route import Route

# Width of each continent's map in yards (the height follows from the map's 1002 x 668 shape).
CONTINENT_YARDS = {maps.KALIMDOR: 36800.0, maps.EASTERN_KINGDOMS: 40741.0}
METRES_PER_YARD = 0.9144
GAP = 30                   # breaks without points longer than this are not playing time (as the replay)


@dataclass
class Line:
    role: str              # small, gold
    name: str              # large


@dataclass
class Section:
    heading: str
    lines: list[Line] = field(default_factory=list)


@dataclass
class Journey:
    played: float = 0.0
    level_from: int | None = None
    level_to: int | None = None
    walked_yards: float = 0.0
    flown_yards: float = 0.0
    flights: int = 0
    teleports: int = 0
    zones: list[int] = field(default_factory=list)              # visited, most time first
    dungeons: list[int] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)            # events per type
    deaths: int = 0
    killer: tuple[str, int] | None = None                       # most frequent cause, times
    screenshots: int = 0
    standing: float = 0.0


def journey(route: Route, events: Iterable[EventRow], levels: Levels, start: float, end: float,
            deaths: Iterable[Death] = (), teleports: Iterable[Teleport] = (), screenshots: int = 0,
            still_spans: Iterable[tuple[float, float]] = ()) -> Journey:
    """The journey's numbers. Dungeons are the instances the route went into where a boss died: cities can be
    instances too (Undercity's Ruins of Lordaeron), and nothing else tells them apart."""
    events = list(events)
    j = Journey()
    j.played = route.timeline(start, end, GAP).total
    j.level_from, j.level_to = levels.at(start), levels.at(end)
    _distances(route, start, end, j)
    time_in: Counter = Counter()
    dungeons: list[int] = []
    for run in route.zone_runs(start, end):
        if run.instance_id is not None:
            if run.instance_id not in dungeons:
                dungeons.append(run.instance_id)
        elif run.map_id is not None and run.map_id not in maps.CONTINENT_IN_WORLD and run.map_id != maps.WORLD:
            time_in[run.map_id] += run.to - run.start
    j.zones = [z for z, _ in time_in.most_common()]
    bosses = {e.payload.get("instanceID") for e in events
              if e.event_type in ("boss_killed", "dungeon_completed") and start <= e.occurred_at <= end}
    j.dungeons = [d for d in dungeons if d in bosses]
    causes: Counter = Counter()
    for e in events:
        if not start <= e.occurred_at <= end:
            continue
        j.counts[e.event_type] += 1
        if e.event_type == "player_died":
            cause = event_types.death_cause(e)
            if cause:
                causes[cause] += 1
    j.deaths = len([d for d in deaths if start <= d.time <= end])
    if causes:
        j.killer = causes.most_common(1)[0]
    j.teleports = len([t for t in teleports if not t.spirit])
    j.screenshots = screenshots
    j.standing = sum(b - a for a, b in still_spans)
    return j


def _distances(route: Route, start: float, end: float, j: Journey) -> None:
    """Walked (and ridden) and flown distance in yards, and the number of flights, over connected route lines."""
    prev = None
    for p in route.points:
        if p.end < start:
            continue
        if p.time > end:
            break
        if prev is not None and route.connected(prev, p, maps.WORLD):
            d = _yards(route, prev, p)
            if d is not None:
                if p.taxi:
                    j.flown_yards += d
                else:
                    j.walked_yards += d
        if p.taxi and (prev is None or not prev.taxi):
            j.flights += 1
        prev = p


def _yards(route: Route, a, b) -> float | None:
    if a.map_id is None or a.x is None or b.x is None:
        return None
    continent = a.map_id if a.map_id in CONTINENT_YARDS else route.continent(a.map_id)
    width = CONTINENT_YARDS.get(continent)
    pa = route.project(a.map_id, a.x, a.y, continent) if width else None
    pb = route.project(b.map_id, b.x, b.y, continent) if width else None
    if pa is None or pb is None:
        return None
    height = width * maps.ART_HEIGHT / maps.ART_WIDTH
    return math.hypot((pb[0] - pa[0]) * width, (pb[1] - pa[1]) * height)


def km(yards: float) -> str:
    value = yards * METRES_PER_YARD / 1000
    text = f"{value:.1f}" if value < 10 else f"{value:.0f}"
    return text.replace(".", tr("common.decimal_sep"))


def sections(j: Journey, name: str, start: float, end: float, zone_name, dungeon_name) -> tuple[list[str], list[Section]]:
    """(title lines, sections) of the credits. zone_name(map_id) and dungeon_name(instance_id) name places."""
    first, last = format_date(int(start)), format_date(int(end))
    title = [name, tr("credits.subtitle"), first if first == last else tr("credits.dates", first=first, last=last)]
    result: list[Section] = []

    def add(heading: str, rows: list[tuple[str, str | None]]) -> None:
        lines = [Line(role, value) for role, value in rows if value]
        if lines:
            result.append(Section(heading, lines))

    c = j.counts
    level = None
    if j.level_from and j.level_to and j.level_to > j.level_from:
        level = tr("credits.level_range", a=j.level_from, b=j.level_to)
    elif j.level_to:
        level = str(j.level_to)
    add(tr("credits.journey"), [
        (tr("credits.played"), format_duration(int(j.played)) if j.played >= 60 else None),
        (tr("credits.level"), level),
        (tr("credits.walked"), tr("credits.km", km=km(j.walked_yards)) if j.walked_yards >= 200 else None),
        (tr("credits.flights"), tr("credits.flights_value", n=j.flights, km=km(j.flown_yards)) if j.flights else None),
        (tr("credits.teleports"), str(j.teleports) if j.teleports else None),
        (tr("credits.standing"), format_duration(int(j.standing)) if j.standing >= 300 else None),
    ])
    add(tr("credits.places"), [
        (tr("credits.home"), zone_name(j.zones[0]) if j.zones else None),
        (tr("credits.zones"), str(len(j.zones)) if len(j.zones) > 1 else None),
        (tr("credits.discovered"), str(c["zone_discovered"]) if c["zone_discovered"] else None),
        (tr("credits.dungeons"), ", ".join(dungeon_name(d) for d in j.dungeons[:4])
         + (f" +{len(j.dungeons) - 4}" if len(j.dungeons) > 4 else "") if j.dungeons else None),
    ])
    add(tr("credits.deeds"), [
        (tr("credits.quests"), str(c["quest_completed"]) if c["quest_completed"] else None),
        (tr("credits.achievements"), str(c["achievement_earned"]) if c["achievement_earned"] else None),
        (tr("credits.rares"), str(c["rare_killed"]) if c["rare_killed"] else None),
        (tr("credits.bosses"), str(c["boss_killed"]) if c["boss_killed"] else None),
        (tr("credits.completed"), str(c["dungeon_completed"]) if c["dungeon_completed"] else None),
        (tr("credits.screenshots"), str(j.screenshots) if j.screenshots else None),
    ])
    add(tr("credits.fallen"), [
        (tr("credits.deaths"), str(j.deaths) if j.deaths else None),
        (tr("credits.killer"), (f"{j.killer[0]} ({j.killer[1]}×)" if j.killer[1] > 1 else j.killer[0])
         if j.killer else None),
    ])
    return title, result
