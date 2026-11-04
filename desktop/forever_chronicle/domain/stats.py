"""Registry of character statistics shown on the overview page.

Each Stat computes one value from the database. To add a statistic, register a new Stat; the
overview page picks it up automatically, ordered by ``order``, as a tile with its game icon: the addon's
RegisterStat icon where the addon has the stat (rerun tools/extract_icons.py after giving a stat a new icon).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from ..i18n import format_date, format_duration, tr
from ..storage.repository import Repository


@dataclass(frozen=True)
class Stat:
    key: str
    label_key: str
    order: int
    compute: Callable[[Repository, str], Any]
    kind: str = "number"                # number | duration | date | text
    group: str = "progress"             # i18n heading stats.group.<group>, description stats.group.<group>.desc
    icon: str = ""                      # the tile's game texture (wow/game_icons.py)


STATS: list[Stat] = []
I = "Interface\\Icons\\"


def register(stat: Stat) -> None:
    STATS.append(stat)
    STATS.sort(key=lambda s: s.order)


def all_icons() -> list[str]:
    """Every texture the stat tiles use (kept in git like the event types' icons, tools/extract_icons.py)."""
    return [s.icon for s in STATS if s.icon]


def compute_all(repo: Repository, character_id: str) -> list[tuple[Stat, Any]]:
    out = []
    for stat in STATS:
        try:
            value = stat.compute(repo, character_id)
        except Exception:
            value = None
        out.append((stat, value))
    return out


def format_value(stat: Stat, value: Any) -> str:
    if value is None:
        return tr("common.unknown")
    if stat.kind == "duration":
        return format_duration(value)
    if stat.kind == "date":
        return format_date(value)
    if stat.kind == "number" and isinstance(value, float):
        return f"{value:.1f}".replace(".", tr("common.decimal_sep"))
    if stat.kind == "number" and isinstance(value, int):
        return f"{value:,}".replace(",", tr("common.thousands_sep"))
    return str(value)


# -- session statistics -------------------------------------------------------------

def session_durations(repo: Repository, cid: str) -> list[int]:
    out = []
    for s in repo.sessions(cid):
        end = s["ended_at"] or (int(time.time()) if s["end_reason"] == "open" else None)
        if end and end > s["started_at"]:
            out.append(end - s["started_at"])
    return out


def _played_total(repo: Repository, cid: str) -> int | None:
    for s in repo.sessions(cid):
        if s["played_total_seconds"] is not None:
            return s["played_total_seconds"]
    return None


def _first_tracked(repo: Repository, cid: str) -> int | None:
    sessions = repo.sessions(cid)
    return min((s["started_at"] for s in sessions), default=None)


def _per_hour(event_type: str) -> Callable[[Repository, str], float | None]:
    def compute(repo: Repository, cid: str) -> float | None:
        seconds = sum(session_durations(repo, cid))
        if seconds < 3600:
            return None
        return repo.count_events(cid, event_type) / (seconds / 3600)
    return compute


register(Stat("played_total", "stats.played_total", 10, _played_total, "duration", "time",
              I + "INV_Misc_PocketWatch_01"))
register(Stat("sessions", "stats.sessions", 12, lambda r, c: len(r.sessions(c)), "number", "time",
              I + "Spell_Nature_TimeStop"))
# Only in the app (no addon icon): an hourglass for the longest session, an old tome for the first record.
register(Stat("longest_session", "stats.longest_session", 13,
              lambda r, c: max(session_durations(r, c), default=None), "duration", "time",
              I + "Spell_Holy_BorrowedTime"))
register(Stat("first_tracked", "stats.first_tracked", 14, _first_tracked, "date", "time", I + "INV_Misc_Book_07"))

def _counter(key: str) -> Callable[[Repository, str], Any]:
    """A counter kept by the addon (imported from its saved data)."""
    def compute(repo: Repository, cid: str) -> int | None:
        value = repo.character_stat(cid, key)
        return int(value) if value is not None else None
    return compute


register(Stat("kills", "stats.kills", 18, _counter("kills"), icon=I + "Ability_Hunter_SniperShot"))
register(Stat("xp_earned", "stats.xp_earned", 19, _counter("xp_earned"), icon=I + "Spell_Holy_InnerFire"))
register(Stat("rares", "stats.rares", 20, lambda r, c: r.count_events(c, "rare_killed"),
              icon=I + "INV_Misc_Head_Dragon_01"))
register(Stat("quests", "stats.quests", 21, lambda r, c: r.count_events(c, "quest_completed"),
              icon=I + "INV_Misc_Note_01"))
# Only in the app: Sprint for the pace.
register(Stat("quests_per_hour", "stats.quests_per_hour", 22, _per_hour("quest_completed"),
              icon=I + "Ability_Rogue_Sprint"))
register(Stat("deaths", "stats.deaths", 23, lambda r, c: r.count_events(c, "player_died"),
              icon=I + "INV_Misc_Bone_HumanSkull_01"))
register(Stat("achievements", "stats.achievements", 24, lambda r, c: r.count_events(c, "achievement_earned"),
              icon=I + "INV_Misc_Ribbon_01"))
register(Stat("zones", "stats.zones", 25, lambda r, c: r.count_events(c, "zone_discovered"),
              icon=I + "INV_Misc_Map_01"))
register(Stat("fish_caught", "stats.fish_caught", 27, _counter("fish_caught"), icon=I + "INV_Misc_Fish_02"))
register(Stat("jumps", "stats.jumps", 28, _counter("jumps"), icon=I + "INV_Gizmo_RocketBoot_01"))
