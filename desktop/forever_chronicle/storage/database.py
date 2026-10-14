"""SQLite database: connection, schema migrations and backups (spec section 6, F-011)."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Each entry upgrades the schema by one version. Never edit a released migration; append a new one.
MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE characters (
        character_id      TEXT PRIMARY KEY,          -- local UUID
        natural_key       TEXT NOT NULL UNIQUE,      -- player GUID, or name-realm fallback
        identity_quality  TEXT NOT NULL,             -- guid | name_based
        player_guid       TEXT,
        name              TEXT NOT NULL,
        name_suffix       TEXT,
        name_history      TEXT,                      -- JSON list
        realm             TEXT,
        realm_normalized  TEXT,
        class_name        TEXT,
        class_file        TEXT,
        race_name         TEXT,
        race_file         TEXT,
        faction           TEXT,
        level             INTEGER,
        client_locale     TEXT,
        client_version    TEXT,
        client_build      TEXT,
        wow_account       TEXT,
        first_seen_at     INTEGER,
        last_seen_at      INTEGER,
        created_at        INTEGER NOT NULL
    );

    CREATE TABLE events (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        event_id       TEXT NOT NULL,
        seq            INTEGER NOT NULL,
        event_type     TEXT NOT NULL,
        occurred_at    INTEGER NOT NULL,              -- UTC epoch seconds
        server_time    INTEGER,
        session_id     TEXT,
        map_id         INTEGER,
        zone_name      TEXT,
        subzone_name   TEXT,
        instance_id    INTEGER,
        x              REAL,
        y              REAL,
        location_quality TEXT,
        payload_json   TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        import_id      INTEGER,
        PRIMARY KEY (character_id, event_id)
    );
    CREATE INDEX events_by_time ON events(character_id, occurred_at);
    CREATE INDEX events_by_type ON events(character_id, event_type);

    CREATE TABLE sessions (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        session_id     TEXT NOT NULL,
        seq            INTEGER NOT NULL,
        started_at     INTEGER NOT NULL,
        ended_at       INTEGER,
        end_reason     TEXT,                          -- open | logout | incomplete
        reload_count   INTEGER NOT NULL DEFAULT 0,
        start_level    INTEGER,
        end_level      INTEGER,
        played_total_seconds INTEGER,
        played_level_seconds INTEGER,
        played_at      INTEGER,
        PRIMARY KEY (character_id, session_id)
    );

    -- Highest seq imported per character and stream, for gap detection.
    CREATE TABLE stream_state (
        character_id TEXT NOT NULL,
        stream       TEXT NOT NULL,
        last_seq     INTEGER NOT NULL,
        PRIMARY KEY (character_id, stream)
    );

    CREATE TABLE data_gaps (
        gap_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        character_id  TEXT NOT NULL,
        stream        TEXT NOT NULL,
        from_seq      INTEGER NOT NULL,
        to_seq        INTEGER NOT NULL,
        before_time   INTEGER,                        -- time of the first record after the gap
        import_id     INTEGER,
        detected_at   INTEGER NOT NULL
    );

    CREATE TABLE import_runs (
        import_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path    TEXT NOT NULL,
        source_type    TEXT NOT NULL,                 -- saved_variables | jsonl
        account        TEXT,
        file_mtime     INTEGER,
        file_size      INTEGER,
        used_backup    INTEGER NOT NULL DEFAULT 0,
        started_at     INTEGER NOT NULL,
        finished_at    INTEGER,
        rows_imported  INTEGER NOT NULL DEFAULT 0,
        rows_duplicate INTEGER NOT NULL DEFAULT 0,
        rows_invalid   INTEGER NOT NULL DEFAULT 0,
        gaps_detected  INTEGER NOT NULL DEFAULT 0,
        status         TEXT NOT NULL,                 -- running | ok | partial | rejected | failed
        message        TEXT
    );

    -- Capability status reported by the addon (spec F-012).
    CREATE TABLE client_capabilities (
        capability    TEXT PRIMARY KEY,
        status        TEXT NOT NULL,
        confirmed_at  INTEGER,
        client_build  TEXT,
        updated_at    INTEGER NOT NULL
    );
    """,
    # 2: screenshots (spec F-003, F-010)
    """
    CREATE TABLE screenshots (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        screenshot_id  TEXT NOT NULL,
        seq            INTEGER NOT NULL,
        trigger_type   TEXT NOT NULL,
        status         TEXT NOT NULL,                 -- api_called | confirmed | failed | stale | ...
        requested_at   INTEGER,
        captured_at    INTEGER,
        file_stamp     TEXT,                          -- MMDDYY_HHMMSS (client local time)
        error_message  TEXT,
        file_path      TEXT,                          -- set by file matching
        file_match     TEXT,                          -- matched | not_found | ambiguous
        PRIMARY KEY (character_id, screenshot_id)
    );
    CREATE TABLE screenshot_events (
        character_id   TEXT NOT NULL,
        screenshot_id  TEXT NOT NULL,
        event_id       TEXT NOT NULL,
        PRIMARY KEY (character_id, event_id)          -- one screenshot per event
    );
    CREATE INDEX screenshot_events_by_shot ON screenshot_events(character_id, screenshot_id);
    """,
    # 3: route points and map geometry (spec F-005)
    """
    CREATE TABLE positions (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        occurred_at    INTEGER NOT NULL,
        until_at       INTEGER,                       -- set when the player stood still
        map_id         INTEGER,                       -- NULL inside instances (zone-only point)
        x              REAL,
        y              REAL,
        instance_id    INTEGER,
        on_taxi        INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (character_id, occurred_at)
    );
    CREATE TABLE map_info (
        map_id         INTEGER PRIMARY KEY,
        name           TEXT,
        map_type       INTEGER,
        parent_map_id  INTEGER,
        continent_id   INTEGER,
        min_x REAL, max_x REAL, min_y REAL, max_y REAL,  -- rectangle on the continent map
        client_build   TEXT
    );
    CREATE TABLE instances (
        instance_id    INTEGER PRIMARY KEY,
        name           TEXT
    );
    """,
    # 4: counters kept by the addon (kills, experience earned, ...) - totals since tracking began
    """
    CREATE TABLE character_stats (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        stat_key       TEXT NOT NULL,
        value          REAL NOT NULL,
        PRIMARY KEY (character_id, stat_key)
    );
    """,
    # 5: profession and recipe snapshots (spec F-008) - mirror of the addon's latest snapshot
    """
    CREATE TABLE professions (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        skill_line     INTEGER NOT NULL,
        name           TEXT NOT NULL,
        icon           INTEGER,
        kind           TEXT,                          -- primary | secondary
        rank           INTEGER,
        max_rank       INTEGER,
        modifier       INTEGER,
        active         INTEGER NOT NULL DEFAULT 1,    -- 0 = unlearned
        first_seen_at  INTEGER,
        updated_at     INTEGER,
        recipe_status  TEXT,                          -- complete | partial | NULL (not captured yet)
        recipes_updated_at INTEGER,
        recipes_total  INTEGER,                       -- size of the unfiltered recipe list
        PRIMARY KEY (character_id, skill_line)
    );
    CREATE TABLE recipes (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        skill_line     INTEGER NOT NULL,
        recipe_id      INTEGER NOT NULL,
        name           TEXT NOT NULL,
        category_id    INTEGER,
        icon           INTEGER,
        first_seen_at  INTEGER,                       -- first snapshot that contained it
        PRIMARY KEY (character_id, skill_line, recipe_id)
    );
    CREATE TABLE recipe_categories (
        character_id   TEXT NOT NULL REFERENCES characters(character_id),
        skill_line     INTEGER NOT NULL,
        category_id    INTEGER NOT NULL,
        parent_id      INTEGER,
        name           TEXT NOT NULL,
        PRIMARY KEY (character_id, skill_line, category_id)
    );
    """,
    # 6: item quality of what a recipe creates (0 poor ... 7 heirloom; NULL = unknown, e.g. enchants)
    """
    ALTER TABLE recipes ADD COLUMN quality INTEGER;
    """,
    # 7: dungeon entrances - instance moments are shown there (no positions inside instances)
    """
    CREATE TABLE instance_entrances (
        instance_id    INTEGER PRIMARY KEY,
        map_id         INTEGER NOT NULL,
        x              REAL NOT NULL,
        y              REAL NOT NULL,
        source         TEXT,                          -- journal | walked
        name           TEXT
    );
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)
KEEP_BACKUPS = 5


class Database:
    def __init__(self, path: Path | str, backup_dir: Path | None = None):
        self.path = Path(path)
        self.backup_dir = backup_dir
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate(existed)

    def close(self) -> None:
        self.conn.close()

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self, existed: bool) -> None:
        current = self.version
        if current > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {current} is newer than this app ({SCHEMA_VERSION})")
        if current == SCHEMA_VERSION:
            return
        if existed:
            self.backup(f"before-migration-{current}-to-{SCHEMA_VERSION}")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            with self.transaction():
                self.conn.executescript("BEGIN;" + MIGRATIONS[version - 1] + f"; PRAGMA user_version = {version};")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on any exception."""
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def backup(self, label: str) -> Path | None:
        """Copy the database to the backup folder, keeping the newest KEEP_BACKUPS copies."""
        if not self.backup_dir:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / f"{self.path.stem}-{time.strftime('%Y%m%d-%H%M%S')}-{label}.db"
        dest = sqlite3.connect(target)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        backups = sorted(self.backup_dir.glob(f"{self.path.stem}-*.db"))
        for old in backups[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
        return target

