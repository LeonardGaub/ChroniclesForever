import json

from forever_chronicle.wow import battlenet, paths


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field(number, payload: bytes) -> bytes:
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def install_entry(uid, path, subfolder):
    """Shaped like a product.db install: uid, product code and a nested settings message with the path."""
    settings = field(1, path.encode()) + varint(2 << 3 | 0) + varint(1) + field(3, subfolder.encode())
    return field(1, uid.encode()) + field(2, uid.encode()) + field(3, settings)


def fake_client(folder, flavor="wow_classic_beta"):
    folder.mkdir(parents=True)
    (folder / ".flavor.info").write_text(f"#Flavor\n{flavor}\n", encoding="utf-8")
    return folder


def test_proto_strings_finds_nested_paths_and_survives_garbage():
    data = field(1, install_entry("wow_classic_beta", "D:/Spiele/Blizzard/World of Warcraft", "_classic_beta_"))
    data += b"\x07\xff\xff garbage"
    strings = battlenet.proto_strings(data)
    assert "D:/Spiele/Blizzard/World of Warcraft" in strings and "_classic_beta_" in strings
    assert battlenet.proto_strings(b"\xff\xff\xff") == []
    assert battlenet.proto_strings(field(1, b"\x0a\x99")) == []     # truncated nested message


def test_product_db_and_config(tmp_path):
    agent = tmp_path / "ProgramData" / "Battle.net" / "Agent"
    agent.mkdir(parents=True)
    (agent / "product.db").write_bytes(
        field(1, install_entry("wow_classic_beta", "D:/Spiele/Blizzard/World of Warcraft", "_classic_beta_"))
        + field(1, install_entry("agent", "C:/ProgramData/Battle.net/Agent", "")))
    assert battlenet.product_db_paths(tmp_path / "ProgramData") == [
        paths.Path("D:/Spiele/Blizzard/World of Warcraft"), paths.Path("C:/ProgramData/Battle.net/Agent")]
    assert battlenet.product_db_paths(tmp_path / "missing") == []

    cfg = tmp_path / "AppData" / "Battle.net"
    cfg.mkdir(parents=True)
    (cfg / "Battle.net.config").write_text(json.dumps({"Client": {"Install": {"DefaultInstallPath": "E:/Games"}}}))
    assert battlenet.config_paths(tmp_path / "AppData") == [paths.Path("E:/Games/World of Warcraft")]
    (cfg / "Battle.net.config").write_text("{broken")
    assert battlenet.config_paths(tmp_path / "AppData") == []


def test_install_roots_merges_sources():
    def broken():
        raise RuntimeError("registry not readable")
    roots = battlenet.install_roots([
        lambda: [paths.Path("D:/WoW/_retail_"), paths.Path("D:/WoW")],
        broken,
        lambda: [paths.Path("d:/wow"), paths.Path("E:/Other")],
    ])
    assert roots == [paths.Path("D:/WoW/_retail_"), paths.Path("D:/WoW"), paths.Path("E:/Other")]


def test_unusual_install_found_through_battlenet(tmp_path, monkeypatch):
    root = tmp_path / "Spiele" / "Blizzard" / "World of Warcraft"
    client = fake_client(root / "_classic_beta_")
    fake_client(root / "_classic_era_", flavor="wow_classic_era")    # another game version: ignored
    monkeypatch.setattr(paths, "candidate_roots", lambda: [])          # no lucky guess from the drive scan
    monkeypatch.setattr(battlenet, "install_roots", lambda: [])
    assert paths.find_forever_installs() == []
    monkeypatch.setattr(battlenet, "install_roots", lambda: [tmp_path / "nothing", root, client])
    found = paths.find_forever_installs()
    assert [c.path for c in found] == [client] and found[0].flavor == "wow_classic_beta"
    assert paths.find_forever_installs(use_battlenet=False) == []


def test_client_from_path_only_looks_at_the_chosen_folder(tmp_path, monkeypatch):
    client = fake_client(tmp_path / "WoW" / "_classic_beta_")
    monkeypatch.setattr(battlenet, "install_roots", lambda: [tmp_path / "WoW"])
    assert paths.client_from_path(tmp_path / "WoW").path == client       # root folder
    assert paths.client_from_path(client).path == client                 # client folder itself
    assert paths.client_from_path(tmp_path / "empty") is None            # no silent fallback to another install
