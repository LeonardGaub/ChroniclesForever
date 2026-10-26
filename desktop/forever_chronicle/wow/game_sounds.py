"""The game's own sound effects for the desktop app: the level-up fanfare, the quest-complete chime, the
achievement sound and others, as WoW plays them.

They come out of the player's own install (wow/casc.py, by fileDataID) into %APPDATA%\\ForeverChronicle\\game_sounds
as OGG files; ui/sound.py turns them into WAV there (QSoundEffect plays WAV only) and plays them instead of the
built-in sounds (option "game_sounds"). Blizzard's files are never kept in git. Without the game (or numpy) the
built-in sounds play.

The fileDataIDs and their names were looked up in the community listfile (wago.tools); they are Classic-era files
that Forever still ships.
"""

from __future__ import annotations

from pathlib import Path

from ..config import app_home
from .paths import ClientInstall

SOUNDS = {
    "level_up": 567431,       # sound/interface/levelup.ogg
    "event": 567439,          # sound/interface/iquestcomplete.ogg (the quest-complete chime)
    "achievement": 569143,    # sound/spells/achievmentsound1.ogg
    "discovery": 567497,      # sound/interface/ignewtaxinodediscovered.ogg
    "click": 567481,          # sound/interface/iuiinterfacebuttona.ogg (igMainMenuOption)
    "revive": 568667,         # sound/spells/resurrection.ogg
    "teleport": 569735,       # sound/spells/teleport.ogg
}

_failed: set[str] = set()     # not readable from the game files (this session): not tried again


def cache_dir() -> Path:
    return app_home() / "game_sounds"


def wav_path(name: str) -> Path | None:
    """The game's sound for an effect, ready to play (None: not taken from the game yet)."""
    path = cache_dir() / f"{name}.wav"
    return path if name in SOUNDS and path.is_file() else None


def ogg_path(name: str) -> Path:
    return cache_dir() / f"{name}.ogg"


def missing() -> list[str]:
    return [name for name in SOUNDS if name not in _failed and wav_path(name) is None]


def extract_missing(client: ClientInstall | None) -> list[str]:
    """Takes the sounds that have no WAV yet out of the local game as OGG files (ogg_path). Returns their names.
    Each file is written under a temporary name first, so nothing ever reads half a file."""
    todo = [name for name in missing() if not ogg_path(name).is_file()]
    ready = [name for name in missing() if ogg_path(name).is_file()]
    if not todo or client is None:
        return ready
    from . import casc
    storage = casc.open_client(client)
    if storage is None:  # no numpy, or the game files cannot be read: the built-in sounds play
        _failed.update(todo)
        return ready
    for name in todo:
        try:
            data = storage.read_fdid(SOUNDS[name])
        except Exception:
            _failed.add(name)
            continue
        if data[:4] != b"OggS":
            _failed.add(name)
            continue
        casc.write_atomic(ogg_path(name), data)
        ready.append(name)
    return ready


def mark_failed(name: str) -> None:
    """A sound that could not be turned into WAV: the built-in one plays this session."""
    _failed.add(name)
