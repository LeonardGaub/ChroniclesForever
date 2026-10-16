"""JSONL export and import of the whole database (spec F-011): backups and moving data between computers.

File format (one JSON object per line, UTF-8):
- Line 1: ``{"record_type": "header", "format": "forever-chronicle", "format_version": 1, "app_version": ...,
  "db_schema": ..., "exported_at": ...}``
- Every other line: ``{"record_type": "<type>", ...columns}``. Records of a character carry ``"character"`` =
  the character's natural key (player GUID), never the local database ID, so files merge across computers.

Import is a merge: idempotent, row by row, and invalid rows are counted and reported instead of failing the
file. Which version of a record wins is defined per record type in ``RECORD_TYPES``. Local-only columns
(database IDs, import bookkeeping, screenshot file paths of this computer) are not exported.

Only my own characters are exported; friends' characters (docs/Sharing_Design.md, version 1) are never
exported again.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .. import __version__
from .database import SCHEMA_VERSION, Database

FORMAT = "forever-chronicle"
FORMAT_VERSION = 1
MAX_MESSAGES = 20


@dataclass(frozen=True)
class RecordType:
    name: str                       # record_type in the file
    table: str
    key: tuple[str, ...]            # identifies a record (together with the character for per-character types)
    per_character: bool = True
    merge: str = "ignore"           # ignore: keep the existing record | replace: take the incoming one |
                                    # newer: take the incoming one if its `compare` value is larger
    compare: str | None = None
    local: tuple[str, ...] = ()     # columns that are never exported


# Order matters: characters before their records.
RECORD_TYPES: list[RecordType] = [
    RecordType("map_info", "map_info", ("map_id",), per_character=False, merge="replace"),
    RecordType("instance", "instances", ("instance_id",), per_character=False, merge="replace"),
    RecordType("instance_entrance", "instance_entrances", ("instance_id",), per_character=False, merge="replace"),
    RecordType("character", "characters", ("natural_key",), per_character=False, merge="newer",
               compare="last_seen_at", local=("character_id", "owner_id")),
    RecordType("character_stat", "character_stats", ("stat_key",), merge="newer", compare="value"),
    RecordType("session", "sessions", ("session_id",), merge="newer", compare="ended_at"),
    RecordType("event", "events", ("event_id",), local=("import_id",)),
    RecordType("screenshot", "screenshots", ("screenshot_id",), merge="newer", compare="captured_at",
               local=("file_path", "file_match")),
    RecordType("screenshot_event", "screenshot_events", ("event_id",)),
    RecordType("screenshot_favorite", "screenshot_favorites", ("screenshot_id",)),
    RecordType("position", "positions", ("occurred_at",), merge="newer", compare="until_at"),
    RecordType("profession", "professions", ("skill_line",), merge="newer", compare="updated_at"),
    RecordType("recipe_category", "recipe_categories", ("skill_line", "category_id"), merge="replace"),
    RecordType("recipe", "recipes", ("skill_line", "recipe_id"), merge="replace"),
    RecordType("gear", "gear", ("slot",), merge="newer", compare="updated_at"),
    RecordType("data_gap", "data_gaps", ("stream", "from_seq", "to_seq"), local=("gap_id", "import_id")),
    RecordType("stream_state", "stream_state", ("stream",), merge="newer", compare="last_seq"),
]
BY_NAME = {t.name: t for t in RECORD_TYPES}


@dataclass
class ExportResult:
    path: Path
    records: int = 0
    characters: int = 0


@dataclass
class JsonlImportResult:
    source: str
    status: str = "ok"                  # ok | partial | rejected | failed
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    invalid: int = 0
    unknown: int = 0                    # record types from a newer app version (skipped)
    characters: int = 0
    backup: Path | None = None
    import_id: int | None = None
    messages: list[str] = field(default_factory=list)

    def problem(self, line: int, text: str) -> None:
        self.invalid += 1
        if len(self.messages) < MAX_MESSAGES:
            self.messages.append(f"line {line}: {text}")


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, tuple[str, bool]]:
    """Column -> (declared type, NOT NULL) of a table."""
    return {r[1]: ((r[2] or "").upper(), bool(r[3])) for r in conn.execute(f"PRAGMA table_info({table})")}


# -- export --------------------------------------------------------------------------------


@dataclass
class ExportFilter:
    """What to export. None everywhere = all of my own characters, all record types (the backup export).
    characters: character_id -> record type names to include for that character.
    types: global record types (map_info, ...) to include.
    screenshots: (character_id, screenshot_id) pairs; only these screenshot records are exported."""
    characters: dict[str, set[str]] | None = None
    types: set[str] | None = None
    screenshots: set[tuple[str, str]] | None = None


def iter_records(db: Database, flt: ExportFilter | None = None) -> Iterator[dict[str, Any]]:
    """The records (without header) of my own characters, filtered."""
    flt = flt or ExportFilter()
    conn = db.conn
    for rt in RECORD_TYPES:
        if flt.types is not None and rt.name not in flt.types:
            continue
        cols = [c for c in _columns(conn, rt.table) if c not in rt.local and c != "character_id"]
        select = ", ".join(f"t.{c}" for c in cols)
        order = ", ".join(f"t.{k}" for k in rt.key)
        if rt.per_character:
            sql = (f"SELECT {select}, t.character_id AS __cid, c.natural_key AS __character FROM {rt.table} t "
                   f"JOIN characters c ON c.character_id = t.character_id WHERE c.owner_id IS NULL "
                   f"ORDER BY c.natural_key, {order}")
        elif rt.name == "character":
            sql = f"SELECT {select}, t.character_id AS __cid FROM {rt.table} t WHERE t.owner_id IS NULL ORDER BY {order}"
        else:
            sql = f"SELECT {select} FROM {rt.table} t ORDER BY {order}"
        for row in conn.execute(sql):
            if rt.per_character or rt.name == "character":
                cid = row["__cid"]
                if flt.characters is not None:
                    wanted = flt.characters.get(cid)
                    if wanted is None or (rt.per_character and rt.name not in wanted):
                        continue
                if flt.screenshots is not None and rt.name in ("screenshot", "screenshot_event", "screenshot_favorite") \
                        and (cid, row["screenshot_id"]) not in flt.screenshots:
                    continue
            rec: dict[str, Any] = {"record_type": rt.name}
            if rt.per_character:
                rec["character"] = row["__character"]
            for c in cols:
                rec[c] = row[c]
            yield rec


def iter_export(db: Database) -> Iterator[dict[str, Any]]:
    yield {"record_type": "header", "format": FORMAT, "format_version": FORMAT_VERSION, "app_version": __version__,
           "db_schema": SCHEMA_VERSION, "exported_at": int(time.time())}
    yield from iter_records(db)


def export_jsonl(db: Database, path: Path) -> ExportResult:
    """Writes the whole database to `path` (via a temporary file, so a failed export leaves no half file)."""
    result = ExportResult(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for rec in iter_export(db):
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n")
            if rec["record_type"] != "header":
                result.records += 1
            if rec["record_type"] == "character":
                result.characters += 1
    tmp.replace(path)
    return result


# -- import --------------------------------------------------------------------------------


def _valid_value(value: Any, declared: str) -> bool:
    if value is None:
        return True
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    if "INT" in declared:
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if "REAL" in declared:
        return isinstance(value, (int, float))
    if "TEXT" in declared:
        return isinstance(value, str)
    return True


class _Importer:
    """Merges records. `characters` maps natural keys to the characters records may be written to
    (default: my own characters; a friend's character is never changed by a backup import)."""

    def __init__(self, db: Database, result: JsonlImportResult, characters: dict[str, str] | None = None):
        self.conn = db.conn
        self.result = result
        self.columns = {rt.name: _columns(self.conn, rt.table) for rt in RECORD_TYPES}
        self.characters: dict[str, str] = characters if characters is not None else {
            r[0]: r[1] for r in self.conn.execute(
                "SELECT natural_key, character_id FROM characters WHERE owner_id IS NULL")}
        self.foreign = {r[0] for r in self.conn.execute(
            "SELECT natural_key FROM characters WHERE owner_id IS NOT NULL")}

    def row(self, line: int, rec: dict[str, Any]) -> None:
        rt = BY_NAME[rec["record_type"]]
        columns = self.columns[rt.name]
        values: dict[str, Any] = {}
        for col, (declared, _) in columns.items():
            if col in rt.local or col == "character_id" or col not in rec:
                continue
            value = rec[col]
            if not _valid_value(value, declared):
                self.result.problem(line, f"{rt.name}: invalid value for {col}")
                return
            values[col] = int(value) if "INT" in declared and isinstance(value, float) else value
        missing = [k for k in rt.key if values.get(k) is None]
        if missing:
            self.result.problem(line, f"{rt.name}: missing {', '.join(missing)}")
            return

        where = {k: values[k] for k in rt.key}
        if rt.per_character:
            character_id = self.characters.get(rec.get("character")) if isinstance(rec.get("character"), str) else None
            if character_id is None:
                self.result.problem(line, f"{rt.name}: unknown character")
                return
            values["character_id"] = where["character_id"] = character_id
        elif rt.name == "character":
            if values["natural_key"] in self.foreign and values["natural_key"] not in self.characters:
                self.result.problem(line, "character: belongs to a friend")
                return
            values.setdefault("created_at", int(time.time()))

        cond = " AND ".join(f"{k} = ?" for k in where)
        compare = rt.compare or rt.key[0]
        existing = self.conn.execute(f"SELECT * FROM {rt.table} WHERE {cond}", tuple(where.values())).fetchone()
        try:
            if existing is None:
                if rt.name == "character":
                    values["character_id"] = str(uuid.uuid4())
                cols = ", ".join(values)
                self.conn.execute(f"INSERT INTO {rt.table} ({cols}) VALUES ({', '.join('?' for _ in values)})",
                                  tuple(values.values()))
                if rt.name == "character":
                    self.characters[values["natural_key"]] = values["character_id"]
                    self.result.characters += 1
                self.result.inserted += 1
                return
            take = rt.merge == "replace" or (
                rt.merge == "newer" and values.get(compare) is not None
                and (existing[compare] is None or values[compare] > existing[compare]))
            updates = {k: v for k, v in values.items()
                       if k not in where and k != "character_id" and existing[k] != v}
            if not take or not updates:
                self.result.unchanged += 1
                return
            sets = ", ".join(f"{k} = ?" for k in updates)
            cur = self.conn.execute(f"UPDATE {rt.table} SET {sets} WHERE {cond}",
                                    (*updates.values(), *where.values()))
            if rt.name == "character":
                self.result.characters += 1
            if cur.rowcount:
                self.result.updated += 1
        except sqlite3.IntegrityError as exc:
            self.result.problem(line, f"{rt.name}: {exc}")


def read_records(lines: list[str], result: JsonlImportResult) -> tuple[dict[str, Any] | None,
                                                                       list[tuple[int, dict[str, Any]]]]:
    """Checks the header and parses the record lines (sorted: characters before their records).
    Returns (header, [(line number, record)]); header is None and result.status "rejected" for unusable files."""
    numbered = [(i + 1, text) for i, text in enumerate(lines) if text.strip()]
    header = None
    if numbered:
        try:
            header = json.loads(numbered[0][1])
        except ValueError:
            header = None
    if not isinstance(header, dict) or header.get("record_type") != "header" or header.get("format") != FORMAT:
        result.status = "rejected"
        result.messages.append("not a Journey Forever export (header line missing)")
        return None, []
    version = header.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        result.status = "rejected"
        result.messages.append(f"export format {version} is newer than this app supports ({FORMAT_VERSION})")
        return None, []

    records: list[tuple[int, int, dict[str, Any]]] = []
    order = {rt.name: i for i, rt in enumerate(RECORD_TYPES)}
    for number, text in numbered[1:]:
        try:
            rec = json.loads(text)
        except ValueError:
            result.problem(number, "not valid JSON")
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("record_type"), str):
            result.problem(number, "record_type missing")
            continue
        if rec["record_type"] not in BY_NAME:
            result.unknown += 1
            continue
        records.append((order[rec["record_type"]], number, rec))
    records.sort(key=lambda r: (r[0], r[1]))  # characters before their records, file order otherwise
    return header, [(number, rec) for _, number, rec in records]


