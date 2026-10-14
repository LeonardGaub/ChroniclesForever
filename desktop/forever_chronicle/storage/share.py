"""Share files for friends (docs/Sharing_Design.md): export selected characters and categories as a
``.fcshare`` file, import a friend's file as read-only friend characters.

A share file is a ZIP with
- ``share.jsonl``: the JSONL format of storage/jsonl.py with ``kind: "share"`` in the header, plus ``share_id``
  (stable per sender's app), ``sender`` (free text name), ``created_at`` and ``characters`` (GUID -> categories);
- ``screenshots/<screenshot_id>.jpg``: only the pictures the sender picked, scaled down.

Import rules: the newest file of a friend is the truth for their characters. Everything a friend shared before
is replaced; characters or categories no longer shared disappear. My own characters are never touched, and a
friend's characters are never exported again. ZIP member names are never used as file paths.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from .database import SCHEMA_VERSION, Database
from .jsonl import (BY_NAME, FORMAT, FORMAT_VERSION, RECORD_TYPES, ExportFilter, JsonlImportResult, _Importer,
                    iter_records, read_records)

# Category -> per-character record types. The character record itself is always included.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "chronicle": ("character_stat", "event", "profession", "recipe", "recipe_category"),
    "routes": ("position",),
    "sessions": ("session",),
    "screenshots": ("screenshot", "screenshot_event"),
}
GLOBAL_TYPES: dict[str, tuple[str, ...]] = {"routes": ("map_info", "instance", "instance_entrance")}
SHAREABLE_TYPES = {"character"} | {t for ts in CATEGORIES.values() for t in ts} | \
    {t for ts in GLOBAL_TYPES.values() for t in ts}

JSONL_NAME = "share.jsonl"
SHARE_ID = re.compile(r"^[0-9a-f]{32}$")
SCREENSHOT_NAME = re.compile(r"^screenshots/([A-Za-z0-9_-]{1,64})\.jpg$")
MAX_JSONL_BYTES = 200 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_MEMBERS = 5000
MAX_SENDER = 64
IMAGE_WIDTH = 1600


@dataclass
class ShareExportResult:
    path: Path
    characters: int = 0
    records: int = 0
    images: int = 0
    missing_images: int = 0


@dataclass
class ShareImportResult(JsonlImportResult):
    sender: str | None = None
    images: int = 0
    skipped_characters: list[str] = field(default_factory=list)


def clean_sender(name: str) -> str:
    """Free text name without control characters, at most MAX_SENDER characters."""
    return "".join(ch for ch in name if ch.isprintable()).strip()[:MAX_SENDER]


# -- export -----------------------------------------------------------------------------------


def _scaled_jpeg(path: Path) -> bytes | None:
    """The picture as JPEG, at most IMAGE_WIDTH wide; None if it cannot be read."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage
    image = QImage(str(path))
    if image.isNull():
        return None
    if image.width() > IMAGE_WIDTH:
        image = image.scaledToWidth(IMAGE_WIDTH, Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "JPG", 85)
    buffer.close()
    return bytes(data)


def export_share(db: Database, path: Path, share_id: str, sender: str, selection: dict[str, set[str]],
                 screenshots: set[tuple[str, str]] | None = None) -> ShareExportResult:
    """Writes a share file. selection: my character_id -> categories; screenshots: picked (character_id,
    screenshot_id) pairs (only for characters with the "screenshots" category)."""
    result = ShareExportResult(path)
    own = {r[0]: r[1] for r in db.conn.execute(
        "SELECT character_id, natural_key FROM characters WHERE owner_id IS NULL")}
    unknown = [cid for cid in selection if cid not in own]
    if unknown:
        raise ValueError("only your own characters can be shared")

    # Pictures first: a screenshot without a readable picture is not shared.
    images: dict[str, bytes] = {}
    picked: set[tuple[str, str]] = set()
    for cid, sid in sorted(screenshots or ()):
        if "screenshots" not in selection.get(cid, ()) or not re.match(r"^[A-Za-z0-9_-]{1,64}$", sid):
            continue
        row = db.conn.execute("SELECT file_path FROM screenshots WHERE character_id = ? AND screenshot_id = ?",
                              (cid, sid)).fetchone()
        data = _scaled_jpeg(Path(row[0])) if row and row[0] and Path(row[0]).is_file() else None
        if data is None:
            result.missing_images += 1
            continue
        images[sid] = data
        picked.add((cid, sid))

    categories = {cid: {c for c in cats if c in CATEGORIES} for cid, cats in selection.items()}
    flt = ExportFilter(
        characters={cid: {t for c in cats for t in CATEGORIES[c]} for cid, cats in categories.items()},
        types={"character"} | {t for cats in categories.values() for c in cats for t in CATEGORIES[c]}
        | {t for cats in categories.values() for c in cats for t in GLOBAL_TYPES.get(c, ())},
        screenshots=picked)
    header = {"record_type": "header", "format": FORMAT, "format_version": FORMAT_VERSION, "kind": "share",
              "app_version": __version__, "db_schema": SCHEMA_VERSION, "share_id": share_id,
              "sender": clean_sender(sender), "created_at": int(time.time()),
              "characters": {own[cid]: sorted(cats) for cid, cats in categories.items()}}
    lines = [json.dumps(header, ensure_ascii=False, separators=(",", ":"))]
    for rec in iter_records(db, flt):
        lines.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        result.records += 1
        if rec["record_type"] == "character":
            result.characters += 1

    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(JSONL_NAME, "\n".join(lines) + "\n")
        for sid, data in images.items():
            zf.writestr(f"screenshots/{sid}.jpg", data, compress_type=zipfile.ZIP_STORED)
    tmp.replace(path)
    result.images = len(images)
    return result


