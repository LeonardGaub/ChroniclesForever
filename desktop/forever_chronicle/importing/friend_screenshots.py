"""Friends' screenshots from the cloud folder, so their characters' cinematic, Chronik and gallery show the pictures.

Each friend's backup holds all their pictures, full size: <cloud>\\<friend>\\screenshots\\WoWScrnShot_<stamp>.jpg
(cloud_backup.py). Only the pictures their screenshot records point to are copied, to
%APPDATA%\\ForeverChronicle\\friend_screenshots\\<friend>\\, so playing them never waits for OneDrive (files on demand)
and they stay when OneDrive is offline. Each record is matched to its picture by the stamp like my own
(screenshot_matcher, up to 2 s apart). Pictures no longer pointed to go, and so do friends who are gone.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..cloud_backup import friend_folders
from ..config import app_home
from ..storage.database import Database
from ..storage.repository import Repository
from .friend_importer import share_id_of
from .screenshot_matcher import index_folder, link_rows

FOLDER = "friend_screenshots"


@dataclass
class FriendScreenshotsResult:
    copied: int = 0      # pictures copied from the cloud now
    removed: int = 0     # local pictures no longer needed
    relinked: int = 0    # screenshot records whose picture changed (new, gone, moved)

    @property
    def changed(self) -> bool:
        return bool(self.copied or self.removed or self.relinked)


def local_folder(home: Path | None = None) -> Path:
    return (home or app_home()) / FOLDER


class _Matches:
    """Stands in for the repository in link_rows: collects which cloud picture each record gets."""

    def __init__(self):
        self.found: dict[tuple[str, str], Path | None] = {}

    def set_screenshot_file(self, character_id: str, screenshot_id: str, path: str | None, result: str) -> None:
        self.found[(character_id, screenshot_id)] = Path(path) if path else None


def _sync_friend(db: Database, owner_id: int, cloud: Path, local: Path, result: FriendScreenshotsResult) -> None:
    rows = db.conn.execute("""SELECT s.* FROM screenshots s JOIN characters c ON c.character_id = s.character_id
                              WHERE c.owner_id = ? AND s.status IN ('api_called', 'confirmed')
                              AND s.file_stamp IS NOT NULL""", (owner_id,)).fetchall()
    matches = _Matches()
    link_rows(matches, rows, index_folder(cloud), set())        # listing the folder downloads nothing
    wanted: set[str] = set()
    repo = Repository(db.conn)
    with db.transaction():
        for row in rows:
            src = matches.found.get((row["character_id"], row["screenshot_id"]))
            path = None
            if src is not None:
                dst = local / src.name
                wanted.add(src.name)
                try:
                    if not (dst.is_file() and dst.stat().st_size == src.stat().st_size):
                        local.mkdir(parents=True, exist_ok=True)
                        tmp = dst.with_name(dst.name + ".tmp")
                        shutil.copyfile(src, tmp)          # reading a OneDrive placeholder downloads it
                        os.replace(tmp, dst)
                        result.copied += 1
                    path = str(dst)
                except OSError:
                    path = row["file_path"] if row["file_path"] and Path(row["file_path"]).is_file() else None
            if path != row["file_path"]:
                repo.set_screenshot_file(row["character_id"], row["screenshot_id"], path,
                                         "matched" if path else "not_found")
                result.relinked += 1
    if local.is_dir():
        for f in local.iterdir():
            if f.is_file() and f.name not in wanted:
                f.unlink(missing_ok=True)
                result.removed += 1


def sync_friend_screenshots(db: Database, cloud: Path | None, own_name: str | None,
                            home: Path | None = None) -> FriendScreenshotsResult:
    result = FriendScreenshotsResult()
    if cloud is None or not cloud.is_dir():
        return result
    local = local_folder(home)
    kept: set[str] = set()
    for folder in friend_folders(cloud, own_name):
        row = db.conn.execute("SELECT owner_id FROM owners WHERE share_id = ?", (share_id_of(folder),)).fetchone()
        if row is None:
            continue  # not imported (a broken file): its pictures would have no records
        kept.add(folder.name.lower())
        _sync_friend(db, row[0], folder / "screenshots", local / folder.name, result)
    if local.is_dir():
        for folder in local.iterdir():
            if folder.is_dir() and folder.name.lower() not in kept:   # friend gone (or from the old layout)
                result.removed += sum(1 for f in folder.rglob("*") if f.is_file())
                shutil.rmtree(folder, ignore_errors=True)
    return result
