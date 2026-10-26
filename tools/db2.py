"""Minimal reader for WDC5 client database files (DB2), numbers only (strings are not needed by the tools).

Format: wowdev.wiki "DB2" (WDC3 layout with a version number and a 128-byte schema string in front).
Each row comes back as {"id": int, "fields": [value or list of values per field], "parent": int | None};
"parent" is the foreign key stored in the relationship map (e.g. UiMapArtTile -> UiMapArt).
Sections encrypted with a TACT key (unreleased rows) are left out: read such files with
casc.read_fdid(..., zero_encrypted=True), which fills their chunks with zeros (table() does).

Also the tools' shared way into the game files: find_install / open_install (the install given with --install, else
found as the desktop app finds it, wow/paths.py) and the file IDs of the tables the tools read. A tool puts
desktop/ and tools/ on sys.path before importing this (also under python -I).
"""

from __future__ import annotations

import struct
from pathlib import Path

from forever_chronicle.wow import casc, paths

NONE, BITPACKED, COMMON, PALLET, PALLET_ARRAY, BITPACKED_SIGNED = range(6)

# The tables the tools read, by fileDataID (unnamed in the root file; identified by their contents), and the
# fields they use.
AREA_TABLE = 1353545              # ZoneName, AreaName, ContinentID, ParentAreaID, AreaBit, ..., [9] ZoneMusic, ...
ZONE_MUSIC = 1310254              # SetName, SilenceIntervalMin[2], SilenceIntervalMax[2], Sounds[2] (day, night)
SOUND_AMBIENCE = 1310628          # Flags, SoundFilterID, FlavorSoundFilterID, AmbienceID[2] (day, night SoundKit), ...
SOUND_KIT_ENTRY = 1237435         # SoundKitID, FileDataID, Frequency, Volume, ...
UI_MAP_ASSIGNMENT = 1957219       # UiMin[2], UiMax[2], Region[6], ID, UiMapID, OrderIndex, MapID, AreaID, ...
UI_MAP_ART = 1957202              # ID, ..., UiMapArtStyleID
UI_MAP_ART_STYLE_LAYER = 1957208  # LayerIndex, LayerWidth, LayerHeight, TileWidth, TileHeight, ...; parent style
UI_MAP_ART_TILE = 1957210         # RowIndex, ColIndex, LayerIndex, FileDataID; parent UiMapArt
UI_MAP_X_MAP_ART = 1957217        # PhaseID, UiMapArtID; parent UiMap
WORLD_MAP_OVERLAY = 1134579       # ID, UiMapArtID, TextureWidth, TextureHeight, OffsetX, OffsetY, ...
WORLD_MAP_OVERLAY_TILE = 1957212  # RowIndex, ColIndex, LayerIndex, FileDataID; parent WorldMapOverlay


def find_install(install: Path | None = None) -> Path:
    """The World of Warcraft folder (the one holding .build.info): the given one, else the folder of the first
    Forever client found (live before beta)."""
    if install:
        return install
    clients = paths.find_forever_installs()
    if not clients:
        raise casc.CascError("WoW Forever not found: give the World of Warcraft folder with --install")
    return clients[0].path.parent


def open_install(install: Path | None = None) -> casc.Casc:
    """The game files of the Forever client in the World of Warcraft folder (find_install)."""
    root = find_install(install)
    return casc.Casc(root, paths.forever_product(root))


def table(storage: casc.Casc, fdid: int) -> list[dict]:
    """The rows of the table with this file ID (encrypted sections left out)."""
    return read_db2(storage.read_fdid(fdid, zero_encrypted=True))


class Db2Error(Exception):
    pass


