"""Imports the addon's SavedVariables into SQLite (spec F-014).

- The file is read once into memory (a snapshot), only if its size and mtime are stable.
- Parsing never executes code (see wow.lua_parser).
- Each file is imported in one transaction. Events are immutable and de-duplicated by ID;
  sessions are updated in place.
- If the file is malformed or truncated, the client's ``.bak`` copy is tried instead.
- Records lost to the addon's retention cap are detected through per-stream ``seq`` numbers.
"""

from __future__ import annotations

import time
from bisect import bisect_left
from dataclasses import dataclass, field
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable

from ..storage.database import Database
from ..storage.repository import PositionPoint, Repository, int_or_none
from ..wow.lua_parser import LuaParseError, as_dict, as_list, parse_saved_variables_bytes, parse_value

VARIABLE_NAME = "ForeverChronicleDB"
SUPPORTED_SCHEMA = 2  # 2: streams packed in the saved file (addon 0.15.0)
STABLE_WAIT_SECONDS = 0.5
# What the app no longer keeps: recipes (removed with the profession page after addon 0.15.0). Files of older
# addon versions still hold them; their events count for the seq numbers but are not stored.
RETIRED_EVENT_TYPES = frozenset({"recipe_learned"})
RETIRED_CAPABILITIES = frozenset({"recipes"})


@dataclass
class ImportResult:
    source: str
    status: str = "ok"                 # ok | partial | rejected | failed | unchanged
    import_id: int | None = None
    characters: int = 0
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    sessions: int = 0
    screenshots: int = 0
    positions: int = 0
    gaps: int = 0
    used_backup: bool = False
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GapCheck:
    gap: tuple[int, int] | None        # (from_seq, to_seq) of missing records
    new_last: int
    reset: bool                        # stream restarted (addon data was deleted/reinstalled)


def check_gap(previous_last: int | None, seqs: list[int]) -> GapCheck:
    """Compares the seq numbers in a file with the highest seq imported before."""
    if not seqs:
        return GapCheck(None, previous_last or 0, False)
    lo, hi = min(seqs), max(seqs)
    if previous_last is None:
        return GapCheck((1, lo - 1) if lo > 1 else None, hi, False)
    if hi < previous_last:
        return GapCheck(None, hi, True)
    gap = (previous_last + 1, lo - 1) if lo > previous_last + 1 else None
    return GapCheck(gap, max(previous_last, hi), False)


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _records(stream: Any, valid: Callable[[Any], bool], result: ImportResult) -> list[dict[str, Any]]:
    """A stream's valid records; the invalid ones are counted."""
    good = []
    for rec in as_list(as_dict(stream).get("records")):
        if valid(rec):
            good.append(rec)
        else:
            result.invalid += 1
    return good


def valid_event(rec: Any) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("id"), str) and rec["id"] != ""
            and isinstance(rec.get("type"), str) and _int(rec.get("seq")) is not None
            and _int(rec.get("time")) is not None)


def valid_screenshot(rec: Any) -> bool:
    return isinstance(rec, dict) and isinstance(rec.get("id"), str) and _int(rec.get("seq")) is not None


def valid_session(rec: Any) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("id"), str) and _int(rec.get("seq")) is not None
            and _int(rec.get("startedAt")) is not None)


def parse_group_stretch(text: Any) -> tuple[int, int, list[dict[str, str]]] | None:
    """The addon's group record "start,until,name/class/guid;..." as (start, until, members), or None."""
    if not isinstance(text, str):
        return None
    parts = text.split(",", 2)
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    members = []
    for member in filter(None, parts[2].split(";")):
        fields = member.split("/")
        if len(fields) != 3 or not fields[2].startswith("Player-"):
            return None
        members.append({"name": fields[0], "class": fields[1], "guid": fields[2]})
    return int(parts[0]), int(parts[1]), members


