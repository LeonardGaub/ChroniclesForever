"""The ground's own textures on the 3D stage's full tiles: grass, rock, sand, as the game blends them.

Each terrain chunk (16 x 16 a tile) lays up to four of the tile's textures over one another through alpha maps
(the tile's tex0 file: MDID texture list, per chunk MCLY layers and MCAL alpha maps, 8-bit 64 x 64, plain or run-
length packed). All of it is read from the player's install at run time (textures.GameTextures' game files), by a
worker per tile:
- the alpha maps go into a 512 x 512 picture per tile (32 pixels a chunk; layers 1-3 in red, green, blue), the
  chunks' texture slots into a 16 x 16 one;
- the textures go into one texture array shared by all tiles (SLOTS layers of 256 x 256, least used reused).
A thread reads each tile's file, worker processes parse it (tex0.py; in a thread its pure-Python unpacking held
the drawing thread up).
The ground shader (terrain.py GROUND_FS) blends them close to the camera and fades to the minimap pictures further
out, where they would only shimmer. Until a tile's splat is ready (or without the game) the minimap shows.
"""

from __future__ import annotations

import struct
from collections import OrderedDict
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLTexture

from .tex0 import chunks as _chunks
from .tex0 import parse_tex0
from .textures import decode, decode_mips

SLOTS = 128                   # texture array layers
LAYER_PX = 256
NONE = 255                    # no layer / its texture not there yet
PARSERS = 2                   # worker processes parsing tiles (tex0.py)