# -- import -----------------------------------------------------------------------------------


def _child_tables() -> list[str]:
    return [rt.table for rt in RECORD_TYPES if rt.per_character]


def delete_character_data(db: Database, character_id: str, keep_character: bool) -> None:
    for table in _child_tables():
        db.conn.execute(f"DELETE FROM {table} WHERE character_id = ?", (character_id,))
    if not keep_character:
        db.conn.execute("DELETE FROM characters WHERE character_id = ?", (character_id,))


def remove_friend(db: Database, owner_id: int, friends_dir: Path | None) -> None:
    """Deletes a friend with all their characters and pictures."""
    row = db.conn.execute("SELECT share_id FROM owners WHERE owner_id = ?", (owner_id,)).fetchone()
    with db.transaction():
        for (cid,) in db.conn.execute("SELECT character_id FROM characters WHERE owner_id = ?", (owner_id,)).fetchall():
            delete_character_data(db, cid, keep_character=False)
        db.conn.execute("DELETE FROM owners WHERE owner_id = ?", (owner_id,))
    if row and friends_dir and SHARE_ID.match(row[0]):
        shutil.rmtree(friends_dir / row[0], ignore_errors=True)


def _read_zip(path: Path, result: ShareImportResult) -> tuple[list[str] | None, dict[str, zipfile.ZipInfo]]:
    """share.jsonl lines and picture members (screenshot_id -> member). Unexpected members are ignored."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        result.status = "rejected"
        result.messages.append(f"not a share file ({exc})")
        return None, {}
    with zf:
        members = zf.infolist()
        if len(members) > MAX_MEMBERS:
            result.status = "rejected"
            result.messages.append("share file has too many entries")
            return None, {}
        jsonl = next((m for m in members if m.filename == JSONL_NAME), None)
        if jsonl is None or jsonl.file_size > MAX_JSONL_BYTES:
            result.status = "rejected"
            result.messages.append("share file has no usable share.jsonl")
            return None, {}
        try:
            text = zf.read(jsonl).decode("utf-8-sig")
        except (zipfile.BadZipFile, UnicodeDecodeError, OSError) as exc:
            result.status = "rejected"
            result.messages.append(f"share.jsonl unreadable ({exc})")
            return None, {}
        images = {}
        for m in members:
            match = SCREENSHOT_NAME.match(m.filename)
            if match and m.file_size <= MAX_IMAGE_BYTES:
                images[match.group(1)] = m
        return text.splitlines(), images


def import_share(db: Database, path: Path, my_share_id: str, friends_dir: Path) -> ShareImportResult:
    """Imports a friend's share file. Their previous data is replaced by this file."""
    result = ShareImportResult(source=str(path))
    lines, image_members = _read_zip(path, result)
    if lines is None:
        return result
    header, records = read_records(lines, result)
    if header is None:
        return result
    share_id, sender, created = header.get("share_id"), header.get("sender"), header.get("created_at")
    shared = header.get("characters")
    if (header.get("kind") != "share" or not isinstance(share_id, str) or not SHARE_ID.match(share_id)
            or not isinstance(sender, str) or not isinstance(created, int) or not isinstance(shared, dict)):
        result.status = "rejected"
        result.messages.append("not a valid share file (header)")
        return result
    if share_id == my_share_id:
        result.status = "rejected"
        result.messages.append("this is your own share file")
        return result
    sender = clean_sender(sender) or "?"
    result.sender = sender

    conn = db.conn
    owner = conn.execute("SELECT * FROM owners WHERE share_id = ?", (share_id,)).fetchone()
    if owner is not None and owner["shared_at"] is not None and created <= owner["shared_at"]:
        result.status = "unchanged"
        result.messages.append("this file is not newer than the one imported before")
        return result

    folder = friends_dir / share_id
    staging = friends_dir / f"{share_id}.new"   # pictures are swapped in only after the database commit
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _import_into(db, path, header, records, image_members, owner, share_id, sender, created, folder, staging,
                     result)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(folder, ignore_errors=True)
    if staging.exists():
        staging.rename(folder)
    return result


