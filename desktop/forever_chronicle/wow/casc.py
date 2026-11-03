"""Read-only access to the local WoW game files (CASC storage), enough to take files out by fileDataID.

Used by wow/game_icons.py, game_fonts.py, game_sounds.py, zone_music.py and the extract tools. Reads only the user's own install: the build
config of one product (.build.info), the local index files, the data archives, the encoding file and the root file.
Nothing is written into the game folder.

Format notes (wowdev.wiki "CASC", "TACT", "BLTE"):
- Data/data/<bucket><version>.idx: 18-byte entries (9-byte EKey prefix, 5-byte archive/offset, 4-byte size).
- data.NNN: a 30-byte header, then the BLTE-encoded file.
- encoding: content key (CKey, from root) -> encoding key (EKey, in the index).
- root (MFST): fileDataID -> CKey, with locale and content flags per block, optional name hashes.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

try:
    import numpy as np
except ImportError:  # optional for the app (open_client gives None); the extract tools need it
    np = None

ENUS = 0x2
ALL_LOCALES = 0xFFFFFFFF
NO_NAME_HASH = 0x10000000


class CascError(Exception):
    pass


class EncryptedError(CascError):
    pass


def read_build_info(install: Path) -> list[dict[str, str]]:
    lines = (install / ".build.info").read_text(encoding="utf-8").splitlines()
    names = [h.split("!")[0] for h in lines[0].split("|")]
    return [dict(zip(names, line.split("|"))) for line in lines[1:] if line.strip()]


def read_config(path: Path) -> dict[str, list[str]]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if " = " in line and not line.startswith("#"):
            key, value = line.split(" = ", 1)
            result[key.strip()] = value.split()
    return result


def blte_decode(data: bytes, zero_encrypted: bool = False) -> bytes:
    """Decodes BLTE data. Encrypted chunks raise EncryptedError, or with zero_encrypted come back as zero bytes of
    their size (client tables keep unreleased rows in encrypted sections; the readable rest is still usable)."""
    if data[:4] != b"BLTE":
        raise CascError("not BLTE data")
    header_size = struct.unpack(">I", data[4:8])[0]
    if header_size == 0:
        chunks = [(len(data) - 8, None)]
        pos = 8
    else:
        count = struct.unpack(">I", b"\0" + data[9:12])[0]
        info_size = 40 if data[8] == 0x10 else 24
        chunks = []
        for i in range(count):
            comp, decomp = struct.unpack(">II", data[12 + i * info_size:20 + i * info_size])
            chunks.append((comp, decomp))
        pos = header_size
    out = []
    for comp, decomp in chunks:
        chunk = data[pos:pos + comp]
        pos += comp
        mode = chunk[:1]
        if mode == b"N":
            out.append(chunk[1:])
        elif mode == b"Z":
            out.append(zlib.decompress(chunk[1:]))
        elif mode == b"F":
            out.append(blte_decode(chunk[1:]))
        elif mode == b"E":
            if not (zero_encrypted and decomp):
                raise EncryptedError("encrypted chunk")
            out.append(b"\0" * decomp)
        else:
            raise CascError(f"unknown BLTE chunk mode {mode!r}")
    return b"".join(out)


def jenkins_path_hash(path: str) -> int:
    """Root name hash: Bob Jenkins' hashlittle2 of the upper-case path with backslashes."""
    return hashlittle2(path.upper().replace("/", "\\").encode("ascii"))


def hashlittle2(data: bytes) -> int:
    """(c << 32) | b of hashlittle2 with zero seeds."""
    mask = 0xFFFFFFFF

    def rot(x, k):
        return ((x << k) | (x >> (32 - k))) & mask

    length = len(data)
    a = b = c = (0xDEADBEEF + length) & mask
    i = 0
    while length > 12:
        a = (a + struct.unpack_from("<I", data, i)[0]) & mask
        b = (b + struct.unpack_from("<I", data, i + 4)[0]) & mask
        c = (c + struct.unpack_from("<I", data, i + 8)[0]) & mask
        a = (a - c) & mask; a ^= rot(c, 4); c = (c + b) & mask
        b = (b - a) & mask; b ^= rot(a, 6); a = (a + c) & mask
        c = (c - b) & mask; c ^= rot(b, 8); b = (b + a) & mask
        a = (a - c) & mask; a ^= rot(c, 16); c = (c + b) & mask
        b = (b - a) & mask; b ^= rot(a, 19); a = (a + c) & mask
        c = (c - b) & mask; c ^= rot(b, 4); b = (b + a) & mask
        i += 12
        length -= 12
    if length == 0:
        return (c << 32) | b
    tail = data[i:] + b"\0" * (12 - length)
    a = (a + struct.unpack_from("<I", tail, 0)[0]) & mask
    b = (b + struct.unpack_from("<I", tail, 4)[0]) & mask
    c = (c + struct.unpack_from("<I", tail, 8)[0]) & mask
    c ^= b; c = (c - rot(b, 14)) & mask
    a ^= c; a = (a - rot(c, 11)) & mask
    b ^= a; b = (b - rot(a, 25)) & mask
    c ^= b; c = (c - rot(b, 16)) & mask
    a ^= c; a = (a - rot(c, 4)) & mask
    b ^= a; b = (b - rot(a, 14)) & mask
    c ^= b; c = (c - rot(b, 24)) & mask
    return (c << 32) | b


