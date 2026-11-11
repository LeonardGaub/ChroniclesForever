"""Updates the installed app (and with it the addon) from the repository's GitHub releases.

Only the copy that "Journey Forever starten.bat" installs updates itself (%LOCALAPPDATA%\\ForeverChronicle\\app);
a git checkout never does (``installed_root``). The steps:

1. ``fetch_latest`` (at app start, in the background): the newest release of the public repository, through the
   GitHub API without login. Its tag is ``v<version>`` and it carries the friends' zip
   (``JourneyForever-<version>-Komplett.zip``, tools/package_for_friends.py --release) and ``<zip>.sha256``.
   The version is the addon's (ForeverChronicle.toc); it is newer when ``setup_addon._version_key`` says so.
2. ``download``: the zip into %LOCALAPPDATA%\\ForeverChronicle\\update\\, checked against the .sha256 file.
3. ``stage``: the zip's addon and app folders unpacked into ``app.new`` beside the app folder.
4. The app closes and ``start_apply`` starts ``python -m forever_chronicle.updater apply``, which waits until the
   app has exited, swaps ``app`` -> ``app.old`` and ``app.new`` -> ``app`` (two renames: the old version stays
   whole if anything fails), starts the new app and notes the outcome in ``update\\result.json``. The new app
   shows that note once (ui/update_dialog.py) and installs its newer addon into WoW as usual
   (setup_addon.update_addon).

New Python packages are not installed here: a version that needs one installs it itself (like ui/audio_setup.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .setup_addon import _version_key, addon_version
from .wow.paths import ADDON_NAME

REPOSITORY = "LeonardGaub/ChroniclesForever"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
USER_AGENT = "JourneyForever-Updater"
ZIP_TOP = "Journey Forever"                               # the zip's one top folder (package_for_friends.TOP)
PARTS = ("addons/ForeverChronicle/", "desktop/forever_chronicle/")
CHUNK = 256 * 1024


class UpdateError(Exception):
    """A failed step, with a message for the player."""


@dataclass
class Release:
    version: str
    notes: str
    zip_name: str
    zip_url: str
    zip_size: int
    sha256_url: str


def zip_name(version: str) -> str:
    return f"JourneyForever-{version}-Komplett.zip"


# -- where ------------------------------------------------------------------------------------------------------

def app_root() -> Path:
    """The folder holding addons\\ and desktop\\ (the repository for a checkout)."""
    return Path(__file__).resolve().parents[2]


def installed_root() -> Path | None:
    """The app folder when this app runs from the launcher's install (%LOCALAPPDATA%\\ForeverChronicle\\app),
    else None: git checkouts and other copies never update themselves."""
    local = os.environ.get("LOCALAPPDATA")
    root = app_root()
    if not local or (root / ".git").exists():
        return None
    expected = (Path(local) / "ForeverChronicle" / "app").resolve()
    return root if os.path.normcase(str(root)) == os.path.normcase(str(expected)) else None


def update_dir(root: Path) -> Path:
    return root.parent / "update"


def staging_dir(root: Path) -> Path:
    return root.with_name(root.name + ".new")


def old_dir(root: Path) -> Path:
    return root.with_name(root.name + ".old")


def current_version(root: Path) -> str | None:
    return addon_version(root / "addons" / ADDON_NAME)


def is_newer(version: str | None, current: str | None) -> bool:
    return bool(_version_key(version)) and _version_key(version) > _version_key(current)


# -- 1. the newest release --------------------------------------------------------------------------------------

def _open(url: str, timeout: float, accept: str = "application/octet-stream"):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(request, timeout=timeout)


def parse_release(data: dict) -> Release | None:
    """The release from the API's JSON, or None when it is not one of ours (tag, zip and checksum)."""
    version = str(data.get("tag_name") or "").removeprefix("v")
    if not _version_key(version) or data.get("draft") or data.get("prerelease"):
        return None
    assets = {a.get("name"): a for a in data.get("assets") or [] if isinstance(a, dict)}
    name = zip_name(version)
    archive, checksum = assets.get(name), assets.get(name + ".sha256")
    if not archive or not checksum:
        return None
    return Release(version, str(data.get("body") or "").strip(), name, archive["browser_download_url"],
                   int(archive.get("size") or 0), checksum["browser_download_url"])


def fetch_latest(url: str = LATEST_URL, timeout: float = 8) -> Release | None:
    """None without internet, before the repository is public, or without a fitting release."""
    try:
        with _open(url, timeout, "application/vnd.github+json") as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):                         # URLError and HTTPError are OSErrors
        return None
    return parse_release(data) if isinstance(data, dict) else None


# -- 2. download ------------------------------------------------------------------------------------------------

