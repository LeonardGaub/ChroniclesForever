"""Cloud backup (docs/Cloud_Backup.md): this PC's addon file, screenshots and app database go to a cloud folder the
player chooses (any folder a cloud client syncs, e.g. OneDrive). Several players can share one folder; each has a
folder of their own, named after the name they type in the app:

    <cloud>\\<name>\\addon\\<account>\\ForeverChronicle_<YYYY-MM-DD_HHMMSS>_<PC>.lua    the newest KEEP are kept
    <cloud>\\<name>\\database\\chronicle_<YYYY-MM-DD_HHMMSS>_<PC>.db                    the newest KEEP are kept
    <cloud>\\<name>\\screenshots\\WoWScrnShot_*.jpg                                      full size, only ever added

Nothing is overwritten: every upload of a changed file is a new dated copy, and the local files are never changed by
an upload. <account> is a hash of the WoW account folder's name. Restoring brings back an addon file, the missing
screenshots or a database copy; what it replaces is saved aside first. My second PC uses the same name and so the
same folder; ``newer_elsewhere`` tells when the newest addon copy there came from the other PC.
Every other player folder in the cloud (one with an addon folder) is a friend's (importing/friend_importer.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import AppConfig, app_home
from .importing.screenshot_matcher import EXTENSIONS, PREFIX
from .storage.database import Database
from .wow.paths import ClientInstall, find_saved_variables

KEEP = 30
ADDON_FILE = "ForeverChronicle.lua"
ADDON_PREFIX, ADDON_SUFFIX = "ForeverChronicle_", ".lua"
DB_PREFIX, DB_SUFFIX = "chronicle_", ".db"
STAMP = "%Y-%m-%d_%H%M%S"
VERSION_NAME = re.compile(r"^(?P<prefix>ForeverChronicle_|chronicle_)(?P<stamp>\d{4}-\d{2}-\d{2}_\d{6})_(?P<pc>.+)"
                          r"(?P<suffix>\.lua|\.db)$")
NEWER_MARGIN = 120     # seconds: a cloud copy counts as newer than the local file only beyond this


@dataclass(frozen=True)
class BackupSettings:
    cloud: Path
    name: str

    @property
    def player_dir(self) -> Path:
        return self.cloud / folder_name(self.name)


@dataclass(frozen=True)
class Version:
    """One dated copy in the cloud."""
    path: Path
    when: datetime
    pc: str
    account: str = ""        # addon copies: the account folder's hash

    @property
    def mine(self) -> bool:
        return self.pc == pc_name()


@dataclass
class BackupResult:
    addon: int = 0           # new addon copies
    database: bool = False   # a new database copy
    screenshots: int = 0     # pictures copied to the cloud
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.addon or self.database or self.screenshots)


@dataclass
class RestoreResult:
    addon: Path | None = None        # where the replaced local file was saved
    screenshots: int = 0
    database: Path | None = None     # the local backup of the replaced database
    errors: list[str] = field(default_factory=list)


def folder_name(name: str) -> str:
    """A player's folder: the name without characters Windows forbids."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .")
    return cleaned[:40].strip(" .") or "Spieler"


def pc_name() -> str:
    """This PC in the copies' names (letters, digits, - and _ only)."""
    raw = os.environ.get("COMPUTERNAME") or socket.gethostname() or "PC"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-") or "PC"


def account_id(account: str) -> str:
    return hashlib.sha256(account.encode("utf-8")).hexdigest()[:8]


def settings(config: AppConfig) -> BackupSettings | None:
    """The chosen cloud folder and name, or None when either is missing."""
    cloud, name = config.extra.get("cloud_folder"), config.extra.get("cloud_name")
    if not isinstance(cloud, str) or not cloud or not isinstance(name, str) or not name.strip():
        return None
    return BackupSettings(Path(cloud), name.strip())


def adopt_old_settings(config: AppConfig) -> None:
    """First start after the friends sync was removed: its cloud folder (%LOCALAPPDATA%\\ForeverChronicle\\sync\\
    config.json) and the name of the old share feature (extra.share_name) as a start. Changes nothing set already."""
    if not config.extra.get("cloud_folder"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        try:
            old = json.loads((Path(base) / "ForeverChronicle" / "sync" / "config.json").read_text(encoding="utf-8-sig"))
            cloud = old.get("cloud") if isinstance(old, dict) else None
        except (OSError, ValueError):
            cloud = None
        if isinstance(cloud, str) and cloud and Path(cloud).is_dir():
            config.set("cloud_folder", cloud)
    share_name = config.extra.get("share_name")
    if not config.extra.get("cloud_name") and isinstance(share_name, str) and share_name.strip():
        config.set("cloud_name", share_name.strip())


# -- state (what this PC uploaded last) ----------------------------------------------------------------


def _state_path() -> Path:
    return app_home() / "cloud_backup.json"


def load_state() -> dict:
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# -- files ----------------------------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_stable(path: Path) -> bytes:
    """The file's bytes, read again while the game is still writing it (the size changed meanwhile)."""
    for _ in range(5):
        data = path.read_bytes()
        if path.stat().st_size == len(data):
            return data
        time.sleep(0.5)
    return path.read_bytes()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)              # reading a OneDrive placeholder downloads it
    os.replace(tmp, dst)


