"""The game's own sound effects for the desktop app: the level-up fanfare, the quest-complete chime, the
achievement sound and others, as WoW plays them.

They come out of the player's own install (wow/casc.py, by fileDataID) into %APPDATA%\\ForeverChronicle\\game_sounds
as OGG files; ui/sound.py turns them into WAV there (QSoundEffect plays WAV only) and plays them instead of the
built-in sounds (option "game_sounds"). Blizzard's files are never kept in git. Without the game (or numpy) the
built-in sounds play.

The fileDataIDs and their names were looked up in the community listfile (wago.tools); they are Classic-era files
that Forever still ships. The flight sounds were found through the game's own tables (see SOUNDS), the wind through
SoundAmbience (LOOPS: pieces joined into one seamless loop, join_loop).
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
    # Flight paths (the cinematic mode). Found through the game's tables: TaxiNodes' mounts (gryphon 541, wind rider
    # 2224) -> CreatureModelData (the models named Gryphon and Wyvern) -> CreatureSoundData -> SoundKitEntry.
    "gryphon_call": 551348,   # the gryphon's aggro call
    "wind_rider_call": 564754,  # the wind rider's (Wyvern) aggro call
    "wing_flap": 564176,      # the wing flap both share
    "wing_flap_soft": 564176,
    "wing_glide": 564172,     # the gryphon's wing glide: a soft whoosh
}
# Sounds put together from several of the game's files. The wind on a flight path: the ten 5 s wind pieces of the
# zones' ambience (SoundAmbience's wind sound kit 292700), joined into one seamless loop.
LOOPS = {"wind": tuple(range(2843055, 2843065))}
LOOP_CROSSFADE = 0.6          # seconds the pieces overlap

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


def loop_path(name: str) -> Path | None:
    """A put-together sound (LOOPS), ready to play (None: not made yet)."""
    path = cache_dir() / f"{name}.wav"
    return path if name in LOOPS and path.is_file() else None


def missing_loops() -> list[str]:
    return [name for name in LOOPS if name not in _failed and loop_path(name) is None]


def extract_loop_pieces(client: ClientInstall | None, name: str) -> list[Path]:
    """Takes a loop's pieces out of the local game as OGG files. Returns them ([] if any is missing)."""
    if client is None:
        return []
    from . import casc
    storage = casc.open_client(client)
    if storage is None:
        _failed.add(name)
        return []
    pieces = []
    for i, fdid in enumerate(LOOPS[name]):
        path = cache_dir() / f"{name}_{i}.ogg"
        try:
            data = storage.read_fdid(fdid)
        except Exception:
            _failed.add(name)
            return []
        casc.write_atomic(path, data)
        pieces.append(path)
    return pieces


def join_loop(wavs: list[Path], target: Path, crossfade: float = LOOP_CROSSFADE) -> bool:
    """Joins 16-bit WAV pieces of the same format into one loop: each piece fades into the next (equal power),
    and the last into the first, so the loop has no seam. Returns whether target was written."""
    import wave

    import numpy as np
    parts = []
    params = None
    for path in wavs:
        with wave.open(str(path), "rb") as w:
            if params is None:
                params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != params or params[1] != 2:
                return False
            parts.append(np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, params[0])
                         .astype(np.float32))
    if not parts:
        return False
    n = int(crossfade * params[2])
    if any(len(p) <= 2 * n for p in parts):
        return False
    rise = np.sin(np.linspace(0, np.pi / 2, n, endpoint=False, dtype=np.float32))[:, None]
    fall = np.cos(np.linspace(0, np.pi / 2, n, endpoint=False, dtype=np.float32))[:, None]
    # Every piece without its head; its tail overlaps the next piece's head (the last one the first's).
    out = []
    for i, part in enumerate(parts):
        nxt = parts[(i + 1) % len(parts)]
        out.append(part[n:-n])
        out.append(part[-n:] * fall + nxt[:n] * rise)
    loop = np.clip(np.concatenate(out), -32768, 32767).astype("<i2")
    part_path = target.with_name(target.name + ".part")
    with wave.open(str(part_path), "wb") as w:
        w.setnchannels(params[0])
        w.setsampwidth(2)
        w.setframerate(params[2])
        w.writeframes(loop.tobytes())
    part_path.replace(target)
    return True


def mark_failed(name: str) -> None:
    """A sound that could not be turned into WAV: the built-in one plays this session."""
    _failed.add(name)