def _import_into(db: Database, path: Path, header: dict[str, Any], records: list[tuple[int, dict[str, Any]]],
                 image_members: dict[str, zipfile.ZipInfo], owner: Any, share_id: str, sender: str, created: int,
                 folder: Path, staging: Path, result: ShareImportResult) -> None:
    conn = db.conn
    shared = header["characters"]
    with db.transaction():
        if owner is None:
            cur = conn.execute("INSERT INTO owners (share_id, display_name) VALUES (?, ?)", (share_id, sender))
            owner_id = int(cur.lastrowid)
        else:
            owner_id = owner["owner_id"]
        conn.execute("UPDATE owners SET display_name = ?, shared_at = ?, imported_at = ? WHERE owner_id = ?",
                     (sender, created, int(time.time()), owner_id))

        # Characters of this file: never one of mine or another friend's.
        taken = {r[0]: r[1] for r in conn.execute(
            "SELECT natural_key, COALESCE(owner_id, 0) FROM characters WHERE COALESCE(owner_id, 0) <> ?", (owner_id,))}
        mine_before = {r[0]: r[1] for r in conn.execute(
            "SELECT natural_key, character_id FROM characters WHERE owner_id = ?", (owner_id,))}
        accepted: set[str] = set()
        for key in shared:
            if not isinstance(key, str):
                continue
            if key in taken:
                result.skipped_characters.append(key)
            else:
                accepted.add(key)
        if result.skipped_characters:
            result.messages.append(f"{len(result.skipped_characters)} characters skipped (already yours or "
                                   f"another friend's)")

        # Replace: everything shared before goes; characters no longer shared go completely.
        for key, cid in mine_before.items():
            delete_character_data(db, cid, keep_character=key in accepted)

        characters = {key: cid for key, cid in mine_before.items() if key in accepted}
        importer = _Importer(db, result, characters)
        importer.foreign = set()
        for number, rec in records:
            rtype = rec["record_type"]
            if rtype not in SHAREABLE_TYPES:
                result.problem(number, f"{rtype}: not allowed in share files")
                continue
            if rtype == "character":
                key = rec.get("natural_key")
                if key not in accepted:
                    continue
                _upsert_friend_character(db, importer, number, rec, owner_id, characters, result)
                continue
            if BY_NAME[rtype].per_character and rec.get("character") not in accepted:
                continue
            importer.row(number, rec)

        missing = accepted - set(characters)
        for key in missing:
            result.problem(0, f"character {key} listed but not included")

        # Pictures: friends/<share_id>/<screenshot_id>.jpg, names from our own pattern, never from the ZIP.
        rows = conn.execute("""SELECT s.character_id, s.screenshot_id FROM screenshots s
                               JOIN characters c ON c.character_id = s.character_id WHERE c.owner_id = ?""",
                            (owner_id,)).fetchall()
        if rows:
            staging.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path) as zf:
                for cid, sid in rows:
                    member = image_members.get(sid)
                    file = None
                    if member is not None:
                        (staging / f"{sid}.jpg").write_bytes(zf.read(member))
                        file = folder / f"{sid}.jpg"
                        result.images += 1
                    conn.execute("UPDATE screenshots SET file_path = ?, file_match = ? WHERE character_id = ? "
                                 "AND screenshot_id = ?", (str(file) if file else None,
                                                          "shared" if file else "not_shared", cid, sid))

        if result.invalid:
            result.status = "partial"
        conn.execute("""INSERT INTO import_runs (source_path, source_type, account, started_at, finished_at, status,
                        rows_imported, rows_duplicate, rows_invalid, message)
                        VALUES (?, 'share', ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (str(path), sender, int(time.time()), int(time.time()), result.status,
                      result.inserted + result.updated, result.unchanged, result.invalid,
                      "; ".join(result.messages) or None))
    result.characters = len(characters)


def _upsert_friend_character(db: Database, importer: _Importer, number: int, rec: dict[str, Any], owner_id: int,
                             characters: dict[str, str], result: ShareImportResult) -> None:
    """Friend characters are replaced as a whole by the newest file (keeping the local character_id)."""
    from .jsonl import _valid_value
    columns = importer.columns["character"]
    values: dict[str, Any] = {}
    for col, (declared, _) in columns.items():
        if col in ("character_id", "owner_id") or col not in rec:
            continue
        if not _valid_value(rec[col], declared):
            result.problem(number, f"character: invalid value for {col}")
            return
        values[col] = rec[col]
    if not isinstance(values.get("name"), str) or not values.get("identity_quality"):
        result.problem(number, "character: name missing")
        return
    values.setdefault("created_at", int(time.time()))
    values["owner_id"] = owner_id
    key = values["natural_key"]
    if key in characters:
        sets = ", ".join(f"{k} = ?" for k in values)
        db.conn.execute(f"UPDATE characters SET {sets} WHERE character_id = ?", (*values.values(), characters[key]))
        result.updated += 1
    else:
        values["character_id"] = str(uuid.uuid4())
        cols = ", ".join(values)
        db.conn.execute(f"INSERT INTO characters ({cols}) VALUES ({', '.join('?' for _ in values)})",
                        tuple(values.values()))
        characters[key] = values["character_id"]
        result.inserted += 1
