"""Writes which music and ambience the game plays in each zone and dungeon, read from the local WoW Forever install,
as desktop/forever_chronicle/zone_music.json (kept in git). The cinematic mode plays them (wow/zone_music.py takes
the files themselves out of the player's own install when needed).

    desktop\\.venv\\Scripts\\python tools\\extract_zone_music.py [--install WOW_FOLDER] [--out FILE]

Chain: UiMapAssignment (uiMapID -> AreaTable ID) -> AreaTable.ZoneMusic -> ZoneMusic.Sounds (day, night SoundKit)
-> SoundKitEntry (SoundKit -> music files). Ambience, under "ambience": AreaTable.AmbienceID ->
SoundAmbience.AmbienceID (day, night SoundKit) -> SoundKitEntry. Dungeons: the top area of the instance map
(AreaTable.ContinentID). Some tables keep unreleased rows in encrypted sections; those are left out (tools/db2.py).
Rerun after a client patch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "tools")]
from db2 import (AREA_TABLE, SOUND_AMBIENCE, SOUND_KIT_ENTRY, UI_MAP_ASSIGNMENT, ZONE_MUSIC,  # noqa: E402
                 open_install, table)
from forever_chronicle.wow import casc  # noqa: E402

CONTINENT_MAPS = (0, 1)       # Eastern Kingdoms, Kalimdor: their areas are zones, not dungeons
MUSIC_COLUMN, AMBIENCE_COLUMN = 9, 7    # AreaTable.ZoneMusic, AreaTable.AmbienceID


def build(storage: casc.Casc) -> dict:
    areas = {r["id"]: r["fields"] for r in table(storage, AREA_TABLE)}
    music_sets = {r["id"]: r["fields"][3] for r in table(storage, ZONE_MUSIC)}
    ambience_sets = {r["id"]: r["fields"][3] for r in table(storage, SOUND_AMBIENCE)}
    kits: dict[int, list[int]] = {}
    for r in table(storage, SOUND_KIT_ENTRY):
        kit, fdid = r["fields"][0], r["fields"][1]
        if fdid:
            kits.setdefault(kit, []).append(fdid)

    def sounds(area_id: int, column: int, sets: dict) -> dict | None:
        """The day and night files of an area's music (or ambience)."""
        fields = areas.get(area_id)
        pair = sets.get(fields[column]) if fields else None
        if not pair:
            return None
        day, night = (sorted(set(kits.get(k, []))) for k in pair)
        if not day and not night:
            return None
        return {"area": area_id, "day": day or night, "night": night or day}

    def collect(column: int, sets: dict) -> tuple[dict, dict]:
        zones: dict[str, dict] = {}
        for r in sorted(table(storage, UI_MAP_ASSIGNMENT), key=lambda r: r["fields"][5]):   # OrderIndex
            ui_map, area_id = r["fields"][4], r["fields"][7]
            found = sounds(area_id, column, sets) if area_id else None
            if found and str(ui_map) not in zones:
                zones[str(ui_map)] = found
        instances: dict[str, dict] = {}
        for area_id in sorted(areas):
            continent, parent = areas[area_id][2], areas[area_id][3]
            if continent in CONTINENT_MAPS or parent != 0 or str(continent) in instances:
                continue
            found = sounds(area_id, column, sets)
            if found:
                instances[str(continent)] = found
        return zones, instances

    zones, instances = collect(MUSIC_COLUMN, music_sets)
    ambience_zones, ambience_instances = collect(AMBIENCE_COLUMN, ambience_sets)
    return {"build": storage.build_name, "zones": zones, "instances": instances,
            "ambience": {"zones": ambience_zones, "instances": ambience_instances}}


def files_of(group: dict) -> set[int]:
    return {f for kind in ("zones", "instances") for m in group[kind].values() for f in m["day"] + m["night"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, help="the World of Warcraft folder (default: found automatically)")
    parser.add_argument("--out", type=Path, default=ROOT / "desktop" / "forever_chronicle" / "zone_music.json")
    args = parser.parse_args()
    storage = open_install(args.install)
    data = build(storage)
    ambience = data["ambience"]
    args.out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{data['build']}: {len(data['zones'])} zones, {len(data['instances'])} dungeons, "
          f"{len(files_of(data))} music files; ambience: {len(ambience['zones'])} zones, "
          f"{len(ambience['instances'])} dungeons, {len(files_of(ambience))} files -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