def _texture(width: int, height: int, data: bytes, nearest: bool) -> QOpenGLTexture:
    image = QImage(data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
    tex = QOpenGLTexture(image, QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
    f = QOpenGLTexture.Filter.Nearest if nearest else QOpenGLTexture.Filter.Linear
    tex.setMinMagFilters(f, f)
    tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
    return tex


class _Splat:
    def __init__(self, mdid, layers, alpha):
        self.mdid, self.layers = mdid, layers
        rgba = np.concatenate([alpha, np.full(alpha.shape[:2] + (1,), 255, np.uint8)], axis=2)
        self.alpha = _texture(rgba.shape[1], rgba.shape[0], rgba.tobytes(), nearest=False)
        self.index: QOpenGLTexture | None = None
        self.slots_seen = None              # the slot assignment the index was made with

    def destroy(self) -> None:
        self.alpha.destroy()
        if self.index is not None:
            self.index.destroy()


class GroundSplat:
    def __init__(self, textures):
        """textures: textures.GameTextures (its game files)."""
        self.textures = textures
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ground")
        self.parsers: ProcessPoolExecutor | None | bool = None    # False: they broke, the thread parses
        self.parsing: dict[tuple, Future] = {}
        self.array: QOpenGLTexture | None = None
        self.slots: OrderedDict[int, int] = OrderedDict()     # texture fileDataID -> array layer (LRU)
        self.ready: set[int] = set()                          # those uploaded
        self.decoding: dict[int, Future] = {}
        self.tiles: dict[tuple, _Splat] = {}
        self.loading: dict[tuple, Future] = {}
        self.wdts: dict[int, np.ndarray] = {}                 # world -> its tiles' tex0 fileDataIDs (64 x 64)

    def initialize(self) -> None:
        t = QOpenGLTexture(QOpenGLTexture.Target.Target2DArray)
        t.setSize(LAYER_PX, LAYER_PX)
        t.setLayers(SLOTS)
        t.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
        t.setMipLevels(t.maximumMipLevels())
        t.allocateStorage()
        t.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
        t.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
        t.setMaximumAnisotropy(8.0)
        self.array = t

    # -- reading (worker) ------------------------------------------------------------------------------------

    def _tex0_ids(self, storage, wdt: int) -> np.ndarray:
        maid = dict(_chunks(storage.read_fdid(wdt)))["MAID"]
        return np.frombuffer(maid, "<u4").reshape(64, 64, 8)[:, :, 3]

    def _load(self, world: int, wdt: int, tx: int, ty: int) -> bytes | None:
        """The tile's tex0 file (read in the thread, parsed in a worker process)."""
        storage = self.textures.storage.result()
        if world not in self.wdts:
            self.wdts[world] = self._tex0_ids(storage, wdt)
        fdid = int(self.wdts[world][ty, tx])
        return storage.read_fdid(fdid) if fdid else None

    @staticmethod
    def _decode_layer(storage, fdid: int):
        """The texture's mip levels as bytes, LAYER_PX down to 1 (the file's own levels; else scaled and halved)."""
        try:
            levels = decode_mips(storage.read_fdid(fdid), LAYER_PX)
        except Exception:
            levels = None
        if levels is not None:
            return [level.tobytes() for level in levels]
        image = decode(storage, fdid)
        if image is None:
            return None
        if image.width() != LAYER_PX or image.height() != LAYER_PX:
            from PySide6.QtCore import Qt
            image = image.scaled(LAYER_PX, LAYER_PX, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        level = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes()).reshape(LAYER_PX, LAYER_PX, 4)
        levels = [level]
        while levels[-1].shape[0] > 1:
            prev = levels[-1].astype(np.uint16)
            levels.append(((prev[0::2, 0::2] + prev[1::2, 0::2] + prev[0::2, 1::2] + prev[1::2, 1::2]) // 4)
                          .astype(np.uint8))
        return [np.ascontiguousarray(level).tobytes() for level in levels]

    # -- the GUI thread ---------------------------------------------------------------------------------------

    def want(self, key: tuple, world: int, wdt: int | None) -> None:
        """Asks for a full tile's splat (key: (world, tx, ty))."""
        if (wdt and self.textures.available and key not in self.tiles and key not in self.loading
                and key not in self.parsing):
            self.loading[key] = self.pool.submit(self._load, world, wdt, key[1], key[2])

    def drop(self, key: tuple) -> None:
        splat = self.tiles.pop(key, None)
        if splat is not None:
            splat.destroy()
        for pending in (self.loading, self.parsing):
            future = pending.pop(key, None)
            if future is not None:
                future.cancel()

    def _slot(self, fdid: int) -> int:
        if fdid in self.slots:
            self.slots.move_to_end(fdid)
            return self.slots[fdid]
        if len(self.slots) < SLOTS:
            slot = len(self.slots)
        else:
            old, slot = self.slots.popitem(last=False)
            self.ready.discard(old)
        self.slots[fdid] = slot
        storage = self.textures.storage.result()
        self.decoding[fdid] = self.pool.submit(self._decode_layer, storage, fdid)
        return slot

    def _parse(self, data: bytes) -> Future:
        """Parses a tile's tex0 in a worker process; in the thread if processes cannot start or broke (slower: the
        drawing then waits for it at times)."""
        if self.parsers is not False:
            try:
                if self.parsers is None:
                    self.parsers = ProcessPoolExecutor(max_workers=PARSERS)
                return self.parsers.submit(parse_tex0, data)
            except Exception:
                self.parsers = False
        return self.pool.submit(parse_tex0, data)

    def pump(self) -> None:
        """Takes in what the worker has read: tiles' splats, decoded textures (GL context current)."""
        for key in [k for k, f in self.loading.items() if f.done()]:
            future = self.loading.pop(key)
            try:
                data = future.result()
            except Exception:
                data = None
            if data is not None:
                self.parsing[key] = self._parse(data)
        for key in [k for k, f in self.parsing.items() if f.done()][:2]:
            future = self.parsing.pop(key)
            try:
                found = future.result()
            except Exception:              # a worker process died: the others go to the thread from now on
                found = None
                self.parsers = False
            if found is not None:
                self.tiles[key] = _Splat(*found)
        for fdid in [f for f, fut in self.decoding.items() if fut.done()][:4]:
            levels = self.decoding.pop(fdid).result()
            if levels is not None and fdid in self.slots:
                for mip, data in enumerate(levels[:self.array.mipLevels()]):
                    self.array.setData(mip, self.slots[fdid], QOpenGLTexture.PixelFormat.RGBA,
                                       QOpenGLTexture.PixelType.UInt8, data)
                self.ready.add(fdid)

    def bind(self, key: tuple, alpha_unit: int, index_unit: int) -> bool:
        """Binds a tile's alpha picture and slot index (made again when its textures' slots changed); False when the
        tile has no splat yet."""
        splat = self.tiles.get(key)
        if splat is None:
            return False
        slots = [self._slot(f) if f else NONE for f in splat.mdid]
        seen = tuple((s if f in self.ready else NONE) for f, s in zip(splat.mdid, slots))
        if seen != splat.slots_seen:
            index = np.full((16, 16, 4), NONE, np.uint8)
            for k in range(4):
                tex = splat.layers[:, :, k]
                ok = tex >= 0
                index[:, :, k][ok] = np.array(seen, np.uint8)[tex[ok]] if len(seen) else NONE
            if splat.index is not None:
                splat.index.destroy()
            splat.index = _texture(16, 16, index.tobytes(), nearest=True)
            splat.slots_seen = seen
        splat.alpha.bind(alpha_unit)
        splat.index.bind(index_unit)
        return True

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.parsers:
            self.parsers.shutdown(wait=False, cancel_futures=True)
        for splat in self.tiles.values():
            splat.destroy()
        self.tiles.clear()
        if self.array is not None:
            self.array.destroy()