def _new_name(prefix: str, suffix: str, now: float | None = None) -> str:
    return f"{prefix}{datetime.fromtimestamp(now or time.time()).strftime(STAMP)}_{pc_name()}{suffix}"


def versions(folder: Path, account: str = "") -> list[Version]:
    """The dated copies in a folder, newest first."""
    found = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    for path in entries:
        match = VERSION_NAME.match(path.name)
        if not match or not path.is_file():
            continue
        try:
            when = datetime.strptime(match.group("stamp"), STAMP)
        except ValueError:
            continue
        found.append(Version(path, when, match.group("pc"), account))
    return sorted(found, key=lambda v: (v.when, v.path.name), reverse=True)


def addon_versions(s: BackupSettings) -> list[Version]:
    """All addon copies in my folder (every account, every PC), newest first."""
    root = s.player_dir / "addon"
    try:
        accounts = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return []
    found = [v for d in accounts for v in versions(d, d.name)]
    return sorted(found, key=lambda v: (v.when, v.path.name), reverse=True)


def database_versions(s: BackupSettings) -> list[Version]:
    return versions(s.player_dir / "database")


def _prune(folder: Path) -> None:
    for old in versions(folder)[KEEP:]:
        old.path.unlink(missing_ok=True)


def _pictures(folder: Path) -> dict[str, Path]:
    try:
        return {f.name: f for f in folder.iterdir()
                if f.is_file() and f.name.startswith(PREFIX) and f.suffix.lower() in EXTENSIONS}
    except OSError:
        return {}


# -- upload ---------------------------------------------------------------------------------------------


def database_snapshot(db: Database, target: Path) -> Path:
    """A consistent copy of the app database (SQLite's backup), made where the database connection lives (the
    main thread); ``upload`` takes it from there."""
    import sqlite3
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    dest = sqlite3.connect(target)
    try:
        db.conn.backup(dest)
    finally:
        dest.close()
    return target


def upload(s: BackupSettings, client: ClientInstall | None, snapshot: Path | None) -> BackupResult:
    """Everything that changed since this PC's last upload goes up as new copies; new screenshots too. Safe to run
    in a worker thread (no database access: ``snapshot`` is the database copy made before)."""
    result = BackupResult()
    state = load_state()
    if not s.cloud.is_dir():
        result.errors.append(f"cloud folder not available: {s.cloud}")
        return result
    now = time.time()
    for sv in (find_saved_variables(client) if client else []):
        try:
            data = _read_stable(sv.path)
            account = account_id(sv.account)
            key = f"addon:{folder_name(s.name)}:{account}"
            folder = s.player_dir / "addon" / account
            digest = _sha(data)
            if state.get(key) == digest and versions(folder):
                continue
            _write(folder / _new_name(ADDON_PREFIX, ADDON_SUFFIX, now), data)
            _prune(folder)
            state[key] = digest
            result.addon += 1
        except OSError as exc:
            result.errors.append(f"{sv.path.name}: {exc}")
    if snapshot is not None and snapshot.is_file():
        try:
            data = snapshot.read_bytes()
            key = f"database:{folder_name(s.name)}"
            folder = s.player_dir / "database"
            digest = _sha(data)
            if state.get(key) != digest or not versions(folder):
                _write(folder / _new_name(DB_PREFIX, DB_SUFFIX, now), data)
                _prune(folder)
                state[key] = digest
                result.database = True
        except OSError as exc:
            result.errors.append(f"database: {exc}")
        finally:
            snapshot.unlink(missing_ok=True)
    if client is not None:
        target = s.player_dir / "screenshots"
        there = _pictures(target)
        for name, src in sorted(_pictures(client.screenshots_dir).items()):
            try:
                if name in there and there[name].stat().st_size == src.stat().st_size:
                    continue
                _copy(src, target / name)
                result.screenshots += 1
            except OSError as exc:
                result.errors.append(f"{name}: {exc}")
    state["last_upload"] = int(now)
    save_state(state)
    return result