def unpack_stream(stream: Any) -> Any:
    """The addon packs streams in the saved file (schema 2, Core/Storage.lua): records = {} and
    packed = {format, kind, chunks}; "lines" chunks hold compact records joined by newlines, "tables" chunks hold
    table records as Lua text "{...},{...}". Returns the stream with its records unpacked, in order."""
    stream = as_dict(stream)
    packed = as_dict(stream.get("packed"))
    if not packed:
        return stream
    records: list[Any] = []
    for chunk in as_list(packed.get("chunks")):
        if not isinstance(chunk, str):
            continue
        if packed.get("kind") == "lines":
            records.extend(line for line in chunk.split("\n") if line)
        else:
            try:
                records.extend(as_list(parse_value("{" + chunk + "}")))
            except LuaParseError:
                continue  # an unreadable chunk is skipped; the addon keeps it
    records.extend(as_list(stream.get("records")))
    unpacked = {k: v for k, v in stream.items() if k != "packed"}
    unpacked["records"] = records
    return unpacked


class ParsedPoints(list):
    """Position records parsed ahead by prepare() (the positions stream's records, or one route archive record
    "point;point;..."): a PositionPoint each, None for an invalid one."""


def _parse_points(texts: list[Any]) -> ParsedPoints:
    return ParsedPoints(PositionPoint.parse(t) if isinstance(t, str) else None for t in texts)


def prepare(variables: dict[str, Any]) -> dict[str, Any]:
    """The work on a parsed file that needs no database, done ahead (the background import runs it in a worker
    thread): unpacks the streams and parses the position points. import_data takes the result like the raw data."""
    for char in as_dict(as_dict(variables.get(VARIABLE_NAME)).get("characters")).values():
        if not isinstance(char, dict) or not isinstance(char.get("streams"), dict):
            continue
        streams = char["streams"] = {name: unpack_stream(s) for name, s in char["streams"].items()}
        positions = streams.get("positions")
        if isinstance(positions, dict) and isinstance(positions.get("records"), list):
            positions["records"] = _parse_points(positions["records"])
        archive = streams.get("routeArchive")
        if isinstance(archive, dict) and isinstance(archive.get("records"), list):
            archive["records"] = [_parse_points(chunk.split(";")) if isinstance(chunk, str) else chunk
                                  for chunk in archive["records"]]
    return variables


@dataclass
class SavedFile:
    """A SavedVariables file read and parsed. Needs no database, so the background import reads in a worker thread
    (read_saved_file) and imports on the main thread (SavedVariablesImporter.import_read)."""
    path: Path
    account: str | None = None
    mtime: int | None = None
    size: int | None = None
    variables: dict[str, Any] | None = None   # parsed and prepared; None: neither the file nor its .bak was readable
    used_backup: bool = False
    error: str | None = None                  # why the main file could not be read
    unchanged: bool = False                   # same mtime and size as at the last import: not read


def read_saved_file(path: Path, account: str | None = None, last: tuple[int, int] | None = None) -> SavedFile:
    """Reads and parses the file (its .bak copy if the file is unreadable). ``last``: (mtime, size) of the last
    import; an unchanged file is not read then. May wait a moment when the game has just written the file."""
    try:
        st = path.stat()
    except OSError:
        st = None
    read = SavedFile(path, account, int(st.st_mtime) if st else None, st.st_size if st else None)
    if st and last is not None and last == (read.mtime, read.size):
        read.unchanged = True
        return read
    for candidate, is_backup in ((path, False), (path.with_name(path.name + ".bak"), True)):
        try:
            read.variables = prepare(parse_saved_variables_bytes(_read_stable(candidate)))
            read.used_backup = is_backup
            return read
        except (OSError, LuaParseError) as exc:
            if read.error is None:
                read.error = str(exc)
    return read


def _read_stable(path: Path) -> bytes:
    before = path.stat()
    if time.time() - before.st_mtime < 5:
        time.sleep(STABLE_WAIT_SECONDS)  # just written: give the client time to finish
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime) or len(raw) != after.st_size:
        raise OSError("file changed while reading; try again after the game has finished saving")
    return raw


