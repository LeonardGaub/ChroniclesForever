"""A terrain tile's ground texture layers (its tex0 file), for ground.py. Without Qt, so that worker processes can
parse them: the alpha maps' run-length packing is unpacked byte by byte in Python, which in a thread held the
drawing thread up (the interpreter lock).

tex0: MDID (the tile's textures, fileDataIDs), then 256 MCNK chunks with MCLY (16-byte layers: texture index,
flags, offset into MCAL, effect) and MCAL (8-bit 64 x 64 alpha maps: these worlds use height texturing, which
implies the big alpha format; flag 0x200: run-length packed).
"""

from __future__ import annotations

import struct

import numpy as np

ALPHA_PX = 32                 # alpha map pixels a chunk in the tile's picture
USE_ALPHA, PACKED = 0x100, 0x200


def chunks(data: bytes):
    i = 0
    while i + 8 <= len(data):
        size = struct.unpack_from("<I", data, i + 4)[0]
        yield data[i:i + 4][::-1].decode("latin1"), data[i + 8:i + 8 + size]
        i += 8 + size


def unpack_alpha(data: bytes, at: int, packed: bool) -> np.ndarray:
    """One layer's 64 x 64 alpha map (0..255) at offset at of MCAL: plain, or run-length packed (a byte's top bit:
    repeat the next byte, else copy the next bytes; its low 7 bits: how many)."""
    if not packed:
        return np.frombuffer(data, np.uint8, 4096, at).reshape(64, 64)
    out = bytearray()
    i = at
    while len(out) < 4096 and i < len(data):
        head = data[i]
        n = head & 0x7F
        if head & 0x80:
            out += data[i + 1:i + 2] * n
            i += 2
        else:
            out += data[i + 1:i + 1 + n]
            i += 1 + n
    out = bytes(out[:4096]).ljust(4096, b"\0")
    return np.frombuffer(out, np.uint8).reshape(64, 64)


def parse_tex0(data: bytes):
    """A tile's texture list (fileDataIDs), per chunk its four layers' texture indices (-1: none) and the tile's
    alpha picture (512 x 512 x 3: layers 1-3)."""
    top = list(chunks(data))
    head = dict(top)
    mdid = list(struct.unpack_from(f"<{len(head.get('MDID', b'')) // 4}I", head.get("MDID", b"")))
    layers = np.full((16, 16, 4), -1, np.int64)
    alpha = np.zeros((16 * ALPHA_PX, 16 * ALPHA_PX, 3), np.uint8)
    step = 64 // ALPHA_PX
    for n, chunk in enumerate(p for t, p in top if t == "MCNK"):
        if n >= 256:
            break
        iy, ix = divmod(n, 16)
        sub = dict(chunks(chunk))
        mcly, mcal = sub.get("MCLY", b""), sub.get("MCAL", b"")
        for k in range(min(4, len(mcly) // 16)):
            tex, flags, offset, _effect = struct.unpack_from("<IIII", mcly, k * 16)
            layers[iy, ix, k] = tex if tex < len(mdid) else -1
            if k and flags & USE_ALPHA and offset < len(mcal):
                a = unpack_alpha(mcal, offset, bool(flags & PACKED))
                alpha[iy * ALPHA_PX:(iy + 1) * ALPHA_PX, ix * ALPHA_PX:(ix + 1) * ALPHA_PX, k - 1] = a[::step, ::step]
    return mdid, layers, alpha
