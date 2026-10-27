"""Locating the WoW Forever client, its account folders and SavedVariables files."""

from __future__ import annotations

import os
import string
from dataclasses import dataclass
from pathlib import Path

from . import battlenet, casc

ADDON_NAME = "ForeverChronicle"
# Product flavors known to run Forever (wowf: the live client, installed on 2026-10-27). A client of any other flavor
# counts too when its build is 1.60 or newer (Forever's version line; Classic Era is 1.15).
FOREVER_FLAVORS = ("wow_classic_beta", "wowf")
FOREVER_VERSION = (1, 60)
TEST_FLAVOR_SUFFIXES = ("_beta", "_ptr")


@dataclass(frozen=True)
class ClientInstall:
    path: Path      # e.g. ...\World of Warcraft\_classic_beta_
    flavor: str     # from .flavor.info, e.g. "wow_classic_beta"

    @property
    def is_test(self) -> bool:
        """Beta or PTR client: a live client is preferred over it."""
        return self.flavor.endswith(TEST_FLAVOR_SUFFIXES)

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


def read_flavor(client_dir: Path) -> str | None:
    """Product flavor from ``.flavor.info`` (second line), or None."""
    info = client_dir / ".flavor.info"
    try:
        lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return lines[1].strip() if len(lines) > 1 else None


def build_version(install_root: Path, flavor: str) -> tuple[int, ...] | None:
    """Client version of a product from the install's ``.build.info``, e.g. (1, 60, 1, 70532), or None."""
    try:
        builds = casc.read_build_info(install_root)
    except (OSError, IndexError):
        return None
    for build in builds:
        if build.get("Product") == flavor:
            try:
                return tuple(int(part) for part in build.get("Version", "").split("."))
            except ValueError:
                return None
    return None


def is_forever(install_root: Path, flavor: str | None) -> bool:
    """Whether the product runs Forever; install_root is the World of Warcraft folder holding ``.build.info``."""
    if not flavor:
        return False
    if flavor in FOREVER_FLAVORS:
        return True
    version = build_version(install_root, flavor)
    return version is not None and version[0] == FOREVER_VERSION[0] and version[:2] >= FOREVER_VERSION


def forever_product(install_root: Path) -> str:
    """The Forever product in a World of Warcraft folder (for casc.Casc): the live client before the beta."""
    flavors = dict.fromkeys(b.get("Product", "") for b in casc.read_build_info(install_root))
    found = sorted((f for f in flavors if is_forever(install_root, f)), key=lambda f: f.endswith(TEST_FLAVOR_SUFFIXES))
    if not found:
        raise casc.CascError(f"no WoW Forever client in {install_root}")
    return found[0]


def candidate_roots() -> list[Path]:
    roots = []
    for drive in string.ascii_uppercase:
        base = Path(f"{drive}:\\")
        for sub in ("Program Files (x86)", "Program Files", "Games", ""):
            roots.append(base / sub / "World of Warcraft" if sub else base / "World of Warcraft")
    return roots


def scan_roots(roots: list[Path]) -> list[ClientInstall]:
    """Forever clients in the given folders: a root that is a client folder itself, or its subfolders.
    Live clients come before beta and PTR clients."""
    found: list[ClientInstall] = []
    seen: set[str] = set()

    def add(folder: Path) -> None:
        key = os.path.normcase(str(folder))
        if key in seen:
            return
        flavor = read_flavor(folder)
        if is_forever(folder.parent, flavor):
            seen.add(key)
            found.append(ClientInstall(folder, flavor))

    for root in roots:
        try:
            if not root.is_dir():
                continue
            add(root)
            children = [c for c in root.iterdir() if c.is_dir()]
        except OSError:
            continue
        for child in children:
            add(child)
    return sorted(found, key=lambda c: c.is_test)


def find_forever_installs(extra_roots: list[Path] | None = None, use_battlenet: bool = True) -> list[ClientInstall]:
    """All Forever clients: given folders first, then where Battle.net says it installed World of Warcraft
    (wow/battlenet.py), then the usual folders on every drive."""
    roots = list(extra_roots or [])
    if use_battlenet:
        roots += battlenet.install_roots()
    return scan_roots(roots + candidate_roots())


def client_from_path(path: Path) -> ClientInstall | None:
    """Accepts the client folder itself or the World of Warcraft root folder. Only looks at this folder.
    A chosen client folder counts whatever its flavor; in a root folder only Forever clients do."""
    flavor = read_flavor(path)
    if flavor:
        return ClientInstall(path, flavor)
    installs = scan_roots([path])
    return installs[0] if installs else None


def pick_client(saved_dir: str | None) -> ClientInstall | None:
    """The saved client folder, unless it is a beta or PTR client and a live Forever client exists (the beta
    folder stays after the release); without a saved folder the first Forever client found."""
    saved = client_from_path(Path(saved_dir)) if saved_dir else None
    if saved and not saved.is_test:
        return saved
    installs = find_forever_installs([saved.path.parent] if saved else None)
    if installs and (not saved or not installs[0].is_test):
        return installs[0]
    return saved


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