def has_changes(s: BackupSettings, client: ClientInstall | None) -> bool:
    """Whether the addon file or the screenshots changed since this PC's last upload (the catch-up at app start)."""
    state = load_state()
    for sv in (find_saved_variables(client) if client else []):
        key = f"addon:{folder_name(s.name)}:{account_id(sv.account)}"
        try:
            if state.get(key) != _sha(sv.path.read_bytes()):
                return True
        except OSError:
            continue
    if client is not None:
        there = _pictures(s.player_dir / "screenshots")
        if any(name not in there for name in _pictures(client.screenshots_dir)):
            return True
    return False


# -- restore --------------------------------------------------------------------------------------------


def restore_addon(version: Version, client: ClientInstall) -> Path | None:
    """Replaces the local addon file of the copy's account with the copy. The local one is saved aside first
    (%APPDATA%\\ForeverChronicle\\backups\\before-restore\\); returns where. Raises FileNotFoundError when this PC has
    no account folder for it (log in to WoW once first)."""
    target = next((sv.path for sv in find_saved_variables(client) if account_id(sv.account) == version.account), None)
    if target is None:
        accounts = client.path / "WTF" / "Account"
        folders = [d for d in accounts.iterdir() if d.is_dir() and account_id(d.name) == version.account] \
            if accounts.is_dir() else []
        if not folders:
            raise FileNotFoundError("no WoW account folder for this copy on this PC (log in to WoW once)")
        target = folders[0] / "SavedVariables" / ADDON_FILE
    saved = None
    if target.is_file():
        saved = app_home() / "backups" / "before-restore" / _new_name(ADDON_PREFIX, ADDON_SUFFIX)
        _copy(target, saved)
    data = version.path.read_bytes()
    _write(target, data)
    state = load_state()
    state[f"addon:{version.path.parents[2].name}:{version.account}"] = _sha(data)   # not uploaded again as new
    save_state(state)
    return saved


def restore_screenshots(s: BackupSettings, client: ClientInstall) -> int:
    """Copies the cloud's pictures that are missing in the game's Screenshots folder; returns how many."""
    here = _pictures(client.screenshots_dir)
    copied = 0
    for name, src in sorted(_pictures(s.player_dir / "screenshots").items()):
        if name not in here:
            _copy(src, client.screenshots_dir / name)
            copied += 1
    return copied


def missing_screenshots(s: BackupSettings, client: ClientInstall | None) -> int:
    if client is None:
        return 0
    here = _pictures(client.screenshots_dir)
    return sum(1 for name in _pictures(s.player_dir / "screenshots") if name not in here)


def restore_database(version: Version, db: Database) -> Path | None:
    """Replaces the app database's contents with the copy (Database.restore backs up the current state first and
    migrates older copies). Returns that backup."""
    local = app_home() / "backups" / "from-cloud" / version.path.name
    _copy(version.path, local)
    try:
        return db.restore(local)
    finally:
        local.unlink(missing_ok=True)


def newer_elsewhere(s: BackupSettings, client: ClientInstall | None) -> Version | None:
    """The newest addon copy in my folder from another PC, when it is newer than this PC's file for that account and
    differs from it: my other PC played since, so restoring may be wanted. Never acts by itself. (This PC's own
    uploads of its older file do not hide it: it compares with the local file's time.)"""
    if client is None:
        return None
    local = {account_id(sv.account): sv.path for sv in find_saved_variables(client)}
    for account, path in local.items():
        newest = [v for v in versions(s.player_dir / "addon" / account, account) if not v.mine][:1]
        if not newest:
            continue
        try:
            mtime = path.stat().st_mtime
            if newest[0].when.timestamp() <= mtime + NEWER_MARGIN:
                continue
            if _sha(newest[0].path.read_bytes()) == _sha(path.read_bytes()):
                continue
        except OSError:
            continue
        return newest[0]
    return None


def summary(s: BackupSettings) -> tuple[int, int, int]:
    """(addon copies, database copies, screenshots) in my cloud folder."""
    return len(addon_versions(s)), len(database_versions(s)), len(_pictures(s.player_dir / "screenshots"))


def friend_folders(cloud: Path, own_name: str | None) -> list[Path]:
    """The other players' folders in the cloud folder: every folder with an addon folder, except mine."""
    mine = folder_name(own_name).lower() if own_name else None
    try:
        entries = sorted(cloud.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [d for d in entries if d.is_dir() and d.name.lower() != mine and (d / "addon").is_dir()]
