import json
import struct
import zlib

import numpy as np
import pytest

from forever_chronicle.domain import terrain
from forever_chronicle.domain.terrain import TerrainPack, decode_heights, tile_of, tile_origin

# Orgrimmar's UiMapAssignment row from the client (tools/build_terrain.py) and the probe's ground truth
# (probe-results, 2026-10-14): GetPlayerMapPosition 0.51648616790771, 0.49701648950577 on 1454 ->
# GetWorldPosFromMapPos 1, {x=1808.9597167969, y=-4405.0268554688}.
ORGRIMMAR_ROW = [0.0, 0.0, 1.0, 1.0, 1338.461, -5083.206, 2273.877, -3680.601, 1, 0]
PROBE_MAP, PROBE_WORLD = (0.51648616790771, 0.49701648950577), (1808.9597167969, -4405.0268554688)


def write_pack(root, heights_by_tile, offset=(100.0, -50.0)):
    (root / "kalimdor").mkdir(parents=True)
    tiles = []
    for (tx, ty), h in heights_by_tile.items():
        base = float(np.floor(h.min()))
        q = np.round((h - base) / terrain.HEIGHT_STEP).astype("<u2")
        data = b"FCH1" + struct.pack("<HHf", h.shape[0], 0, base) + zlib.compress(q.tobytes())
        (root / "kalimdor" / f"h_{tx}_{ty}.bin").write_bytes(data)
        tiles.append([tx, ty, float(h.min()), float(h.max())])
    index = {"format": 1, "build": "test", "ui_maps": {"1454": [ORGRIMMAR_ROW]},
             "continents": {"kalimdor": {"map_id": 1, "offset": list(offset), "tiles": tiles}}}
    (root / "index.json").write_text(json.dumps(index), "utf-8")
    return TerrainPack(root)


def test_map_position_to_world_matches_the_game(tmp_path):
    pack = write_pack(tmp_path, {})
    world, wx, wy = pack.world_pos(1454, *PROBE_MAP)
    assert world == 1
    assert wx == pytest.approx(PROBE_WORLD[0], abs=0.05)
    assert wy == pytest.approx(PROBE_WORLD[1], abs=0.05)
    assert pack.world_pos(9999, 0.5, 0.5) is None


def test_shared_world_round_trip(tmp_path):
    pack = write_pack(tmp_path, {}, offset=(100.0, -50.0))
    east, north = pack.shared(1, 1808.96, -4405.03)
    assert (east, north) == pytest.approx((4405.03 + 100.0, 1808.96 - 50.0))
    assert pack.unshared(1, east, north) == pytest.approx((1808.96, -4405.03))


def test_tiles_run_from_north_west():
    tx, ty, fx, fy = tile_of(*PROBE_WORLD)
    assert (tx, ty) == (40, 28)                     # Orgrimmar: east of the middle, north of it
    east, north = tile_origin(tx, ty)
    assert -PROBE_WORLD[1] == pytest.approx(east + fx * terrain.TILE_YARDS)
    assert PROBE_WORLD[0] == pytest.approx(north - fy * terrain.TILE_YARDS)


def test_heights_are_sampled_between_vertices(tmp_path):
    grid = np.zeros((129, 129), np.float32)
    grid += np.arange(129, dtype=np.float32)[None, :]          # rises 1 yd per vertex towards the east
    grid += 1000 * np.arange(129, dtype=np.float32)[:, None] / 128  # and 1000 yd over the tile towards the south
    pack = write_pack(tmp_path, {(40, 28): grid})
    east0, north0 = tile_origin(40, 28)
    step = terrain.TILE_YARDS / 128
    # 10.5 vertices east, a quarter of the tile south
    wx, wy = north0 - terrain.TILE_YARDS / 4, -(east0 + 10.5 * step)
    assert pack.height_at(1, wx, wy) == pytest.approx(10.5 + 250.0, abs=0.1)
    assert pack.height_at(1, 0.0, 0.0) == 0.0                 # no tile there: sea level
    assert pack.heights(1, 40, 28) is pack.heights(1, 40, 28)   # kept once loaded


def test_place_gives_shared_position_and_ground(tmp_path):
    grid = np.full((129, 129), 42.0, np.float32)
    pack = write_pack(tmp_path, {(40, 28): grid}, offset=(0.0, 0.0))
    east, north, z = pack.place(1454, *PROBE_MAP)
    assert (east, north) == pytest.approx((-PROBE_WORLD[1], PROBE_WORLD[0]), abs=0.05)
    assert z == pytest.approx(42.0, abs=0.05)


def test_height_file_round_trip():
    h = np.linspace(-20, 300, 129 * 129, dtype=np.float32).reshape(129, 129)
    base = float(np.floor(h.min()))
    q = np.round((h - base) / terrain.HEIGHT_STEP).astype("<u2")
    out = decode_heights(b"FCH1" + struct.pack("<HHf", 129, 0, base) + zlib.compress(q.tobytes()))
    assert np.abs(out - h).max() <= terrain.HEIGHT_STEP / 2 + 1e-3


@pytest.mark.skipif(not TerrainPack.available(), reason="no terrain pack baked")
def test_real_pack_puts_orgrimmar_on_the_ground():
    pack = TerrainPack()
    east, north, z = pack.place(1454, *PROBE_MAP)
    low, high = pack.continents[1].tiles[(40, 28)]
    assert low <= z <= high and -60 < z < 100     # the Cleft of Shadow, a ravine a little below sea level


