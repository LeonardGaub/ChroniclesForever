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


def build_info(root, *products):
    """A .build.info listing (product, version) pairs, like the one in the World of Warcraft folder."""
    lines = ["Branch!STRING:0|Active!DEC:1|Version!STRING:0|Product!STRING:0"]
    lines += [f"eu|1|{version}|{product}" for product, version in products]
    (root / ".build.info").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_live_client_found_by_version_and_preferred_over_the_beta(tmp_path):
    root = tmp_path / "WoW"
    beta = fake_client(root / "_classic_beta_")
    live = fake_client(root / "_forever_", flavor="wow_forever")         # live flavor unknown before the release
    fake_client(root / "_classic_era_", flavor="wow_classic_era")
    build_info(root, ("wow_classic_era", "1.15.9.70003"), ("wow_classic_beta", "1.60.1.70532"),
               ("wow_forever", "1.60.2.71000"))
    found = paths.scan_roots([root])
    assert [c.path for c in found] == [live, beta]                           # Classic Era (1.15) is no Forever client
    assert paths.forever_product(root) == "wow_forever"
    assert paths.client_from_path(root).path == live


def test_chosen_client_folder_counts_whatever_its_flavor(tmp_path):
    client = fake_client(tmp_path / "WoW" / "_new_", flavor="wow_something_new")
    assert paths.scan_roots([tmp_path / "WoW"]) == []                        # not found on its own
    assert paths.client_from_path(client) == paths.ClientInstall(client, "wow_something_new")


def test_pick_client_moves_from_the_saved_beta_to_the_live_client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "candidate_roots", lambda: [])
    monkeypatch.setattr(battlenet, "install_roots", lambda: [])
    root = tmp_path / "WoW"
    beta = fake_client(root / "_classic_beta_")
    assert paths.pick_client(str(beta)).path == beta                         # before the release: the beta
    assert paths.pick_client(None) is None                                   # nothing found without a saved folder
    live = fake_client(root / "_classic_", flavor="wow_classic")
    build_info(root, ("wow_classic_beta", "1.60.1.70532"), ("wow_classic", "1.60.2.71000"))
    assert paths.pick_client(str(beta)).path == live                         # the beta folder stays after the release
    other = fake_client(tmp_path / "Other" / "_x_", flavor="wow_x")
    assert paths.pick_client(str(other)).path == other                       # a live pick is kept as it is
