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
    glyph: str                          # small symbol, where the game icon is missing (wow/game_icons.py)
    color: str                          # glyph colour (as the addon's timeline ticks, UI/Pages/Map.lua)
    describe: Callable[[EventRow], str]  # one-line description
    icon: str = ""                      # the addon's icon of the type (its RegisterEventType icon)
    highlight: str = ""                 # "milestone" | "danger" | "": map pin look, as the addon's
    pin_icon: str = ""                  # map pins: this texture instead of the icon (the addon's pinIcon)
    detail: Callable[[EventRow], str] | None = None  # extra detail (the addon's details tooltip lines)


ICONS = "Interface\\Icons\\"
SCREENSHOT_ICON = ICONS + "INV_Misc_Spyglass_02"  # the addon's chronicle shows screenshots with it

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


def detail(event: EventRow) -> str:
    """The type's extra detail for an event (a death's killing blow), or ""."""
    try:
        fn = get(event.event_type).detail
        return fn(event) if fn else ""
    except Exception:  # a malformed payload must never break the timeline
        return ""


def icon_of(event: EventRow, pin: bool = False) -> int | str:
    """The event's icon as the addon shows it: the one recorded with the event (a fileDataID: achievement,
    profession, recipe), else its type's. pin: the type's map pin texture wins (the death skull)."""
    et = get(event.event_type)
    if pin and et.pin_icon:
        return et.pin_icon
    own = event.payload.get("icon")
    if isinstance(own, int) and not isinstance(own, bool) and own > 0:
        return own
    return et.icon


def all_icons() -> list[str]:
    """Every texture the event types use (the icons kept in git, tools/extract_icons.py)."""
    found = [SCREENSHOT_ICON]
    for et in REGISTRY.values():
        found += [p for p in (et.icon, et.pin_icon) if p and p not in found]
    return found


def location_text(event: EventRow) -> str:
    parts = [p for p in (event.subzone_name, event.zone_name) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    return ", ".join(parts)


def _quest(e: EventRow) -> str:
    title = e.payload.get("title") or f"#{e.payload.get('questID', '?')}"
    return tr("evt.quest_completed.text", title=title)


DEATH_ENVIRONMENTS = ("falling", "drowning", "fatigue", "fire", "lava", "slime")


def death_cause(e: EventRow) -> str:
    """What killed the character, from the game's death recap as the addon recorded it (since 0.15.0):
    "Killed by Hogger", "Drowned", or "" when unknown."""
    p = e.payload
    env = p.get("environment")
    if env in DEATH_ENVIRONMENTS:
        return tr(f"evt.player_died.env.{env}")
    who = p.get("killer") or p.get("spell")
    return tr("evt.player_died.killed_by", killer=who) if who else ""


def _died(e: EventRow) -> str:
    where = e.subzone_name or e.zone_name
    cause = death_cause(e)
    if cause:
        return tr("evt.player_died.cause_in", cause=cause, where=where) if where else cause
    return tr("evt.player_died.text_in", where=where) if where else tr("evt.player_died.text")


def _killing_blow(e: EventRow) -> str:
    """The killing blow: "Uppercut: 412 damage (37 overkill)"."""
    p = e.payload
    damage, overkill = p.get("damage"), p.get("overkill")
    if not isinstance(damage, int):
        return ""
    env = p.get("environment")
    how = p.get("spell") or (tr(f"evt.player_died.env.{env}") if env in DEATH_ENVIRONMENTS
                             else tr("evt.player_died.melee"))
    num = lambda n: f"{n:,}".replace(",", tr("common.thousands_sep"))
    if isinstance(overkill, int) and overkill > 0:
        return tr("evt.player_died.blow_overkill", how=how, damage=num(damage), overkill=num(overkill))
    return tr("evt.player_died.blow", how=how, damage=num(damage))


def _achievement(e: EventRow) -> str:
    name = e.payload.get("name") or f"#{e.payload.get('achievementID', '?')}"
    return tr("evt.achievement_earned.text", name=name)


register(EventType("session_started", "evt.session_started", "◷", "#9d8f75",
                   lambda e: tr("evt.session_started.text"), ICONS + "INV_Misc_PocketWatch_01"))
register(EventType("level_up", "evt.level_up", "▲", "#ffd100",
                   lambda e: tr("evt.level_up.text", level=e.payload.get("level", "?")),
                   ICONS + "Spell_Holy_InnerFire", highlight="milestone"))
register(EventType("quest_completed", "evt.quest_completed", "!", "#ffd100", _quest, ICONS + "INV_Misc_Note_01"))
register(EventType("player_died", "evt.player_died", "☠", "#ff3333", _died, ICONS + "INV_Misc_Bone_HumanSkull_01",
                   highlight="danger", pin_icon="Interface\\TargetingFrame\\UI-TargetingFrame-Skull",
                   detail=_killing_blow))
register(EventType("zone_discovered", "evt.zone_discovered", "⚑", "#73d9ff",
                   lambda e: tr("evt.zone_discovered.text", zone=e.payload.get("zone") or e.zone_name or "?"),
                   ICONS + "INV_Misc_Map_01"))
register(EventType("achievement_earned", "evt.achievement_earned", "★", "#ff8c1a", _achievement,
                   ICONS + "INV_Misc_Book_09", highlight="milestone"))
register(EventType("rare_killed", "evt.rare_killed", "◆", "#cc73ff",
                   lambda e: tr("evt.rare_killed.text", name=e.payload.get("name") or "?"),
                   ICONS + "INV_Misc_Head_Dragon_01"))


def _boss(e: EventRow) -> str:
    name, where = e.payload.get("name") or "?", e.payload.get("instance")
    return tr("evt.boss_killed.text_in", name=name, instance=where) if where else tr("evt.boss_killed.text", name=name)


register(EventType("boss_killed", "evt.boss_killed", "⚔", "#cc8c4d", _boss, ICONS + "INV_Sword_04"))
register(EventType("dungeon_completed", "evt.dungeon_completed", "♛", "#ffffff",
                   lambda e: tr("evt.dungeon_completed.text", instance=e.payload.get("instance") or "?",
                                boss=e.payload.get("boss") or "?"),
                   ICONS + "INV_Misc_Key_03", highlight="milestone"))


def rank_name(max_rank: int | None) -> str:
    """Classic rank by maximum skill (Apprentice 75 ... Artisan 300); other values show the number."""
    key = {75: "rank.apprentice", 150: "rank.journeyman", 225: "rank.expert", 300: "rank.artisan"}.get(max_rank or 0)
    return tr(key) if key else str(max_rank or "?")


def _recipe(e: EventRow) -> str:
    name = e.payload.get("name") or f"#{e.payload.get('recipeID', '?')}"
    return tr("evt.recipe_learned.text", name=name)


register(EventType("profession_learned", "evt.profession_learned", "⚒", "#40c040",
                   lambda e: tr("evt.profession_learned.text", name=e.payload.get("name") or "?"),
                   ICONS + "Trade_BlackSmithing", highlight="milestone"))
register(EventType("profession_rank", "evt.profession_rank", "⚒", "#40c040",
                   lambda e: tr("evt.profession_rank.text", name=e.payload.get("name") or "?",
                                rank=rank_name(e.payload.get("maxRank"))),
                   ICONS + "Trade_BlackSmithing"))
register(EventType("recipe_learned", "evt.recipe_learned", "✎", "#40c040", _recipe, ICONS + "INV_Scroll_03"))
