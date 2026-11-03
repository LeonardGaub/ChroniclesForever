"""World map objects (WMO: buildings, bridges, city walls) from the game files, for tools/build_terrain.py.

Format notes (wowdev.wiki "WMO", "ADT/v18" MODF), checked against the installed client on 2026-11-03:
- obj0 ADT, MODF (64 bytes): fileDataID (flag 0x8), uniqueId (a building on several tiles is listed on each),
  position (x, y up, z), rotation in degrees, the rotated model's box, flags, doodad set, name set, scale (1024 = 1,
  flag 0x4).
- Placement: placement = Ry(ry) . Rx(rx) . Rz(rz) . B . model * scale + position, with B taking model (x, y, z up) to
  placement (y, z, x): fitted to the stored boxes of 1,524 placements (0.65 yd mean error over the six edges).
  World: x (north) = 17066 2/3 - placement z, y (west) = 17066 2/3 - placement x, z = placement y.
- Root: MOHD (box at byte 36), MOMT (64 bytes a material; [2] blend mode), MOGI (32 bytes a group; flags 0x8
  exterior, 0x2000 interior), GFID (the groups' fileDataIDs, once per LOD: the big ones have 3-4 levels).
- Group: MOGP (68-byte header, then sub-chunks): MOVT (positions), MONR (normals), MOCV (vertex colours BGRA, the
  baked shade), MOVI (uint16 indices), MOBA (24-byte batches: [12] start index, [16] count, [22] flags, [23]
  material; flag 0x2 takes the material from [10]). Only the batches are drawn: collision-only triangles are in
  none.
"""

from __future__ import annotations

import math
import struct

import numpy as np

from build_terrain import chunks

MAP_CORNER = 32 * 1600 / 3
EXTERIOR, INTERIOR = 0x8, 0x2000
OPAQUE, ALPHA_KEY = 0, 1      # MOMT blend modes; the others are glass and glows
DRAWN = (OPAQUE, ALPHA_KEY)
# model (x, y, z up) -> placement (x, y up, z): placement x = model y, placement y = model z, placement z = model x
BASIS = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]])
# placement -> the terrain pack's true (east, north, up): east = -world y = placement x - corner,
# north = world x = corner - placement z, up = placement y
TO_PACK = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
PACK_SHIFT = np.array([-MAP_CORNER, MAP_CORNER, 0.0])