class SavedVariablesImporter:
    def __init__(self, db: Database):
        self.db = db
        self.repo = Repository(db.conn)
        self._owner_id: int | None = None

    # -- file handling ------------------------------------------------------------

    def import_file(self, path: Path, account: str | None = None, skip_unchanged: bool = False) -> ImportResult:
        return self.import_read(read_saved_file(path, account, self.last_seen(path) if skip_unchanged else None))

    def last_seen(self, path: Path) -> tuple[int, int] | None:
        """(mtime, size) of the file at its last import, for read_saved_file's skip of unchanged files."""
        last = self.repo.last_import_for(str(path))
        return (last["file_mtime"], last["file_size"]) if last else None

    def import_read(self, read: SavedFile) -> ImportResult:
        """Imports a file read by read_saved_file (or records that it could not be read)."""
        result = ImportResult(source=str(read.path))
        if read.unchanged:
            result.status = "unchanged"
            return result
        result.used_backup = read.used_backup
        if read.variables is None:
            result.status = "failed"
            result.messages.append(read.error or "file could not be read")
            with self.db.transaction():
                result.import_id = self.repo.start_import(str(read.path), "saved_variables", read.account,
                                                          read.mtime, read.size)
                self.repo.finish_import(result.import_id, status="failed", message=result.messages[-1])
            return result
        if read.used_backup:
            result.messages.append(f"main file unreadable ({read.error}); imported the .bak copy instead")
        return self.import_data(read.variables, str(read.path), read.account, read.mtime, read.size, result)

    # -- data -----------------------------------------------------------------------

    def import_data(self, variables: dict[str, Any], source: str, account: str | None = None,
                    mtime: int | None = None, size: int | None = None,
                    result: ImportResult | None = None, owner_id: int | None = None) -> ImportResult:
        """``owner_id``: the characters belong to a friend (importing/friend_importer.py): marked as theirs in the
        same transaction, without gap tracking (a friend's file holds only the newest records)."""
        result = result or ImportResult(source=source)
        db_root = variables.get(VARIABLE_NAME)
        self._owner_id = owner_id
        with self.db.transaction():
            import_id = self.repo.start_import(source, "saved_variables" if owner_id is None else "friend",
                                               account, mtime, size)
            result.import_id = import_id
            reason = self._check_root(db_root)
            if reason:
                result.status = "rejected"
                result.messages.append(reason)
                self.repo.finish_import(import_id, status="rejected", message=reason)
                return result

            schema = _int(db_root.get("schemaVersion")) or 1
            for key, char in as_dict(db_root.get("characters")).items():
                if not isinstance(key, str) or not isinstance(char, dict):
                    result.invalid += 1
                    continue
                self._import_character(key, char, account, schema, import_id, result)
            self._import_capabilities(db_root)
            self._import_maps(db_root)

            if result.invalid:
                result.status = "partial"
                result.messages.append(f"{result.invalid} invalid records skipped")
            self.repo.finish_import(import_id, status=result.status, rows_imported=result.imported,
                                    rows_duplicate=result.duplicates, rows_invalid=result.invalid,
                                    gaps_detected=result.gaps, used_backup=int(result.used_backup),
                                    message="; ".join(result.messages) or None)
        return result

    @staticmethod
    def _check_root(db_root: Any) -> str | None:
        if not isinstance(db_root, dict):
            return f"{VARIABLE_NAME} not found in file"
        schema = _int(db_root.get("schemaVersion"))
        if schema is None:
            return "schemaVersion missing"
        if schema > SUPPORTED_SCHEMA:
            return f"data schema {schema} is newer than this app supports ({SUPPORTED_SCHEMA}); please update the app"
        return None

    def _import_character(self, key: str, char: dict[str, Any], account: str | None, schema: int,
                          import_id: int, result: ImportResult) -> None:
        info = as_dict(char.get("info"))
        character_id = self.repo.upsert_character(key, info, account)
        if self._owner_id is not None:
            self.db.conn.execute("UPDATE characters SET owner_id = ? WHERE character_id = ?",
                                 (self._owner_id, character_id))
        result.characters += 1
        # Counters kept by the addon (kills, experience, ...): totals, replaced on every import.
        for stat_key, value in as_dict(char.get("stats")).items():
            if isinstance(stat_key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                self.repo.set_character_stat(character_id, stat_key, value)
        streams = {name: unpack_stream(stream) for name, stream in as_dict(char.get("streams")).items()}

        events = _records(streams.get("events"), valid_event, result)
        for rec in events:
            rec["seq"], rec["time"] = _int(rec["seq"]), _int(rec["time"])
            if rec["type"] in RETIRED_EVENT_TYPES:
                continue
            if self.repo.insert_event(character_id, rec, import_id, schema):
                result.imported += 1
            else:
                result.duplicates += 1
        self._track_stream(character_id, "events", events, import_id, result)

        sessions = _records(streams.get("sessions"), valid_session, result)
        for rec in sessions:
            self.repo.upsert_session(character_id, rec)
            rec["time"] = rec.get("startedAt")
        result.sessions += len(sessions)
        self._track_stream(character_id, "sessions", sessions, import_id, result)

        shots = _records(streams.get("screenshots"), valid_screenshot, result)
        for rec in shots:
            rec["seq"] = _int(rec["seq"])
            rec["events"] = as_list(rec.get("events"))
            rec["time"] = _int(rec.get("capturedAt")) or _int(rec.get("requestedAt"))
            self.repo.upsert_screenshot(character_id, rec)
        result.screenshots += len(shots)
        self._track_stream(character_id, "screenshots", shots, import_id, result)

        # Compact stream: one string per point, seq implicit (nextSeq - count + index).
        pos_stream = as_dict(streams.get("positions"))
        raw = as_list(pos_stream.get("records"))
        next_seq = _int(pos_stream.get("nextSeq")) or (len(raw) + 1)
        first_seq = next_seq - len(raw)
        parsed = raw if isinstance(raw, ParsedPoints) else _parse_points(raw)
        points = [(seq, p) for seq, p in enumerate(parsed, first_seq) if p is not None]   # (seq, point)
        result.invalid += len(raw) - len(points)
        self.repo.upsert_positions(character_id, self._positions_to_write(character_id, points))
        result.positions += len(points)
        self._track_seqs(character_id, "positions", [(seq, p.time) for seq, p in points], import_id, result)
        # Route archive: old points the addon thinned out when the positions stream was full ("point;point;..."
        # per record). They are the same points, so they only fill in what was not imported in time.
        archived = []
        for chunk in as_list(as_dict(streams.get("routeArchive")).get("records")):
            if isinstance(chunk, ParsedPoints):
                chunk_points = chunk
            else:
                chunk_points = _parse_points(chunk.split(";")) if isinstance(chunk, str) else []
            for point in chunk_points:
                if point is None:
                    result.invalid += 1
                else:
                    archived.append(point)
        self.repo.upsert_positions(character_id, archived)
        # Group: one string per stretch with the same group, "start,until,name/class/guid;..." (Modules/Group.lua).
        for text in as_list(as_dict(streams.get("group")).get("records")):
            stretch = parse_group_stretch(text)
            if stretch:
                self.repo.upsert_group_stretch(character_id, *stretch)
            else:
                result.invalid += 1
        # Metrics: one string per minute with a change, "time,xpEarned,kills,money,level" (Modules/Metrics.lua).
        for text in as_list(as_dict(streams.get("metrics")).get("records")):
            try:
                values = [int(v) for v in text.split(",")] if isinstance(text, str) else []
            except ValueError:
                values = []
            if len(values) == 5:
                self.repo.upsert_metric(character_id, *values)
            else:
                result.invalid += 1
        self._import_gear(character_id, as_dict(as_dict(char.get("snapshots")).get("gear")), result)

    def _import_gear(self, character_id: str, snap: dict[str, Any], result: ImportResult) -> None:
        """The equipped items (snapshot): replaces the stored gear when the addon has a gear snapshot."""
        if _int(snap.get("updatedAt")) is None:
            return
        items = []
        for it in as_list(snap.get("slots")):
            if (isinstance(it, dict) and _int(it.get("slot")) is not None and isinstance(it.get("link"), str)
                    and it["link"].startswith("|c") and len(it["link"]) < 512):
                items.append({"slot": _int(it["slot"]), "slotName": it.get("slotName") if isinstance(
                    it.get("slotName"), str) else None, "item": _int(it.get("item")), "link": it["link"],
                    "icon": it.get("icon"), "quality": _int(it.get("quality"))})
            else:
                result.invalid += 1
        self.repo.replace_gear(character_id, items, _int(snap.get("updatedAt")))

    def _positions_to_write(self, character_id: str, points: list[tuple[int, PositionPoint]]) -> list[PositionPoint]:
        """The positions stream's points that may be new or changed since the last import. The addon only ever
        changes its newest point (a stationary point's until grows, Modules/Positions.lua), so the points before the
        newest one imported last time are stored as they are and left out; that one is written again. Trusted only
        when that point is in the file and stored: else (a restarted stream, a friend's file, a seq number merged in
        from another PC's export) all points are written, as before."""
        last = None if self._owner_id is not None else self.repo.last_seq(character_id, "positions")
        start = 0
        if last is not None and points and points[-1][0] >= last:
            i = bisect_left(points, last, key=itemgetter(0))   # seqs rise with the index
            if i < len(points) and points[i][0] == last and self.repo.has_position(character_id, points[i][1].time):
                start = i
        return [p for _, p in points[start:]]

    def _track_stream(self, character_id: str, stream: str, records: list[dict[str, Any]], import_id: int,
                      result: ImportResult) -> None:
        if self._owner_id is None:
            self._track_seqs(character_id, stream, [(_int(r["seq"]), r.get("time")) for r in records], import_id,
                             result)

    def _track_seqs(self, character_id: str, stream: str, seq_times: list[tuple[int, Any]], import_id: int,
                    result: ImportResult) -> None:
        """_track_stream with the records' (seq, time) pairs."""
        if self._owner_id is not None:
            return
        seqs = [seq for seq, _ in seq_times]
        check = check_gap(self.repo.last_seq(character_id, stream), seqs)
        if check.reset:
            result.messages.append(f"{stream}: addon data was reset; numbering restarted")
        if check.gap:
            first_after = min(seq_times, key=itemgetter(0))
            self.repo.add_gap(character_id, stream, check.gap[0], check.gap[1], _int(first_after[1]), import_id)
            result.gaps += 1
        if seqs:
            self.repo.set_last_seq(character_id, stream, check.new_last)

    def _import_maps(self, db_root: dict[str, Any]) -> None:
        for key, info in as_dict(db_root.get("maps")).items():
            map_id = int_or_none(key)
            if map_id is not None and isinstance(info, dict):
                self.repo.upsert_map_info(map_id, info)
        for key, name in as_dict(db_root.get("instances")).items():
            instance_id = int_or_none(key)
            if instance_id is not None and isinstance(name, str):
                self.repo.upsert_instance(instance_id, name)
        for key, e in as_dict(db_root.get("entrances")).items():
            instance_id = int_or_none(key)
            if instance_id is None or not isinstance(e, dict):
                continue
            map_id, x, y = _int(e.get("mapID")), e.get("x"), e.get("y")
            if (map_id is not None and isinstance(x, (int, float)) and isinstance(y, (int, float))
                    and 0 <= x <= 1 and 0 <= y <= 1):
                self.repo.upsert_entrance(instance_id, map_id, float(x), float(y),
                                          e.get("source") if isinstance(e.get("source"), str) else None,
                                          e.get("name") if isinstance(e.get("name"), str) else None)

    def _import_capabilities(self, db_root: dict[str, Any]) -> None:
        caps = as_dict(as_dict(db_root.get("diagnostics")).get("capabilities"))
        for key, cap in caps.items():
            if (isinstance(key, str) and key not in RETIRED_CAPABILITIES and isinstance(cap, dict)
                    and isinstance(cap.get("status"), str)):
                self.repo.set_capability(key, cap["status"], _int(cap.get("confirmedAt")),
                                         None if cap.get("build") is None else str(cap.get("build")))
