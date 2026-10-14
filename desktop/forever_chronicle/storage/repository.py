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
    realm: str | None
    level: int | None
    class_name: str | None
    class_file: str | None
    race_name: str | None
    faction: str | None
    last_seen_at: int | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Character":
        return cls(row["character_id"], row["name"], row["realm"], row["level"], row["class_name"],
                   row["class_file"], row["race_name"], row["faction"], row["last_seen_at"])


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

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "EventRow":
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = {}
        return cls(row["character_id"], row["event_id"], row["event_type"], row["occurred_at"],
                   row["zone_name"], row["subzone_name"], row["map_id"], row["x"], row["y"], payload)


@dataclass(frozen=True)
class PositionPoint:
    time: int
    until: int | None
    map_id: int | None
    x: float | None
    y: float | None
    instance_id: int | None
    taxi: bool

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
        return cls(t, until, map_id, x, y, instance_id, "T" in parts[5])


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

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
        rows = self.conn.execute("SELECT * FROM characters ORDER BY last_seen_at DESC, name").fetchall()
        return [Character.from_row(r) for r in rows]

    # -- events -----------------------------------------------------------------

    def insert_event(self, character_id: str, rec: dict[str, Any], import_id: int, schema_version: int) -> bool:
        """Inserts an event; returns False if it already exists (duplicate import)."""
        loc = rec.get("location") if isinstance(rec.get("location"), dict) else {}
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO events (character_id, event_id, seq, event_type, occurred_at, server_time,
               session_id, map_id, zone_name, subzone_name, instance_id, x, y, location_quality, payload_json,
               schema_version, import_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (character_id, rec["id"], rec["seq"], rec["type"], rec["time"], rec.get("serverTime"), rec.get("session"),
             loc.get("mapID"), loc.get("zone"), loc.get("subzone"), loc.get("instanceID"), loc.get("x"), loc.get("y"),
             loc.get("quality"), json.dumps(rec.get("data") or {}, ensure_ascii=False), schema_version, import_id))
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
        return [EventRow.from_row(r) for r in self.conn.execute(sql, args).fetchall()]

    def event_types_for(self, character_id: str) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT event_type FROM events WHERE character_id = ? ORDER BY 1",
                                 (character_id,)).fetchall()
        return [r[0] for r in rows]

    def count_events(self, character_id: str, event_type: str | None = None) -> int:
        if event_type:
            q = "SELECT COUNT(*) FROM events WHERE character_id = ? AND event_type = ?"
            return self.conn.execute(q, (character_id, event_type)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM events WHERE character_id = ?", (character_id,)).fetchone()[0]

    # -- sessions ---------------------------------------------------------------

    def upsert_session(self, character_id: str, rec: dict[str, Any]) -> None:
        """Sessions change while the character plays, so they are replaced on every import."""
        self.conn.execute(
            """INSERT INTO sessions (character_id, session_id, seq, started_at, ended_at, end_reason, reload_count,
               start_level, end_level, played_total_seconds, played_level_seconds, played_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (character_id, session_id) DO UPDATE SET
               ended_at = excluded.ended_at, end_reason = excluded.end_reason, reload_count = excluded.reload_count,
               end_level = excluded.end_level, played_total_seconds = excluded.played_total_seconds,
               played_level_seconds = excluded.played_level_seconds, played_at = excluded.played_at""",
            (character_id, rec["id"], rec["seq"], rec["startedAt"], rec.get("endedAt"), rec.get("endReason"),
             rec.get("reloads") or 0, rec.get("startLevel"), rec.get("endLevel"), rec.get("playedTotal"),
             rec.get("playedLevel"), rec.get("playedAt")))

    def sessions(self, character_id: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sessions WHERE character_id = ? ORDER BY started_at DESC",
                                 (character_id,)).fetchall()

    # -- stream state and gaps --------------------------------------------------

    def last_seq(self, character_id: str, stream: str) -> int | None:
        row = self.conn.execute("SELECT last_seq FROM stream_state WHERE character_id = ? AND stream = ?",
                                (character_id, stream)).fetchone()
        return row[0] if row else None

    def set_last_seq(self, character_id: str, stream: str, seq: int) -> None:
        self.conn.execute("""INSERT INTO stream_state (character_id, stream, last_seq) VALUES (?,?,?)
                             ON CONFLICT (character_id, stream) DO UPDATE SET last_seq = excluded.last_seq""",
                          (character_id, stream, seq))

    def add_gap(self, character_id: str, stream: str, from_seq: int, to_seq: int, before_time: int | None,
                import_id: int) -> None:
        self.conn.execute("""INSERT INTO data_gaps (character_id, stream, from_seq, to_seq, before_time, import_id,
                             detected_at) VALUES (?,?,?,?,?,?,?)""",
                          (character_id, stream, from_seq, to_seq, before_time, import_id, int(time.time())))

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
        self.conn.execute(
            """INSERT INTO screenshots (character_id, screenshot_id, seq, trigger_type, status, requested_at,
               captured_at, file_stamp, error_message) VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (character_id, screenshot_id) DO UPDATE SET status = excluded.status,
               captured_at = excluded.captured_at, file_stamp = excluded.file_stamp,
               error_message = excluded.error_message""",
            (character_id, rec["id"], rec["seq"], rec.get("trigger") or "?", rec.get("status") or "?",
             rec.get("requestedAt"), rec.get("capturedAt"), rec.get("fileStamp"), rec.get("error")))
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
        return self.conn.execute("""SELECT * FROM screenshots WHERE status IN ('api_called', 'confirmed')
                                    AND file_path IS NULL AND file_stamp IS NOT NULL
                                    AND COALESCE(file_match, '') <> 'ambiguous'""").fetchall()

    def claimed_files(self) -> set[str]:
        rows = self.conn.execute("SELECT file_path FROM screenshots WHERE file_path IS NOT NULL").fetchall()
        return {r[0] for r in rows}

    def set_screenshot_file(self, character_id: str, screenshot_id: str, path: str | None, match: str) -> None:
        self.conn.execute("""UPDATE screenshots SET file_path = ?, file_match = ?
                             WHERE character_id = ? AND screenshot_id = ?""",
                          (path, match, character_id, screenshot_id))

    def screenshot_files_by_event(self, character_id: str) -> dict[str, str]:
        """event_id -> screenshot file path (only for matched files)."""
        rows = self.conn.execute("""SELECT se.event_id, s.file_path FROM screenshot_events se
                                    JOIN screenshots s ON s.character_id = se.character_id
                                    AND s.screenshot_id = se.screenshot_id
                                    WHERE se.character_id = ? AND s.file_path IS NOT NULL""",
                                 (character_id,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def event(self, character_id: str, event_id: str) -> EventRow | None:
        row = self.conn.execute("SELECT * FROM events WHERE character_id = ? AND event_id = ?",
                                (character_id, event_id)).fetchone()
        return EventRow.from_row(row) if row else None

    def count_screenshots(self, character_id: str) -> int:
        return self.conn.execute("""SELECT COUNT(*) FROM screenshots WHERE character_id = ?
                                    AND status IN ('api_called', 'confirmed')""", (character_id,)).fetchone()[0]

    # -- positions and maps -------------------------------------------------------

    def upsert_position(self, character_id: str, p: "PositionPoint") -> None:
        """Inserts a point. A stationary point may have grown (until_at) since the last import."""
        self.conn.execute(
            """INSERT INTO positions (character_id, occurred_at, until_at, map_id, x, y, instance_id, on_taxi)
               VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (character_id, occurred_at) DO UPDATE SET
               until_at = excluded.until_at WHERE excluded.until_at IS NOT positions.until_at""",
            (character_id, p.time, p.until, p.map_id, p.x, p.y, p.instance_id, int(p.taxi)))

    def positions(self, character_id: str, start: int | None = None, end: int | None = None) -> list["PositionPoint"]:
        sql = "SELECT * FROM positions WHERE character_id = ?"
        args: list[Any] = [character_id]
        if start is not None:
            sql += " AND COALESCE(until_at, occurred_at) >= ?"
            args.append(start)
        if end is not None:
            sql += " AND occurred_at <= ?"
            args.append(end)
        rows = self.conn.execute(sql + " ORDER BY occurred_at", args).fetchall()
        return [PositionPoint(r["occurred_at"], r["until_at"], r["map_id"], r["x"], r["y"], r["instance_id"],
                              bool(r["on_taxi"])) for r in rows]

    def upsert_map_info(self, map_id: int, info: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO map_info (map_id, name, map_type, parent_map_id, continent_id, min_x, max_x, min_y, max_y,
               client_build) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (map_id) DO UPDATE SET name = excluded.name,
               map_type = excluded.map_type, parent_map_id = excluded.parent_map_id,
               continent_id = excluded.continent_id, min_x = excluded.min_x, max_x = excluded.max_x,
               min_y = excluded.min_y, max_y = excluded.max_y, client_build = excluded.client_build""",
            (map_id, info.get("name"), info.get("mapType"), info.get("parent"), info.get("continent"),
             info.get("minX"), info.get("maxX"), info.get("minY"), info.get("maxY"),
             None if info.get("build") is None else str(info.get("build"))))

    def map_infos(self) -> dict[int, sqlite3.Row]:
        return {r["map_id"]: r for r in self.conn.execute("SELECT * FROM map_info").fetchall()}

    def upsert_instance(self, instance_id: int, name: str) -> None:
        self.conn.execute("""INSERT INTO instances (instance_id, name) VALUES (?, ?)
                             ON CONFLICT (instance_id) DO UPDATE SET name = excluded.name""", (instance_id, name))

    def instance_names(self) -> dict[int, str]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT instance_id, name FROM instances").fetchall()}

    # -- capabilities -----------------------------------------------------------

    def set_capability(self, key: str, status: str, confirmed_at: int | None, build: str | None) -> None:
        self.conn.execute("""INSERT INTO client_capabilities (capability, status, confirmed_at, client_build, updated_at)
                             VALUES (?,?,?,?,?) ON CONFLICT (capability) DO UPDATE SET status = excluded.status,
                             confirmed_at = excluded.confirmed_at, client_build = excluded.client_build,
                             updated_at = excluded.updated_at""",
                          (key, status, confirmed_at, build, int(time.time())))

    def capabilities(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM client_capabilities ORDER BY capability").fetchall()
