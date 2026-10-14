"""Publishes the current addon and the sync scripts into the shared cloud folder (docs/Sharing_Design.md v2):

    <cloud>/addon/ForeverChronicle, <cloud>/addon/ForeverChronicle_Share   (mirrored)
    <cloud>/tools/ForeverSync.ps1, ForeverSync.vbs, Einrichten.bat

Every PC's sync script then installs the new version (also this one). The cloud folder is taken from this PC's
sync settings (%LOCALAPPDATA%\\ForeverChronicle\\sync\\config.json) or given as an argument:

    desktop\\.venv\\Scripts\\python tools\\publish_to_cloud.py [<cloud folder>]
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ("ForeverChronicle", "ForeverChronicle_Share")
TOOLS = ("ForeverSync.ps1", "ForeverSync.vbs", "Einrichten.bat")


def cloud_from_config() -> Path | None:
    config = Path(os.environ.get("LOCALAPPDATA", "")) / "ForeverChronicle" / "sync" / "config.json"
    try:
        return Path(json.loads(config.read_text(encoding="utf-8-sig"))["cloud"])
    except (OSError, ValueError, KeyError):
        return None


def mirror(src: Path, dst: Path) -> int:
    """Copies changed files, removes files that are gone. Returns the number of changes."""
    changes = 0
    wanted = set()
    for f in src.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts:
            rel = f.relative_to(src)
            wanted.add(rel)
            target = dst / rel
            if not target.exists() or not filecmp.cmp(f, target, shallow=False):
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".tmp")
                shutil.copy2(f, tmp)
                os.replace(tmp, target)   # cloud clients upload complete files only
                changes += 1
    if dst.exists():
        for f in sorted(dst.rglob("*"), reverse=True):
            rel = f.relative_to(dst)
            if f.is_file() and rel not in wanted:
                f.unlink()
                changes += 1
            elif f.is_dir() and not any(f.iterdir()):
                f.rmdir()
    return changes


def publish(cloud: Path) -> dict[str, int]:
    if not cloud.is_dir():
        raise SystemExit(f"Cloud folder not found: {cloud}")
    result = {}
    for name in ADDONS:
        result[f"addon/{name}"] = mirror(ROOT / "addons" / name, cloud / "addon" / name)
    tools = cloud / "tools"
    tools.mkdir(exist_ok=True)
    changed = 0
    for name in TOOLS:
        src, dst = ROOT / "sync" / name, tools / name
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            shutil.copy2(src, dst)
            changed += 1
    result["tools"] = changed
    (cloud / "players").mkdir(exist_ok=True)
    return result


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else cloud_from_config()
    if target is None:
        raise SystemExit("No cloud folder: give it as an argument or run Einrichten.bat on this PC first.")
    for part, n in publish(target).items():
        print(f"{part}: {n} change(s)")
    print(f"Published to {target}. Every PC installs it on its next sync run (WoW closed).")
