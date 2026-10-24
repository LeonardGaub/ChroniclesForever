"""Builds the seamless world map for the desktop app from OpenMap's baked zone art.

OpenMap (an installed addon, MIT; the map art is Blizzard's) stitches every zone map into one picture of Azeroth
and ships it baked as world tiles: Media/Textures/MapZones/<i>_<j>.blp, ns.MapZoneArt in Data/ZoneArt.lua.
Their unit is the world map's art pixel (947.jpg, 1002 x 668), the "world unit" of domain/maps.py
(CONTINENT_ON_WORLD, world_xy). Baked tile (i, j) covers step/px world units from (i, j) times that, its outer
(size - step) / 2 pixels being its neighbours' edge. The tiles hold land only (transparent sea), so the world
art, scaled up, stays underneath as the sea, its coastal band repainted as OpenMap paints the sea there (the
continents' big names sit in it).

Output (wow/map_art.py world_base / world_tile; kept in git like the zone maps):
    maps/world/base.jpg        the whole world at BASE_PX pixels per world unit
    maps/world/<i>_<j>.jpg     detail tiles at TILE_PX px per unit, each TILE_UNITS world units square from
                               (i, j) * TILE_UNITS, plus TILE_MARGIN pixels of its neighbours on every side
                               (tiles overlap, so no seams show between them); only where there is land

    desktop\\.venv\\Scripts\\python -I tools\\build_world_map.py [--openmap FOLDER] [--out FOLDER]

Rerun after OpenMap or the client updates the map art.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from forever_chronicle.wow.map_art import BASE_PX, TILE_MARGIN, TILE_PX, TILE_UNITS  # noqa: E402

DEFAULT_OPENMAP = Path(r"C:\Program Files (x86)\World of Warcraft\_classic_beta_\Interface\AddOns\OpenMap")
WORLD_ART = ROOT / "desktop" / "forever_chronicle" / "maps" / "947.jpg"
WORLD_W, WORLD_H = 1002, 668
# The continents' names on the world art that reach past the coastal band (world units, measured on 947.jpg):
# KALIMDOR's K and R, EASTERN KINGDOMS' first letters.
LETTERING = [(104, 300, 133, 338), (312, 300, 340, 338), (634, 362, 700, 418)]
SEA_SPOTS, SEA_HATCH = 48, 14       # world units per tile of the sea's mottling and of its wave strokes
UI_MAP_ASSIGNMENT = 1957219   # (tools/extract_zone_music.py)


def zone_art(openmap: Path) -> dict:
    text = re.sub(r"--[^\n]*", "", (openmap / "Data" / "ZoneArt.lua").read_text(encoding="utf-8"))
    num = lambda key: float(re.search(rf"\b{key}\s*=\s*([\d.]+)", text).group(1))  # noqa: E731
    tiles = [int(t) for t in re.findall(r"\d+", re.split(r"\btiles\s*=\s*\{", text, maxsplit=1)[1].split("}", 1)[0])]
    return {"px": num("px"), "size": int(num("size")), "step": int(num("step")), "tiles": tiles}


class World:
    """Paints any rectangle of the world (world units) at any resolution, so tiles and base agree."""

    def __init__(self, openmap: Path):
        self.openmap = openmap
        tex = openmap / "Media" / "Textures"
        self.art = Image.open(WORLD_ART).convert("RGB")
        # the sea's colour: the world art's own, blurred past its lettering (no halo where the band meets it)
        self.sea = self.art.filter(ImageFilter.GaussianBlur(9))
        band = Image.open(tex / "MapSeaCoast" / "947.tga").getchannel("A").resize((WORLD_W, WORLD_H), Image.BICUBIC)
        draw = ImageDraw.Draw(band)
        for box in LETTERING:
            draw.rectangle(box, fill=255)
        self.band = band.filter(ImageFilter.GaussianBlur(3))
        self.spots = [Image.open(tex / f"{n}.tga").convert("RGBA") for n in ("MapSeaDark", "MapSeaLight")]
        self.hatch = Image.open(tex / "MapHatch.tga").convert("RGBA")
        self.baked = zone_art(openmap)
        self._baked_cache: dict[int, Image.Image] = {}

    @staticmethod
    def _sample(img: Image.Image, x0: float, y0: float, size: tuple[int, int], px: float) -> Image.Image:
        """img (one pixel per world unit) over the rectangle from (x0, y0), at px pixels per unit."""
        return img.transform(size, Image.AFFINE, (1 / px, 0, x0, 0, 1 / px, y0), Image.BICUBIC)

    @staticmethod
    def _pattern(tex: Image.Image, x0: float, y0: float, size: tuple[int, int], px: float, units: float) -> Image.Image:
        """tex repeated every `units` world units, aligned to the world's corner."""
        side = max(1, round(units * px))
        tile = tex.resize((side, round(side * tex.height / tex.width)), Image.LANCZOS)
        ox, oy = round(x0 * px) % tile.width, round(y0 * px) % tile.height
        out = Image.new(tile.mode, size)
        for y in range(-oy, size[1], tile.height):
            for x in range(-ox, size[0], tile.width):
                out.paste(tile, (x, y))
        return out

    def _baked_tile(self, key: int) -> Image.Image:
        if key not in self._baked_cache:
            i, j = divmod(key, 256)
            img = Image.open(self.openmap / "Media" / "Textures" / "MapZones" / f"{i}_{j}.blp").convert("RGBA")
            inset = (self.baked["size"] - self.baked["step"]) // 2
            self._baked_cache[key] = img.crop((inset, inset, inset + self.baked["step"], inset + self.baked["step"]))
        return self._baked_cache[key]

    def land_tiles(self) -> list[tuple[float, float, float, float]]:
        """The baked tiles' rectangles (world units)."""
        s = self.baked["step"] / self.baked["px"]
        return [(i * s, j * s, (i + 1) * s, (j + 1) * s) for i, j in (divmod(k, 256) for k in self.baked["tiles"])]

    def paint(self, x0: float, y0: float, size: tuple[int, int], px: float) -> Image.Image:
        sea = self._sample(self.sea, x0, y0, size, px)
        for spots in self.spots:
            pattern = self._pattern(spots, x0, y0, size, px, SEA_SPOTS)
            sea.paste(pattern.convert("RGB"), (0, 0), pattern.getchannel("A").point(lambda a: a * 0.6))
        hatch = self._pattern(self.hatch, x0, y0, size, px, SEA_HATCH)
        sea.paste(hatch.convert("RGB"), (0, 0), hatch.getchannel("A").point(lambda a: a * 0.5))
        out = self._sample(self.art, x0, y0, size, px)
        out.paste(sea, (0, 0), self._sample(self.band, x0, y0, size, px))
        # the zones, from OpenMap's baked tiles
        s, bpx = self.baked["step"] / self.baked["px"], self.baked["px"]
        x1, y1 = x0 + size[0] / px, y0 + size[1] / px
        for key in self.baked["tiles"]:
            i, j = divmod(key, 256)
            if (i + 1) * s <= x0 or i * s >= x1 or (j + 1) * s <= y0 or j * s >= y1:
                continue
            tile = self._baked_tile(key)
            left, top = (i * s - x0) * px, (j * s - y0) * px
            if px != bpx:
                l, t = math.floor(left), math.floor(top)
                w = math.floor(left + s * px) - l
                h = math.floor(top + s * px) - t
                tile = tile.resize((max(1, w), max(1, h)), Image.LANCZOS)
                left, top = l, t
            out.paste(tile, (round(left), round(top)), tile)
        return out


