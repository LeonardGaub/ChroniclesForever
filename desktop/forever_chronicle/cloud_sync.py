"""The cloud sync (sync/ForeverSync.ps1, docs/Sharing_Design.md) as the desktop app sees it: whether it is set up
on this PC, its log, what is in the cloud folder (my upload, friends' files) and in the game (the friends file), and
the commands for one run (push my data, pull friends' data) or the setup with a first run.

The sync runs only when asked: the app starts the repository's script (next to this app), which owns the cloud
folder and the game's Friends\\FriendsData.lua. Its settings and log stay in %LOCALAPPDATA%\\ForeverChronicle\\sync.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# As in ForeverSync.ps1: <name>-<id>-<account>.lua, or <shareId>-<account>.lua from scripts before 2026-10-16.
PLAYER_FILE = re.compile(r"^(?:(?P<name>\w{1,24})-(?P<id>[0-9a-f]{8})|(?P<long_id>[0-9a-f]{32}))"
                         r"-(?P<account>[0-9a-f]{8})\.lua$")
SHARE_NAME = re.compile(r'^[ \t]?\["name"\]\s*=\s*"((?:[^"\\\r\n]|\\.)*)"', re.MULTILINE)
FRIEND_ENTRY = re.compile(r'^add\("', re.MULTILINE)
MAX_PLAYER_BYTES = 8 * 1024 * 1024


def sync_dir() -> Path:
    """Where the script keeps its settings, log and backups (%LOCALAPPDATA%\\ForeverChronicle\\sync)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ForeverChronicle" / "sync"


def sync_script() -> Path | None:
    """The repository's sync script (None: the app runs without its repository)."""
    script = REPO / "sync" / "ForeverSync.ps1"
    return script if script.is_file() else None


@dataclass(frozen=True)
class SyncSetup:
    folder: Path
    cloud: str
    share_id: str = ""
    client: str = ""

    @property
    def friends_file(self) -> Path | None:
        if not self.client:
            return None
        return Path(self.client) / "Interface" / "AddOns" / "ForeverChronicle_Share" / "Friends" / "FriendsData.lua"


@dataclass(frozen=True)
class PlayerFile:
    """One player's upload in <cloud>\\players: mine (this PC's shareId) or a friend's."""
    path: Path
    name: str          # the name friends see, from the file; "?" when it cannot be read
    mine: bool
    modified: float
    size: int


def find_setup(folder: Path | None = None) -> SyncSetup | None:
    folder = folder or sync_dir()
    try:
        config = json.loads((folder / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(config, dict) or not config.get("cloud"):
        return None
    return SyncSetup(folder, str(config["cloud"]), str(config.get("shareId") or ""), str(config.get("client") or ""))


def _powershell(script: Path, *args: str) -> tuple[str, list[str]]:
    return "powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]


def run_command(script: Path, folder: Path) -> tuple[str, list[str]]:
    """One run: upload my data, fetch friends' data into the game, addon update, daily backup."""
    return _powershell(script, "-Once", "-DataDir", str(folder))


def setup_command(script: Path, folder: Path) -> tuple[str, list[str]]:
    """The setup (finds the cloud folder and the game, else asks) with a first run."""
    return _powershell(script, "-Setup", "-DataDir", str(folder))


def log_size(folder: Path) -> int:
    try:
        return (folder / "sync.log").stat().st_size
    except OSError:
        return 0


def log_lines(folder: Path, since: int = 0) -> list[str]:
    """The log's lines from byte offset ``since`` (e.g. its size before a run) on."""
    log = folder / "sync.log"
    try:
        with log.open("rb") as f:
            f.seek(since if since <= log.stat().st_size else 0)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.lstrip("﻿").splitlines() if line.strip()]


def share_name(text: str) -> str:
    """The name friends see: the top-level "name" of a share file."""
    match = SHARE_NAME.search(text)
    return re.sub(r"\\(.)", r"\1", match.group(1)) if match else "?"


def player_files(setup: SyncSetup) -> list[PlayerFile]:
    """All players' uploads in the cloud folder, mine first, then friends' by name."""
    players = Path(setup.cloud) / "players"
    try:
        entries = list(players.iterdir())
    except OSError:
        return []
    files = []
    for path in entries:
        match = PLAYER_FILE.match(path.name)
        if not match or not path.is_file():
            continue
        file_id = match.group("id") or match.group("long_id")
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace") if stat.st_size <= MAX_PLAYER_BYTES else ""
        except OSError:
            continue
        files.append(PlayerFile(path, share_name(text), bool(setup.share_id) and setup.share_id.startswith(file_id),
                                stat.st_mtime, stat.st_size))
    return sorted(files, key=lambda f: (not f.mine, f.name.lower(), f.path.name))


def friends_in_game(setup: SyncSetup) -> tuple[int, float] | None:
    """How many friends' files the game's friends file holds, and when the sync wrote it (None: not written yet)."""
    path = setup.friends_file
    if path is None:
        return None
    try:
        return len(FRIEND_ENTRY.findall(path.read_text(encoding="utf-8", errors="replace"))), path.stat().st_mtime
    except OSError:
        return None
