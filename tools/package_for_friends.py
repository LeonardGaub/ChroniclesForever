"""Builds the zip to share with friends (Google Drive and the like): the addon, the desktop app and
"Journey Forever starten.bat", which sets everything up on their PC with one double-click.

    desktop\\.venv\\Scripts\\python tools\\package_for_friends.py [target.zip]
    desktop\\.venv\\Scripts\\python tools\\package_for_friends.py --release

--release also publishes the zip as GitHub release v<version> of the repository, which the installed apps
download at start (desktop/forever_chronicle/updater.py). It needs a clean, pushed main and a version that has
no release yet (raise "## Version:" in ForeverChronicle.toc first); the release notes are CHANGELOG.md's section
for that version. The token comes from GITHUB_TOKEN or git's credential manager (the one git push uses).

Output: dist/friends/JourneyForever-<version>-Komplett.zip (about 35 MB, most of it the map images), with one
folder "Journey Forever" at the top:
    Journey Forever starten.bat     Python, packages, app copy to %LOCALAPPDATA%, addon into WoW, shortcut
                                    (asked once), start
    LIES MICH.txt                   the steps for the friend
    addons/ForeverChronicle/        the addon
    desktop/forever_chronicle/      the desktop app (source; the venv is built on the friend's PC)

Beside the zip: <zip>.sha256, which the app checks the download against.
Files come from git (tracked plus untracked, not ignored), so caches, venvs and local leftovers stay out.
The CurseForge upload (addon only) is tools/package_curseforge.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "Journey Forever"
LAUNCHER = "Journey Forever starten.bat"
PARTS = ("addons/ForeverChronicle/", "desktop/forever_chronicle/")
REPOSITORY = "LeonardGaub/ChroniclesForever"     # desktop/forever_chronicle/updater.py reads its releases
API = f"https://api.github.com/repos/{REPOSITORY}"
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
- Neue Version: die App fragt beim Start selbst nach ("Jetzt aktualisieren") und bringt dabei auch
  das neue Addon mit. Klappt das mal nicht: die neue ZIP entpacken und "{launcher}" wieder
  doppelklicken. Deine Daten bleiben erhalten (sie liegen in %APPDATA%\\ForeverChronicle).
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
    checksum_file(dest).write_text(f"{sha256(dest)}  {dest.name}\n", encoding="ascii")
    return dest


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_file(zip_path: Path) -> Path:
    return zip_path.with_name(zip_path.name + ".sha256")


# -- GitHub release (--release) ---------------------------------------------------------------------------------

def release_notes(v: str, changelog: str | None = None) -> str:
    """CHANGELOG.md's section "## <version> ..." without its heading ("" if there is none)."""
    text = changelog if changelog is not None else (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(v)}(?![\w.]).*?$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def token() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    answer = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    for line in answer.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("No GitHub token: set GITHUB_TOKEN or sign in to GitHub with git (git push) once")


def api(method: str, url: str, secret: str, body: bytes | None = None,
        content_type: str = "application/json") -> dict:
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {secret}", "Accept": "application/vnd.github+json",
        "User-Agent": "JourneyForever-Packager", "Content-Type": content_type})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read() or b"{}")


def check_publishable() -> str:
    """The commit to release: everything committed and pushed, so the release matches the repository."""
    if git("status", "--porcelain", "--", LAUNCHER, *PARTS, "CHANGELOG.md").strip():
        raise SystemExit("--release needs everything committed (addon, app, launcher, CHANGELOG.md)")
    if git("rev-list", "--count", "@{u}..HEAD").strip() != "0":
        raise SystemExit("--release needs the commits pushed first (git push)")
    return git("rev-parse", "HEAD").strip()


def publish(path: Path, v: str, commit: str) -> str:
    secret = token()
    tag = f"v{v}"
    try:
        api("GET", f"{API}/releases/tags/{tag}", secret)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    else:
        raise SystemExit(f"Release {tag} exists already: raise the version in ForeverChronicle.toc first")
    notes = release_notes(v)
    if not notes:
        print(f"Hinweis: CHANGELOG.md has no section '## {v}', the release has no notes.")
    created = api("POST", f"{API}/releases", secret, json.dumps({
        "tag_name": tag, "target_commitish": commit, "name": f"Journey Forever {v}", "body": notes,
    }).encode("utf-8"))
    upload = created["upload_url"].split("{", 1)[0]
    for file, kind in ((path, "application/zip"), (checksum_file(path), "text/plain")):
        query = urllib.parse.urlencode({"name": file.name})
        api("POST", f"{upload}?{query}", secret, file.read_bytes(), kind)
    return created.get("html_url", tag)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Builds the friends' zip; --release also publishes it.")
    parser.add_argument("target", nargs="?", type=Path, help="zip path (default: dist/friends/...)")
    parser.add_argument("--release", action="store_true", help="publish as GitHub release v<version>")
    args = parser.parse_args()
    commit = check_publishable() if args.release else ""
    if not args.release and git("status", "--porcelain", "--", LAUNCHER, *PARTS).strip():
        print("Hinweis: uncommitted changes in the addon or app are included in the zip.")
    path = build(args.target)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    print(f"{path}  ({len(names)} files, {path.stat().st_size / (1024 * 1024):.1f} MB)")
    if args.release:
        print(f"Published: {publish(path, version(), commit)}")
