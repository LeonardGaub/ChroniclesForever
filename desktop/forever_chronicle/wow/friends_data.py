"""Writes friends' characters for the addon (docs/Sharing_Design.md, phase 2):
``<client>\\Interface\\AddOns\\ForeverChronicle\\Friends\\FriendsData.lua``.

The game runs this file as Lua code at every UI load, and its content comes from other people's share files.
It is therefore produced by a strict serializer: only numbers, booleans, strings and tables; every string is
plain ASCII with all quotes, backslashes, control characters and non-ASCII bytes written as \\ddd escapes, so no
value can end a string or inject code. Each character is built inside its own function, which keeps every
function far below Lua 5.1's limit of constants per function.

Every friend character has the same shape as the addon's own character records (info, stats, streams,
snapshots), trimmed so the file stays small even for ~10 friends with several characters each.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import ADDON_NAME, ClientInstall

EVENTS_PER_CHARACTER = 200        # newest chronicle entries per character
ROUTE_SESSIONS = 3                # routes of the newest sessions per character
POINTS_WITHOUT_SESSIONS = 3000    # newest points when no sessions were shared
MAX_POINTS_TOTAL = 60000          # all friends together
MAX_STRING = 500                  # longest string value taken from event payloads
MAX_DEPTH = 12
FILE_PARTS = ("Friends", "FriendsData.lua")


class LuaSerializeError(ValueError):
    pass


def lua_string(text: str) -> str:
    """A Lua string literal that is plain ASCII: only safe printable characters stay as they are."""
    out = ['"']
    for b in text.encode("utf-8"):
        if 0x20 <= b < 0x7F and b not in (0x22, 0x5C):   # printable ASCII except " and \
            out.append(chr(b))
        else:
            out.append(f"\\{b:03d}")
    out.append('"')
    return "".join(out)


def lua_value(value: Any, depth: int = 0) -> str:
    if depth > MAX_DEPTH:
        raise LuaSerializeError("nested too deeply")
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LuaSerializeError("not a finite number")
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (list, tuple)):
        return "{" + ",".join(lua_value(v, depth + 1) for v in value) + "}"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if v is None:
                continue
            if isinstance(k, bool) or not isinstance(k, (str, int)):
                raise LuaSerializeError("table keys must be strings or integers")
            key = f"[{k}]" if isinstance(k, int) else f"[{lua_string(k)}]"
            parts.append(f"{key}={lua_value(v, depth + 1)}")
        return "{" + ",".join(parts) + "}"
    raise LuaSerializeError(f"unsupported value {type(value).__name__}")


# -- data ------------------------------------------------------------------------------------


def _clip(value: Any, depth: int = 0) -> Any:
    """Event payloads come from JSON: keep plain values, shorten long strings, drop anything odd."""
    if depth > 6:
        return None
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if not isinstance(value, float) or math.isfinite(value) else None
    if isinstance(value, list):
        return [_clip(v, depth + 1) for v in value[:50]]
    if isinstance(value, dict):
        return {k: _clip(v, depth + 1) for k, v in list(value.items())[:50] if isinstance(k, str)}
    return None


def _info(c: sqlite3.Row) -> dict[str, Any]:
    return {"key": c["natural_key"], "guid": c["player_guid"], "name": c["name"], "nameSuffix": c["name_suffix"],
            "realm": c["realm"], "className": c["class_name"], "classFile": c["class_file"], "raceName": c["race_name"],
            "raceFile": c["race_file"], "faction": c["faction"], "level": c["level"],
            "firstSeenAt": c["first_seen_at"], "lastSeenAt": c["last_seen_at"]}


def _events(conn: sqlite3.Connection, cid: str) -> list[dict[str, Any]]:
    rows = conn.execute("""SELECT * FROM events WHERE character_id = ? ORDER BY occurred_at DESC, seq DESC LIMIT ?""",
                        (cid, EVENTS_PER_CHARACTER)).fetchall()
    out = []
    for r in reversed(rows):
        try:
            data = json.loads(r["payload_json"])
        except (TypeError, ValueError):
            data = {}
        location = {"zone": r["zone_name"], "subzone": r["subzone_name"], "mapID": r["map_id"], "x": r["x"],
                    "y": r["y"], "instanceID": r["instance_id"], "quality": r["location_quality"]}
        out.append({"id": r["event_id"], "seq": r["seq"], "type": r["event_type"], "time": r["occurred_at"],
                    "location": {k: v for k, v in location.items() if v is not None} or None,
                    "data": _clip(data) if isinstance(data, dict) else {}})
    return out


def _sessions(conn: sqlite3.Connection, cid: str, last_seen: int | None) -> list[dict[str, Any]]:
    out = []
    for r in conn.execute("SELECT * FROM sessions WHERE character_id = ? ORDER BY started_at", (cid,)):
        ended = r["ended_at"]
        reason = r["end_reason"]
        if ended is None:  # still open when shared: closed at the last time the friend's app knew of
            ended, reason = max(r["started_at"], last_seen or r["started_at"]), "incomplete"
        out.append({"id": r["session_id"], "seq": r["seq"], "startedAt": r["started_at"], "endedAt": ended,
                    "endReason": reason, "reloads": r["reload_count"], "startLevel": r["start_level"],
                    "endLevel": r["end_level"], "playedTotal": r["played_total_seconds"],
                    "playedLevel": r["played_level_seconds"], "playedAt": r["played_at"]})
    return out


def _point(r: sqlite3.Row) -> str:
    """The addon's compact position format: time,mapID,x,y,until,flags,instanceID."""
    def num(v):
        return "" if v is None else f"{v:.4f}"
    return ",".join([str(r["occurred_at"]), "" if r["map_id"] is None else str(r["map_id"]), num(r["x"]),
                     num(r["y"]), "" if r["until_at"] is None else str(r["until_at"]), "T" if r["on_taxi"] else "",
                     "" if r["instance_id"] is None else str(r["instance_id"])])


