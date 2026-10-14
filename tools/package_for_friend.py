"""Builds dist/ForeverChronicle-<version>.zip for a friend: the addon, the desktop app (source, no venv),
"Forever Chronicle starten.bat", which sets everything up on the friend's PC, and the map images from this
PC's app folder (%APPDATA%\\ForeverChronicle\\maps), bundled as desktop/forever_chronicle/maps/.

    desktop\\.venv\\Scripts\\python tools\\package_for_friend.py
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
TOP = "ForeverChronicle"
SKIP_PARTS = {"__pycache__", ".venv", "tests", "forever_chronicle.egg-info"}

README = """Forever Chronicle {version}
==========================

1. Diesen Ordner an einen festen Platz entpacken (z. B. Dokumente\\ForeverChronicle), nicht im ZIP starten.
2. "Forever Chronicle starten.bat" doppelklicken.
   - Beim ersten Start wird Python eingerichtet (fragt nach, falls Python fehlt) und die App installiert.
     Das dauert ein paar Minuten.
   - Das Addon wird automatisch in deinen WoW-Forever-Ordner kopiert (gefunden ueber Battle.net).
   - Danach startet die Desktop-App. Spaeter einfach immer ueber diese Datei starten: sie aktualisiert
     auch das Addon, wenn du eine neue Version bekommst.
3. Im Spiel /reload eingeben (oder das Spiel neu starten). Das Fenster oeffnest du mit /fc oder dem
   Minimap-Knopf.

Freunde: Das Teilen mit Freunden laeuft ueber den gemeinsamen Cloud-Ordner (dort tools\Einrichten.bat
einmal starten). Im Spiel waehlst du oben im Fenster aus, wessen Charakter du sehen willst.

Die Kartenbilder fuer die Karte in der Desktop-App sind schon dabei.
"""


def version() -> str:
    toc = (ROOT / "addons" / "ForeverChronicle" / "ForeverChronicle.toc").read_text(encoding="utf-8")
    match = re.search(r"^## Version:\s*(\S+)", toc, re.M)
    return match.group(1) if match else "dev"


def files() -> list[tuple[Path, str]]:
    out = [(ROOT / "Forever Chronicle starten.bat", "Forever Chronicle starten.bat"),
           (ROOT / "desktop" / "pyproject.toml", "desktop/pyproject.toml")]
    for base in (ROOT / "addons" / "ForeverChronicle", ROOT / "desktop" / "forever_chronicle"):
        for f in sorted(base.rglob("*")):
            rel = f.relative_to(ROOT)
            if f.is_file() and not SKIP_PARTS.intersection(rel.parts) and f.suffix != ".pyc":
                out.append((f, rel.as_posix()))
    return out


def map_images(home: Path | None = None) -> list[Path]:
    """The imported map images of this PC (<app home>/maps/<uiMapID>.jpg|png)."""
    if home is None:
        override = os.environ.get("FOREVER_CHRONICLE_HOME")
        home = Path(override) if override else Path(os.environ.get("APPDATA") or Path.home()) / "ForeverChronicle"
    folder = home / "maps"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.stem.isdigit() and p.suffix.lower() in IMAGE_EXTENSIONS)


def build(dest: Path | None = None, home: Path | None = None) -> Path:
    v = version()
    dest = dest or ROOT / "dist" / f"ForeverChronicle-{v}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, name in files():
            zf.write(src, f"{TOP}/{name}")
        for image in map_images(home):   # already compressed: store
            zf.write(image, f"{TOP}/desktop/forever_chronicle/maps/{image.name}", compress_type=zipfile.ZIP_STORED)
        zf.writestr(f"{TOP}/LIES MICH.txt", README.format(version=v).replace("\n", "\r\n"))
    return dest


if __name__ == "__main__":
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    maps = sum(1 for n in names if "/forever_chronicle/maps/" in n)
    print(f"{path}  ({len(names)} files, {maps} map images, {path.stat().st_size // (1024 * 1024)} MB)")
    if not maps:
        print("Hinweis: keine Kartenbilder gefunden (erst in der App unter Import einlesen).")
