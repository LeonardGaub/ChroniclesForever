"""Installs (or updates) the addon in this PC's WoW Forever client. Used by "Journey Forever starten.bat":

    python -m forever_chronicle.setup_addon <path to addons\\ForeverChronicle>

The game folder comes from the app settings, else Battle.net / the usual folders (wow/paths.py); if none is
found, the user is asked for it. The choice is saved, so the desktop app uses the same folder.
Friends\\FriendsData.lua in the game folder belongs to the desktop app and is never overwritten.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .wow.paths import ADDON_NAME, ClientInstall, client_from_path, find_forever_installs

KEEP = {Path("Friends") / "FriendsData.lua"}   # written by the desktop app in the game folder


@dataclass
class InstallResult:
    target: Path
    copied: int
    removed: int
    version: str | None


def bundled_addon() -> Path | None:
    """The addon next to the app: addons\\ForeverChronicle in the repository or the friends' package."""
    source = Path(__file__).resolve().parents[2] / "addons" / ADDON_NAME
    return source if (source / f"{ADDON_NAME}.toc").is_file() else None


def addon_version(addon: Path) -> str | None:
    try:
        for line in (addon / f"{ADDON_NAME}.toc").read_text(encoding="utf-8").splitlines():
            if line.startswith("## Version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def install_addon(source: Path, client: ClientInstall) -> InstallResult:
    """Mirrors the addon folder into the client's AddOns folder (stale files removed, KEEP files kept)."""
    if not (source / f"{ADDON_NAME}.toc").is_file():
        raise FileNotFoundError(f"{source} is not the {ADDON_NAME} addon folder")
    target = client.addons_dir / ADDON_NAME
    target.mkdir(parents=True, exist_ok=True)
    wanted = set()
    copied = 0
    for file in source.rglob("*"):
        if not file.is_file() or "__pycache__" in file.parts:
            continue
        rel = file.relative_to(source)
        wanted.add(rel)
        dest = target / rel
        if rel in KEEP and dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)
        copied += 1
    removed = 0
    for file in sorted(target.rglob("*"), reverse=True):
        rel = file.relative_to(target)
        if file.is_file() and rel not in wanted and rel not in KEEP:
            file.unlink()
            removed += 1
        elif file.is_dir() and not any(file.iterdir()):
            file.rmdir()
    return InstallResult(target, copied, removed, addon_version(source))


def find_client(config: AppConfig, ask=input) -> ClientInstall | None:
    if config.client_dir:
        client = client_from_path(Path(config.client_dir))
        if client:
            return client
    installs = find_forever_installs()
    if installs:
        return installs[0]
    print("WoW Forever wurde nicht automatisch gefunden.")
    while True:
        answer = ask("Pfad zum Spielordner (z. B. D:\\Spiele\\World of Warcraft), leer = abbrechen: ").strip().strip('"')
        if not answer:
            return None
        client = client_from_path(Path(answer))
        if client:
            return client
        print("In diesem Ordner ist kein WoW-Forever-Client. Bitte den Ordner 'World of Warcraft' oder "
              "'_classic_beta_' angeben.")


def main(argv: list[str] | None = None, ask=input) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("Aufruf: python -m forever_chronicle.setup_addon <Addon-Ordner>")
        return 2
    config = AppConfig.load()
    client = find_client(config, ask)
    if client is None:
        print("Abgebrochen: kein Spielordner.")
        return 1
    if config.client_dir != str(client.path):
        config.client_dir = str(client.path)
        config.save()
    try:
        result = install_addon(Path(argv[0]), client)
    except OSError as exc:
        print(f"Addon konnte nicht installiert werden: {exc}")
        print("Tipp: Spiel schließen und erneut starten; ggf. Schreibrechte für den Spielordner prüfen.")
        return 1
    print(f"Addon Journey Forever {result.version or ''} installiert: {result.target}")
    print("Läuft das Spiel gerade, im Spiel /reload eingeben (bei einer neuen Addon-Version: Spiel neu starten).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
