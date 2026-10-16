"""wow/casc.py (game file reader for tools/extract_maps.py): name hash and BLTE decoding."""

import struct
import zlib

import pytest

pytest.importorskip("numpy")
from forever_chronicle.wow import casc  # noqa: E402


def test_hashlittle2_reference_vector():
    h = casc.hashlittle2(b"Four score and seven years ago")
    assert (h >> 32, h & 0xFFFFFFFF) == (0x17770551, 0xCE7226E6)


def test_path_hash_ignores_case_and_slashes():
    assert casc.jenkins_path_hash("Interface/Icons/a.blp") == casc.jenkins_path_hash(r"INTERFACE\ICONS\A.BLP")


def test_blte_single_and_chunked():
    assert casc.blte_decode(b"BLTE" + struct.pack(">I", 0) + b"Nhello") == b"hello"
    chunks = [b"N" + b"abc", b"Z" + zlib.compress(b"defg")]
    header = bytes([0x0F]) + len(chunks).to_bytes(3, "big")
    for c in chunks:
        header += struct.pack(">II", len(c), 0) + b"\0" * 16
    data = b"BLTE" + struct.pack(">I", 8 + len(header)) + header + b"".join(chunks)
    assert casc.blte_decode(data) == b"abcdefg"


def test_blte_encrypted_chunk_is_reported():
    with pytest.raises(casc.EncryptedError):
        casc.blte_decode(b"BLTE" + struct.pack(">I", 0) + b"E....")
