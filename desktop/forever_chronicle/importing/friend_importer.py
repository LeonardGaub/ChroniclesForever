"""Friends' characters from the cloud folder (cloud_backup.py, docs/Cloud_Backup.md): every other player's folder
holds the dated copies of their addon file; the newest copy per WoW account becomes read-only characters under that
friend (owners table, characters.owner_id).

- One owner per player folder: share_id "player:<folder name in lower case>", display name the folder's name.
- A newer copy adds to what the app has of that friend: chronicle entries are kept by ID, route points by time,
  sessions, stats and gear are updated. A character no longer in their files goes with everything.
  Unchanged copies are skipped.
- A friend whose folder is gone from the cloud is removed; so are friends of the removed friends sync (their
  share_id has the old form), until they back up into a folder of their own.
- Parsing never executes code (wow.lua_parser).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..cloud_backup import friend_folders, versions
from ..storage.database import Database
from ..storage.jsonl import RECORD_TYPES
from ..storage.repository import int_or_none
from ..wow.lua_parser import LuaParseError, as_dict, parse_saved_variables_bytes
from .sv_importer import VARIABLE_NAME, ImportResult, SavedVariablesImporter


@dataclass
class FriendImportResult:
    friends: int = 0             # friends' folders in the cloud
    imported: list[str] = field(default_factory=list)    # names of friends imported now
    unchanged: int = 0
    removed: list[str] = field(default_factory=list)     # names of friends whose folder is gone
    failed: list[str] = field(default_factory=list)      # "name: reason"

    @property
    def changed(self) -> bool:
        return bool(self.imported or self.removed)


def share_id_of(folder: Path) -> str:
    return f"player:{folder.name.lower()}"


def newest_copies(folder: Path) -> list[Path]:
    """The newest addon copy of each of the friend's WoW accounts."""
    try:
        accounts = sorted(d for d in (folder / "addon").iterdir() if d.is_dir())
    except OSError:
        return []
    return [newest[0].path for newest in (versions(d)[:1] for d in accounts) if newest]


def import_friends(db: Database, cloud: Path | None, own_name: str | None) -> FriendImportResult:
    result = FriendImportResult()
    if cloud is None or not cloud.is_dir():
        return result          # no cloud folder (or OneDrive not running): keep what we have
    importer = SavedVariablesImporter(db)
    seen = set()
    for folder in friend_folders(cloud, own_name):
        files = newest_copies(folder)
        if not files:
            continue
        share_id = share_id_of(folder)
        seen.add(share_id)
        result.friends += 1
        try:
            modified = max(int(f.stat().st_mtime) for f in files)
        except OSError as exc:
            result.failed.append(f"{folder.name}: {exc}")
            continue
        row = db.conn.execute("SELECT owner_id, shared_at FROM owners WHERE share_id = ?", (share_id,)).fetchone()
        has_characters = row is not None and db.conn.execute(
            "SELECT 1 FROM characters WHERE owner_id = ? LIMIT 1", (row[0],)).fetchone() is not None
        if row is not None and row[1] == modified and has_characters:
            result.unchanged += 1
            continue
        try:
            reason = _import_friend(db, importer, files, share_id, folder.name, modified)
        except Exception as exc:  # a friend's file is not ours: whatever is wrong in it must not stop the others
            db.conn.rollback()
            reason = f"{type(exc).__name__}: {exc}"
        if reason:
            result.failed.append(f"{folder.name}: {reason}")
        else:
            result.imported.append(folder.name)
    for owner_id, share_id, name in db.conn.execute("SELECT owner_id, share_id, display_name FROM owners").fetchall():
        if share_id not in seen:
            with db.transaction():
                remove_owner(db, owner_id)
            result.removed.append(name)
    return result


def _import_friend(db: Database, importer: SavedVariablesImporter, files: list[Path], share_id: str, name: str,
                   modified: int) -> str | None:
    """Imports one friend's newest copies; returns why they were not imported (None: imported)."""
    characters: dict[str, Any] = {}
    root: dict[str, Any] = {"schemaVersion": 1, "characters": characters, "maps": {}, "instances": {},
                            "entrances": {}}
    size = 0
    for path in files:
        try:
            raw = path.read_bytes()                  # reading a OneDrive placeholder downloads it
            data = as_dict(parse_saved_variables_bytes(raw).get(VARIABLE_NAME))
        except (OSError, LuaParseError) as exc:
            return str(exc)
        if not data:
            return f"{VARIABLE_NAME} not found in {path.name}"
        size += len(raw)
        root["schemaVersion"] = max(root["schemaVersion"], int_or_none(data.get("schemaVersion")) or 1)
        for key, char in as_dict(data.get("characters")).items():
            if isinstance(key, str) and isinstance(char, dict):
                characters[f"friend:{share_id}:{key}"] = char
        for part in ("maps", "instances", "entrances"):
            for k, v in as_dict(data.get(part)).items():
                root[part].setdefault(k, v)

    # Everything below runs in the import's transaction (sqlite3 opens it with the first change).
    row = db.conn.execute("SELECT owner_id FROM owners WHERE share_id = ?", (share_id,)).fetchone()
    if row is None:
        owner_id = int(db.conn.execute("INSERT INTO owners (share_id, display_name) VALUES (?, ?)",
                                       (share_id, name)).lastrowid)
    else:
        owner_id = row[0]
    db.conn.execute("UPDATE owners SET display_name = ?, imported_at = ? WHERE owner_id = ?",
                    (name, int(time.time()), owner_id))
    for (character_id, natural_key) in db.conn.execute(
            "SELECT character_id, natural_key FROM characters WHERE owner_id = ?", (owner_id,)).fetchall():
        if natural_key not in characters:  # no longer in their files: goes with everything
            delete_character_data(db, character_id, keep_character=False)
    result = importer.import_data({VARIABLE_NAME: root}, str(files[0].parent.parent.parent), name, modified, size,
                                  ImportResult(source=name), owner_id=owner_id)
    if result.status in ("rejected", "failed"):
        return "; ".join(result.messages) or result.status
    # Only an imported copy counts as done: a rejected one (e.g. a newer addon) is tried again after an app update.
    with db.transaction():
        db.conn.execute("UPDATE owners SET shared_at = ? WHERE owner_id = ?", (modified, owner_id))
    return None


def delete_character_data(db: Database, character_id: str, keep_character: bool) -> None:
    for rt in RECORD_TYPES:
        if rt.per_character:
            db.conn.execute(f"DELETE FROM {rt.table} WHERE character_id = ?", (character_id,))
    if not keep_character:
        db.conn.execute("DELETE FROM characters WHERE character_id = ?", (character_id,))


def remove_owner(db: Database, owner_id: int) -> None:
    """A friend with all their characters."""
    for (character_id,) in db.conn.execute("SELECT character_id FROM characters WHERE owner_id = ?",
                                           (owner_id,)).fetchall():
        delete_character_data(db, character_id, keep_character=False)
    db.conn.execute("DELETE FROM owners WHERE owner_id = ?", (owner_id,))
