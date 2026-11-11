"""Queries used by the importer and the UI. All SQL lives here."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class Character:
    character_id: str
    name: str
    name_suffix: str | None
    realm: str | None
    level: int | None
    class_name: str | None
    class_file: str | None
    race_name: str | None
    faction: str | None
    last_seen_at: int | None
    owner_id: int | None = None         # None = my own character, else a friend (owners table)
    owner_name: str | None = None
    xp: tuple[int, int, int] | None = None   # the experience bar last seen: (when, xp, xp to the next level)
    race_file: str | None = None        # the game's race token ("Scourge", "NightElf", ...)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Character":
        keys = row.keys()
        return cls(row["character_id"], row["name"], row["name_suffix"], row["realm"], row["level"],
                   row["class_name"], row["class_file"], row["race_name"], row["faction"], row["last_seen_at"],
                   row["owner_id"] if "owner_id" in keys else None,
                   row["owner_name"] if "owner_name" in keys else None,
                   (row["xp_at"], row["xp"], row["xp_max"]) if "xp_at" in keys and row["xp_at"] is not None
                   and row["xp"] is not None and row["xp_max"] else None,
                   row["race_file"] if "race_file" in keys else None)

    @property
    def is_friend(self) -> bool:
        return self.owner_id is not None

    @property
    def full_name(self) -> str:
        """Name with the last name that Forever characters have (second value of UnitName)."""
        return f"{self.name} {self.name_suffix}" if self.name_suffix else self.name


@dataclass
class EventRow:
    character_id: str
    event_id: str
    event_type: str
    occurred_at: int
    zone_name: str | None
    subzone_name: str | None
    map_id: int | None
    x: float | None
    y: float | None
    payload: dict[str, Any]
    instance_id: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "EventRow":
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = {}
        return cls(row["character_id"], row["event_id"], row["event_type"], row["occurred_at"],
                   row["zone_name"], row["subzone_name"], row["map_id"], row["x"], row["y"], payload,
                   row["instance_id"])


# Some servers send PLAYER_DEAD twice for one death; addons up to 0.16.0 recorded both (the first with the killer,
# the second with the release and revival). A death this many seconds after a death not revived yet is that echo.
DEATH_ECHO = 3


def _echo_of(kept: EventRow, death: EventRow) -> bool:
    revived = kept.payload.get("revivedAt")
    return (death.character_id == kept.character_id and 0 <= death.occurred_at - kept.occurred_at <= DEATH_ECHO
            and not (isinstance(revived, int) and revived <= death.occurred_at))


def merge_death_echoes(rows: list[EventRow]) -> list[EventRow]:
    """rows (in recording order) with each death's echo (DEATH_ECHO) folded into the death: one event that has both
    halves' data, the first one's where both have a value."""
    deaths = [r for r in rows if r.event_type == "player_died"]
    if len(deaths) < 2:
        return rows
    merged: dict[int, EventRow] = {}         # id of the kept row -> the kept row with its echo's data
    dropped: set[int] = set()
    kept: EventRow | None = None
    for death in sorted(deaths, key=lambda r: (r.character_id, r.occurred_at)):   # stable: ties keep their order
        current = merged.get(id(kept)) if kept is not None else None
        if kept is not None and _echo_of(current or kept, death):
            base = current or kept
            merged[id(kept)] = EventRow(**{**base.__dict__, "payload": {**death.payload, **base.payload}})
            dropped.add(id(death))
        else:
            kept = death
    return [merged.get(id(r), r) for r in rows if id(r) not in dropped]


@dataclass(frozen=True)
class PositionPoint:
    time: int
    until: int | None
    map_id: int | None
    x: float | None
    y: float | None
    instance_id: int | None
    taxi: bool
    jump: bool = False                  # first point after a loading screen: not connected to the one before
    mounted: bool = False               # riding (not on a flight path)
    cause: str | None = None            # a teleport the player cast: "hearth" (hearthstone) or "spell"

    @property
    def end(self) -> int:
        return self.until or self.time

    @classmethod
    def parse(cls, text: str) -> "PositionPoint | None":
        """Parses the addon's compact format: time,mapID,x,y,until,flags,instanceID."""
        parts = text.split(",")
        if len(parts) != 7:
            return None
        try:
            t = int(parts[0])
            map_id = int(parts[1]) if parts[1] else None
            x = float(parts[2]) if parts[2] else None
            y = float(parts[3]) if parts[3] else None
            until = int(parts[4]) if parts[4] else None
            instance_id = int(parts[6]) if parts[6] else None
        except ValueError:
            return None
        if (x is None) != (y is None) or (map_id is None and instance_id is None):
            return None
        if x is not None and not (0 <= x <= 1 and 0 <= y <= 1):
            return None
        flags = parts[5]
        cause = "hearth" if "H" in flags else "spell" if "P" in flags else None
        return cls(t, until, map_id, x, y, instance_id, "T" in flags, "J" in flags, "M" in flags, cause)


