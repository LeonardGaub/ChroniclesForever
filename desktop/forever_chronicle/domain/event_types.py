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
    color: str                          # glyph colour
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
register(EventType("player_died", "evt.player_died", "☠", "#ff4040", _died))
register(EventType("zone_discovered", "evt.zone_discovered", "⚑", "#69ccf0",
                   lambda e: tr("evt.zone_discovered.text", zone=e.payload.get("zone") or e.zone_name or "?")))
register(EventType("achievement_earned", "evt.achievement_earned", "★", "#ff8000", _achievement))
