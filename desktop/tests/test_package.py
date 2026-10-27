"""The bundled map images and the addon installer used by "Journey Forever starten.bat"."""

from pathlib import Path

from forever_chronicle import setup_addon
from forever_chronicle.config import AppConfig
from forever_chronicle.wow import map_art, paths
from forever_chronicle.wow.paths import ClientInstall

REPO = Path(__file__).resolve().parents[2]


def test_map_images_live_in_git():
    """The one map folder (wow/map_art.py): the client images from tools/extract_maps.py, kept in git."""
    folder = Path(map_art.__file__).resolve().parents[1] / "maps"
    assert folder == REPO / "desktop" / "forever_chronicle" / "maps"
    assert (folder / "1412.jpg").is_file() and len(list(folder.glob("*.jpg"))) >= 52


def fake_client(tmp_path) -> ClientInstall:
    root = tmp_path / "WoW" / "_classic_beta_"
    root.mkdir(parents=True)
    (root / ".flavor.info").write_text("#\nwow_classic_beta\n")
    return ClientInstall(root, "wow_classic_beta")


def test_install_addon_removes_stale_files_and_the_old_companion(tmp_path):
    source = REPO / "addons" / "ForeverChronicle"
    client = fake_client(tmp_path)
    target = client.addons_dir / "ForeverChronicle"
    target.mkdir(parents=True)
    (target / "Old.lua").write_text("stale")
    companion = client.addons_dir / "ForeverChronicle_Share" / "Friends"
    companion.mkdir(parents=True)
    (companion / "FriendsData.lua").write_text("ForeverChronicleFriends = {}")
    result = setup_addon.install_addon(source, client)
    assert (target / "ForeverChronicle.toc").read_bytes() == (source / "ForeverChronicle.toc").read_bytes()
    assert not (target / "Old.lua").exists() and result.removed == 1
    assert result.version and result.target == target
    assert not (client.addons_dir / "ForeverChronicle_Share").exists()


def test_update_addon_at_start_only_when_newer(tmp_path, monkeypatch):
    client = fake_client(tmp_path)
    assert setup_addon.update_addon(client) is None, "not installed yet: the setup does the first install"
    setup_addon.install_addon(REPO / "addons" / "ForeverChronicle", client)
    assert setup_addon.update_addon(client) is None, "same version: nothing to do"
    toc = client.addons_dir / "ForeverChronicle" / "ForeverChronicle.toc"
    toc.write_text(toc.read_text(encoding="utf-8").replace("## Version: ", "## Version: 0.0.", 1), encoding="utf-8")
    (client.addons_dir / "ForeverChronicle_Share").mkdir()
    monkeypatch.setattr(setup_addon, "game_running", lambda _path: True)
    assert setup_addon.update_addon(client) is None, "never while WoW runs"
    monkeypatch.setattr(setup_addon, "game_running", lambda _path: False)
    assert setup_addon.update_addon(client) is not None
    assert "## Version: 0.0." not in toc.read_text(encoding="utf-8")
    assert not (client.addons_dir / "ForeverChronicle_Share").exists()


def test_setup_main_asks_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths, "find_forever_installs", lambda *_args: [])
    client = fake_client(tmp_path)
    answers = iter([str(tmp_path / "nowhere"), str(tmp_path / "WoW")])
    code = setup_addon.main([str(REPO / "addons" / "ForeverChronicle")], ask=lambda _prompt: next(answers))
    assert code == 0
    assert (client.addons_dir / "ForeverChronicle" / "ForeverChronicle.toc").is_file()
    assert AppConfig.load().client_dir == str(client.path)                     # the app uses the same folder
    # Next start: found from the settings without asking.
    assert setup_addon.main([str(REPO / "addons" / "ForeverChronicle")], ask=lambda _p: 1 / 0) == 0
    # Nothing found and the user gives up.
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path / "home2"))
    assert setup_addon.main([str(REPO / "addons" / "ForeverChronicle")], ask=lambda _p: "") == 1
