"""Friends' screenshots from the cloud folder, so their characters' cinematic, Chronik and gallery show the pictures.

Each friend's sync uploads the pictures of their shared characters, scaled down, sorted per character
(sync/ForeverSync.ps1, Send-Screenshots):  <cloud>\\screenshots\\<player file name>\\<character>-<realm>\\WoWScrnShot_<stamp>.jpg
Here they are copied to %APPDATA%\\ForeverChronicle\\friend_screenshots\\ in the same folders, so playing them never
waits for OneDrive (files on demand) and they stay when OneDrive is offline. The copy follows the cloud: new pictures
come, pictures the friend no longer shares go, and so do friends whose file is gone.

The friend's screenshot records come with their share file (friend_importer); each is linked to its picture by the
stamp, like my own (screenshot_matcher). The sync names each picture after the addon's stamp, so they match exactly.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..cloud_sync import SyncSetup
from ..config import app_home
from ..storage.database import Database
from ..storage.repository import Repository
from .friend_importer import friend_files
from .screenshot_matcher import EXTENSIONS, PREFIX, link_rows

FOLDER = "friend_screenshots"


@dataclass
class FriendScreenshotsResult:
    copied: int = 0      # pictures copied from the cloud now
    removed: int = 0     # local pictures the friends no longer share
    relinked: int = 0    # screenshot records whose picture changed (new, gone, moved)

    @property
    def changed(self) -> bool:
        return bool(self.copied or self.removed or self.relinked)


def local_folder(home: Path | None = None) -> Path:
    return (home or app_home()) / FOLDER


def _pictures(folder: Path) -> dict[Path, Path]:
    """Pictures in a player's folder: path relative to it (character\\file) -> path. Empty when the folder is missing."""
    found: dict[Path, Path] = {}
    try:
        characters = [d for d in folder.iterdir() if d.is_dir()]
        for character in characters:
            for f in character.iterdir():
                if f.is_file() and f.name.startswith(PREFIX) and f.suffix.lower() in EXTENSIONS:
                    found[f.relative_to(folder)] = f
    except OSError:
        pass
    return found


def _mirror(source: Path, target: Path, result: FriendScreenshotsResult) -> None:
    wanted = _pictures(source)
    for rel, src in wanted.items():
        dst = target / rel
        try:
            size = src.stat().st_size
            if dst.is_file() and dst.stat().st_size == size:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".tmp")
            shutil.copyfile(src, tmp)            # reading a OneDrive placeholder downloads it
            os.replace(tmp, dst)
            result.copied += 1
        except OSError:
            continue                             # not downloaded yet (OneDrive offline): next time
    for rel, dst in _pictures(target).items():
        if rel not in wanted:
            dst.unlink(missing_ok=True)
            result.removed += 1
    if target.is_dir():
        for character in target.iterdir():
            if character.is_dir() and not any(character.iterdir()):
                character.rmdir()
        if not any(target.iterdir()):
            target.rmdir()


def _link(db: Database, owner_id: int, folder: Path) -> int:
    """Links the friend's screenshot records to the local pictures. Returns how many records changed."""
    rows = db.conn.execute("""SELECT s.* FROM screenshots s JOIN characters c ON c.character_id = s.character_id
                              WHERE c.owner_id = ? AND s.status IN ('api_called', 'confirmed')
                              AND s.file_stamp IS NOT NULL""", (owner_id,)).fetchall()
    before = {(r["character_id"], r["screenshot_id"]): r["file_path"] for r in rows}
    index: dict[str, list[Path]] = {}
    for f in _pictures(folder).values():
        index.setdefault(f.stem[len(PREFIX):], []).append(f)
    link_rows(Repository(db.conn), rows, index, set())
    after = db.conn.execute("""SELECT s.character_id, s.screenshot_id, s.file_path FROM screenshots s
                               JOIN characters c ON c.character_id = s.character_id WHERE c.owner_id = ?""",
                            (owner_id,)).fetchall()
    return sum(1 for cid, sid, path in after if (cid, sid) in before and before[(cid, sid)] != path)


def sync_friend_screenshots(db: Database, setup: SyncSetup, home: Path | None = None) -> FriendScreenshotsResult:
    result = FriendScreenshotsResult()
    files = friend_files(setup)
    if files is None:
        return result
    cloud = Path(setup.cloud) / "screenshots"
    local = local_folder(home)
    kept: set[str] = set()
    for f, share_id in files:
        row = db.conn.execute("SELECT owner_id FROM owners WHERE share_id = ?", (share_id,)).fetchone()
        if row is None:
            continue  # not imported (a broken file): its pictures would have no records
        name = f.path.stem
        kept.add(name)
        _mirror(cloud / name, local / name, result)
        with db.transaction():
            result.relinked += _link(db, row[0], local / name)
    if local.is_dir():
        for folder in local.iterdir():
            if folder.is_dir() and folder.name not in kept:   # friend gone, or renamed (the new name was copied)
                result.removed += len(_pictures(folder))
                shutil.rmtree(folder, ignore_errors=True)
    return result
