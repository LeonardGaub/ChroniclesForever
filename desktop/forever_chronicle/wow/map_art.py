"""Map artwork provided by the user (private use, not distributed).

Artwork lives in ``<app home>/maps/<uiMapID>.jpg|png``. ``import_map_art`` copies the fully explored zone
images from the user's archive (a .zip or a folder containing "Explored zones/<name>.jpg") into that folder,
renamed by uiMapID. Only known image names are taken; nothing from the archive is executed or extracted
under its own path.
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


def find_art(map_id: int | None, folder: Path | None = None) -> Path | None:
    if map_id is None:
        return None
    folder = folder or art_dir()
    for ext in (".jpg", ".png", ".jpeg"):
        path = folder / f"{map_id}{ext}"
        if path.is_file():
            return path
    return None


def available_art(folder: Path | None = None) -> set[int]:
    folder = folder or art_dir()
    try:
        return {int(p.stem) for p in folder.iterdir() if p.stem.isdigit() and p.suffix.lower() in IMAGE_EXTENSIONS}
    except OSError:
        return set()


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
