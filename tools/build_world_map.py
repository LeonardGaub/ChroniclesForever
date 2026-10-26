"""Builds the seamless world map for the desktop app from OpenMap's baked zone art.

OpenMap (an installed addon, MIT; the map art is Blizzard's) stitches every zone map into one picture of Azeroth
and ships it baked as world tiles: Media/Textures/MapZones/<i>_<j>.blp, ns.MapZoneArt in Data/ZoneArt.lua.
Their unit is the world map's art pixel (947.jpg, 1002 x 668), the "world unit" of domain/maps.py
(CONTINENT_ON_WORLD, world_xy). Baked tile (i, j) covers step/px world units from (i, j) times that, its outer
(size - step) / 2 pixels being its neighbours' edge. The tiles hold land only (transparent sea), so the world
art, scaled up, stays underneath as the sea, its coastal band repainted as OpenMap paints the sea there (the
continents' big names sit in it).

The cities: OpenMap's baked art leaves them out (Orgrimmar is a hole, the banners of Undercity, Thunder Bluff and
Darnassus are blurred out), as OpenMap lays each city's own map and banner over them. The app shows a city's own
map only while the player is inside, so outside it the tiles carry the city as the Classic zone map paints it:
the city's zone's map (maps/<zone>.jpg) where its art is clean (OpenMap's MapEdge mask, inside the torn frame),
the neighbouring zone maps where it is not, thin gaps filled from around them, and the zone's name banner for the
city (OpenMap's MapBanner) on top, all feathered into the tiles round it. Placed by the game's UiMapAssignment.

Output (wow/map_art.py world_base / world_tile; kept in git like the zone maps):
    maps/world/base.jpg        the whole world at BASE_PX pixels per world unit
    maps/world/<i>_<j>.jpg     detail tiles at TILE_PX px per unit, each TILE_UNITS world units square from
                               (i, j) * TILE_UNITS, plus TILE_MARGIN pixels of its neighbours on every side
                               (tiles overlap, so no seams show between them); only where there is land

    desktop\\.venv\\Scripts\\python -I tools\\build_world_map.py [--openmap FOLDER] [--out FOLDER]

Rerun after OpenMap or the client updates the map art, or after tools/extract_maps.py (the cities' zone maps).
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
ZONE_MAPS = ROOT / "desktop" / "forever_chronicle" / "maps"
# Each city's zone, whose map paints the city with its name banner (OpenMap's ns.MapCityZones).
CITY_ZONES = {1453: 1429, 1454: 1411, 1455: 1426, 1456: 1412, 1457: 1438, 1458: 1420}
CITY_PAD = 0.3            # a city's patch reaches this share of the city's size past its rectangle ...
CITY_FEATHER = 0.25       # ... and fades out over this share of it towards the patch's edge
GAP_BLUR = 2.5            # world units: thin strips no zone paints cleanly are filled from around them
SEAM_BLUR = 3.0           # ... and how softly the zone maps meet (world units)
HOLE_BLUR = 3.5           # ... and the mirrored painting fades into OpenMap's round a city's hole
EDGE_GAIN = 2.0           # a zone map counts as fully clean where its MapEdge mask is above 1 / EDGE_GAIN
MIRROR, MIRROR_REACH = 0.2, 16.0  # the city's zone map goes on mirrored this share of it past its edge, fading out
                          # over this many world units


def zone_art(openmap: Path) -> dict:
    text = re.sub(r"--[^\n]*", "", (openmap / "Data" / "ZoneArt.lua").read_text(encoding="utf-8"))
    num = lambda key: float(re.search(rf"\b{key}\s*=\s*([\d.]+)", text).group(1))  # noqa: E731
    tiles = [int(t) for t in re.findall(r"\d+", re.split(r"\btiles\s*=\s*\{", text, maxsplit=1)[1].split("}", 1)[0])]
    return {"px": num("px"), "size": int(num("size")), "step": int(num("step")), "tiles": tiles}


class World:
    """Paints any rectangle of the world (world units) at any resolution, so tiles and base agree."""

    def __init__(self, openmap: Path, install: Path | None = None):
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
        self.cities = city_patches(openmap, install, self.baked_alpha) if install is not None else []

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

    def baked_alpha(self, x0: float, y0: float, size: tuple[int, int], px: float) -> Image.Image:
        """How much OpenMap's baked zones cover the rectangle from (x0, y0) at px pixels per unit (L, 0..255)."""
        out = Image.new("L", size, 0)
        s = self.baked["step"] / self.baked["px"]
        x1, y1 = x0 + size[0] / px, y0 + size[1] / px
        for key in self.baked["tiles"]:
            i, j = divmod(key, 256)
            if (i + 1) * s <= x0 or i * s >= x1 or (j + 1) * s <= y0 or j * s >= y1:
                continue
            side = round(s * px)
            out.paste(self._baked_tile(key).getchannel("A").resize((side, side), Image.BILINEAR),
                      (round((i * s - x0) * px), round((j * s - y0) * px)))
        return out

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
        # the cities as their zones paint them
        for left, top, patch in self.cities:
            right, bottom = left + patch.width / TILE_PX, top + patch.height / TILE_PX
            if right <= x0 or left >= x1 or bottom <= y0 or top >= y1:
                continue
            k = TILE_PX / px
            part = patch.transform(size, Image.AFFINE, (k, 0, (x0 - left) * TILE_PX, 0, k, (y0 - top) * TILE_PX),
                                   Image.BICUBIC)
            out.paste(part.convert("RGB"), (0, 0), part.getchannel("A"))
        return out