def read_db2(data: bytes) -> list[dict]:
    if data[:4] != b"WDC5":
        raise Db2Error(f"unsupported DB2 format {data[:4]!r}")
    pos = 8 + 128
    (record_count, field_count, record_size, string_size, table_hash, layout_hash, min_id, max_id, locale,
     flags, id_index, total_fields, bitpacked_offset, lookup_count, storage_info_size, common_size,
     pallet_size, section_count) = struct.unpack_from("<9IHH7I", data, pos)
    pos += 68
    sections = []
    for _ in range(section_count):
        sections.append(struct.unpack_from("<Q8I", data, pos))
        pos += 40
    pos += 4 * field_count  # field structure (size, offset): the storage info below has the same and more
    infos = []
    for _ in range(storage_info_size // 24):
        infos.append(struct.unpack_from("<HHIIIII", data, pos))
        pos += 24
    pallets, commons = [], []
    p = pos
    for info in infos:
        n = info[2] if info[3] in (PALLET, PALLET_ARRAY) else 0
        pallets.append(struct.unpack_from(f"<{n // 4}I", data, p))
        p += n
    pos += pallet_size
    p = pos
    for info in infos:
        n = info[2] if info[3] == COMMON else 0
        values = struct.unpack_from(f"<{n // 4}I", data, p)
        commons.append(dict(zip(values[0::2], values[1::2])))
        p += n
    if flags & 1:
        raise Db2Error("offset-map DB2 files are not supported")

    rows = []
    for (key_hash, offset, count, strings, _end, id_list_size, rel_size, offset_map_count,
         copy_count) in sections:
        if count == 0 or key_hash != 0:
            continue
        records_at = offset
        p = offset + count * record_size + strings
        ids = list(struct.unpack_from(f"<{id_list_size // 4}I", data, p)) if id_list_size else None
        p += id_list_size
        copies = [struct.unpack_from("<II", data, p + 8 * i) for i in range(copy_count)]
        p += 8 * copy_count + 6 * offset_map_count
        parents = {}
        if rel_size:
            n = struct.unpack_from("<I", data, p)[0]
            for i in range(n):
                foreign, index = struct.unpack_from("<II", data, p + 12 + 8 * i)
                parents[index] = foreign
        section_rows = []
        for i in range(count):
            rec = data[records_at + i * record_size:records_at + (i + 1) * record_size]
            bits = int.from_bytes(rec + b"\0" * 8, "little")
            values = []
            for f, (off_bits, size_bits, _add, kind, v1, v2, v3) in enumerate(infos):
                if kind == NONE:
                    width = size_bits // 8
                    raw = rec[off_bits // 8:off_bits // 8 + width]
                    n = max(1, width // 4)
                    vals = list(struct.unpack_from(f"<{n}I", raw.ljust(4 * n, b"\0")))
                    values.append(vals[0] if n == 1 else vals)
                elif kind in (BITPACKED, BITPACKED_SIGNED):
                    v = (bits >> off_bits) & ((1 << size_bits) - 1)
                    if kind == BITPACKED_SIGNED and v >> (size_bits - 1):
                        v -= 1 << size_bits
                    values.append(v)
                elif kind == COMMON:
                    values.append(None)  # filled once the id is known
                elif kind == PALLET:
                    values.append(pallets[f][(bits >> off_bits) & ((1 << size_bits) - 1)])
                elif kind == PALLET_ARRAY:
                    index = (bits >> off_bits) & ((1 << size_bits) - 1)
                    values.append(list(pallets[f][index * v3:(index + 1) * v3]))
                else:
                    raise Db2Error(f"unknown storage type {kind}")
            row_id = ids[i] if ids else values[id_index]
            for f, info in enumerate(infos):
                if info[3] == COMMON:
                    values[f] = commons[f].get(row_id, info[4])
            section_rows.append({"id": row_id, "fields": values, "parent": parents.get(i)})
        by_id = {r["id"]: r for r in section_rows}
        for new_id, old_id in copies:
            if old_id in by_id:
                section_rows.append({**by_id[old_id], "id": new_id})
        rows.extend(section_rows)
    return rows

