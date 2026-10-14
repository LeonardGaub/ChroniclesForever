"""Where Battle.net installed World of Warcraft: install folders from the Battle.net agent's product database,
the Battle.net client settings and the Windows uninstall entries. Read-only; every source is optional.

product.db (``%ProgramData%\\Battle.net\\Agent\\product.db``) is a protobuf message without a published schema.
It is decoded generically (wire format only) and every string that looks like a folder path is a candidate.
The caller then checks each candidate for a Forever client (``.flavor.info``), so a wrong guess costs nothing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable, Iterable

DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
MAX_DEPTH = 8


# -- protobuf wire format ----------------------------------------------------------------------


def _varint(data: bytes, i: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        if i >= len(data) or shift > 63:
            raise ValueError("truncated varint")
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, i
        shift += 7


def proto_strings(data: bytes, depth: int = 0, out: list[str] | None = None) -> list[str]:
    """All printable UTF-8 strings in a protobuf message, including nested messages. Stops quietly at data
    that is not valid wire format (returns what was found until then)."""
    out = [] if out is None else out
    i = 0
    try:
        while i < len(data):
            key, i = _varint(data, i)
            wire = key & 7
            if wire == 0:
                _, i = _varint(data, i)
            elif wire == 1:
                i += 8
            elif wire == 5:
                i += 4
            elif wire == 2:
                length, i = _varint(data, i)
                chunk = data[i:i + length]
                if len(chunk) != length:
                    raise ValueError("truncated field")
                i += length
                try:
                    text = chunk.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text and text.isprintable():
                    out.append(text)
                elif depth < MAX_DEPTH:
                    proto_strings(chunk, depth + 1, out)
            else:
                raise ValueError("unknown wire type")
    except ValueError:
        pass
    return out


# -- sources ---------------------------------------------------------------------------------


def product_db_paths(program_data: Path | None = None) -> list[Path]:
    base = program_data or Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    try:
        data = (base / "Battle.net" / "Agent" / "product.db").read_bytes()
    except OSError:
        return []
    return [Path(s) for s in proto_strings(data) if DRIVE_PATH.match(s)]


def config_paths(app_data: Path | None = None) -> list[Path]:
    """The default install folder from Battle.net.config (installs go to <it>\\World of Warcraft)."""
    base = app_data or Path(os.environ.get("APPDATA") or "")
    try:
        config = json.loads((base / "Battle.net" / "Battle.net.config").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    default = (config.get("Client") or {}).get("Install", {}).get("DefaultInstallPath") \
        if isinstance(config, dict) and isinstance(config.get("Client"), dict) else None
    if not isinstance(default, str) or not DRIVE_PATH.match(default):
        return []
    return [Path(default) / "World of Warcraft"]


UNINSTALL_KEYS = (r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")


def registry_paths() -> list[Path]:
    """InstallLocation of uninstall entries named like World of Warcraft (Windows only)."""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key_path in UNINSTALL_KEYS:
            try:
                key = winreg.OpenKey(root, key_path)
            except OSError:
                continue
            with key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                            name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                            location = str(winreg.QueryValueEx(sub, "InstallLocation")[0])
                    except OSError:
                        continue
                    if "world of warcraft" in name.lower() and DRIVE_PATH.match(location):
                        found.append(Path(location))
    return found


def install_roots(sources: Iterable[Callable[[], list[Path]]] | None = None) -> list[Path]:
    """Candidate folders from all Battle.net sources, without duplicates, in source order. A path that names
    a client folder itself (e.g. ...\\_retail_) is followed by its parent."""
    sources = sources if sources is not None else (product_db_paths, config_paths, registry_paths)
    out: list[Path] = []
    seen: set[str] = set()
    for source in sources:
        try:
            paths = source()
        except Exception:  # an unreadable source must never stop detection
            continue
        for p in paths:
            for candidate in (p, p.parent) if p.name.startswith("_") else (p,):
                key = os.path.normcase(str(candidate))
                if key not in seen:
                    seen.add(key)
                    out.append(candidate)
    return out
