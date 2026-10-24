"""Carries keybinds, macros, interface settings, Edit Mode layouts, the other addons and their settings, and the
graphics/sound settings from the WoW Forever beta client to the live client (release 2026-11-04).

    desktop\\.venv\\Scripts\\python tools\\port_settings.py account [--apply]
    desktop\\.venv\\Scripts\\python tools\\port_settings.py characters
    desktop\\.venv\\Scripts\\python tools\\port_settings.py characters --map Blind-Bullseye=Blind-Realm [--apply]
    desktop\\.venv\\Scripts\\python tools\\port_settings.py server-sync off|on [--apply]

Without --apply nothing is written: the tool lists what it would do. WoW must be closed (both clients).
The clients are found like the desktop app finds them (forever_chronicle/wow/paths.py): the beta is the source,
the live client the target; --from / --to take client folders instead.

- account: the account-wide files (keybinds, macros, interface settings, Edit Mode, chat, text-to-speech), the
  addon folders the live client does not have yet (never ForeverChronicle and ForeverChronicle_Share: the sync
  script and CurseForge install those), the account SavedVariables of Blizzard's UI and of the copied or already
  installed addons (not the chronicle's: the live chronicle starts fresh), and Config.wtf without the beta's
  connection, login and cache lines (portal "test" would connect the live client to the test servers).
- characters: lists the characters of both clients. The live characters are new, on new realms, and their folder
  exists only after logging in with them once; --map OLD=NEW (repeatable) then copies a beta character's
  keybinds, layout, chat windows, enabled addons and SavedVariables onto the live one.
- server-sync: Blizzard keeps keybinds, macros and settings on its servers too; the -cache files are the local
  copies. If the first login replaces the copied files with the server's empty ones, run "server-sync off", copy
  again and log in; "server-sync on" turns it back on afterwards.

Every file that is replaced is first saved under <live client>\\PortBackup\\<time>\\.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
from forever_chronicle.wow import paths  # noqa: E402

ACCOUNT_FILES = ("bindings-cache.wtf", "config-cache.wtf", "macros-cache.txt", "edit-mode-cache-account.txt",
                 "chat-frontend-cache.txt", "tts-cache-account.txt")
CHARACTER_FILES = ("bindings-cache.wtf", "config-cache.wtf", "macros-cache.txt", "edit-mode-cache-character.txt",
                   "layout-local.txt", "chat-cache.txt", "click-bindings-cache.txt", "AddOns.txt",
                   "tts-cache-character.txt")
OWN_ADDONS = ("ForeverChronicle", "ForeverChronicle_Share")
# Config.wtf lines that belong to the client, not to the player: connection, login, caches, survey, option versions.
CLIENT_CVARS = re.compile(r"(portal|agentUID|realm\w*|account\w*|lastAccountName|lastCharacter\w*|currentGameMode|"
                          r"plunderstormRealm|engineSurvey\w*|CACHE-.*|videoOptionsVersion|seenConfigurationWarnings|"
                          r"gameTip)", re.IGNORECASE)
SERVER_SYNC_CVARS = ("synchronizeSettings", "synchronizeConfig", "synchronizeBindings", "synchronizeMacros",
                     "synchronizeChatFrames")
CVAR_LINE = re.compile(r'^SET\s+(\S+)\s+"(.*)"\s*$')


class PortError(Exception):
    pass


@dataclass
class Plan:
    """What a step does: files to copy, folders to copy, Config.wtf text to write. Applied only with --apply."""
    target: Path
    files: list[tuple[Path, Path]] = field(default_factory=list)
    folders: list[tuple[Path, Path]] = field(default_factory=list)
    texts: list[tuple[Path, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        rel = lambda p: str(p.relative_to(self.target))  # noqa: E731
        lines = [f"addon  {rel(dst)}" for _, dst in self.folders]
        lines += [f"{'replace' if dst.exists() else 'new':7} {rel(dst)}" for _, dst in self.files]
        lines += [f"{'replace' if dst.exists() else 'new':7} {rel(dst)}" for dst, _ in self.texts]
        return lines + self.notes

    def apply(self, stamp: str | None = None) -> Path | None:
        backup = self.target / "PortBackup" / (stamp or time.strftime("%Y-%m-%d_%H-%M-%S"))
        replaced = [dst for _, dst in self.files if dst.exists()] + [dst for dst, _ in self.texts if dst.exists()]
        for dst in replaced:
            saved = backup / dst.relative_to(self.target)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, saved)
        for src, dst in self.folders:
            shutil.copytree(src, dst)
        for src, dst in self.files:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        for dst, text in self.texts:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
        return backup if replaced else None


# -- clients ------------------------------------------------------------------------------------------------

def find_clients(source: Path | None, target: Path | None) -> tuple[paths.ClientInstall, paths.ClientInstall]:
    installs = paths.find_forever_installs()
    src = paths.client_from_path(source) if source else next((c for c in installs if c.is_test), None)
    dst = paths.client_from_path(target) if target else next((c for c in installs if not c.is_test), None)
    if not src:
        raise PortError("Beta client not found: give its folder with --from.")
    if not dst:
        raise PortError("Live client not found (installed yet?): give its folder with --to.")
    if src.path == dst.path:
        raise PortError(f"Source and target are the same folder: {src.path}")
    return src, dst


def running_exes(clients: list[paths.ClientInstall]) -> list[str]:
    """The clients' game executables that are running now (Windows tasklist)."""
    names = {exe.name.lower() for c in clients for exe in c.path.glob("*.exe") if exe.name != "BlizzardError.exe"}
    if not names or sys.platform != "win32":
        return []
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return sorted({row[0] for row in csv.reader(io.StringIO(out)) if row and row[0].lower() in names})


