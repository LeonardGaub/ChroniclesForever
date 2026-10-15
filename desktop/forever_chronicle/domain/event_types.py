"""Registry of event types: how each recorded event is named and shown in the timeline.

To support a new event type from the addon, register an EventType here (or in a new module that
is imported by ``domain/__init__.py``). Unknown types are still shown, using their raw type key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..i18n import tr
from ..storage.repository import EventRow


@dataclass(frozen=True)
class EventType:
    key: str
    label_key: str                      # i18n key: name of the type (filters, legends)
    glyph: str                          # small symbol for the timeline
    color: str                          # glyph colour (as the addon's timeline ticks, UI/Pages/Map.lua)
    describe: Callable[[EventRow], str]  # one-line description


REGISTRY: dict[str, EventType] = {}


def register(event_type: EventType) -> None:
    REGISTRY[event_type.key] = event_type


def get(key: str) -> EventType:
    return REGISTRY.get(key) or EventType(key, key, "•", "#9d8f75", lambda e: e.event_type)


def describe(event: EventRow) -> str:
    try:
        return get(event.event_type).describe(event)
    except Exception:  # a malformed payload must never break the timeline
        return event.event_type


def location_text(event: EventRow) -> str:
    parts = [p for p in (event.subzone_name, event.zone_name) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    return ", ".join(parts)


def _quest(e: EventRow) -> str:
    title = e.payload.get("title") or f"#{e.payload.get('questID', '?')}"
    return tr("evt.quest_completed.text", title=title)


def _died(e: EventRow) -> str:
    where = e.subzone_name or e.zone_name
    return tr("evt.player_died.text_in", where=where) if where else tr("evt.player_died.text")


def _achievement(e: EventRow) -> str:
    name = e.payload.get("name") or f"#{e.payload.get('achievementID', '?')}"
    return tr("evt.achievement_earned.text", name=name)


register(EventType("session_started", "evt.session_started", "◷", "#9d8f75",
                   lambda e: tr("evt.session_started.text")))
register(EventType("level_up", "evt.level_up", "▲", "#ffd100",
                   lambda e: tr("evt.level_up.text", level=e.payload.get("level", "?"))))
register(EventType("quest_completed", "evt.quest_completed", "!", "#ffd100", _quest))
register(EventType("player_died", "evt.player_died", "☠", "#ff3333", _died))
register(EventType("zone_discovered", "evt.zone_discovered", "⚑", "#73d9ff",
                   lambda e: tr("evt.zone_discovered.text", zone=e.payload.get("zone") or e.zone_name or "?")))
register(EventType("achievement_earned", "evt.achievement_earned", "★", "#ff8c1a", _achievement))
register(EventType("rare_killed", "evt.rare_killed", "◆", "#cc73ff",
                   lambda e: tr("evt.rare_killed.text", name=e.payload.get("name") or "?")))


def _boss(e: EventRow) -> str:
    name, where = e.payload.get("name") or "?", e.payload.get("instance")
    return tr("evt.boss_killed.text_in", name=name, instance=where) if where else tr("evt.boss_killed.text", name=name)


register(EventType("boss_killed", "evt.boss_killed", "⚔", "#cc8c4d", _boss))
register(EventType("dungeon_completed", "evt.dungeon_completed", "♛", "#ffffff",
                   lambda e: tr("evt.dungeon_completed.text", instance=e.payload.get("instance") or "?",
                                boss=e.payload.get("boss") or "?")))


def rank_name(max_rank: int | None) -> str:
    """Classic rank by maximum skill (Apprentice 75 ... Artisan 300); other values show the number."""
    key = {75: "rank.apprentice", 150: "rank.journeyman", 225: "rank.expert", 300: "rank.artisan"}.get(max_rank or 0)
    return tr(key) if key else str(max_rank or "?")


def _recipe(e: EventRow) -> str:
    name = e.payload.get("name") or f"#{e.payload.get('recipeID', '?')}"
    return tr("evt.recipe_learned.text", name=name)


register(EventType("profession_learned", "evt.profession_learned", "⚒", "#40c040",
                   lambda e: tr("evt.profession_learned.text", name=e.payload.get("name") or "?")))
register(EventType("profession_rank", "evt.profession_rank", "⚒", "#40c040",
                   lambda e: tr("evt.profession_rank.text", name=e.payload.get("name") or "?",
                                rank=rank_name(e.payload.get("maxRank")))))
register(EventType("recipe_learned", "evt.recipe_learned", "✎", "#40c040", _recipe))
