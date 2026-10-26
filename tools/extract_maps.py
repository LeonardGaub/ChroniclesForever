"""Takes the world map images out of the local WoW Forever install and saves them as <uiMapID>.jpg for the
desktop app, fully explored, as the game draws them: the map's base tiles with every exploration overlay on top.

    desktop\\.venv\\Scripts\\pip install -e desktop[tools]      (once: Pillow and numpy)
    desktop\\.venv\\Scripts\\python tools\\extract_maps.py [--out FOLDER] [--install WOW_FOLDER] [--maps 1412,1413]

Default output: desktop/forever_chronicle/maps/ (the images kept in git). Reads only the game files
(forever_chronicle/wow/casc.py) and their map tables (tools/db2.py); nothing in the game folder is changed.
Forever reworked some zones (Mulgore, 2026-10-16), so the Classic map images no longer match every zone.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "tools")]
from db2 import (UI_MAP_ART, UI_MAP_ART_STYLE_LAYER, UI_MAP_ART_TILE, UI_MAP_X_MAP_ART,  # noqa: E402
                 WORLD_MAP_OVERLAY, WORLD_MAP_OVERLAY_TILE, open_install, table)
from forever_chronicle.wow import casc  # noqa: E402

OUT_SIZE = (1002, 668)  # desktop/forever_chronicle/domain/maps.py ART_WIDTH, ART_HEIGHT
TILE = 256


class MapSource:
    def __init__(self, install: Path | None):
        self.casc = open_install(install)
        self.art_of_map: dict[int, int] = {}
        for r in table(self.casc, UI_MAP_X_MAP_ART):
            phase, art = r["fields"][0], r["fields"][1]
            if phase == 0 or r["parent"] not in self.art_of_map:
                self.art_of_map[r["parent"]] = art
        self.style_of_art = {r["id"]: r["fields"][2] for r in table(self.casc, UI_MAP_ART)}
        self.layer_of_style = {}
        for r in table(self.casc, UI_MAP_ART_STYLE_LAYER):
            f = r["fields"]
            if f[0] == 0:
                self.layer_of_style[r["parent"]] = (f[1], f[2], f[3], f[4])
        self.tiles: dict[int, list[tuple[int, int, int]]] = {}
        for r in table(self.casc, UI_MAP_ART_TILE):
            row, col, layer, fdid = r["fields"]
            if layer == 0:
                self.tiles.setdefault(r["parent"], []).append((row, col, fdid))
        self.overlays: dict[int, list[tuple[int, int, int, int, int]]] = {}
        for r in table(self.casc, WORLD_MAP_OVERLAY):
            f = r["fields"]
            self.overlays.setdefault(f[1], []).append((r["id"], f[2], f[3], f[4], f[5]))
        self.overlay_tiles: dict[int, list[tuple[int, int, int]]] = {}
        for r in table(self.casc, WORLD_MAP_OVERLAY_TILE):
            row, col, layer, fdid = r["fields"]
            if layer == 0:
                self.overlay_tiles.setdefault(r["parent"], []).append((row, col, fdid))

    def maps(self) -> list[int]:
        return sorted(m for m, art in self.art_of_map.items() if art in self.tiles)

    def blp(self, fdid: int) -> Image.Image:
        return Image.open(io.BytesIO(self.casc.read_fdid(fdid))).convert("RGBA")

    def render(self, map_id: int) -> Image.Image:
        art = self.art_of_map[map_id]
        width, height, tile_w, tile_h = self.layer_of_style.get(self.style_of_art.get(art), (*OUT_SIZE, TILE, TILE))
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        for row, col, fdid in self.tiles[art]:
            tile = self.blp(fdid)
            if tile.size != (tile_w, tile_h):
                tile = tile.resize((tile_w, tile_h), Image.LANCZOS)
            canvas.alpha_composite(tile, (col * tile_w, row * tile_h))
        # Exploration overlays as in Blizzard's MapExplorationPin: 256-px tiles, the last row and column cut
        # to what is left of the overlay's size (their files are padded to a power of two).
        for overlay_id, tex_w, tex_h, off_x, off_y in self.overlays.get(art, []):
            wide, tall = math.ceil(tex_w / TILE), math.ceil(tex_h / TILE)
            for row, col, fdid in self.overlay_tiles.get(overlay_id, []):
                if row >= tall or col >= wide:
                    continue
                pw = TILE if col < wide - 1 else (tex_w % TILE or TILE)
                ph = TILE if row < tall - 1 else (tex_h % TILE or TILE)
                tile = self.blp(fdid)
                canvas.alpha_composite(tile.crop((0, 0, pw, ph)), (off_x + col * TILE, off_y + row * TILE))
        return canvas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, help="the World of Warcraft folder (default: found automatically)")
    parser.add_argument("--out", type=Path, default=ROOT / "desktop" / "forever_chronicle" / "maps")
    parser.add_argument("--maps", help="comma-separated uiMapIDs (default: every map with art)")
    args = parser.parse_args()
    source = MapSource(args.install)
    print(f"{source.casc.build_name}: {len(source.maps())} maps with art")
    wanted = [int(m) for m in args.maps.split(",")] if args.maps else source.maps()
    args.out.mkdir(parents=True, exist_ok=True)
    failed = []
    for map_id in wanted:
        try:
            image = source.render(map_id)
        except (KeyError, casc.CascError) as e:
            failed.append(map_id)
            print(f"  {map_id}: skipped ({e})")
            continue
        if image.size != OUT_SIZE:
            image = image.resize(OUT_SIZE, Image.LANCZOS)
        image.convert("RGB").save(args.out / f"{map_id}.jpg", quality=92)
        print(f"  {map_id}.jpg")
    if failed:
        print("not extracted:", ", ".join(map(str, failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