def _rot(axis: int, a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    if axis == 0:
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == 1:
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def placements(obj0: bytes) -> list[dict]:
    """The buildings placed by an obj0 ADT: fileDataID, uniqueId and the model -> pack transform (3 x 3, shift)."""
    m = dict(chunks(obj0)).get("MODF", b"")
    out = []
    for i in range(len(m) // 64):
        fdid, uid, px, py, pz, rx, ry, rz, *_box, flags, _dset, _nset, scale = struct.unpack_from(
            "<II3f3f6fHHHH", m, i * 64)
        if not flags & 0x8:              # a name offset instead of a fileDataID (not used by these clients)
            continue
        k = scale / 1024 if flags & 0x4 else 1.0
        rot = _rot(1, math.radians(ry)) @ _rot(0, math.radians(rx)) @ _rot(2, math.radians(rz))
        linear = TO_PACK @ rot @ BASIS * k
        shift = TO_PACK @ np.array([px, py, pz]) + PACK_SHIFT
        out.append({"fdid": fdid, "uid": uid, "linear": linear, "shift": shift})
    return out


def first_chunks(data: bytes) -> dict[str, bytes]:
    """The chunks by tag, the first of each (a group has a second MOTV and MOCV for its other texture layers)."""
    out: dict[str, bytes] = {}
    for tag, payload in chunks(data):
        out.setdefault(tag, payload)
    return out


def mesh(storage, fdid: int, above=None):
    """A building's drawn geometry, all groups in one: positions (n x 3, model space), normals (n x 3), shade
    (n, 0..1 from the baked vertex colours, 1 without), texture coordinates (n x 2), triangle indices and per
    triangle its material: (texture fileDataID, blend mode).
    Which groups: a building with levels (the big ones: cities, keeps) takes its LOD 1 groups; its groups without
    one are interior groups the game leaves out from afar, but the drone looks down into them (classic Orgrimmar is
    all interior), so they come in full where they reach above the ground (above: a group's top middle in model
    space -> True) and stay out underground (Undercity, caves, mines). A building without levels takes its exterior
    groups (a house's rooms are under its roof), or all where above() allows if it has none.
    Which batches: opaque ones and alpha-cut ones (fences, banners, leaves: DRAWN), not glass or glows."""
    root = dict(chunks(storage.read_fdid(fdid)))
    mogi, momt = root.get("MOGI", b""), root.get("MOMT", b"")
    groups = len(mogi) // 32
    if not groups or "GFID" not in root:
        return None
    gfid = struct.unpack_from(f"<{len(root['GFID']) // 4}I", root["GFID"])
    levels = len(gfid) // groups
    lod = 1 if levels > 1 else 0
    flags = [struct.unpack_from("<I", mogi, g * 32)[0] for g in range(groups)]
    any_exterior = any(f & EXTERIOR for f in flags)
    materials = [struct.unpack_from("<IIII", momt, i * 64) for i in range(len(momt) // 64)]   # flags, shader, blend, tex
    tops = [np.array(struct.unpack_from("<6f", mogi, g * 32 + 4)) for g in range(groups)]
    pos, nrm, shade, uvs, idx, mats, base = [], [], [], [], [], [], 0
    for g in range(groups):
        f = gfid[lod * groups + g] if lod else 0
        if not f:
            if lod == 0 and any_exterior and not flags[g] & EXTERIOR:
                continue
            f = gfid[g]
            b = tops[g]
            if not f or (not flags[g] & EXTERIOR and above is not None
                         and not above(np.array([(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, b[5]]))):
                continue
        sub = first_chunks(dict(chunks(storage.read_fdid(f)))["MOGP"][68:])
        movt, movi, moba = sub.get("MOVT", b""), sub.get("MOVI", b""), sub.get("MOBA", b"")
        n = len(movt) // 12
        if not n or not movi or not moba:
            continue
        indices = np.frombuffer(movi, "<u2")
        drawn, drawn_mats = [], []
        for b in range(len(moba) // 24):
            large, start, count = struct.unpack_from("<HIH", moba, b * 24 + 10)
            bflags, material = moba[b * 24 + 22], moba[b * 24 + 23]
            if bflags & 0x2:
                material = large
            blend = materials[material][2] if material < len(materials) else OPAQUE
            if blend not in DRAWN:
                continue
            tex = materials[material][3] if material < len(materials) else 0
            tris = indices[start:start + count - count % 3]
            drawn.append(tris)
            drawn_mats.extend([(tex, blend)] * (len(tris) // 3))
        if not drawn:
            continue
        tris = np.concatenate(drawn).astype(np.int64)
        if tris.size == 0 or tris.max() >= n:
            continue
        pos.append(np.frombuffer(movt, "<f4").reshape(n, 3))
        monr = sub.get("MONR", b"")
        nrm.append(np.frombuffer(monr, "<f4").reshape(n, 3) if len(monr) == 12 * n else np.tile([0.0, 0.0, 1.0], (n, 1)))
        motv = sub.get("MOTV", b"")
        uvs.append(np.frombuffer(motv, "<f4").reshape(n, 2) if len(motv) == 8 * n else np.zeros((n, 2), np.float32))
        mocv = sub.get("MOCV", b"")
        if len(mocv) >= 4 * n:
            bgra = np.frombuffer(mocv, np.uint8, 4 * n).reshape(n, 4).astype(np.float32) / 255
            shade.append(np.clip((bgra[:, 2] * 0.3 + bgra[:, 1] * 0.59 + bgra[:, 0] * 0.11) * 1.6, 0.35, 1.0))
        else:
            shade.append(np.ones(n, np.float32))
        idx.append(tris + base)
        mats.extend(drawn_mats)
        base += n
    if not idx:
        return None
    return (np.concatenate(pos), np.concatenate(nrm), np.concatenate(shade), np.concatenate(uvs),
            np.concatenate(idx), mats)


def encode_mesh(pos, nrm, shade, uv, idx, mats) -> bytes:
    """"FCB2", box low (3 f32), box size (3 f32), vertex, index and batch counts (u32), then zlib of the
    positions (u16 x 3 over the box), normals (i8 x 3), shade (u8), texture coordinates (f16 x 2), indices (u16
    below 65,536 vertices, else u32) and the batches (u32 x 4: first index, index count, texture fileDataID,
    blend mode). Triangles are sorted by material, a batch for each; vertices alike in everything are merged."""
    import zlib
    low = pos.min(axis=0)
    size = np.maximum(pos.max(axis=0) - low, 1e-3)
    q = np.round((pos - low) / size * 65535).astype("<u2")
    n8 = np.clip(np.round(nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-6) * 127), -127, 127)
    s8 = np.round(np.clip(shade, 0, 1) * 255).astype(np.uint8)
    t16 = uv.astype("<f2")
    key = np.concatenate([q.astype(np.int64), n8.astype(np.int64), s8[:, None].astype(np.int64),
                          t16.view("<u2").astype(np.int64)], axis=1)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    q, n8, s8, t16 = q[first], n8[first], s8[first], t16[first]
    tri = inverse.ravel()[idx].reshape(-1, 3)
    mat = np.array(mats, np.int64).reshape(-1, 2)
    keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    tri, mat = tri[keep], mat[keep]
    order = np.lexsort((mat[:, 1], mat[:, 0]))
    tri, mat = tri[order], mat[order]
    batches = []
    if len(mat):
        change = np.nonzero((np.diff(mat, axis=0) != 0).any(axis=1))[0] + 1
        for a, b in zip(np.concatenate([[0], change]), np.concatenate([change, [len(mat)]])):
            batches.append((int(a) * 3, int(b - a) * 3, int(mat[a, 0]), int(mat[a, 1])))
    wide = len(q) >= 65536
    body = (q.tobytes() + n8.astype(np.int8).tobytes() + s8.tobytes() + t16.tobytes()
            + tri.ravel().astype("<u4" if wide else "<u2").tobytes() + np.array(batches, "<u4").tobytes())
    return (b"FCB2" + struct.pack("<3f3fIII", *low, *size, len(q), tri.size, len(batches)) + zlib.compress(body, 9))


def floors(pack, world: int, step: float, highest: bool = False) -> dict[tuple[int, int], float]:
    """Where the player walks on buildings: for each terrain grid point (global column, row: east / step,
    north / step in true yards) under a building, the lowest upward-facing building surface that is not below
    the ground there (a city's floor, a bridge's deck, a house's ground floor). There is no height in the
    recorded route, so this is the best guess for where it runs.
    highest: the highest building surface there instead, of any facing (the roofs, tower tops, arches: what can
    stand between the camera and the marker)."""
    b = pack.buildings(world)
    off = np.array([*pack.continents[world].offset, 0.0])
    best: dict[tuple[int, int], float] = {}
    for i in range(len(b)):
        pos, _nrm, _shade, idx = pack.building_mesh(int(b.fdids[i]))[:4]
        w = pos @ b.linear[i].T + b.shift[i] - off
        tri = idx.reshape(-1, 3)
        A, B, C = w[tri[:, 0]], w[tri[:, 1]], w[tri[:, 2]]
        if not highest:
            n = np.cross(B - A, C - A)
            up = np.abs(n[:, 2]) > 0.6 * np.maximum(np.linalg.norm(n, axis=1), 1e-9)
            A, B, C = A[up], B[up], C[up]
        if not len(A):
            continue
        lo = np.ceil(np.minimum(np.minimum(A, B), C)[:, :2] / step).astype(np.int64)
        hi = np.floor(np.maximum(np.maximum(A, B), C)[:, :2] / step).astype(np.int64)
        span = np.maximum(hi - lo + 1, 0)
        points, heights = [], []
        small = (span[:, 0] <= 4) & (span[:, 1] <= 4) & (span[:, 0] > 0) & (span[:, 1] > 0)
        for sel, size in ((small, 4), (~small & (span[:, 0] > 0) & (span[:, 1] > 0), None)):
            ks = np.nonzero(sel)[0]
            if size is None:                          # the few big triangles one by one
                for k in ks:
                    gx, gy = np.meshgrid(np.arange(lo[k, 0], hi[k, 0] + 1), np.arange(lo[k, 1], hi[k, 1] + 1))
                    _sample(A[k:k + 1], B[k:k + 1], C[k:k + 1], gx.ravel()[None], gy.ravel()[None], step,
                            points, heights)
                continue
            if not len(ks):
                continue
            ox, oy = np.meshgrid(np.arange(size), np.arange(size))
            gx = lo[ks, 0:1] + ox.ravel()[None]
            gy = lo[ks, 1:2] + oy.ravel()[None]
            _sample(A[ks], B[ks], C[ks], gx, gy, step, points, heights)
        if not points:
            continue
        g = np.concatenate(points)
        z = np.concatenate(heights)
        if not highest:
            ground = pack.surface_many(g[:, 0] * step + off[0], g[:, 1] * step + off[1], water=False)
            keep = z >= ground - 1.0
            g, z = g[keep], z[keep]
        order = np.lexsort((-z if highest else z, g[:, 1], g[:, 0]))
        g, z = g[order], z[order]
        first = np.ones(len(g), bool)
        first[1:] = (g[1:] != g[:-1]).any(axis=1)
        for (cx, cy), h in zip(map(tuple, g[first]), z[first]):
            if (cx, cy) not in best or (h > best[(cx, cy)] if highest else h < best[(cx, cy)]):
                best[(cx, cy)] = float(h)
    return best


def _sample(A, B, C, gx, gy, step, points, heights) -> None:
    """Grid points (gx, gy per triangle) inside triangles ABC (x, y in yards) and the triangles' heights there."""
    px, py = gx * step - A[:, 0:1], gy * step - A[:, 1:2]
    v0x, v0y = (B[:, 0] - A[:, 0])[:, None], (B[:, 1] - A[:, 1])[:, None]
    v1x, v1y = (C[:, 0] - A[:, 0])[:, None], (C[:, 1] - A[:, 1])[:, None]
    d = v0x * v1y - v0y * v1x
    ok = np.abs(d) > 1e-9
    d = np.where(ok, d, 1.0)
    u = (px * v1y - py * v1x) / d
    v = (v0x * py - v0y * px) / d
    inside = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
    if not inside.any():
        return
    z = A[:, 2:3] + u * (B[:, 2] - A[:, 2])[:, None] + v * (C[:, 2] - A[:, 2])[:, None]
    points.append(np.stack([gx[inside], gy[inside]], axis=1))
    heights.append(z[inside])
