"""Map artwork (private use).

Artwork lives in ``<app home>/maps/<uiMapID>.jpg|png``. ``import_map_art`` copies the fully explored zone
images from the user's archive (a .zip or a folder containing "Explored zones/<name>.jpg") into that folder,
renamed by uiMapID. Only known image names are taken; nothing from the archive is executed or extracted
under its own path.

The 52 explored-zone images also ship with the code in ``forever_chronicle/maps/`` (kept in the private repo and
in the friend package, tools/package_for_friend.py). Lookups use the user's own folder first, then the bundled
images.
"""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

from ..config import app_home
from ..domain.maps import BY_ART

MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
SOURCE_FOLDER = "explored zones"


def art_dir() -> Path:
    return app_home() / "maps"


def bundled_dir() -> Path:
    """Images shipped with the app (in git and in the friend package)."""
    return Path(__file__).resolve().parents[1] / "maps"


def _folders(folder: Path | None) -> list[Path]:
    return [folder] if folder is not None else [art_dir(), bundled_dir()]


def find_art(map_id: int | None, folder: Path | None = None) -> Path | None:
    if map_id is None:
        return None
    for base in _folders(folder):
        for ext in (".jpg", ".png", ".jpeg"):
            path = base / f"{map_id}{ext}"
            if path.is_file():
                return path
    return None


def available_art(folder: Path | None = None) -> set[int]:
    found: set[int] = set()
    for base in _folders(folder):
        try:
            found |= {int(p.stem) for p in base.iterdir()
                      if p.stem.isdigit() and p.suffix.lower() in IMAGE_EXTENSIONS}
        except OSError:
            pass
    return found


def _looks_like_image(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"


def _target(name: str) -> tuple[int, str] | None:
    """(map_id, extension) for a source file name like 'Explored zones/barrens.jpg', else None."""
    path = PurePosixPath(name.replace("\\", "/"))
    if path.parent.name.lower() != SOURCE_FOLDER or path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    known = BY_ART.get(path.stem.lower())
    if not known:
        return None
    ext = ".png" if path.suffix.lower() == ".png" else ".jpg"
    return known.map_id, ext


def import_map_art(source: Path, dest: Path | None = None) -> int:
    """Copies known map images from a .zip or folder into the art folder. Returns the number of images."""
    dest = dest or art_dir()
    dest.mkdir(parents=True, exist_ok=True)
    count = 0

    def store(name: str, data: bytes) -> None:
        nonlocal count
        target = _target(name)
        if not target or len(data) > MAX_IMAGE_BYTES or not _looks_like_image(data):
            return
        map_id, ext = target
        for old in dest.glob(f"{map_id}.*"):
            old.unlink()
        (dest / f"{map_id}{ext}").write_bytes(data)
        count += 1

    if source.is_dir():
        for path in source.rglob("*"):
            if path.is_file() and not any(part.startswith("__MACOSX") for part in path.parts):
                if _target(path.relative_to(source).as_posix()) and path.stat().st_size <= MAX_IMAGE_BYTES:
                    store(path.relative_to(source).as_posix(), path.read_bytes())
    else:
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                if info.is_dir() or info.filename.startswith("__MACOSX") or info.file_size > MAX_IMAGE_BYTES:
                    continue
                if _target(info.filename):
                    store(info.filename, archive.read(info))
    return count