def write_liquids(root, tx, ty, heights, kinds):
    (root / "kalimdor" / f"w_{tx}_{ty}.bin").write_bytes(
        b"FCW1" + zlib.compress(heights.astype("<f2").tobytes() + kinds.astype(np.uint8).tobytes()))
    index = json.loads((root / "index.json").read_text("utf-8"))
    for t in index["continents"]["kalimdor"]["tiles"]:
        if (t[0], t[1]) == (tx, ty):
            t.append(1)
    (root / "index.json").write_text(json.dumps(index), "utf-8")
    return TerrainPack(root)


def test_liquids_lift_the_player_to_their_surface(tmp_path):
    grid = np.full((129, 129), -12.0, np.float32)            # a lake bed under water at 5 yd
    write_pack(tmp_path, {(40, 28): grid})
    heights = np.full((129, 129), np.nan, np.float32)
    heights[:65, :] = 5.0
    kinds = np.zeros((128, 128), np.uint8)
    kinds[:64, :] = terrain.WATER                            # the northern half is a lake
    pack = write_liquids(tmp_path, 40, 28, heights, kinds)
    east0, north0 = tile_origin(40, 28)
    wet = (north0 - terrain.TILE_YARDS * 0.25, -(east0 + 100))
    dry = (north0 - terrain.TILE_YARDS * 0.75, -(east0 + 100))
    assert pack.water_at(1, *wet) == pytest.approx(5.0)
    assert pack.surface_at(1, *wet) == pytest.approx(5.0)
    assert pack.water_at(1, *dry) is None
    assert pack.surface_at(1, *dry) == pytest.approx(-12.0)
    assert pack.water_at(1, 0.0, 0.0) == terrain.SEA_LEVEL    # off the tiles: the open sea
    assert pack.surface_at(1, 0.0, 0.0) == terrain.SEA_LEVEL


def test_dry_tiles_have_no_liquid_file(tmp_path):
    pack = write_pack(tmp_path, {(40, 28): np.zeros((129, 129), np.float32)})
    assert pack.liquids(1, 40, 28) is None
    heights, kinds = pack.overview_liquids(1)                # no overview file yet: all dry
    assert np.isnan(heights).all() and not kinds.any()


def test_shared_positions_find_their_world(tmp_path):
    pack = write_pack(tmp_path, {(40, 28): np.full((129, 129), 30.0, np.float32)}, offset=(0.0, 0.0))
    east, north = pack.shared(1, *PROBE_WORLD)
    assert pack.world_at(east, north) == 1
    assert pack.ground_shared(east, north) == pytest.approx(30.0)
    assert pack.world_at(east + 50000, north) is None
    assert pack.surface_shared(east + 50000, north) == terrain.SEA_LEVEL
    assert not pack.sky_island(1)              # without the world map's rows nothing counts as apart


def test_map_positions_reach_the_shared_world_even_between_rectangles(tmp_path):
    pack = write_pack(tmp_path, {}, offset=(100.0, -50.0))
    index = json.loads((tmp_path / "index.json").read_text("utf-8"))
    # A made-up world map: Kalimdor's rectangle in the left half.
    index["ui_maps"]["947"] = [[0.0, 0.0, 0.5, 1.0, -12800.0, -9600.0, 12266.7, 6933.3, 1, 0]]
    (tmp_path / "index.json").write_text(json.dumps(index), "utf-8")
    pack = TerrainPack(tmp_path)
    inside = pack.map_to_shared(947, 0.25, 0.5)
    world, wx, wy = pack.world_pos(947, 0.25, 0.5)
    assert inside == pytest.approx(pack.shared(world, wx, wy))
    edge, beyond = pack.map_to_shared(947, 0.5, 0.5), pack.map_to_shared(947, 0.6, 0.5)
    step = (edge[0] - inside[0]) / 0.25                      # yards east per world map share
    assert beyond[0] == pytest.approx(edge[0] + 0.1 * step)  # carried on east of the rectangle, no jump
    assert beyond[1] == pytest.approx(edge[1])
    assert pack.map_to_shared(1454, *PROBE_MAP) == pytest.approx(pack.shared(1, *PROBE_WORLD), abs=0.05)
    assert pack.map_to_shared(9999, 0.5, 0.5) is None


def test_many_positions_sample_like_one(tmp_path):
    grid = np.add.outer(np.arange(129, dtype=np.float32), np.arange(129, dtype=np.float32))   # a slope
    write_pack(tmp_path, {(40, 28): grid, (41, 28): grid + 500}, offset=(10.0, 20.0))
    heights = np.full((129, 129), np.nan, np.float32)
    heights[:, :65] = 400.0
    kinds = np.zeros((128, 128), np.uint8)
    kinds[:, :64] = terrain.WATER                            # a deep lake over the western half
    pack = write_liquids(tmp_path, 40, 28, heights, kinds)
    rng = np.random.default_rng(3)
    e0, n0 = tile_origin(40, 28)
    east = e0 + 10.0 + rng.uniform(-200, 2 * terrain.TILE_YARDS + 200, 300)
    north = n0 + 20.0 - rng.uniform(0, terrain.TILE_YARDS, 300)
    many = pack.surface_many(east, north)
    one = [pack.surface_shared(e, n) for e, n in zip(east, north)]
    assert many == pytest.approx(one, abs=1e-3)
    dry = pack.surface_many(east, north, water=False)
    assert dry == pytest.approx([pack.ground_shared(e, n) for e, n in zip(east, north)], abs=1e-3)