def account_dirs(client: paths.ClientInstall) -> list[Path]:
    base = client.path / "WTF" / "Account"
    return sorted(p for p in base.iterdir() if p.is_dir() and p.name != "SavedVariables") if base.is_dir() else []


def pair_accounts(src: paths.ClientInstall, dst: paths.ClientInstall) -> list[tuple[Path, Path]]:
    """Account folders are named after the Battle.net account and the WoW license, the same in both clients.
    A missing target folder is created (it appears with the first login anyway)."""
    sources = account_dirs(src)
    targets = {p.name: p for p in account_dirs(dst)}
    if len(sources) == 1 and len(targets) == 1 and sources[0].name not in targets:
        return [(sources[0], next(iter(targets.values())))]
    return [(s, targets.get(s.name, dst.path / "WTF" / "Account" / s.name)) for s in sources]


# -- account --------------------------------------------------------------------------------------------------

def merge_config(source_text: str, target_text: str | None) -> str:
    """The beta's Config.wtf with the live client's own lines (connection, login, caches) kept or left out."""
    def cvars(text):
        return {m[1]: m[2] for line in text.splitlines() if (m := CVAR_LINE.match(line))}
    merged = {k: v for k, v in cvars(source_text).items() if not CLIENT_CVARS.fullmatch(k)}
    for k, v in cvars(target_text or "").items():
        if CLIENT_CVARS.fullmatch(k) or k not in merged:
            merged[k] = v
    return "".join(f'SET {k} "{v}"\n' for k, v in merged.items())


def wanted_saved_variables(folder: Path, addons: set[str]) -> list[Path]:
    """SavedVariables of Blizzard's UI and of the given addons; not the chronicle's, not the beta's PTR feedback."""
    if not folder.is_dir():
        return []
    files = []
    for f in sorted(folder.glob("*.lua")):
        name = f.stem
        if name in OWN_ADDONS or "PTRFeedback" in name:
            continue
        if name.startswith("Blizzard_") or name in addons:
            files.append(f)
    return files


def addon_names(client: paths.ClientInstall) -> set[str]:
    return {p.name for p in client.addons_dir.iterdir() if p.is_dir()} if client.addons_dir.is_dir() else set()


def plan_account(src: paths.ClientInstall, dst: paths.ClientInstall) -> Plan:
    plan = Plan(dst.path)
    installed = addon_names(dst)
    for name in sorted(addon_names(src) - installed - set(OWN_ADDONS)):
        plan.folders.append((src.addons_dir / name, dst.addons_dir / name))
    addons = addon_names(src) | installed
    for s_acc, d_acc in pair_accounts(src, dst):
        for name in ACCOUNT_FILES:
            if (s_acc / name).is_file():
                plan.files.append((s_acc / name, d_acc / name))
        for f in wanted_saved_variables(s_acc / "SavedVariables", addons):
            plan.files.append((f, d_acc / "SavedVariables" / f.name))
    config = src.path / "WTF" / "Config.wtf"
    if config.is_file():
        target = dst.path / "WTF" / "Config.wtf"
        old = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        plan.texts.append((target, merge_config(config.read_text(encoding="utf-8", errors="replace"), old)))
    skipped = sorted(addon_names(src) & installed - set(OWN_ADDONS))
    if skipped:
        plan.notes.append("kept (already installed in the live client): " + ", ".join(skipped))
    return plan