def placement(install: Path) -> dict[int, tuple[float, float, float, float]]:
    """Where the game places each continent on the world map 947 (domain/maps.py CONTINENT_IN_WORLD), as
    C_Map.GetMapRectOnMap does: through the world positions (yards) of the maps' UiMapAssignment rows."""
    import struct

    import db2
    from forever_chronicle.wow import casc, paths

    rows = db2.read_db2(casc.Casc(install, paths.forever_product(install)).read_fdid(UI_MAP_ASSIGNMENT, zero_encrypted=True))
    real = lambda bits: struct.unpack("<f", struct.pack("<I", bits))[0]  # noqa: E731
    assigned: dict[int, list] = {}
    for r in rows:    # UiMin[2], UiMax[2], Region[6] (min x, y, z, max x, y, z), ID, UiMapID, OrderIndex, MapID
        f = r["fields"]
        assigned.setdefault(f[4], []).append(([real(v) for v in f[0]], [real(v) for v in f[1]],
                                              [real(v) for v in f[2]], f[6]))

    def to_ui(a, wx, wy):
        (u0, v0), (u1, v1), (x0, y0, _, x1, y1, _), _ = a
        return u0 + (u1 - u0) * (y1 - wy) / (y1 - y0), v0 + (v1 - v0) * (x1 - wx) / (x1 - x0)

    def to_world(a, u, v):
        (u0, v0), (u1, v1), (x0, y0, _, x1, y1, _), _ = a
        return x1 - (v - v0) / (v1 - v0) * (x1 - x0), y1 - (u - u0) / (u1 - u0) * (y1 - y0)

    out = {}
    for continent in (1414, 1415):
        own = assigned[continent][0]
        world = next(a for a in assigned[947] if a[3] == own[3])     # the world map's part for that continent
        l, t = to_ui(world, *to_world(own, 0, 0))
        r, b = to_ui(world, *to_world(own, 1, 1))
        out[continent] = (round(l, 5), round(r, 5), round(t, 5), round(b, 5))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--openmap", type=Path, default=DEFAULT_OPENMAP)
    ap.add_argument("--out", type=Path, default=ROOT / "desktop" / "forever_chronicle" / "maps" / "world")
    ap.add_argument("--placement", action="store_true",
                    help="only print where the game places the continents on the world map (CONTINENT_IN_WORLD)")
    ap.add_argument("--install", type=Path, default=Path(r"C:\Program Files (x86)\World of Warcraft"))
    args = ap.parse_args()
    if args.placement:
        for continent, rect in placement(args.install).items():
            print(continent, rect)
        return
    world = World(args.openmap)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    base = world.paint(0, 0, (round(WORLD_W * BASE_PX), round(WORLD_H * BASE_PX)), BASE_PX)
    base.save(args.out / "base.jpg", quality=88)

    land = world.land_tiles()
    side = TILE_UNITS * TILE_PX + 2 * TILE_MARGIN
    count, total = 0, 0
    for i in range(math.ceil(WORLD_W / TILE_UNITS)):
        for j in range(math.ceil(WORLD_H / TILE_UNITS)):
            x0, y0 = i * TILE_UNITS, j * TILE_UNITS
            x1, y1 = x0 + TILE_UNITS, y0 + TILE_UNITS
            if not any(l < x1 and r > x0 and t < y1 and b > y0 for l, t, r, b in land):
                continue
            m = TILE_MARGIN / TILE_PX
            tile = world.paint(x0 - m, y0 - m, (side, side), TILE_PX)
            path = args.out / f"{i}_{j}.jpg"
            tile.save(path, quality=86)
            count += 1
            total += path.stat().st_size
    print(f"{args.out}: base {base.size[0]} x {base.size[1]}, {count} detail tiles, "
          f"{(total + (args.out / 'base.jpg').stat().st_size) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
