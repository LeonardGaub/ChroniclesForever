"""Builds the CurseForge upload: only the main addon folder, checked against the rules first.

    desktop\\.venv\\Scripts\\python tools\\package_curseforge.py

Output in dist/curseforge/:
    ForeverChronicle/                     the addon folder as uploaded (for a look before uploading)
    JourneyForever-<version>.zip          the upload: the addon folder at the top level of the zip

Not part of it: the friends companion (ForeverChronicle_Share), the cloud sync scripts, the desktop app, tests.

Checks (the build stops on any error):
- Blizzard UI Add-On Development Policy: code visible (plain Lua, no compiled or encoded files), no advertising,
  no donation requests, no paid features.
- CurseForge: no third-party download links, the zip holds the addon folder at its top level, the .toc is named
  like its folder.
- Clean addon: nothing the player sees refers to the private desktop app, the cloud sync or the friends
  companion; the .toc lists exactly the files that exist.
"""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = "ForeverChronicle"
SOURCE = ROOT / "addons" / ADDON
DIST = ROOT / "dist" / "curseforge"

ALLOWED_SUFFIXES = {".lua", ".toc", ".xml", ".tga", ".blp", ".ogg", ".mp3", ".ttf", ".txt", ".md"}
# Words that must not appear in anything the player sees (locale strings, .toc notes).
FORBIDDEN_TEXT = {
    r"https?://|www\.": "web link",
    r"donat|spende|patreon|ko-fi|paypal|buymeacoffee": "donation request",
    r"desktop": "the private desktop app",
    r"cloud|sync": "the private cloud sync",
    r"ForeverChronicle_Share|Freunde-Daten|ForeverChronicleFriends": "the friends companion",
}
# Code may not use these at all (the companion's job; the main addon must work alone).
FORBIDDEN_CODE = {
    r"ForeverChronicleFriends|ForeverChronicleShareDB|ForeverChronicle_Share": "friends companion data",
    r"\bloadstring\b|\bRunScript\b": "loading code at runtime",
}
# Reviewed exceptions: (file, what) -> why it is allowed.
ALLOWED_CODE = {
    ("Core/Storage.lua", "loading code at runtime"):
        "unpacks the saved file's packed records: only text that passes plainData() (literal data, no names or "
        "calls) is compiled, with an empty environment",
}


def toc_info(folder: Path) -> tuple[dict[str, str], list[str]]:
    lines = (folder / f"{folder.name}.toc").read_text(encoding="utf-8").splitlines()
    tags = {}
    files = []
    for line in lines:
        line = line.strip()
        if line.startswith("##"):
            key, _, value = line[2:].partition(":")
            tags[key.strip()] = value.strip()
        elif line and not line.startswith("#"):
            files.append(line.replace("\\", "/"))
    return tags, files


def locale_strings(text: str) -> list[str]:
    return re.findall(r'=\s*"((?:[^"\\]|\\.)*)"', text)


def check(folder: Path) -> list[str]:
    errors = []
    toc = folder / f"{folder.name}.toc"
    if not toc.is_file():
        return [f"{toc.name} missing: the .toc must be named like its folder"]
    tags, listed = toc_info(folder)
    for tag in ("Interface", "Title", "Version"):
        if not tags.get(tag):
            errors.append(f".toc: ## {tag} missing")
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    for f in files:
        if Path(f).suffix.lower() not in ALLOWED_SUFFIXES:
            errors.append(f"{f}: file type not allowed in an addon upload")
    lua = [f for f in files if f.endswith(".lua")]
    for f in listed:
        if f not in files:
            errors.append(f".toc lists {f}, which does not exist")
    for f in lua:
        if f not in listed:
            errors.append(f"{f} is not listed in the .toc (left over?)")
    visible = [f"{k}: {v}" for k, v in tags.items() if k.startswith(("Notes", "Title"))]
    for f in lua:
        text = (folder / f).read_text(encoding="utf-8")
        if f.startswith("Locales/"):
            visible += [f"{f}: {s}" for s in locale_strings(text)]
        code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())  # without comments
        for pattern, what in FORBIDDEN_CODE.items():
            if re.search(pattern, code) and (f, what) not in ALLOWED_CODE:
                errors.append(f"{f}: uses {what}")
    for item in visible:
        for pattern, what in FORBIDDEN_TEXT.items():
            if re.search(pattern, item, re.IGNORECASE):
                errors.append(f"player-visible text mentions {what}: {item[:120]}")
    return errors


def build() -> Path:
    errors = check(SOURCE)
    if errors:
        print("Not packaged - fix first:")
        for e in errors:
            print("  - " + e)
        raise SystemExit(1)
    tags, _ = toc_info(SOURCE)
    version = tags["Version"]
    folder = DIST / ADDON
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(SOURCE, folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    zip_path = DIST / f"JourneyForever-{version}.zip"   # project name; the folder inside stays ForeverChronicle
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                zf.write(f, f"{ADDON}/{f.relative_to(folder).as_posix()}")
    return zip_path


if __name__ == "__main__":
    path = build()
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    print(f"{path}  ({len(names)} files, {path.stat().st_size // 1024} KB)")
    print(f"Folder to look at: {DIST / ADDON}")
    sys.exit(0)