class LocalStorage:
    """The local index and data archives (shared by all products in the install)."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        newest: dict[int, Path] = {}
        for p in data_dir.glob("*.idx"):
            bucket = int(p.name[:2], 16)
            if bucket not in newest or p.name > newest[bucket].name:
                newest[bucket] = p
        self.index: dict[bytes, tuple[int, int, int]] = {}
        for p in newest.values():
            raw = p.read_bytes()
            size = struct.unpack_from("<I", raw, 0x20)[0]
            entries = raw[0x28:0x28 + size]
            for i in range(0, len(entries) - 17, 18):
                key = entries[i:i + 9]
                if key in self.index:
                    continue
                loc = int.from_bytes(entries[i + 9:i + 14], "big")
                length = struct.unpack_from("<I", entries, i + 14)[0]
                self.index[key] = (loc >> 30, loc & 0x3FFFFFFF, length)
        self._archives: dict[int, object] = {}

    def has(self, ekey: bytes) -> bool:
        return ekey[:9] in self.index

    def read(self, ekey: bytes, zero_encrypted: bool = False) -> bytes:
        entry = self.index.get(ekey[:9])
        if entry is None:
            raise CascError(f"{ekey.hex()} is not in the local storage")
        archive, offset, length = entry
        f = self._archives.get(archive)
        if f is None:
            f = open(self.data_dir / f"data.{archive:03d}", "rb")
            self._archives[archive] = f
        f.seek(offset)
        raw = f.read(length)
        return blte_decode(raw[30:], zero_encrypted)


class Encoding:
    def __init__(self, data: bytes):
        if data[:2] != b"EN":
            raise CascError("bad encoding file")
        _, ckey_size, ekey_size, page_kb, _, page_count, _, _, espec_size = struct.unpack_from(
            ">BBBHHIIBI", data, 2)
        pos = 22 + espec_size
        self.first_keys = [data[pos + i * 32:pos + i * 32 + ckey_size] for i in range(page_count)]
        self.pages_at = pos + page_count * 32
        self.page_size = page_kb * 1024
        self.data = data
        self.ckey_size, self.ekey_size = ckey_size, ekey_size

    def ekey(self, ckey: bytes) -> bytes | None:
        import bisect
        page = bisect.bisect_right(self.first_keys, ckey) - 1
        if page < 0:
            return None
        pos = self.pages_at + page * self.page_size
        end = pos + self.page_size
        d = self.data
        while pos < end:
            count = d[pos]
            if count == 0:
                break
            key = d[pos + 6:pos + 6 + self.ckey_size]
            if key == ckey:
                at = pos + 6 + self.ckey_size
                return d[at:at + self.ekey_size]
            pos += 6 + self.ckey_size + count * self.ekey_size
        return None


class Root:
    """fileDataID -> CKey (enUS or all locales), and name hash -> fileDataID."""

    def __init__(self, data: bytes):
        if data[:4] != b"TSFM":
            raise CascError("unsupported root format (expected MFST)")
        a, b = struct.unpack_from("<II", data, 4)
        if a in (0x14, 0x18) and b in (1, 2):
            header_size, version = a, b
            total, named = struct.unpack_from("<II", data, 12)
            pos = header_size
        else:
            version, total, named = 1, a, b
            pos = 12
        ids, ckeys, hashes, hash_ids = [], [], [], []
        while pos < len(data):
            count = struct.unpack_from("<I", data, pos)[0]
            if version == 2:
                locale, u1, u2, u3 = struct.unpack_from("<IIIB", data, pos + 4)
                content = u1 | u2 | (u3 << 17)
                pos += 17
            else:
                content, locale = struct.unpack_from("<II", data, pos + 4)
                pos += 12
            deltas = np.frombuffer(data, "<i4", count, pos)
            pos += 4 * count
            fdids = np.cumsum(deltas.astype(np.int64) + 1) - 1
            keys = np.frombuffer(data, "u1", 16 * count, pos).reshape(count, 16)
            pos += 16 * count
            has_names = not (content & NO_NAME_HASH)
            if has_names:
                h = np.frombuffer(data, "<u8", count, pos)
                pos += 8 * count
            if locale & ENUS or locale == ALL_LOCALES:
                ids.append(fdids)
                ckeys.append(keys)
                if has_names:
                    hashes.append(h)
                    hash_ids.append(fdids)
        all_ids = np.concatenate(ids)
        order = np.argsort(all_ids, kind="stable")
        self.ids = all_ids[order]
        self.ckeys = np.concatenate(ckeys)[order]
        h = np.concatenate(hashes) if hashes else np.zeros(0, "<u8")
        hid = np.concatenate(hash_ids) if hash_ids else np.zeros(0, np.int64)
        horder = np.argsort(h)
        self.hashes, self.hash_ids = h[horder], hid[horder]

    def ckey(self, fdid: int) -> bytes | None:
        i = np.searchsorted(self.ids, fdid)
        if i < len(self.ids) and self.ids[i] == fdid:
            return bytes(self.ckeys[i])
        return None

    def ckeys_of(self, fdid: int) -> list[bytes]:
        """All the file's content keys: a file can be listed in several blocks (content flags: variants), of which
        an install may hold only one (found on 2026-11-03: building and ground textures have two, the first
        listed one not installed)."""
        i = int(np.searchsorted(self.ids, fdid, side="left"))
        j = int(np.searchsorted(self.ids, fdid, side="right"))
        return list(dict.fromkeys(bytes(k) for k in self.ckeys[i:j]))

    def fdid_by_name(self, path: str) -> int | None:
        h = np.uint64(jenkins_path_hash(path))
        i = np.searchsorted(self.hashes, h)
        if i < len(self.hashes) and self.hashes[i] == h:
            return int(self.hash_ids[i])
        return None


class Casc:
    def __init__(self, install: Path, product: str):
        if np is None:
            raise CascError("numpy is not installed")
        builds = [b for b in read_build_info(install) if b.get("Product") == product]
        if not builds:
            raise CascError(f"product {product} is not installed")
        self.build = builds[0]
        key = self.build["Build Key"]
        config = read_config(install / "Data" / "config" / key[:2] / key[2:4] / key)
        self.build_name = config.get("build-name", ["?"])[0]
        self.storage = LocalStorage(install / "Data" / "data")
        self.encoding = Encoding(self.storage.read(bytes.fromhex(config["encoding"][1])))
        root_ekey = self.encoding.ekey(bytes.fromhex(config["root"][0]))
        if root_ekey is None:
            raise CascError("root not found in encoding")
        self.root = Root(self.storage.read(root_ekey))

    def read_fdid(self, fdid: int, zero_encrypted: bool = False) -> bytes:
        """The file's content, from whichever of its variants (root blocks) this install holds."""
        ckeys = self.root.ckeys_of(fdid)
        if not ckeys:
            raise CascError(f"fileDataID {fdid} is not in the root")
        ekeys = [e for e in (self.encoding.ekey(k) for k in ckeys) if e is not None]
        if not ekeys:
            raise CascError(f"fileDataID {fdid} has no encoding entry")
        local = next((e for e in ekeys if self.storage.has(e)), ekeys[0])
        return self.storage.read(local, zero_encrypted)

    def read_name(self, path: str) -> bytes:
        fdid = self.root.fdid_by_name(path)
        if fdid is None:
            raise CascError(f"{path} is not in the root")
        return self.read_fdid(fdid)


def open_client(client) -> Casc | None:
    """The game files of a found client (wow/paths.ClientInstall); None without numpy or when they cannot be read."""
    try:
        return Casc(client.path.parent, client.flavor)
    except Exception:
        return None


def write_atomic(path: Path, data: bytes) -> None:
    """Writes a file taken out of the game under a temporary name first, so nothing ever reads half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)
