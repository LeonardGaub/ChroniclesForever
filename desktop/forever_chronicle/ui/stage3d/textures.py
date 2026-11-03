"""The game's own textures for the 3D stage, read from the player's install while the replay runs (never in git):
building walls and roofs, and the ground's texture layers.

The game files are opened in the background (wow/casc.py: ~1-2 s); each texture is read by a worker thread and
decoded from its stored mip level that is at most MAX_PX wide (decode_blp: numpy; Pillow's BLP decoder works in
pure Python and held the drawing thread up), uploaded a few a frame and kept while drawn (LRU, KEEP).
Until a texture is there (or without the game, or without Pillow) the callers draw their fallback: the minimap's
colours.
"""

from __future__ import annotations

import io
import struct
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLTexture

MAX_PX = 256
UPLOADS_PER_FRAME = 6
KEEP = 420                       # textures kept on the graphics card


def _rgb565(c: np.ndarray) -> np.ndarray:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return np.stack([r * 255 // 31, g * 255 // 63, b * 255 // 31], axis=-1).astype(np.int32)


def _dxt_colors(blocks: np.ndarray, four: bool) -> np.ndarray:
    """RGBA of 4 x 4 pixel colour blocks (8 bytes each: two 565 colours, 2-bit indices); four: always the four
    colour mode (DXT3/5), else DXT1's rule (c0 <= c1: three colours and transparent)."""
    c0 = blocks[:, 0].astype(np.int32) | (blocks[:, 1].astype(np.int32) << 8)
    c1 = blocks[:, 2].astype(np.int32) | (blocks[:, 3].astype(np.int32) << 8)
    a, b = _rgb565(c0), _rgb565(c1)
    opaque = np.ones(len(blocks), bool) if four else c0 > c1
    pal = np.zeros((len(blocks), 4, 4), np.int32)
    pal[:, 0, :3], pal[:, 1, :3] = a, b
    pal[:, 2, :3] = np.where(opaque[:, None], (2 * a + b) // 3, (a + b) // 2)
    pal[:, 3, :3] = np.where(opaque[:, None], (a + 2 * b) // 3, 0)
    pal[:, :, 3] = 255
    pal[:, 3, 3] = np.where(opaque, 255, 0)
    bits = (blocks[:, 4].astype(np.uint32) | (blocks[:, 5].astype(np.uint32) << 8)
            | (blocks[:, 6].astype(np.uint32) << 16) | (blocks[:, 7].astype(np.uint32) << 24))
    sel = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))[None]) & 3
    return np.take_along_axis(pal, sel[:, :, None].astype(np.int64).repeat(4, axis=2), axis=1)   # (n, 16, 4)


def _dxt(data: bytes, w: int, h: int, kind: int) -> np.ndarray:
    """A DXT1 (kind 0), DXT3 (1) or DXT5 (7) image as h x w x 4."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    size = 8 if kind == 0 else 16
    raw = np.frombuffer(data, np.uint8, bw * bh * size).reshape(-1, size)
    if kind == 0:
        px = _dxt_colors(raw, four=False)
    else:
        px = _dxt_colors(raw[:, 8:], four=True)
        if kind == 1:
            nib = np.stack([raw[:, :8] & 15, raw[:, :8] >> 4], axis=-1).reshape(-1, 16).astype(np.int32)
            px[:, :, 3] = nib * 17
        else:
            a0, a1 = raw[:, 0].astype(np.int32), raw[:, 1].astype(np.int32)
            k = np.arange(8)
            eight = np.where(k[None] == 0, a0[:, None], np.where(k[None] == 1, a1[:, None],
                                                                 ((8 - k[None]) * a0[:, None] + (k[None] - 1) * a1[:, None]) // 7))
            six = np.where(k[None] == 0, a0[:, None], np.where(k[None] == 1, a1[:, None],
                           np.where(k[None] == 6, 0, np.where(k[None] == 7, 255,
                                    ((6 - k[None]) * a0[:, None] + (k[None] - 1) * a1[:, None]) // 5))))
            table = np.where((a0 > a1)[:, None], eight, six)
            bits = np.zeros(len(raw), np.uint64)
            for i in range(6):
                bits |= raw[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
            sel = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))[None]) & np.uint64(7)).astype(np.int64)
            px[:, :, 3] = np.take_along_axis(table, sel, axis=1)
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w].astype(np.uint8)


def decode_blp(data: bytes, max_px: int = MAX_PX) -> np.ndarray | None:
    """A BLP2 texture as h x w x 4 (RGBA) from its largest stored mip level at most max_px wide; None for another
    format."""
    if data[:4] != b"BLP2":
        return None
    encoding, alpha_depth, alpha_kind, mips = data[8], data[9], data[10], data[11]
    w, h = struct.unpack_from("<II", data, 12)
    offsets = struct.unpack_from("<16I", data, 20)
    sizes = struct.unpack_from("<16I", data, 84)
    level = 0
    while mips and level < 15 and max(w >> level, h >> level) > max_px and sizes[level + 1]:
        level += 1
    lw, lh = max(1, w >> level), max(1, h >> level)
    chunk = data[offsets[level]:offsets[level] + sizes[level]]
    if encoding == 2:
        return _dxt(chunk, lw, lh, alpha_kind)
    if encoding == 3:
        bgra = np.frombuffer(chunk, np.uint8, lw * lh * 4).reshape(lh, lw, 4)
        return bgra[:, :, [2, 1, 0, 3]].copy()
    if encoding == 1:
        palette = np.frombuffer(data, np.uint8, 1024, 148).reshape(256, 4)[:, [2, 1, 0, 3]].copy()
        index = np.frombuffer(chunk, np.uint8, lw * lh)
        rgba = palette[index].reshape(lh, lw, 4)
        alpha = chunk[lw * lh:]
        if alpha_depth == 8:
            rgba[:, :, 3] = np.frombuffer(alpha, np.uint8, lw * lh).reshape(lh, lw)
        elif alpha_depth == 4:
            a = np.frombuffer(alpha, np.uint8, (lw * lh + 1) // 2)
            rgba[:, :, 3] = (np.stack([a & 15, a >> 4], -1).ravel()[:lw * lh] * 17).reshape(lh, lw)
        elif alpha_depth == 1:
            a = np.unpackbits(np.frombuffer(alpha, np.uint8, (lw * lh + 7) // 8), bitorder="little")
            rgba[:, :, 3] = (a[:lw * lh] * 255).reshape(lh, lw)
        else:
            rgba[:, :, 3] = 255
        return rgba
    return None


def decode(storage, fdid: int) -> QImage | None:
    """A texture file as an RGBA picture at most MAX_PX wide, None when it cannot be read."""
    try:
        data = storage.read_fdid(fdid)
    except Exception:
        return None
    try:
        rgba = decode_blp(data)
    except Exception:
        rgba = None
    if rgba is not None:
        h, w = rgba.shape[:2]
        return QImage(rgba.tobytes(), w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    if max(image.size) > MAX_PX:
        k = MAX_PX / max(image.size)
        image = image.resize((max(1, round(image.width * k)), max(1, round(image.height * k))), Image.LANCZOS)
    data = image.tobytes()
    return QImage(data, image.width, image.height, 4 * image.width, QImage.Format.Format_RGBA8888).copy()


def gl_texture(image: QImage) -> QOpenGLTexture:
    tex = QOpenGLTexture(image, QOpenGLTexture.MipMapGeneration.GenerateMipMaps)
    tex.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
    tex.setMaximumAnisotropy(8.0)
    tex.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
    return tex


class GameTextures:
    def __init__(self, opener):
        """opener: () -> the game files (casc.Casc) or None; called once, in the background."""
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="textures")
        self.storage: Future = self.pool.submit(opener)
        self.loaded: OrderedDict[int, QOpenGLTexture] = OrderedDict()
        self.loading: dict[int, Future] = {}
        self.failed: set[int] = set()

    @property
    def available(self) -> bool:
        return self.storage.done() and self.storage.exception() is None and self.storage.result() is not None

    def get(self, fdid: int) -> QOpenGLTexture | None:
        """The texture if it is there (else asks for it and returns None: draw the fallback meanwhile)."""
        tex = self.loaded.get(fdid)
        if tex is not None:
            self.loaded.move_to_end(fdid)
            return tex
        if fdid and fdid not in self.loading and fdid not in self.failed and self.available:
            self.loading[fdid] = self.pool.submit(decode, self.storage.result(), fdid)
        return None

    def pump(self) -> None:
        """Uploads what the workers have decoded (GL context current); drops the least used beyond KEEP."""
        uploads = 0
        for fdid in [f for f, fut in self.loading.items() if fut.done()]:
            if uploads >= UPLOADS_PER_FRAME:
                break
            image = self.loading.pop(fdid).result()
            if image is None:
                self.failed.add(fdid)
                continue
            self.loaded[fdid] = gl_texture(image)
            uploads += 1
        while len(self.loaded) > KEEP:
            _, tex = self.loaded.popitem(last=False)
            tex.destroy()

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        for tex in self.loaded.values():
            tex.destroy()
        self.loaded.clear()