def download(release: Release, folder: Path, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False, timeout: float = 30) -> Path:
    """The release zip in ``folder``, its SHA-256 checked. Raises UpdateError."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with _open(release.sha256_url, timeout) as response:
            expected = response.read(4096).decode("ascii", "replace").split()[0].lower()
    except (OSError, IndexError) as exc:
        raise UpdateError(f"Prüfsumme nicht ladbar: {exc}") from exc
    target = folder / release.zip_name
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with _open(release.zip_url, timeout) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or release.zip_size or 0)
            done = 0
            while chunk := response.read(CHUNK):
                if cancelled():
                    raise UpdateError("Abgebrochen")
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download fehlgeschlagen: {exc}") from exc
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise UpdateError("Die Datei ist beschädigt angekommen (Prüfsumme falsch). Bitte später erneut versuchen.")
    part.replace(target)
    return target


# -- 3. unpack beside the app -----------------------------------------------------------------------------------

def stage(archive: Path, version: str, root: Path) -> Path:
    """The zip's addon and app folders in ``app.new``, checked to be the announced version."""
    staging = staging_dir(root)
    shutil.rmtree(staging, ignore_errors=True)
    if staging.exists():
        raise UpdateError(f"{staging} lässt sich nicht leeren")
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                path = PurePosixPath(info.filename)
                if info.is_dir() or not path.parts or path.parts[0] != ZIP_TOP:
                    continue
                rel = PurePosixPath(*path.parts[1:])
                if ".." in rel.parts or not any(str(rel).startswith(p) for p in PARTS):
                    continue
                dest = staging.joinpath(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Entpacken fehlgeschlagen: {exc}") from exc
    found = current_version(staging)
    if found != version or not (staging / "desktop" / "forever_chronicle" / "__main__.py").is_file():
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Das Paket enthält nicht Version {version} (gefunden: {found})")
    return staging


# -- 4. swap after the app has closed ---------------------------------------------------------------------------

def swap(root: Path, staging: Path, attempts: int = 40, pause: float = 0.5) -> None:
    """``app`` -> ``app.old``, ``app.new`` -> ``app``. Retries while files are still in use (the closing app, a
    virus scanner); the old version is put back if the second rename fails."""
    old = old_dir(root)
    shutil.rmtree(old, ignore_errors=True)
    for attempt in range(attempts):
        try:
            root.rename(old)
            break
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause)
    try:
        staging.rename(root)
    except OSError:
        old.rename(root)
        raise
    shutil.rmtree(old, ignore_errors=True)


def wait_for_exit(pid: int, timeout: float = 60) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.WinDLL("kernel32")
        handle = kernel.OpenProcess(0x00100000, False, pid)           # SYNCHRONIZE
        if handle:
            kernel.WaitForSingleObject(handle, int(timeout * 1000))
            kernel.CloseHandle(handle)
        return
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)


def _detached() -> int:
    return getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def start_apply(root: Path) -> None:
    """Called by the closing app: the apply step in its own process, run from outside the app folder."""
    env = dict(os.environ, PYTHONPATH=str(root / "desktop"))
    subprocess.Popen([sys.executable, "-m", "forever_chronicle.updater", "apply", str(os.getpid()), str(root)],
                     cwd=root.parent, env=env, creationflags=_detached(), close_fds=True)


def start_app(root: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.Popen([sys.executable, "-m", "forever_chronicle"], cwd=root / "desktop", env=env,
                     creationflags=_detached(), close_fds=True)


def write_result(root: Path, ok: bool, version: str | None, error: str = "") -> None:
    folder = update_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_text(json.dumps({"ok": ok, "version": version, "error": error}),
                                        encoding="utf-8")


def take_result(root: Path) -> dict | None:
    """The last apply step's outcome, once (the file is removed)."""
    path = update_dir(root) / "result.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    return data if isinstance(data, dict) else None


def clean_up(root: Path) -> None:
    """At start: leftovers of an earlier update (old version, downloads)."""
    shutil.rmtree(old_dir(root), ignore_errors=True)
    for file in update_dir(root).glob("*.zip*"):
        file.unlink(missing_ok=True)


def apply(pid: int, root: Path, launch: Callable[[Path], None] = start_app) -> bool:
    staging = staging_dir(root)
    version = current_version(staging)
    wait_for_exit(pid)
    try:
        swap(root, staging)
    except OSError as exc:
        write_result(root, False, version, str(exc))
        ok = False
    else:
        write_result(root, True, version)
        ok = True
    launch(root)
    return ok


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3 or argv[0] != "apply":
        print("Aufruf: python -m forever_chronicle.updater apply <pid> <app-Ordner>")
        return 2
    return 0 if apply(int(argv[1]), Path(argv[2])) else 1


if __name__ == "__main__":
    sys.exit(main())
