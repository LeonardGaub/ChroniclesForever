"""Event icons from the game: the textures the addon shows, as small PNG files.

An icon is a texture path (the event type's icon, e.g. "Interface\\Icons\\INV_Misc_Note_01") or a fileDataID (the
icon the addon records with an event: achievement, profession, mount). Its file is named after the texture
("inv_misc_note_01.png") or the ID ("136243.png"). Two folders, the first one wins:
- forever_chronicle/icons/: the event types' icons (domain/event_types.py), kept in git; tools/extract_icons.py
  writes them.
- %APPDATA%\\ForeverChronicle\\icons\\: icons taken from the local game install when needed (extract_missing,
  after each import). Needs numpy and Pillow; without them, or without the game, the app shows its symbols.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable, Union

from ..config import app_home
from .paths import ClientInstall

Icon = Union[int, str]

BUNDLED = Path(__file__).resolve().parents[1] / "icons"
ICON_FOLDER = "Interface\\Icons\\"

_failed: set[str] = set()  # not in the game files (this session): not looked up again
generation = 0              # counts extractions, so pictures of icons that were missing can be loaded again


def cache_dir() -> Path:
    return app_home() / "icons"


def name_of(icon: Icon | None) -> str | None:
    """File name (without .png) of an icon, or None for no icon."""
    if isinstance(icon, bool) or icon is None:
        return None
    if isinstance(icon, int):
        return str(icon) if icon > 0 else None
    icon = icon.strip()
    if icon.isdigit():
        return icon if int(icon) > 0 else None
    name = icon.replace("/", "\\").rsplit("\\", 1)[-1]
    if name.lower().endswith(".blp"):
        name = name[:-4]
    return name.lower() or None


def game_path(icon: str) -> str:
    """Path of a texture in the game files (texture paths without a folder are icons)."""
    path = icon.replace("/", "\\")
    if "\\" not in path:
        path = ICON_FOLDER + path
    return path if path.lower().endswith(".blp") else path + ".blp"


def find(icon: Icon | None) -> Path | None:
    name = name_of(icon)
    if not name:
        return None
    for folder in (BUNDLED, cache_dir()):
        path = folder / f"{name}.png"
        if path.is_file():
            return path
    return None


def missing(icons: Iterable[Icon | None]) -> list[Icon]:
    """The icons without a file that were not looked up in vain before, one per name."""
    result, seen = [], set()
    for icon in icons:
        name = name_of(icon)
        if name and name not in seen and name not in _failed and find(icon) is None:
            seen.add(name)
            result.append(int(name) if name.isdigit() else icon)
    return result


def extract(install_root: Path, product: str, icons: Iterable[Icon], out_dir: Path) -> list[str]:
    """Takes icons out of the game files (install_root: the "World of Warcraft" folder) into out_dir as PNG.
    Returns the names written; the others are remembered as missing. Raises ImportError without numpy or
    Pillow and casc.CascError if the install cannot be read."""
    from PIL import Image

    from . import casc

    storage = casc.Casc(install_root, product)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for icon in icons:
        name = name_of(icon)
        if not name:
            continue
        try:
            data = storage.read_fdid(int(name)) if name.isdigit() else storage.read_name(game_path(str(icon)))
            Image.open(io.BytesIO(data)).convert("RGBA").save(out_dir / f"{name}.png")
            written.append(name)
        except Exception:  # not in the files, encrypted, or no picture: the app keeps its symbol
            _failed.add(name)
    return written


def extract_missing(client: ClientInstall | None, icons: Iterable[Icon | None]) -> int:
    """Takes the icons that have no file yet out of the local game into the cache folder. Returns how many."""
    global generation
    todo = missing(icons)
    if not todo or client is None:
        return 0
    try:
        written = extract(client.path.parent, client.flavor, todo, cache_dir())
    except Exception:  # no numpy/Pillow, or the game files cannot be read: not tried again this session
        _failed.update(n for n in map(name_of, todo) if n)
        return 0
    if written:
        generation += 1
    return len(written)
