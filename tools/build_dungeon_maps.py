"""Builds the addon's dungeon map table (addons/ForeverChronicle/Data/DungeonMaps.lua): for every dungeon and raid
of WoW Forever, its floors with their names and the file IDs of their map tiles. It also writes the same floors as
pictures for the desktop app (desktop/forever_chronicle/maps/dungeon_<instanceID>_<floor>.jpg, 1002 x 668 like the
zone maps, and dungeons.json with the names): the app cannot draw the client's tiles by file ID.

    desktop\\.venv\\Scripts\\python tools\\build_dungeon_maps.py [--install WOW_FOLDER] [--preview FOLDER] [--no-desktop]

The Forever client still has Blizzard's dungeon map pictures (the 256-px tiles), but its own map tables no longer
link them to any map, so the game shows no dungeon maps. The links come from the map tables of WoW Classic 5.5.4
(wago.tools, cached in tools/.cache/), the same pictures; the addon draws the tiles by file ID. Only dungeons that
exist in Forever and whose every tile is in the Forever install are kept. Forever's own new dungeons (Ruins of
Lordaeron and others) have no map in Blizzard's data.
--preview writes every floor as a picture, to check the tile order by eye.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db2  # noqa: E402
from forever_chronicle.wow import casc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTALL = Path(r"C:\Program Files (x86)\World of Warcraft")
PRODUCT = "wow_classic_beta"
WAGO_BUILD = "5.5.4.70268"
WAGO_URL = "https://wago.tools/db2/{table}/csv?build={build}&locale={locale}"
CACHE = ROOT / "tools" / ".cache" / "wago"
OUT = ROOT / "addons" / "ForeverChronicle" / "Data" / "DungeonMaps.lua"
DESKTOP_MAPS = ROOT / "desktop" / "forever_chronicle" / "maps"
DESKTOP_SIZE = (1002, 668)   # the desktop's map canvas (domain/maps.py ART_WIDTH, ART_HEIGHT)
DESKTOP_LOCALES = {"enUS": "en", "deDE": "de"}
FOREVER_MAP_TABLE = 1349477  # Map.db2 (instance IDs)
DUNGEON_MAP_TYPES = (4, 6)   # UiMap.Type: dungeon, micro (Zul'Farrak, Zul'Gurub, Ruins of Ahn'Qiraj)
PARTY, RAID = 1, 2           # Map.InstanceType
LOCALES = ("enUS", "deDE")


def wago(table: str, locale: str = "enUS") -> list[dict[str, str]]:
    path = CACHE / WAGO_BUILD / f"{table}.{locale}.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = WAGO_URL.format(table=table, build=WAGO_BUILD, locale=locale)
        request = urllib.request.Request(url, headers={"User-Agent": "JourneyForever-tools/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            path.write_bytes(response.read())
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build(install: Path) -> tuple[dict[int, dict], casc.Casc]:
    storage = casc.Casc(install, PRODUCT)
    forever_maps = {r["id"] for r in db2.read_db2(storage.read_fdid(FOREVER_MAP_TABLE, zero_encrypted=True))}

    names = {loc: {int(r["ID"]): r["MapName_lang"] for r in wago("Map", loc)} for loc in LOCALES}
    instances = sorted(int(r["ID"]) for r in wago("Map")
                       if int(r["InstanceType"]) in (PARTY, RAID) and int(r["ID"]) in forever_maps)
    dungeon_maps = {int(r["ID"]) for r in wago("UiMap") if int(r["Type"]) in DUNGEON_MAP_TYPES}
    floor_names = {loc: {int(r["UiMapID"]): r["Name_lang"] for r in wago("UiMapGroupMember", loc)} for loc in LOCALES}
    floor_index = {int(r["UiMapID"]): int(r["FloorIndex"]) for r in wago("UiMapGroupMember")}
    ui_maps_of: dict[int, list[int]] = {}
    for r in wago("UiMapAssignment"):
        ui_map, instance = int(r["UiMapID"]), int(r["MapID"])
        if ui_map in dungeon_maps and ui_map not in ui_maps_of.setdefault(instance, []):
            ui_maps_of[instance].append(ui_map)
    art_of: dict[int, int] = {}
    for r in sorted(wago("UiMapXMapArt"), key=lambda r: int(r["PhaseID"]) != 0):
        art_of.setdefault(int(r["UiMapID"]), int(r["UiMapArtID"]))
    style_of = {int(r["ID"]): int(r["UiMapArtStyleID"]) for r in wago("UiMapArt")}
    layer_of = {int(r["UiMapArtStyleID"]): tuple(int(r[k]) for k in ("LayerWidth", "LayerHeight", "TileWidth", "TileHeight"))
                for r in wago("UiMapArtStyleLayer") if r["LayerIndex"] == "0"}
    tiles_of: dict[int, list[tuple[int, int, int]]] = {}
    for r in wago("UiMapArtTile"):
        if r["LayerIndex"] == "0":
            tiles_of.setdefault(int(r["UiMapArtID"]), []).append((int(r["RowIndex"]), int(r["ColIndex"]), int(r["FileDataID"])))

    result: dict[int, dict] = {}
    for instance in instances:
        floors = []
        for ui_map in sorted(ui_maps_of.get(instance, []), key=lambda m: (floor_index.get(m, 0), m)):
            art = art_of.get(ui_map)
            layer = layer_of.get(style_of.get(art))
            tiles = sorted(tiles_of.get(art, []))
            if not (layer and tiles):
                continue
            width, height, tile_w, tile_h = layer
            cols, rows = -(-width // tile_w), -(-height // tile_h)
            if len(tiles) != cols * rows:
                print(f"  {instance} floor {ui_map}: {len(tiles)} tiles for {cols}x{rows}, skipped")
                continue
            floors.append({"uiMap": ui_map, "layer": layer, "tiles": [t[2] for t in tiles],
                           "names": {loc: floor_names[loc].get(ui_map) for loc in LOCALES}})
        if not floors:
            continue
        missing = [f for floor in floors for f in floor["tiles"] if not has_file(storage, f)]
        if missing:
            print(f"  {instance} {names['enUS'][instance]}: {len(missing)} tiles missing in Forever, skipped")
            continue
        result[instance] = {"names": {loc: names[loc][instance] for loc in LOCALES}, "floors": floors}
    return result, storage


def has_file(storage: casc.Casc, fdid: int) -> bool:
    try:
        storage.read_fdid(fdid)
        return True
    except casc.CascError:
        return False


def lua_string(text: str | None) -> str:
    if text is None:
        return "nil"
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_lua(dungeons: dict[int, dict], path: Path) -> None:
    layouts = {floor["layer"] for d in dungeons.values() for floor in d["floors"]}
    default = max(layouts, key=lambda lay: sum(f["layer"] == lay for d in dungeons.values() for f in d["floors"]))
    lines = [
        "-- Journey Forever - dungeon maps (generated by tools/build_dungeon_maps.py; regenerate rather than edit)",
        "-- Blizzard's dungeon map pictures, which the Forever client still has but no longer links to a map: per",
        f"-- instance ID its floors, each with its names and its map tiles (file IDs, row by row). Map tables of WoW",
        f"-- Classic {WAGO_BUILD}; only dungeons whose every tile is in the Forever install.",
        "--   [instanceID] = { name = { enUS, deDE }, floors = { { name = { enUS, deDE } | nil, tiles = { ... },",
        "--     layout = { width, height, tileWidth, tileHeight } | nil (the default below) }, ... } }",
        "",
        "local ADDON, FC = ...",
        "",
        f"FC.DUNGEON_MAP_LAYOUT = {{ {', '.join(map(str, default))} }}",
        "",
        "FC.DungeonMaps = {",
    ]
    for instance, d in sorted(dungeons.items()):
        lines.append(f"  [{instance}] = {{ -- {d['names']['enUS']}")
        lines.append(f"    name = {{ enUS = {lua_string(d['names']['enUS'])}, deDE = {lua_string(d['names']['deDE'])} }},")
        lines.append("    floors = {")
        single = len(d["floors"]) == 1
        for floor in d["floors"]:
            parts = []
            if not single and floor["names"]["enUS"]:
                parts.append(f"name = {{ enUS = {lua_string(floor['names']['enUS'])}, deDE = {lua_string(floor['names']['deDE'])} }}")
            if floor["layer"] != default:
                parts.append(f"layout = {{ {', '.join(map(str, floor['layer']))} }}")
            parts.append(f"tiles = {{ {', '.join(map(str, floor['tiles']))} }}")
            lines.append(f"      {{ {', '.join(parts)} }},")
        lines.append("    },")
        lines.append("  },")
    lines.append("}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\r\n")


def floor_picture(floor: dict, storage: casc.Casc):
    """A floor's tiles put together (a PIL image of the layer's size)."""
    from PIL import Image

    width, height, tile_w, tile_h = floor["layer"]
    cols = -(-width // tile_w)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    for n, fdid in enumerate(floor["tiles"]):
        tile = Image.open(io.BytesIO(storage.read_fdid(fdid))).convert("RGBA")
        canvas.alpha_composite(tile.resize((tile_w, tile_h)), ((n % cols) * tile_w, (n // cols) * tile_h))
    return canvas.convert("RGB")


def preview(dungeons: dict[int, dict], storage: casc.Casc, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for instance, d in dungeons.items():
        for i, floor in enumerate(d["floors"], 1):
            floor_picture(floor, storage).save(folder / f"{instance}_{i}.jpg", quality=85)


def write_desktop(dungeons: dict[int, dict], storage: casc.Casc, folder: Path) -> None:
    """The desktop app's dungeon maps: every floor as dungeon_<instanceID>_<floor>.jpg on the zone maps' canvas,
    and dungeons.json with the dungeon and floor names (domain/dungeons.py reads it). Old pictures are removed."""
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("dungeon_*.jpg"):
        old.unlink()
    table = {}
    for instance, d in sorted(dungeons.items()):
        single = len(d["floors"]) == 1
        floors = []
        for i, floor in enumerate(d["floors"], 1):
            picture = floor_picture(floor, storage)
            if picture.size != DESKTOP_SIZE:
                picture = picture.resize(DESKTOP_SIZE, Image.LANCZOS)
            picture.save(folder / f"dungeon_{instance}_{i}.jpg", quality=88)
            names = floor["names"]
            floors.append({"name": None if single or not names["enUS"] else
                           {DESKTOP_LOCALES[loc]: names[loc] or names["enUS"] for loc in LOCALES}})
        table[str(instance)] = {"name": {DESKTOP_LOCALES[loc]: d["names"][loc] for loc in LOCALES},
                                "floors": floors}
    data = {"source": f"tools/build_dungeon_maps.py, map tables of WoW Classic {WAGO_BUILD}", "dungeons": table}
    (folder / "dungeons.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--preview", type=Path, help="also write every floor as <instanceID>_<floor>.jpg here")
    parser.add_argument("--desktop", type=Path, default=DESKTOP_MAPS, help="the desktop app's map folder")
    parser.add_argument("--no-desktop", action="store_true", help="do not write the desktop app's pictures")
    args = parser.parse_args()
    dungeons, storage = build(args.install)
    write_lua(dungeons, args.out)
    floors = sum(len(d["floors"]) for d in dungeons.values())
    print(f"{storage.build_name}: {len(dungeons)} dungeons, {floors} floors -> {args.out}")
    for instance, d in sorted(dungeons.items()):
        print(f"  {instance:5} {d['names']['enUS']} ({len(d['floors'])})")
    if args.preview:
        preview(dungeons, storage, args.preview)
    if not args.no_desktop:
        write_desktop(dungeons, storage, args.desktop)
        print(f"  desktop: {floors} pictures and dungeons.json -> {args.desktop}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