def import_jsonl(db: Database, path: Path) -> JsonlImportResult:
    """Merges a JSONL export into the database. A backup of the database is made first."""
    result = JsonlImportResult(source=str(path))
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        result.status = "failed"
        result.messages.append(str(exc))
        return result
    header, records = read_records(lines, result)
    if header is None:
        return result
    if header.get("kind", "backup") != "backup":
        result.status = "rejected"
        result.messages.append("this is not a backup export")
        return result

    result.backup = db.backup("before-jsonl-import")
    st = path.stat()
    with db.transaction():
        cur = db.conn.execute("""INSERT INTO import_runs (source_path, source_type, file_mtime, file_size, started_at,
                                 status) VALUES (?, 'jsonl', ?, ?, ?, 'running')""",
                              (str(path), int(st.st_mtime), st.st_size, int(time.time())))
        result.import_id = int(cur.lastrowid)
        importer = _Importer(db, result)
        for number, rec in records:
            importer.row(number, rec)
        if result.invalid:
            result.status = "partial"
        if result.unknown:
            result.messages.append(f"{result.unknown} records of unknown types skipped (newer app version?)")
        db.conn.execute("""UPDATE import_runs SET finished_at = ?, status = ?, rows_imported = ?, rows_duplicate = ?,
                           rows_invalid = ?, message = ? WHERE import_id = ?""",
                        (int(time.time()), result.status, result.inserted + result.updated, result.unchanged,
                         result.invalid, "; ".join(result.messages) or None, result.import_id))
    return result