# -- characters ---------------------------------------------------------------------------------------------

def characters(client: paths.ClientInstall) -> dict[str, Path]:
    """Character folders by their path below the account folder ("70/Blind-Bullseye", "Some Realm/Gagel")."""
    found = {}
    for account in account_dirs(client):
        for group in sorted(p for p in account.iterdir() if p.is_dir() and p.name != "SavedVariables"):
            for char in sorted(p for p in group.iterdir() if p.is_dir()):
                found[f"{group.name}/{char.name}"] = char
    return found


def resolve(chars: dict[str, Path], name: str, which: str) -> Path:
    if name in chars:
        return chars[name]
    matches = [p for key, p in chars.items() if key.split("/", 1)[1].lower() == name.lower()]
    if len(matches) != 1:
        hint = "not found" if not matches else "ambiguous, use GROUP/NAME"
        raise PortError(f"{which} character {name!r} {hint}. Known: {', '.join(chars) or 'none'}")
    return matches[0]


def plan_characters(src: paths.ClientInstall, dst: paths.ClientInstall, mapping: list[str]) -> Plan:
    plan = Plan(dst.path)
    old_chars, new_chars = characters(src), characters(dst)
    addons = addon_names(src) | addon_names(dst)
    for pair in mapping:
        old, sep, new = pair.partition("=")
        if not sep:
            raise PortError(f"--map takes OLD=NEW, got {pair!r}")
        s_char = resolve(old_chars, old.strip(), "Beta")
        d_char = resolve(new_chars, new.strip(), "Live")
        for name in CHARACTER_FILES:
            if (s_char / name).is_file():
                plan.files.append((s_char / name, d_char / name))
        for f in wanted_saved_variables(s_char / "SavedVariables", addons):
            plan.files.append((f, d_char / "SavedVariables" / f.name))
    return plan


# -- server sync --------------------------------------------------------------------------------------------

def plan_server_sync(dst: paths.ClientInstall, on: bool) -> Plan:
    plan = Plan(dst.path)
    config = dst.path / "WTF" / "Config.wtf"
    lines = config.read_text(encoding="utf-8", errors="replace").splitlines() if config.is_file() else []
    lines = [line for line in lines if not ((m := CVAR_LINE.match(line)) and m[1] in SERVER_SYNC_CVARS)]
    lines += [f'SET {name} "{1 if on else 0}"' for name in SERVER_SYNC_CVARS]
    plan.texts.append((config, "\n".join(lines) + "\n"))
    return plan


# -- main -----------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--from", dest="source", type=Path, help="beta client folder (default: found)")
    common.add_argument("--to", dest="target", type=Path, help="live client folder (default: found)")
    common.add_argument("--apply", action="store_true", help="write the changes (default: only list them)")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("account", parents=[common], help="account settings, addons, their SavedVariables, Config.wtf")
    chars = steps.add_parser("characters", parents=[common], help="list characters; --map OLD=NEW copies one")
    chars.add_argument("--map", action="append", default=[], metavar="OLD=NEW")
    sync = steps.add_parser("server-sync", parents=[common],
                            help="turn Blizzard's settings sync off or on in the live client")
    sync.add_argument("state", choices=("off", "on"))
    args = parser.parse_args(argv)
    try:
        src, dst = find_clients(args.source, args.target)
        print(f"Beta: {src.path} ({src.flavor})\nLive: {dst.path} ({dst.flavor})")
        if args.step == "characters" and not args.map:
            for label, client in (("Beta", src), ("Live", dst)):
                print(f"{label} characters: {', '.join(characters(client)) or 'none (log in once first)'}")
            return 0
        if args.step == "account":
            plan = plan_account(src, dst)
        elif args.step == "characters":
            plan = plan_characters(src, dst, args.map)
        else:
            plan = plan_server_sync(dst, args.state == "on")
        for line in plan.describe():
            print("  " + line)
        if not args.apply:
            print("Nothing written. Run again with --apply.")
            return 0
        running = running_exes([src, dst])
        if running:
            raise PortError(f"WoW is running ({', '.join(running)}): close it first.")
        backup = plan.apply()
        print("Done." + (f" Replaced files saved in {backup}" if backup else ""))
        return 0
    except PortError as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