def int_or_none(text: Any) -> int | None:
    if isinstance(text, bool):
        return None
    if isinstance(text, int):
        return text
    if isinstance(text, float) and text.is_integer():
        return int(text)
    if isinstance(text, str) and text.isdigit():
        return int(text)
    return None


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _upsert(self, table: str, values: dict[str, Any], key: tuple[str, ...],
                update: Iterable[str] | None = None) -> None:
        """Inserts a row; if one with the same key exists, sets its other columns (or only `update`) instead."""
        sets = ", ".join(f"{c} = excluded.{c}" for c in (update or [c for c in values if c not in key]))
        self.conn.execute(f"""INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})
                              ON CONFLICT ({', '.join(key)}) DO UPDATE SET {sets}""", tuple(values.values()))

    # -- characters -------------------------------------------------------------

    def upsert_character(self, natural_key: str, info: dict[str, Any], account: str | None) -> str:
        """Creates or updates a character by natural key and returns its local UUID."""
        row = self.conn.execute("SELECT character_id, name, name_history FROM characters WHERE natural_key = ?",
                                (natural_key,)).fetchone()
        fields = {
            "identity_quality": info.get("identityQuality") or "guid",
            "player_guid": info.get("guid"),
            "name": info.get("name") or "?",
            "name_suffix": info.get("nameSuffix"),
            "realm": info.get("realm"),
            "realm_normalized": info.get("realmNormalized"),
            "class_name": info.get("className"),
            "class_file": info.get("classFile"),
            "race_name": info.get("raceName"),
            "race_file": info.get("raceFile"),
            "xp": info.get("xp") if isinstance(info.get("xp"), int) else None,
            "xp_max": info.get("xpMax") if isinstance(info.get("xpMax"), int) else None,
            "xp_at": info.get("xpAt") if isinstance(info.get("xpAt"), int) else None,
            "faction": info.get("faction"),
            "level": info.get("level"),
            "client_locale": info.get("locale"),
            "client_version": info.get("clientVersion"),
            "client_build": None if info.get("clientBuild") is None else str(info.get("clientBuild")),
            "wow_account": account,
            "first_seen_at": info.get("firstSeenAt"),
            "last_seen_at": info.get("lastSeenAt"),
        }
        history = info.get("nameHistory")
        if history:
            fields["name_history"] = json.dumps(history, ensure_ascii=False)
        if row:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self.conn.execute(f"UPDATE characters SET {sets} WHERE character_id = ?",
                              (*fields.values(), row["character_id"]))
            return row["character_id"]
        character_id = str(uuid.uuid4())
        fields.update(character_id=character_id, natural_key=natural_key, created_at=int(time.time()))
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        self.conn.execute(f"INSERT INTO characters ({cols}) VALUES ({marks})", tuple(fields.values()))
        return character_id

    def list_characters(self) -> list[Character]:
        """My characters first, then friends' characters grouped by friend."""
        rows = self.conn.execute(
            """SELECT c.*, o.display_name AS owner_name FROM characters c LEFT JOIN owners o ON o.owner_id = c.owner_id
               ORDER BY c.owner_id IS NOT NULL, o.display_name COLLATE NOCASE, c.owner_id,
               c.last_seen_at DESC, c.name""").fetchall()
        return [Character.from_row(r) for r in rows]

    def character(self, character_id: str | None) -> Character | None:
        row = self.conn.execute(
            """SELECT c.*, o.display_name AS owner_name FROM characters c LEFT JOIN owners o ON o.owner_id = c.owner_id
               WHERE c.character_id = ?""", (character_id,)).fetchone()
        return Character.from_row(row) if row else None

    # -- events -----------------------------------------------------------------

    def insert_event(self, character_id: str, rec: dict[str, Any], import_id: int, schema_version: int) -> bool:
        """Inserts an event; returns False if it already exists (duplicate import). The addon may fill in an event
        later (a death's revival, a moment's text): an existing event then takes the newer data."""
        loc = rec.get("location") if isinstance(rec.get("location"), dict) else {}
        payload = json.dumps(rec.get("data") or {}, ensure_ascii=False)
        self.conn.execute("UPDATE events SET payload_json = ? WHERE character_id = ? AND event_id = ? "
                          "AND payload_json != ?", (payload, character_id, rec["id"], payload))
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO events (character_id, event_id, seq, event_type, occurred_at, server_time,
               session_id, map_id, zone_name, subzone_name, instance_id, x, y, location_quality, payload_json,
               schema_version, import_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (character_id, rec["id"], rec["seq"], rec["type"], rec["time"], rec.get("serverTime"), rec.get("session"),
             loc.get("mapID"), loc.get("zone"), loc.get("subzone"), loc.get("instanceID"), loc.get("x"), loc.get("y"),
             loc.get("quality"), payload, schema_version, import_id))
        return cur.rowcount == 1

    def events(self, character_id: str, types: Iterable[str] | None = None, search: str | None = None,
               limit: int = 5000) -> list[EventRow]:
        sql = "SELECT * FROM events WHERE character_id = ?"
        args: list[Any] = [character_id]
        types = list(types or [])
        if types:
            sql += f" AND event_type IN ({','.join('?' for _ in types)})"
            args += types
        if search:
            sql += " AND (payload_json LIKE ? OR zone_name LIKE ? OR subzone_name LIKE ?)"
            args += [f"%{search}%"] * 3
        sql += " ORDER BY occurred_at DESC, seq DESC LIMIT ?"
        args.append(limit)
        rows = [EventRow.from_row(r) for r in self.conn.execute(sql, args).fetchall()]
        return merge_death_echoes(rows[::-1])[::-1]

    def events_of_imports(self, import_ids: Iterable[int]) -> list[EventRow]:
        """The events these imports added, in time order (all characters)."""
        ids = list(import_ids)
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(f"SELECT * FROM events WHERE import_id IN ({marks}) ORDER BY occurred_at, seq", ids)
        return merge_death_echoes([EventRow.from_row(r) for r in rows])

    def event_types_for(self, character_id: str) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT event_type FROM events WHERE character_id = ? ORDER BY 1",
                                 (character_id,)).fetchall()
        return [r[0] for r in rows]

    def count_events(self, character_id: str, event_type: str) -> int:
        if event_type == "player_died":                     # without the echoes (merge_death_echoes)
            return self.conn.execute(
                """SELECT COUNT(*) FROM events e WHERE e.character_id = ? AND e.event_type = 'player_died'
                   AND NOT EXISTS (SELECT 1 FROM events p WHERE p.character_id = e.character_id
                       AND p.event_type = 'player_died' AND p.seq < e.seq
                       AND p.occurred_at BETWEEN e.occurred_at - ? AND e.occurred_at
                       AND COALESCE(json_extract(p.payload_json, '$.revivedAt'), e.occurred_at + 1) > e.occurred_at)""",
                (character_id, DEATH_ECHO)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM events WHERE character_id = ? AND event_type = ?",
                                 (character_id, event_type)).fetchone()[0]

    # -- sessions ---------------------------------------------------------------

    def upsert_session(self, character_id: str, rec: dict[str, Any]) -> None:
        """Sessions change while the character plays, so they are replaced on every import."""
        self._upsert("sessions", {
            "character_id": character_id, "session_id": rec["id"], "seq": rec["seq"], "started_at": rec["startedAt"],
            "ended_at": rec.get("endedAt"), "end_reason": rec.get("endReason"), "reload_count": rec.get("reloads") or 0,
            "start_level": rec.get("startLevel"), "end_level": rec.get("endLevel"),
            "played_total_seconds": rec.get("playedTotal"), "played_level_seconds": rec.get("playedLevel"),
            "played_at": rec.get("playedAt")}, ("character_id", "session_id"),
            update=("ended_at", "end_reason", "reload_count", "end_level", "played_total_seconds",
                    "played_level_seconds", "played_at"))

    def sessions(self, character_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sessions WHERE character_id = ? ORDER BY started_at DESC",
                                 (character_id,)).fetchall()

    # -- stream state and gaps --------------------------------------------------

    def last_seq(self, character_id: str, stream: str) -> int | None:
        row = self.conn.execute("SELECT last_seq FROM stream_state WHERE character_id = ? AND stream = ?",
                                (character_id, stream)).fetchone()
        return row[0] if row else None

    def set_last_seq(self, character_id: str, stream: str, seq: int) -> None:
        self._upsert("stream_state", {"character_id": character_id, "stream": stream, "last_seq": seq},
                     ("character_id", "stream"))

    def add_gap(self, character_id: str, stream: str, from_seq: int, to_seq: int, before_time: int | None,
                import_id: int) -> None:
        self.conn.execute("""INSERT INTO data_gaps (character_id, stream, from_seq, to_seq, before_time, import_id,
                             detected_at) VALUES (?,?,?,?,?,?,?)""",
                          (character_id, stream, from_seq, to_seq, before_time, import_id, int(time.time())))

    def event_icons(self) -> list[int]:
        """The icons recorded with events (fileDataIDs: achievements, professions, mounts, ...), all characters."""
        rows = self.conn.execute("""SELECT DISTINCT json_extract(payload_json, '$.icon') FROM events
                                    WHERE json_valid(payload_json)
                                    AND json_type(payload_json, '$.icon') = 'integer'""").fetchall()
        return [r[0] for r in rows if r[0] > 0]

    def gaps(self, character_id: str | None = None) -> list[sqlite3.Row]:
        if character_id:
            return self.conn.execute("SELECT * FROM data_gaps WHERE character_id = ? ORDER BY before_time DESC",
                                     (character_id,)).fetchall()
        return self.conn.execute("SELECT * FROM data_gaps ORDER BY detected_at DESC").fetchall()

    # -- import runs ------------------------------------------------------------

    def start_import(self, source_path: str, source_type: str, account: str | None, mtime: int | None,
                     size: int | None) -> int:
        cur = self.conn.execute("""INSERT INTO import_runs (source_path, source_type, account, file_mtime, file_size,
                                   started_at, status) VALUES (?,?,?,?,?,?, 'running')""",
                                (source_path, source_type, account, mtime, size, int(time.time())))
        return int(cur.lastrowid)

    def finish_import(self, import_id: int, **fields: Any) -> None:
        fields["finished_at"] = int(time.time())
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE import_runs SET {sets} WHERE import_id = ?", (*fields.values(), import_id))

    def import_runs(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM import_runs ORDER BY import_id DESC LIMIT ?", (limit,)).fetchall()

    def last_import_for(self, source_path: str) -> sqlite3.Row | None:
        return self.conn.execute("""SELECT * FROM import_runs WHERE source_path = ? AND status IN ('ok', 'partial')
                                    ORDER BY import_id DESC LIMIT 1""", (source_path,)).fetchone()

    # -- screenshots -------------------------------------------------------------

    def upsert_screenshot(self, character_id: str, rec: dict[str, Any]) -> None:
        """Status and linked events can change until the addon saves again, so records are replaced."""
        self._upsert("screenshots", {
            "character_id": character_id, "screenshot_id": rec["id"], "seq": rec["seq"],
            "trigger_type": rec.get("trigger") or "?", "status": rec.get("status") or "?",
            "requested_at": rec.get("requestedAt"), "captured_at": rec.get("capturedAt"),
            "file_stamp": rec.get("fileStamp"), "error_message": rec.get("error")}, ("character_id", "screenshot_id"),
            update=("status", "captured_at", "file_stamp", "error_message"))
        for event_id in rec.get("events") or []:
            if isinstance(event_id, str):
                self.conn.execute("""INSERT OR IGNORE INTO screenshot_events (character_id, screenshot_id, event_id)
                                     VALUES (?,?,?)""", (character_id, rec["id"], event_id))

    def screenshots(self, character_id: str, only_files: bool = False) -> list[sqlite3.Row]:
        sql = """SELECT s.*, (SELECT e.event_id FROM screenshot_events se JOIN events e
                   ON e.character_id = se.character_id AND e.event_id = se.event_id
                   WHERE se.character_id = s.character_id AND se.screenshot_id = s.screenshot_id
                   ORDER BY e.seq LIMIT 1) AS first_event_id,
                 (SELECT COUNT(*) FROM screenshot_events se WHERE se.character_id = s.character_id
                   AND se.screenshot_id = s.screenshot_id) AS event_count
                 FROM screenshots s WHERE s.character_id = ?"""
        if only_files:
            sql += " AND s.status IN ('api_called', 'confirmed')"
        return self.conn.execute(sql + " ORDER BY COALESCE(s.captured_at, s.requested_at) DESC",
                                 (character_id,)).fetchall()

    def unmatched_screenshots(self) -> list[sqlite3.Row]:
        # Only my own characters: friends' pictures come with their share file, never from my folder.
        return self.conn.execute("""SELECT * FROM screenshots WHERE status IN ('api_called', 'confirmed')
                                    AND file_path IS NULL AND file_stamp IS NOT NULL
                                    AND COALESCE(file_match, '') <> 'ambiguous'
                                    AND character_id IN (SELECT character_id FROM characters
                                                         WHERE owner_id IS NULL)""").fetchall()

    def claimed_files(self) -> set[str]:
        rows = self.conn.execute("SELECT file_path FROM screenshots WHERE file_path IS NOT NULL").fetchall()
        return {r[0] for r in rows}

    def set_screenshot_file(self, character_id: str, screenshot_id: str, path: str | None, match: str) -> None:
        self.conn.execute("""UPDATE screenshots SET file_path = ?, file_match = ?
                             WHERE character_id = ? AND screenshot_id = ?""",
                          (path, match, character_id, screenshot_id))

    def screenshots_by_event(self, character_id: str) -> dict[str, sqlite3.Row]:
        """event_id -> the screenshot taken for it (file_path is NULL while no file was found). If several
        screenshots name the same event, one with a file wins, then the newest."""
        rows = self.conn.execute("""SELECT se.event_id, s.* FROM screenshot_events se
                                    JOIN screenshots s ON s.character_id = se.character_id
                                    AND s.screenshot_id = se.screenshot_id
                                    WHERE se.character_id = ? AND s.status IN ('api_called', 'confirmed')
                                    ORDER BY s.file_path IS NOT NULL, COALESCE(s.captured_at, s.requested_at)""",
                                 (character_id,)).fetchall()
        return {r["event_id"]: r for r in rows}  # later rows (better ones) overwrite earlier ones

    def favorite_screenshots(self, character_id: str) -> set[str]:
        rows = self.conn.execute("SELECT screenshot_id FROM screenshot_favorites WHERE character_id = ?",
                                 (character_id,)).fetchall()
        return {r[0] for r in rows}

    def set_favorite(self, character_id: str, screenshot_id: str, favorite: bool) -> None:
        if favorite:
            self.conn.execute("""INSERT OR IGNORE INTO screenshot_favorites (character_id, screenshot_id, added_at)
                                 VALUES (?, ?, strftime('%s', 'now'))""", (character_id, screenshot_id))
        else:
            self.conn.execute("DELETE FROM screenshot_favorites WHERE character_id = ? AND screenshot_id = ?",
                              (character_id, screenshot_id))
        self.conn.commit()          # a click in the gallery: kept at once, outside any import

    def event(self, character_id: str, event_id: str) -> EventRow | None:
        row = self.conn.execute("SELECT * FROM events WHERE character_id = ? AND event_id = ?",
                                (character_id, event_id)).fetchone()
        return EventRow.from_row(row) if row else None

    # -- positions and maps -------------------------------------------------------

    _UPSERT_POSITION = """INSERT INTO positions (character_id, occurred_at, until_at, map_id, x, y, instance_id,
        on_taxi, jump, mounted, cause) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (character_id, occurred_at) DO UPDATE
        SET until_at = excluded.until_at, jump = excluded.jump, mounted = excluded.mounted, cause = excluded.cause
        WHERE excluded.until_at IS NOT positions.until_at OR excluded.jump != positions.jump
        OR excluded.mounted != positions.mounted OR excluded.cause IS NOT positions.cause"""

    def upsert_position(self, character_id: str, p: "PositionPoint") -> None:
        """Inserts a point. A stationary point may have grown (until_at) since the last import."""
        self.upsert_positions(character_id, (p,))

    def upsert_positions(self, character_id: str, points: Iterable["PositionPoint"]) -> None:
        """upsert_position for many points in one statement (the import writes tens of thousands)."""
        self.conn.executemany(self._UPSERT_POSITION, (
            (character_id, p.time, p.until, p.map_id, p.x, p.y, p.instance_id, int(p.taxi), int(p.jump),
             int(p.mounted), p.cause) for p in points))

    def has_position(self, character_id: str, occurred_at: int) -> bool:
        return self.conn.execute("SELECT 1 FROM positions WHERE character_id = ? AND occurred_at = ?",
                                 (character_id, occurred_at)).fetchone() is not None

    def positions(self, character_id: str) -> list["PositionPoint"]:
        rows = self.conn.execute("SELECT * FROM positions WHERE character_id = ? ORDER BY occurred_at",
                                 (character_id,)).fetchall()
        return [PositionPoint(r["occurred_at"], r["until_at"], r["map_id"], r["x"], r["y"], r["instance_id"],
                              bool(r["on_taxi"]), bool(r["jump"]), bool(r["mounted"]), r["cause"]) for r in rows]

    # -- group (who the player played with) ---------------------------------------

    def upsert_group_stretch(self, character_id: str, started_at: int, until_at: int,
                             members: list[dict[str, str]]) -> None:
        self._upsert("group_stretches", {"character_id": character_id, "started_at": started_at,
                                         "until_at": until_at,
                                         "members_json": json.dumps(members, ensure_ascii=False)},
                     ("character_id", "started_at"))

    def group_stretches(self, character_id: str) -> list[tuple[int, int, list[dict[str, str]]]]:
        """(from, until, members) in time order; a member is {"name", "class", "guid"}."""
        out = []
        for r in self.conn.execute("SELECT started_at, until_at, members_json FROM group_stretches "
                                   "WHERE character_id = ? ORDER BY started_at", (character_id,)):
            try:
                members = [m for m in json.loads(r["members_json"]) if isinstance(m, dict)]
            except (TypeError, ValueError):
                members = []
            out.append((r["started_at"], r["until_at"], members))
        return out

    def characters_by_guid(self) -> dict[str, "Character"]:
        """All characters (mine and friends') by player GUID."""
        rows = self.conn.execute(
            """SELECT c.*, o.display_name AS owner_name FROM characters c LEFT JOIN owners o ON o.owner_id = c.owner_id
               WHERE c.player_guid IS NOT NULL""").fetchall()
        return {r["player_guid"]: Character.from_row(r) for r in rows}

    def upsert_map_info(self, map_id: int, info: dict[str, Any]) -> None:
        self._upsert("map_info", {
            "map_id": map_id, "name": info.get("name"), "map_type": info.get("mapType"),
            "parent_map_id": info.get("parent"), "continent_id": info.get("continent"), "min_x": info.get("minX"),
            "max_x": info.get("maxX"), "min_y": info.get("minY"), "max_y": info.get("maxY"),
            "client_build": None if info.get("build") is None else str(info.get("build"))}, ("map_id",))

    def map_infos(self) -> dict[int, sqlite3.Row]:
        return {r["map_id"]: r for r in self.conn.execute("SELECT * FROM map_info").fetchall()}

    def upsert_instance(self, instance_id: int, name: str) -> None:
        self._upsert("instances", {"instance_id": instance_id, "name": name}, ("instance_id",))

    def instance_names(self) -> dict[int, str]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT instance_id, name FROM instances").fetchall()}

    def upsert_entrance(self, instance_id: int, map_id: int, x: float, y: float, source: str | None,
                        name: str | None) -> None:
        self._upsert("instance_entrances", {"instance_id": instance_id, "map_id": map_id, "x": x, "y": y,
                                            "source": source, "name": name}, ("instance_id",))

    def entrances(self) -> dict[int, tuple[int, float, float]]:
        """Recorded dungeon entrances: instance ID -> (map ID, x, y)."""
        rows = self.conn.execute("SELECT instance_id, map_id, x, y FROM instance_entrances").fetchall()
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    # -- metrics (the addon's minute samples) --------------------------------------

    def upsert_metric(self, character_id: str, t: int, xp: int, kills: int | None, money: int | None,
                      level: int | None) -> None:
        self._upsert("metrics", {"character_id": character_id, "occurred_at": t, "xp": xp, "kills": kills,
                                 "money": money, "level": level}, ("character_id", "occurred_at"))

    def metrics(self, character_id: str) -> list[tuple[int, int, int | None]]:
        """(time, experience earned in total, level) of the samples, in time order."""
        return [(r["occurred_at"], r["xp"], r["level"]) for r in self.conn.execute(
            "SELECT occurred_at, xp, level FROM metrics WHERE character_id = ? ORDER BY occurred_at",
            (character_id,))]

    # -- counters from the addon --------------------------------------------------

    def set_character_stat(self, character_id: str, key: str, value: float) -> None:
        self._upsert("character_stats", {"character_id": character_id, "stat_key": key, "value": value},
                     ("character_id", "stat_key"))

    def character_stat(self, character_id: str, key: str) -> float | None:
        row = self.conn.execute("SELECT value FROM character_stats WHERE character_id = ? AND stat_key = ?",
                                (character_id, key)).fetchone()
        return row[0] if row else None

    def replace_gear(self, character_id: str, items: list[dict[str, Any]], updated_at: int | None) -> None:
        """The equipped items as of the snapshot (slots not listed are empty)."""
        self.conn.execute("DELETE FROM gear WHERE character_id = ?", (character_id,))
        for it in items:
            self.conn.execute("""INSERT OR REPLACE INTO gear (character_id, slot, slot_name, item_id, link, icon, quality,
                                 updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                              (character_id, it["slot"], it.get("slotName"), it.get("item"), it["link"],
                               int_or_none(it.get("icon")), it.get("quality"), updated_at))

    def gear(self, character_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM gear WHERE character_id = ? ORDER BY slot", (character_id,)).fetchall()

    # -- capabilities -----------------------------------------------------------

    def set_capability(self, key: str, status: str, confirmed_at: int | None, build: str | None) -> None:
        self._upsert("client_capabilities", {"capability": key, "status": status, "confirmed_at": confirmed_at,
                                             "client_build": build, "updated_at": int(time.time())}, ("capability",))

    def capabilities(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM client_capabilities ORDER BY capability").fetchall()
