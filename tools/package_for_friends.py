"""Builds the zip to share with friends (Google Drive and the like): the addon, the desktop app and
"Journey Forever starten.bat", which sets everything up on their PC with one double-click.

    desktop\\.venv\\Scripts\\python tools\\package_for_friends.py [target.zip]

Output: dist/friends/JourneyForever-<version>-Komplett.zip (about 35 MB, most of it the map images), with one
folder "Journey Forever" at the top:
    Journey Forever starten.bat     Python, packages, app copy to %LOCALAPPDATA%, addon into WoW, shortcut
                                    (asked once), start
    LIES MICH.txt                   the steps for the friend
    addons/ForeverChronicle/        the addon
    desktop/forever_chronicle/      the desktop app (source; the venv is built on the friend's PC)

Files come from git (tracked plus untracked, not ignored), so caches, venvs and local leftovers stay out.
The CurseForge upload (addon only) is tools/package_curseforge.py.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "Journey Forever"
LAUNCHER = "Journey Forever starten.bat"
PARTS = ("addons/ForeverChronicle/", "desktop/forever_chronicle/")
STORED = {".jpg", ".jpeg", ".png", ".ogg", ".mp3", ".ico"}   # already compressed

README = """Journey Forever {version}
==========================

Addon fuer WoW Forever plus Desktop-App (Chronik, Statistiken, Kino-Modus, Cloud-Backup).

Installieren
------------
1. Die ZIP-Datei entpacken: Rechtsklick -> "Alle extrahieren...". Nicht direkt im ZIP starten.
2. Im entpackten Ordner "{launcher}" doppelklicken.
   - Meldet Windows "Der Computer wurde durch Windows geschuetzt": auf "Weitere Informationen" und
     dann "Trotzdem ausfuehren" klicken.
   - Beim ersten Mal wird Python eingerichtet (fragt nach, falls es fehlt) und die App installiert.
     Das dauert ein paar Minuten und braucht Internet.
   - Das Addon wird automatisch in deinen WoW-Forever-Ordner kopiert. Wird das Spiel nicht gefunden,
     fragt das Fenster nach dem Ordner (z. B. C:\\Program Files (x86)\\World of Warcraft).
   - Am Ende fragt das Fenster, ob es die Verknuepfung "Journey Forever" auf dem Desktop und im
     Startmenue anlegen soll (J = ja, N = nein). Danach startet die App von selbst.
3. Ist WoW gerade offen: im Spiel /reload eingeben. Das Addon-Fenster oeffnest du mit /fj oder
   dem Knopf an der Minimap.

Mit Verknuepfung brauchst du den entpackten Ordner und die ZIP danach nicht mehr. Ohne Verknuepfung
den Ordner behalten: die App startest du dann immer wieder ueber "{launcher}".

Spaeter
-------
- Starten: Verknuepfung "Journey Forever" (oder "{launcher}").
- Neue Version: die neue ZIP entpacken und "{launcher}" wieder doppelklicken.
  Deine Daten bleiben erhalten (sie liegen in %APPDATA%\\ForeverChronicle).
- Die App liest deine Spieldaten, wenn du dich im Spiel ausloggst oder /reload eingibst.

Probleme? Ein Foto/Screenshot vom Fenster an Leon schicken.
"""


def version() -> str:
    toc = (ROOT / "addons" / "ForeverChronicle" / "ForeverChronicle.toc").read_text(encoding="utf-8")
    match = re.search(r"^## Version:\s*(\S+)", toc, re.M)
    return match.group(1) if match else "dev"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def files() -> list[str]:
    """Repository-relative paths in the zip besides the readme: the launcher and the two folders."""
    listed = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *PARTS).split("\0")
    paths = sorted(p for p in listed if p and (ROOT / p).is_file() and "__pycache__" not in p)
    return [LAUNCHER, *paths]


def build(dest: Path | None = None) -> Path:
    v = version()
    dest = dest or ROOT / "dist" / "friends" / f"JourneyForever-{v}-Komplett.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    launcher = (ROOT / LAUNCHER).read_bytes()
    if b"\r\n" not in launcher or launcher.replace(b"\r\n", b"").count(b"\n"):
        raise SystemExit(f"{LAUNCHER} needs Windows line endings (CRLF), or cmd.exe misreads its labels")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files():
            stored = Path(rel).suffix.lower() in STORED
            zf.write(ROOT / rel, f"{TOP}/{rel}", compress_type=zipfile.ZIP_STORED if stored else None)
        readme = README.format(version=v, launcher=LAUNCHER).replace("\n", "\r\n")
        zf.writestr(f"{TOP}/LIES MICH.txt", readme.encode("ascii"))
    return dest


if __name__ == "__main__":
    if git("status", "--porcelain", "--", LAUNCHER, *PARTS).strip():
        print("Hinweis: uncommitted changes in the addon or app are included in the zip.")
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    print(f"{path}  ({len(names)} files, {path.stat().st_size / (1024 * 1024):.1f} MB)")