def _banners(openmap: Path) -> dict[int, tuple[int, int, int, int, int]]:
    """OpenMap's ns.MapBanners: [city] = (zone, x, y, width, height), the zone's banner for the city."""
    text = (openmap / "Data" / "Banners.lua").read_text(encoding="utf-8")
    block = text.split("ns.MapBanners", 1)[1].split("}\n", 1)[0]
    return {int(m[0]): tuple(int(v) for v in m[1:])
            for m in re.findall(r"\[(\d+)\]\s*=\s*\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}", block)}


def city_patches(openmap: Path, install: Path, baked_alpha) -> list[tuple[float, float, Image.Image]]:
    """Each city as the Classic zone maps paint it, for the tiles (module docstring): (left, top, RGBA patch at
    TILE_PX pixels per world unit), its alpha feathered into the tiles round it. baked_alpha: World.baked_alpha."""
    import numpy as np

    tex = openmap / "Media" / "Textures"
    zones = [int(f.stem) for f in (tex / "MapEdge").glob("*.tga") if f.stem.isdigit()
             and (ZONE_MAPS / f"{f.stem}.jpg").is_file()]
    rects = map_rects(install, list(CITY_ZONES) + zones)
    banners = _banners(openmap)
    out = []
    for city, home in CITY_ZONES.items():
        if city not in rects or home not in rects:
            continue
        l, r, t, b = rects[city]
        pad_x, pad_y = (r - l) * CITY_PAD * WORLD_W, (b - t) * CITY_PAD * WORLD_H
        x0, y0, x1, y1 = l * WORLD_W, t * WORLD_H, r * WORLD_W, b * WORLD_H
        # the zone's name banner for the city, as the zone map has it (OpenMap cut it from the zone's art)
        banner = banners.get(city)
        if banner is not None and (banner[0] not in rects or not (tex / "MapBanner" / f"{city}.tga").is_file()):
            banner = None
        if banner is not None:
            zone, bx, by, bw, bh = banner
            zl, zr, zt, zb = rects[zone]
            ux, uy = (zr - zl) * WORLD_W / 1002, (zb - zt) * WORLD_H / 668    # world units per zone art pixel
            banner = (zl * WORLD_W + bx * ux, zt * WORLD_H + by * uy, bw * ux, bh * uy)
            x0, y0 = min(x0, banner[0]), min(y0, banner[1])
            x1, y1 = max(x1, banner[0] + banner[2]), max(y1, banner[1] + banner[3])
        x0, y0, x1, y1 = x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y
        size = (round((x1 - x0) * TILE_PX), round((y1 - y0) * TILE_PX))

        def sample(img: Image.Image, rect: tuple[float, float, float, float]) -> np.ndarray:
            """img (covering rect: left, right, top, bottom shares of the world map) over the patch, 0..1."""
            zl, zr, zt, zb = rect
            sx, sy = img.width / ((zr - zl) * WORLD_W), img.height / ((zb - zt) * WORLD_H)
            part = img.transform(size, Image.AFFINE, (sx / TILE_PX, 0, (x0 - zl * WORLD_W) * sx, 0, sy / TILE_PX,
                                                      (y0 - zt * WORLD_H) * sy), Image.BICUBIC)
            return np.asarray(part, dtype=np.float32) / 255

        def blur(a: np.ndarray, units: float) -> np.ndarray:
            img = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
            return np.asarray(img.filter(ImageFilter.GaussianBlur(units * TILE_PX)), dtype=np.float32) / 255

        def soft(w: np.ndarray) -> np.ndarray:
            """w with its edge softened inward: it fades out inside where it was, never past it (a layer's
            colours stop at its edge)."""
            return np.clip(blur(w, SEAM_BLUR) * 2 - 1, 0, 1)

        def solid(img: Image.Image) -> Image.Image:
            return Image.new("L", img.size, 255)

        # The city's own zone's map inside its frame (MapEdge): the Classic map of the city.
        zl, zr, zt, zb = rects[home]
        art = Image.open(ZONE_MAPS / f"{home}.jpg").convert("RGB")
        edge = Image.open(tex / "MapEdge" / f"{home}.tga").getchannel("A").resize(art.size, Image.BILINEAR)
        home_in = soft(np.clip(sample(edge, rects[home]) * EDGE_GAIN, 0, 1))
        # Past that, inside the hole OpenMap's baked art leaves for a city it cuts out for its own map
        # (MapCityMask: Orgrimmar above Durotar's map), it goes on as its mirror image for a few world units,
        # without the zone's banner (MapBannerHole; the banner is laid on top below): the painting's own texture
        # across the strip no map paints cleanly, rather than a smear. Elsewhere past the zone maps OpenMap's own
        # art stays (the sea off Stormwind).
        e = np.asarray(edge) >= 128
        cols, rows = np.flatnonzero(e[art.height // 2]), np.flatnonzero(e[:, art.width // 2])
        ix0, ix1, iy0, iy1 = cols[0], cols[-1] + 1, rows[0], rows[-1] + 1     # the art inside its frame
        hole_file = tex / "MapBannerHole" / f"{home}.tga"
        keep = (Image.open(hole_file).getchannel("A").resize(art.size, Image.BILINEAR) if hole_file.is_file()
                else solid(art))
        inner = np.asarray(art)[iy0:iy1, ix0:ix1]
        valid = np.asarray(keep)[iy0:iy1, ix0:ix1]
        mx, my = round(inner.shape[1] * MIRROR), round(inner.shape[0] * MIRROR)
        mirrored = Image.fromarray(np.pad(inner, ((my, my), (mx, mx), (0, 0)), mode="reflect"))
        mirrored_valid = Image.fromarray(np.pad(valid, ((my, my), (mx, mx)), mode="reflect"))
        ux, uy = (zr - zl) / art.width, (zb - zt) / art.height                # world shares per art pixel
        zl, zr, zt, zb = zl + ix0 * ux, zl + ix1 * ux, zt + iy0 * uy, zt + iy1 * uy   # the inner rectangle
        extent = (zl - mx * ux, zr + mx * ux, zt - my * uy, zb + my * uy)
        home_rgb = sample(mirrored, extent)
        xs = x0 + (np.arange(size[0]) + 0.5) / TILE_PX
        ys = y0 + (np.arange(size[1]) + 0.5) / TILE_PX
        out_x = np.maximum(np.maximum(zl * WORLD_W - xs, xs - zr * WORLD_W), 0)
        out_y = np.maximum(np.maximum(zt * WORLD_H - ys, ys - zb * WORLD_H), 0)
        reach = np.clip(1 - np.maximum(out_y[:, None], out_x[None, :]) / MIRROR_REACH, 0, 1)
        if (tex / "MapCityMask" / f"{city}.tga").is_file():
            hole = blur(1 - np.asarray(baked_alpha(x0, y0, size, TILE_PX), dtype=np.float32) / 255, HOLE_BLUR)
            mirror = (reach * reach * (3 - 2 * reach) * hole * (1 - home_in)
                      * soft(sample(solid(mirrored), extent) * sample(mirrored_valid, extent)))
        else:
            mirror = np.zeros_like(home_in)
        # the other zones' maps where they are clean (the cleanest one wins where several are)
        sums, total, other_w = np.zeros_like(home_rgb), np.zeros_like(home_in), np.zeros_like(home_in)
        for zone in zones:
            ol, orr, ot, ob = rects.get(zone, (0, 0, 0, 0))
            if zone == home or orr * WORLD_W <= x0 or ol * WORLD_W >= x1 or ob * WORLD_H <= y0 or ot * WORLD_H >= y1:
                continue
            w = soft(np.clip(sample(Image.open(tex / "MapEdge" / f"{zone}.tga").getchannel("A"), rects[zone])
                             * EDGE_GAIN, 0, 1))
            sums += sample(Image.open(ZONE_MAPS / f"{zone}.jpg").convert("RGB"), rects[zone]) * (w ** 4)[..., None]
            total += w ** 4
            other_w = np.maximum(other_w, w)
        other_rgb = sums / np.maximum(total, 1e-6)[..., None]
        other_w = other_w * (1 - home_in)
        mirror_w = mirror * (1 - home_in - other_w).clip(0, 1)
        home_w = home_in + mirror_w
        cover = np.clip(home_w + other_w, 0, 1)
        rgb = (home_rgb * home_w[..., None] + other_rgb * other_w[..., None]) / np.maximum(home_w + other_w,
                                                                                          1e-4)[..., None]
        # thin strips no map paints cleanly (between two torn frames): filled from around them
        spread = blur(cover, GAP_BLUR)
        around = np.stack([blur(rgb[..., c] * cover, GAP_BLUR) for c in range(3)], -1) / np.maximum(spread,
                                                                                                 1e-3)[..., None]
        rgb = rgb * cover[..., None] + np.clip(around, 0, 1) * (1 - cover[..., None])
        # feathered towards the patch's edge, and nothing where no map paints at all
        fx = np.clip(np.minimum(np.arange(size[0]), size[0] - 1 - np.arange(size[0])) / (pad_x * CITY_FEATHER
                     / CITY_PAD * TILE_PX), 0, 1)
        fy = np.clip(np.minimum(np.arange(size[1]), size[1] - 1 - np.arange(size[1])) / (pad_y * CITY_FEATHER
                     / CITY_PAD * TILE_PX), 0, 1)
        smooth = lambda v: v * v * (3 - 2 * v)  # noqa: E731
        alpha = smooth(fy)[:, None] * smooth(fx)[None, :] * np.clip(spread * 4, 0, 1)
        patch = Image.fromarray(np.clip(np.dstack([rgb, alpha]) * 255, 0, 255).astype(np.uint8), "RGBA")
        if banner is not None:
            bx, by, bw, bh = banner
            img = Image.open(tex / "MapBanner" / f"{city}.tga").convert("RGBA")
            img = img.resize((max(1, round(bw * TILE_PX)), max(1, round(bh * TILE_PX))), Image.LANCZOS)
            patch.alpha_composite(img, (round((bx - x0) * TILE_PX), round((by - y0) * TILE_PX)))
        out.append((x0, y0, patch))
    return out


def map_rects(install: Path, map_ids) -> dict[int, tuple[float, float, float, float]]:
    """Where the game places each map on the world map 947, as (left, right, top, bottom) shares of its art, as
    C_Map.GetMapRectOnMap does: through the world positions (yards) of the maps' UiMapAssignment rows. Maps
    without a part of the world map for their world (Forever's own islands) are left out."""
    import struct

    import db2
    from forever_chronicle.wow import casc, paths

    rows = db2.read_db2(casc.Casc(install, paths.forever_product(install)).read_fdid(UI_MAP_ASSIGNMENT, zero_encrypted=True))
    real = lambda bits: struct.unpack("<f", struct.pack("<I", bits))[0]  # noqa: E731
    assigned: dict[int, list] = {}
    for r in rows:    # UiMin[2], UiMax[2], Region[6] (min x, y, z, max x, y, z), ID, UiMapID, OrderIndex, MapID
        f = r["fields"]
        assigned.setdefault(f[4], []).append(([real(v) for v in f[0]], [real(v) for v in f[1]],
                                              [real(v) for v in f[2]], f[6], f[5]))

    def to_ui(a, wx, wy):
        (u0, v0), (u1, v1), (x0, y0, _, x1, y1, _), *_ = a
        return u0 + (u1 - u0) * (y1 - wy) / (y1 - y0), v0 + (v1 - v0) * (x1 - wx) / (x1 - x0)

    def to_world(a, u, v):
        (u0, v0), (u1, v1), (x0, y0, _, x1, y1, _), *_ = a
        return x1 - (v - v0) / (v1 - v0) * (x1 - x0), y1 - (u - u0) / (u1 - u0) * (y1 - y0)

    out = {}
    for map_id in map_ids:
        if map_id not in assigned:
            continue
        own = min(assigned[map_id], key=lambda a: a[4])                # its main row (OrderIndex)
        world = next((a for a in assigned[947] if a[3] == own[3]), None)   # the world map's part for its world
        if world is None:
            continue
        l, t = to_ui(world, *to_world(own, 0, 0))
        r, b = to_ui(world, *to_world(own, 1, 1))
        out[map_id] = (l, r, t, b)
    return out


def placement(install: Path) -> dict[int, tuple[float, float, float, float]]:
    """Where the game places each continent on the world map 947 (domain/maps.py CONTINENT_IN_WORLD)."""
    return {c: tuple(round(v, 5) for v in rect) for c, rect in map_rects(install, (1414, 1415)).items()}


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
    world = World(args.openmap, args.install)
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
