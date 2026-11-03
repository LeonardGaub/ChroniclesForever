"""The 3D map's readers of the game's texture formats: BLP2 (DXT1/5), the ground's alpha maps."""

import struct

import numpy as np

from forever_chronicle.ui.stage3d.tex0 import unpack_alpha
from forever_chronicle.ui.stage3d.textures import decode_blp, decode_mips


def blp(width, height, kind, levels):
    """A BLP2 file of DXT blocks (kind 0: DXT1, 7: DXT5), levels: the mip levels' block data."""
    head = b"BLP2" + struct.pack("<I", 1) + bytes([2, 8 if kind else 0, kind, 1]) + struct.pack("<II", width, height)
    offsets, sizes, at = [], [], 148 + 1024
    for data in levels:
        offsets.append(at)
        sizes.append(len(data))
        at += len(data)
    offsets += [0] * (16 - len(offsets))
    sizes += [0] * (16 - len(sizes))
    return head + struct.pack("<16I", *offsets) + struct.pack("<16I", *sizes) + bytes(1024) + b"".join(levels)


def dxt1_block(c0, c1, indices):
    bits = sum(i << (2 * k) for k, i in enumerate(indices))
    return struct.pack("<HHI", c0, c1, bits)


def test_dxt1_blocks_decode_to_their_colours():
    red, blue = 0xF800, 0x001F
    indices = [0, 1, 2, 3] * 4                       # each row: red, blue, 2/3 red, 1/3 red
    data = blp(4, 4, 0, [dxt1_block(red, blue, indices)])
    rgba = decode_blp(data)
    assert rgba.shape == (4, 4, 4)
    assert tuple(rgba[0, 0]) == (255, 0, 0, 255)
    assert tuple(rgba[0, 1]) == (0, 0, 255, 255)
    assert tuple(rgba[0, 2]) == (170, 0, 85, 255)
    # c0 <= c1: three colours and transparent
    rgba = decode_blp(blp(4, 4, 0, [dxt1_block(blue, red, [3] * 16)]))
    assert rgba[2, 2, 3] == 0


def test_dxt5_alpha_and_the_mip_level_chosen():
    colour = dxt1_block(0xFFFF, 0xFFFF, [0] * 16)
    alpha_bits = sum(1 << (3 * k) for k in range(16))        # every pixel index 1: alpha1
    block = bytes([200, 40]) + alpha_bits.to_bytes(6, "little") + colour
    big = block * 4                                          # 8 x 8: 2 x 2 blocks
    data = blp(8, 8, 7, [big, block])
    assert decode_blp(data, 8).shape == (8, 8, 4)
    small = decode_blp(data, 4)
    assert small.shape == (4, 4, 4) and (small[:, :, 3] == 40).all()
    levels = decode_mips(data, 4)
    assert [lv.shape[0] for lv in levels] == [4, 2, 1]


def test_alpha_maps_unpack_runs_and_copies():
    packed = bytes([0x80 | 100, 7]) + bytes([3, 1, 2, 3]) + bytes([0x80 | 127, 255]) * 40
    a = unpack_alpha(packed, 0, packed=True)
    flat = a.ravel()
    assert a.shape == (64, 64)
    assert (flat[:100] == 7).all() and list(flat[100:103]) == [1, 2, 3] and flat[103] == 255
    plain = bytes(range(256)) * 16
    assert (unpack_alpha(plain, 0, packed=False).ravel() == np.frombuffer(plain, np.uint8)).all()
