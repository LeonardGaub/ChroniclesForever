"""Links screenshot records to image files in the client's Screenshots folder (spec F-003, F-010).

The client names files ``WoWScrnShot_MMDDYY_HHMMSS.<ext>`` using the local time of the capture, and the
addon stores the same stamp. A file whose stamp differs by up to TOLERANCE seconds also counts, because the
file is written a moment after the call. The nearest unclaimed file wins. If two files are equally near,
the record is marked ``ambiguous`` and left unlinked rather than guessed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from ..storage.repository import Repository

PREFIX = "WoWScrnShot_"
EXTENSIONS = (".jpg", ".jpeg", ".png", ".tga")
STAMP_FORMAT = "%m%d%y_%H%M%S"
TOLERANCE = 2


def parse_stamp(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, STAMP_FORMAT)
    except (TypeError, ValueError):
        return None


def index_folder(folder: Path) -> dict[str, list[Path]]:
    """stamp -> files with that stamp."""
    index: dict[str, list[Path]] = {}
    try:
        files = list(folder.iterdir())
    except OSError:
        return index
    for f in files:
        if f.suffix.lower() in EXTENSIONS and f.name.startswith(PREFIX):
            index.setdefault(f.stem[len(PREFIX):], []).append(f)
    return index


def match_screenshots(repo: Repository, folder: Path | None) -> int:
    """Matches all unlinked screenshot records. Returns the number of newly matched files."""
    if folder is None or not folder.is_dir():
        return 0
    index = index_folder(folder)
    claimed = repo.claimed_files()
    matched = 0
    rows = sorted(repo.unmatched_screenshots(), key=lambda r: (r["captured_at"] or 0, r["seq"]))
    for row in rows:
        base = parse_stamp(row["file_stamp"])
        if base is None:
            continue
        result, path = "not_found", None
        for distance in range(TOLERANCE + 1):
            offsets = (0,) if distance == 0 else (distance, -distance)
            found = []
            for offset in offsets:
                stamp = (base + timedelta(seconds=offset)).strftime(STAMP_FORMAT)
                found += [f for f in index.get(stamp, []) if str(f) not in claimed]
            if len(found) == 1:
                result, path = "matched", str(found[0])
                break
            if len(found) > 1:
                result = "ambiguous"
                break
        repo.set_screenshot_file(row["character_id"], row["screenshot_id"], path, result)
        if path:
            claimed.add(path)
            matched += 1
    return matched
