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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..storage.database import Database
from ..storage.repository import PositionPoint, Recipe, RecipeCategory, Repository
from ..wow.lua_parser import LuaParseError, as_dict, as_list, parse_saved_variables_bytes

VARIABLE_NAME = "ForeverChronicleDB"
SUPPORTED_SCHEMA = 1
STABLE_WAIT_SECONDS = 0.5


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
    recipes: int = 0
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


def valid_event(rec: Any) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("id"), str) and rec["id"] != ""
            and isinstance(rec.get("type"), str) and _int(rec.get("seq")) is not None
            and _int(rec.get("time")) is not None)


def valid_screenshot(rec: Any) -> bool:
    return isinstance(rec, dict) and isinstance(rec.get("id"), str) and _int(rec.get("seq")) is not None


def valid_session(rec: Any) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("id"), str) and _int(rec.get("seq")) is not None
            and _int(rec.get("startedAt")) is not None)


class SavedVariablesImporter:
    def __init__(self, db: Database):
        self.db = db
        self.repo = Repository(db.conn)

    # -- file handling ------------------------------------------------------------

    def import_file(self, path: Path, account: str | None = None, skip_unchanged: bool = False) -> ImportResult:
        result = ImportResult(source=str(path))
        try:
            st = path.stat()
        except OSError:
            st = None
        if st and skip_unchanged:
            last = self.repo.last_import_for(str(path))
            if last and last["file_mtime"] == int(st.st_mtime) and last["file_size"] == st.st_size:
                result.status = "unchanged"
                return result

        data, used_backup, error = self._read(path)
        result.used_backup = used_backup
        if data is None:
            result.status = "failed"
            result.messages.append(error or "file could not be read")
            with self.db.transaction():
                result.import_id = self.repo.start_import(str(path), "saved_variables", account,
                                                          int(st.st_mtime) if st else None, st.st_size if st else None)
                self.repo.finish_import(result.import_id, status="failed", message=result.messages[-1])
            return result
        if used_backup:
            result.messages.append(f"main file unreadable ({error}); imported the .bak copy instead")
        return self.import_data(data, str(path), account, int(st.st_mtime) if st else None,
                                st.st_size if st else None, result)

    def _read(self, path: Path) -> tuple[dict[str, Any] | None, bool, str | None]:
        """Returns (parsed variables, used_backup, error of the main file)."""
        error = None
        for candidate, is_backup in ((path, False), (path.with_name(path.name + ".bak"), True)):
            try:
                raw = self._read_stable(candidate)
                return parse_saved_variables_bytes(raw), is_backup, error
            except (OSError, LuaParseError) as exc:
                if error is None:
                    error = str(exc)
        return None, False, error

    @staticmethod
    def _read_stable(path: Path) -> bytes:
        before = path.stat()
        if time.time() - before.st_mtime < 5:
            time.sleep(STABLE_WAIT_SECONDS)  # just written: give the client time to finish
        raw = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime) != (after.st_size, after.st_mtime) or len(raw) != after.st_size:
            raise OSError("file changed while reading; try again after the game has finished saving")
        return raw

    # -- data -----------------------------------------------------------------------

    def import_data(self, variables: dict[str, Any], source: str, account: str | None = None,
                    mtime: int | None = None, size: int | None = None,
                    result: ImportResult | None = None) -> ImportResult:
        result = result or ImportResult(source=source)
        db_root = variables.get(VARIABLE_NAME)
        with self.db.transaction():
            import_id = self.repo.start_import(source, "saved_variables", account, mtime, size)
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
        result.characters += 1
        # Counters kept by the addon (kills, experience, ...): totals, replaced on every import.
        for stat_key, value in as_dict(char.get("stats")).items():
            if isinstance(stat_key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                self.repo.set_character_stat(character_id, stat_key, value)
        streams = as_dict(char.get("streams"))

        events = as_list(as_dict(streams.get("events")).get("records"))
        good_events = []
        for rec in events:
            if valid_event(rec):
                good_events.append(rec)
            else:
                result.invalid += 1
        for rec in good_events:
            rec["seq"], rec["time"] = _int(rec["seq"]), _int(rec["time"])
            if self.repo.insert_event(character_id, rec, import_id, schema):
                result.imported += 1
            else:
                result.duplicates += 1
        self._track_stream(character_id, "events", good_events, import_id, result)

        sessions = as_list(as_dict(streams.get("sessions")).get("records"))
        good_sessions = []
        for rec in sessions:
            if valid_session(rec):
                good_sessions.append(rec)
                self.repo.upsert_session(character_id, rec)
                result.sessions += 1
            else:
                result.invalid += 1
        for rec in good_sessions:
            rec["time"] = rec.get("startedAt")
        self._track_stream(character_id, "sessions", good_sessions, import_id, result)

        shots = as_list(as_dict(streams.get("screenshots")).get("records"))
        good_shots = []
        for rec in shots:
            if valid_screenshot(rec):
                rec["seq"] = _int(rec["seq"])
                rec["events"] = as_list(rec.get("events"))
                rec["time"] = _int(rec.get("capturedAt")) or _int(rec.get("requestedAt"))
                self.repo.upsert_screenshot(character_id, rec)
                good_shots.append(rec)
                result.screenshots += 1
            else:
                result.invalid += 1
        self._track_stream(character_id, "screenshots", good_shots, import_id, result)

        # Compact stream: one string per point, seq implicit (nextSeq - count + index).
        pos_stream = as_dict(streams.get("positions"))
        raw = as_list(pos_stream.get("records"))
        next_seq = _int(pos_stream.get("nextSeq")) or (len(raw) + 1)
        first_seq = next_seq - len(raw)
        good_points = []
        for i, text in enumerate(raw):
            point = PositionPoint.parse(text) if isinstance(text, str) else None
            if point is None:
                result.invalid += 1
                continue
            self.repo.upsert_position(character_id, point)
            good_points.append({"seq": first_seq + i, "time": point.time})
            result.positions += 1
        self._track_stream(character_id, "positions", good_points, import_id, result)
        self._import_professions(character_id, as_dict(as_dict(char.get("snapshots")).get("professions")), result)
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

    def _import_professions(self, character_id: str, snap: dict[str, Any], result: ImportResult) -> None:
        """Mirrors the addon's profession snapshot (spec F-008). A recipe list replaces the stored one only
        when it is complete; a partial list only adds recipes."""
        for prof in as_list(snap.get("list")):
            if not isinstance(prof, dict) or _int(prof.get("skillLine")) is None or not isinstance(prof.get("name"), str):
                result.invalid += 1
                continue
            skill_line = _int(prof["skillLine"])
            prof = dict(prof, skillLine=skill_line)
            for key in ("rank", "maxRank", "modifier", "firstSeenAt", "updatedAt"):
                prof[key] = _int(prof.get(key))
            recipes = as_dict(prof.get("recipes"))
            status = recipes.get("status")
            if recipes and status not in ("complete", "partial"):
                result.invalid += 1
                recipes = {}
            prof["recipes"] = recipes
            self.repo.upsert_profession(character_id, prof)
            if not recipes:
                continue
            for text in as_list(recipes.get("categories")):
                cat = RecipeCategory.parse(text) if isinstance(text, str) else None
                if cat:
                    self.repo.upsert_recipe_category(character_id, skill_line, cat.category_id, cat.parent_id,
                                                     cat.name)
            parsed = []
            fmt = _int(recipes.get("format"))
            for text in as_list(recipes.get("list")):
                recipe = Recipe.parse(text, fmt) if isinstance(text, str) else None
                if recipe is None:
                    result.invalid += 1
                else:
                    parsed.append(recipe)
            self.repo.replace_recipes(character_id, skill_line, parsed, status == "complete",
                                      _int(recipes.get("updatedAt")))
            result.recipes += len(parsed)

    def _track_stream(self, character_id: str, stream: str, records: list[dict[str, Any]], import_id: int,
                      result: ImportResult) -> None:
        seqs = [_int(r["seq"]) for r in records]
        check = check_gap(self.repo.last_seq(character_id, stream), seqs)
        if check.reset:
            result.messages.append(f"{stream}: addon data was reset; numbering restarted")
        if check.gap:
            first_after = min((r for r in records), key=lambda r: _int(r["seq"]))
            self.repo.add_gap(character_id, stream, check.gap[0], check.gap[1], _int(first_after.get("time")),
                              import_id)
            result.gaps += 1
        if seqs:
            self.repo.set_last_seq(character_id, stream, check.new_last)

    def _import_maps(self, db_root: dict[str, Any]) -> None:
        for key, info in as_dict(db_root.get("maps")).items():
            map_id = _int(key) if not isinstance(key, str) else (int(key) if key.isdigit() else None)
            if map_id is not None and isinstance(info, dict):
                self.repo.upsert_map_info(map_id, info)
        for key, name in as_dict(db_root.get("instances")).items():
            instance_id = _int(key) if not isinstance(key, str) else (int(key) if key.isdigit() else None)
            if instance_id is not None and isinstance(name, str):
                self.repo.upsert_instance(instance_id, name)
        for key, e in as_dict(db_root.get("entrances")).items():
            instance_id = _int(key) if not isinstance(key, str) else (int(key) if key.isdigit() else None)
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
            if isinstance(key, str) and isinstance(cap, dict) and isinstance(cap.get("status"), str):
                self.repo.set_capability(key, cap["status"], _int(cap.get("confirmedAt")),
                                         None if cap.get("build") is None else str(cap.get("build")))
