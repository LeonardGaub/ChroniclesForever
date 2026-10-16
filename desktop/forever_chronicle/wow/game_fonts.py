"""The game's own fonts: Friz Quadrata (headings, buttons, tabs) and Morpheus (large titles), as WoW draws them.

They come out of the player's own install (wow/casc.py, by their names in the game files) into
%APPDATA%\\ForeverChronicle\\fonts the first time the app starts with the game found, and are loaded into the app
from there on every start (QFontDatabase). Blizzard's files are never kept in git. Without them (no game, no numpy)
the app falls back to the serif fonts in ui/theme.py.
"""

from __future__ import annotations

from pathlib import Path

from ..config import app_home
from .paths import ClientInstall

FILES = {"FRIZQT__.TTF": "Fonts\\FRIZQT__.TTF", "MORPHEUS.TTF": "Fonts\\MORPHEUS.TTF"}
HEADING = "Friz Quadrata TT"   # their family names
TITLE = "Morpheus"

loaded: list[str] = []         # families loaded into the app this session


def cache_dir() -> Path:
    return app_home() / "fonts"


def missing() -> list[str]:
    return [name for name in FILES if not (cache_dir() / name).is_file()]


def extract_missing(client: ClientInstall | None) -> int:
    """Takes the fonts that are not in the cache yet out of the local game. Returns how many were added."""
    todo = missing()
    if not todo or client is None:
        return 0
    try:
        from . import casc
        storage = casc.Casc(client.path.parent, client.flavor)
    except Exception:  # no numpy, or the game files cannot be read: the app keeps its fallback fonts
        return 0
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for name in todo:
        try:
            data = storage.read_name(FILES[name])
        except Exception:
            continue
        part = folder / f"{name}.part"
        part.write_bytes(data)
        part.replace(folder / name)
        written += 1
    return written


def load() -> list[str]:
    """Loads the cached fonts into the app (once per session). Returns the families now available."""
    from PySide6.QtGui import QFontDatabase

    for name in FILES:
        path = cache_dir() / name
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        for family in QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []:
            if family not in loaded:
                loaded.append(family)
    return list(loaded)


def install(client: ClientInstall | None) -> list[str]:
    """Takes the fonts from the game if needed and loads them."""
    extract_missing(client)
    return load()
