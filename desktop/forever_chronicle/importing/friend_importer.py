"""Friends' characters from the cloud folder (docs/Sharing_Design.md): each friend's share file
(<cloud>\\players\\<name>-<id>-<account>.lua, written by their game, uploaded by their sync) becomes read-only
characters under that friend (owners table, characters.owner_id).

- One owner per friend file: share_id "<id>-<account>" (the first 8 characters of their shareId and their account
  hash), so a renamed friend stays the same owner.
- A newer file adds to what the app has of that friend (since 2026-10-16; before, it replaced it): a share file
  holds only the newest records (200 chronicle entries, 20,000 route points per character), so the app keeps the
  history beyond that, like it does for my own characters. Chronicle entries are kept by ID, route points by time,
  sessions, stats, gear and professions are updated. A character no longer in the file goes with everything.
  An unchanged file is skipped.
- A friend whose file is gone from the cloud is removed.
- Parsing never executes code (wow.lua_parser); a file of more than 8 MB is skipped, like the sync script does.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..cloud_sync import MAX_PLAYER_BYTES, PLAYER_FILE, PlayerFile, SyncSetup, player_files
from ..storage.database import Database
from ..storage.jsonl import RECORD_TYPES
from ..wow.lua_parser import LuaParseError, as_dict, as_list, parse_saved_variables_bytes
from .sv_importer import ImportResult, SavedVariablesImporter

SHARE_VARIABLE = "ForeverChronicleShareDB"


@dataclass
class FriendImportResult:
    friends: int = 0             # friend files in the cloud
    imported: list[str] = field(default_factory=list)    # names of friends imported now
    unchanged: int = 0
    removed: list[str] = field(default_factory=list)     # names of friends whose file is gone
    failed: list[str] = field(default_factory=list)      # "name: reason"

    @property
    def changed(self) -> bool:
        return bool(self.imported or self.removed)


def share_id_of(path: Path) -> str | None:
    match = PLAYER_FILE.match(path.name)
    if not match:
        return None
    return f"{match.group('id')}-{match.group('account')}"


def friend_files(setup: SyncSetup) -> list[tuple[PlayerFile, str]] | None:
    """The friends' files in the cloud with their share_id, one per friend (the first in player_files' order).
    None when the cloud folder is not available (OneDrive not running?): then keep what we have."""
    if not (Path(setup.cloud) / "players").is_dir():
        return None
    files, seen = [], set()
    for f in player_files(setup):
        share_id = share_id_of(f.path)
        if f.mine or share_id is None or share_id in seen:
            continue
        seen.add(share_id)
        files.append((f, share_id))
    return files


def import_friends(db: Database, setup: SyncSetup) -> FriendImportResult:
    result = FriendImportResult()
    files = friend_files(setup)
    if files is None:
        return result
    importer = SavedVariablesImporter(db)
    for f, share_id in files:
        result.friends += 1
        row = db.conn.execute("SELECT owner_id, shared_at FROM owners WHERE share_id = ?", (share_id,)).fetchone()
        has_characters = row is not None and db.conn.execute(
            "SELECT 1 FROM characters WHERE owner_id = ? LIMIT 1", (row[0],)).fetchone() is not None
        if row is not None and row[1] == int(f.modified) and has_characters:
            result.unchanged += 1
            continue
        reason = _import_friend(db, importer, f.path, share_id, f.name, int(f.modified))
        if reason:
            result.failed.append(f"{f.name}: {reason}")
        else:
            result.imported.append(f.name)
    seen = {share_id for _, share_id in files}
    for owner_id, share_id, name in db.conn.execute("SELECT owner_id, share_id, display_name FROM owners").fetchall():
        if share_id not in seen:
            with db.transaction():
                remove_owner(db, owner_id)
            result.removed.append(name)
    return result


def _import_friend(db: Database, importer: SavedVariablesImporter, path: Path, share_id: str, name: str,
                   modified: int) -> str | None:
    """Imports one friend file; returns why it was not imported (None: imported)."""
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_PLAYER_BYTES:
            return "too large"
        share = as_dict(parse_saved_variables_bytes(raw).get(SHARE_VARIABLE))
    except (OSError, LuaParseError) as exc:
        return str(exc)
    if not share:
        return f"{SHARE_VARIABLE} not found"
    characters: dict[str, Any] = {}
    for char in as_list(share.get("characters")):
        info = as_dict(as_dict(char).get("info"))
        key = info.get("key") or info.get("guid")
        if isinstance(key, str) and key:
            characters[f"friend:{share_id}:{key}"] = char
    root = {"schemaVersion": 2 if (share.get("format") or 1) >= 2 else 1, "characters": characters,
            "maps": share.get("maps"), "instances": share.get("instances"), "entrances": share.get("entrances")}

    # Everything below runs in the import's transaction (sqlite3 opens it with the first change).
    row = db.conn.execute("SELECT owner_id FROM owners WHERE share_id = ?", (share_id,)).fetchone()
    if row is None:
        owner_id = int(db.conn.execute("INSERT INTO owners (share_id, display_name) VALUES (?, ?)",
                                       (share_id, name)).lastrowid)
    else:
        owner_id = row[0]
    db.conn.execute("UPDATE owners SET display_name = ?, shared_at = ?, imported_at = ? WHERE owner_id = ?",
                    (name, modified, int(time.time()), owner_id))
    for (character_id, natural_key) in db.conn.execute(
            "SELECT character_id, natural_key FROM characters WHERE owner_id = ?", (owner_id,)).fetchall():
        if natural_key not in characters:  # no longer shared: goes with everything
            delete_character_data(db, character_id, keep_character=False)
    result = importer.import_data({"ForeverChronicleDB": root}, str(path), name, modified, len(raw),
                                  ImportResult(source=str(path)), owner_id=owner_id)
    if result.status in ("rejected", "failed"):
        return "; ".join(result.messages) or result.status
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