def _positions(conn: sqlite3.Connection, cid: str, sessions: list[dict[str, Any]], limit: int) -> list[str]:
    if sessions:
        since = sessions[-ROUTE_SESSIONS:][0]["startedAt"]
        rows = conn.execute("""SELECT * FROM positions WHERE character_id = ? AND occurred_at >= ?
                               ORDER BY occurred_at DESC LIMIT ?""", (cid, since, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM positions WHERE character_id = ? ORDER BY occurred_at DESC LIMIT ?",
                            (cid, min(limit, POINTS_WITHOUT_SESSIONS))).fetchall()
    return [_point(r) for r in reversed(rows)]


def _professions(conn: sqlite3.Connection, cid: str) -> dict[str, Any]:
    out = []
    for p in conn.execute("SELECT * FROM professions WHERE character_id = ? AND active = 1", (cid,)):
        prof = {"skillLine": p["skill_line"], "name": p["name"], "icon": p["icon"], "kind": p["kind"], "rank": p["rank"],
                "maxRank": p["max_rank"], "modifier": p["modifier"], "active": True, "updatedAt": p["updated_at"]}
        if p["recipe_status"] in ("complete", "partial"):
            recipes = [",".join(["" if v is None else str(v) for v in (r["recipe_id"], r["category_id"], r["icon"],
                                                                       r["quality"])] + [r["name"]])
                       for r in conn.execute("SELECT * FROM recipes WHERE character_id = ? AND skill_line = ? "
                                             "ORDER BY recipe_id", (cid, p["skill_line"]))]
            categories = [",".join([str(c["category_id"]), "" if c["parent_id"] is None else str(c["parent_id"]),
                                    c["name"]])
                          for c in conn.execute("SELECT * FROM recipe_categories WHERE character_id = ? AND "
                                                "skill_line = ?", (cid, p["skill_line"]))]
            prof["recipes"] = {"status": p["recipe_status"], "updatedAt": p["recipes_updated_at"],
                               "total": p["recipes_total"], "format": 2, "list": recipes, "categories": categories}
        out.append(prof)
    return {"list": out, "baseline": True}


def _gear(conn: sqlite3.Connection, cid: str) -> dict[str, Any]:
    """The addon's gear snapshot shape (Modules/Gear.lua)."""
    rows = conn.execute("SELECT * FROM gear WHERE character_id = ? ORDER BY slot", (cid,)).fetchall()
    return {"updatedAt": max((r["updated_at"] or 0 for r in rows), default=None) or None,
            "slots": [{"slot": r["slot"], "slotName": r["slot_name"], "link": r["link"], "item": r["item_id"],
                       "icon": r["icon"], "quality": r["quality"]} for r in rows]}


def build_friends_data(conn: sqlite3.Connection, now: int | None = None) -> dict[str, Any]:
    """All friends' characters in the addon's own record shape, trimmed (see the limits above)."""
    owners = conn.execute("SELECT * FROM owners ORDER BY display_name COLLATE NOCASE").fetchall()
    chars = conn.execute("SELECT * FROM characters WHERE owner_id IS NOT NULL ORDER BY last_seen_at DESC").fetchall()
    per_char_points = MAX_POINTS_TOTAL // max(1, len(chars))
    friends, map_ids, instance_ids = [], set(), set()
    for o in owners:
        characters = []
        for c in chars:
            if c["owner_id"] != o["owner_id"]:
                continue
            cid = c["character_id"]
            sessions = _sessions(conn, cid, c["last_seen_at"])
            points = _positions(conn, cid, sessions, per_char_points)
            events = _events(conn, cid)
            stats = {r[0]: r[1] for r in conn.execute(
                "SELECT stat_key, value FROM character_stats WHERE character_id = ?", (cid,))}
            for e in events:
                loc = e["location"] or {}
                map_ids.add(loc.get("mapID"))
                instance_ids.add(loc.get("instanceID"))
            for p in points:
                fields = p.split(",")
                map_ids.add(int(fields[1]) if fields[1] else None)
                instance_ids.add(int(fields[6]) if fields[6] else None)
            characters.append({
                "info": _info(c),
                "stats": {k: (int(v) if float(v).is_integer() else v) for k, v in stats.items()},
                "streams": {"events": {"records": events}, "sessions": {"records": sessions},
                            "positions": {"nextSeq": len(points) + 1, "records": points}},
                "snapshots": {"professions": _professions(conn, cid), "gear": _gear(conn, cid)},
            })
        friends.append({"name": o["display_name"], "sharedAt": o["shared_at"], "characters": characters})

    maps = {}
    for r in conn.execute("SELECT * FROM map_info"):
        if r["map_id"] in map_ids:
            maps[str(r["map_id"])] = {"name": r["name"], "mapType": r["map_type"], "parent": r["parent_map_id"],
                                      "continent": r["continent_id"], "minX": r["min_x"], "maxX": r["max_x"],
                                      "minY": r["min_y"], "maxY": r["max_y"]}
    continents = {m["continent"] for m in maps.values() if m["continent"]}
    for r in conn.execute("SELECT * FROM map_info"):
        if r["map_id"] in continents and str(r["map_id"]) not in maps:
            maps[str(r["map_id"])] = {"name": r["name"], "mapType": r["map_type"], "parent": r["parent_map_id"]}
    instances = {str(r[0]): r[1] for r in conn.execute("SELECT instance_id, name FROM instances") if r[0] in instance_ids}
    entrances = {str(r[0]): {"mapID": r[1], "x": r[2], "y": r[3]}
                 for r in conn.execute("SELECT instance_id, map_id, x, y FROM instance_entrances") if r[0] in instance_ids}
    return {"version": 1, "generatedAt": now or int(time.time()), "friends": friends, "maps": maps,
            "instances": instances, "entrances": entrances}


def render(data: dict[str, Any]) -> str:
    """The Lua file. Every character is built in its own function (constants limit per function)."""
    lines = ["-- Forever Chronicle: friends' characters, written by the desktop app. Do not edit; it is replaced.",
             "ForeverChronicleFriends = " + lua_value({k: v for k, v in data.items() if k != "friends"} | {"friends": []}),
             "local F = ForeverChronicleFriends.friends"]
    for i, friend in enumerate(data["friends"], 1):
        head = {k: v for k, v in friend.items() if k != "characters"} | {"characters": []}
        lines.append(f"F[{i}] = {lua_value(head)}")
        for j, char in enumerate(friend["characters"], 1):
            lines.append(f"F[{i}].characters[{j}] = (function() return {lua_value(char)} end)()")
    return "\n".join(lines) + "\n"


@dataclass
class FriendsDataResult:
    status: str                  # ok | no_client | no_addon | failed
    path: Path | None = None
    friends: int = 0
    characters: int = 0
    size: int = 0
    message: str | None = None


def friends_data_path(client: ClientInstall) -> Path:
    return client.addons_dir / ADDON_NAME / FILE_PARTS[0] / FILE_PARTS[1]


def write_friends_data(conn: sqlite3.Connection, client: ClientInstall | None) -> FriendsDataResult:
    """Writes the file for the addon (also when there are no friends: an empty list replaces old data)."""
    if client is None:
        return FriendsDataResult("no_client")
    addon = client.addons_dir / ADDON_NAME
    if not (addon / f"{ADDON_NAME}.toc").is_file():
        return FriendsDataResult("no_addon", path=addon)
    path = friends_data_path(client)
    data = build_friends_data(conn)
    try:
        text = render(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="ascii", newline="\n")
        os.replace(tmp, path)
    except (OSError, LuaSerializeError) as exc:
        return FriendsDataResult("failed", path=path, message=str(exc))
    return FriendsDataResult("ok", path=path, friends=len(data["friends"]),
                             characters=sum(len(f["characters"]) for f in data["friends"]), size=len(text))
