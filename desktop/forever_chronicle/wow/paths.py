"""Locating the WoW Forever client, its account folders and SavedVariables files."""

from __future__ import annotations

import string
from dataclasses import dataclass
from pathlib import Path

ADDON_NAME = "ForeverChronicle"
# Product flavors that run Forever. The beta uses "wow_classic_beta"; add the live flavor when known.
FOREVER_FLAVORS = ("wow_classic_beta",)


@dataclass(frozen=True)
class ClientInstall:
    path: Path      # e.g. ...\World of Warcraft\_classic_beta_
    flavor: str     # from .flavor.info, e.g. "wow_classic_beta"

    @property
    def screenshots_dir(self) -> Path:
        return self.path / "Screenshots"

    @property
    def addons_dir(self) -> Path:
        return self.path / "Interface" / "AddOns"


@dataclass(frozen=True)
class SavedVariablesFile:
    account: str    # account folder name, e.g. "131324136#1"
    path: Path

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ".bak")


def read_flavor(client_dir: Path) -> str | None:
    """Product flavor from ``.flavor.info`` (second line), or None."""
    info = client_dir / ".flavor.info"
    try:
        lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return lines[1].strip() if len(lines) > 1 else None


def candidate_roots() -> list[Path]:
    roots = []
    for drive in string.ascii_uppercase:
        base = Path(f"{drive}:\\")
        for sub in ("Program Files (x86)", "Program Files", "Games", ""):
            roots.append(base / sub / "World of Warcraft" if sub else base / "World of Warcraft")
    return roots


def find_forever_installs(extra_roots: list[Path] | None = None) -> list[ClientInstall]:
    """All client folders whose flavor is a known Forever flavor."""
    found = []
    seen = set()
    for root in (extra_roots or []) + candidate_roots():
        try:
            if not root.is_dir():
                continue
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child in seen:
                continue
            flavor = read_flavor(child)
            if flavor in FOREVER_FLAVORS:
                seen.add(child)
                found.append(ClientInstall(child, flavor))
    return found


def client_from_path(path: Path) -> ClientInstall | None:
    """Accepts the client folder itself or the World of Warcraft root folder."""
    flavor = read_flavor(path)
    if flavor:
        return ClientInstall(path, flavor)
    installs = find_forever_installs([path])
    return installs[0] if installs else None


def find_saved_variables(client: ClientInstall, addon: str = ADDON_NAME) -> list[SavedVariablesFile]:
    """SavedVariables files of the addon, one per account folder."""
    accounts_dir = client.path / "WTF" / "Account"
    result = []
    try:
        accounts = sorted(p for p in accounts_dir.iterdir() if p.is_dir())
    except OSError:
        return result
    for account in accounts:
        sv = account / "SavedVariables" / f"{addon}.lua"
        if sv.is_file() or sv.with_name(sv.name + ".bak").is_file():
            result.append(SavedVariablesFile(account.name, sv))
    return result
