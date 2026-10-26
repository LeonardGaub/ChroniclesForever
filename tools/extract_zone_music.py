"""Writes which music the game plays in each zone and dungeon, read from the local WoW Forever install, as
desktop/forever_chronicle/zone_music.json (kept in git). The cinematic mode plays it (wow/zone_music.py takes the
music files themselves out of the player's own install when needed).

    desktop\\.venv\\Scripts\\python tools\\extract_zone_music.py [--install WOW_FOLDER] [--out FILE]

Chain: UiMapAssignment (uiMapID -> AreaTable ID) -> AreaTable.ZoneMusic -> ZoneMusic.Sounds (day, night SoundKit)
-> SoundKitEntry (SoundKit -> music files). Dungeons: the top area of the instance map (AreaTable.ContinentID).
Some tables keep unreleased rows in encrypted sections; those are left out (tools/db2.py). Rerun after a client
patch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "tools")]
from db2 import AREA_TABLE, SOUND_KIT_ENTRY, UI_MAP_ASSIGNMENT, ZONE_MUSIC, open_install, table  # noqa: E402
from forever_chronicle.wow import casc  # noqa: E402

CONTINENT_MAPS = (0, 1)       # Eastern Kingdoms, Kalimdor: their areas are zones, not dungeons


def build(storage: casc.Casc) -> dict:
    areas = {r["id"]: r["fields"] for r in table(storage, AREA_TABLE)}
    sets = {r["id"]: r["fields"][3] for r in table(storage, ZONE_MUSIC)}
    kits: dict[int, list[int]] = {}
    for r in table(storage, SOUND_KIT_ENTRY):
        kit, fdid = r["fields"][0], r["fields"][1]
        if fdid:
            kits.setdefault(kit, []).append(fdid)

    def music(area_id: int) -> dict | None:
        fields = areas.get(area_id)
        sounds = sets.get(fields[9]) if fields else None
        if not sounds:
            return None
        day, night = (sorted(set(kits.get(k, []))) for k in sounds)
        if not day and not night:
            return None
        return {"area": area_id, "day": day or night, "night": night or day}

    zones: dict[str, dict] = {}
    for r in sorted(table(storage, UI_MAP_ASSIGNMENT), key=lambda r: r["fields"][5]):   # OrderIndex
        ui_map, area_id = r["fields"][4], r["fields"][7]
        found = music(area_id) if area_id else None
        if found and str(ui_map) not in zones:
            zones[str(ui_map)] = found
    instances: dict[str, dict] = {}
    for area_id in sorted(areas):
        continent, parent = areas[area_id][2], areas[area_id][3]
        if continent in CONTINENT_MAPS or parent != 0 or str(continent) in instances:
            continue
        found = music(area_id)
        if found:
            instances[str(continent)] = found
    return {"build": storage.build_name, "zones": zones, "instances": instances}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, help="the World of Warcraft folder (default: found automatically)")
    parser.add_argument("--out", type=Path, default=ROOT / "desktop" / "forever_chronicle" / "zone_music.json")
    args = parser.parse_args()
    storage = open_install(args.install)
    data = build(storage)
    files = {f for group in ("zones", "instances") for m in data[group].values() for f in m["day"] + m["night"]}
    args.out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{data['build']}: {len(data['zones'])} zones, {len(data['instances'])} dungeons, {len(files)} music files"
          f" -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
