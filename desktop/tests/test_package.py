"""The friend package (tools/package_for_friend.py), bundled map images and the addon installer used by
"Forever Chronicle starten.bat"."""

import importlib.util
import zipfile
from pathlib import Path

from forever_chronicle import setup_addon
from forever_chronicle.config import AppConfig
from forever_chronicle.wow import map_art
from forever_chronicle.wow.paths import ClientInstall

REPO = Path(__file__).resolve().parents[2]


def load_packager():
    spec = importlib.util.spec_from_file_location("package_for_friend", REPO / "tools" / "package_for_friend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_contents(tmp_path):
    home = tmp_path / "home"
    (home / "maps").mkdir(parents=True)
    (home / "maps" / "1413.jpg").write_bytes(b"\xff\xd8\xff barrens")
    (home / "maps" / "notes.txt").write_text("not a map")
    dest = load_packager().build(tmp_path / "friend.zip", home)
    names = set(zipfile.ZipFile(dest).namelist())
    top = "ForeverChronicle/"
    assert top + "Forever Chronicle starten.bat" in names and top + "LIES MICH.txt" in names
    assert top + "addons/ForeverChronicle/ForeverChronicle.toc" in names
    assert not [n for n in names if "ForeverChronicle_Share" in n or "Friends/" in n]  # friends parts: cloud only
    assert top + "desktop/forever_chronicle/app.py" in names and top + "desktop/pyproject.toml" in names
    assert top + "desktop/forever_chronicle/maps/1413.jpg" in names
    assert not [n for n in names if "notes.txt" in n or "/tests/" in n or ".venv" in n or "__pycache__" in n]
    bat = zipfile.ZipFile(dest).read(top + "Forever Chronicle starten.bat")
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")          # Windows line endings


def test_bundled_maps_are_a_fallback(tmp_path, monkeypatch):
    own, bundled = tmp_path / "own", tmp_path / "bundled"
    own.mkdir()
    bundled.mkdir()
    (bundled / "1413.jpg").write_bytes(b"x")
    (bundled / "1411.jpg").write_bytes(b"x")
    (own / "1413.png").write_bytes(b"x")
    monkeypatch.setattr(map_art, "art_dir", lambda: own)
    monkeypatch.setattr(map_art, "bundled_dir", lambda: bundled)
    assert map_art.find_art(1413) == own / "1413.png"           # the user's own image wins
    assert map_art.find_art(1411) == bundled / "1411.jpg"
    assert map_art.find_art(9999) is None
    assert map_art.available_art() == {1411, 1413}
    assert map_art.find_art(1411, folder=own) is None           # an explicit folder is used alone


def fake_client(tmp_path) -> ClientInstall:
    root = tmp_path / "WoW" / "_classic_beta_"
    root.mkdir(parents=True)
    (root / ".flavor.info").write_text("#\nwow_classic_beta\n")
    return ClientInstall(root, "wow_classic_beta")


def test_install_addon_keeps_friends_file(tmp_path):
    source = REPO / "addons" / "ForeverChronicle"
    client = fake_client(tmp_path)
    target = client.addons_dir / "ForeverChronicle"
    (target / "Friends").mkdir(parents=True)
    (target / "Friends" / "FriendsData.lua").write_text("ForeverChronicleFriends = { friends = {} } -- from the app")
    (target / "Old.lua").write_text("stale")
    result = setup_addon.install_addon(source, client)
    assert (target / "ForeverChronicle.toc").read_bytes() == (source / "ForeverChronicle.toc").read_bytes()
    assert "from the app" in (target / "Friends" / "FriendsData.lua").read_text()
    assert not (target / "Old.lua").exists() and result.removed == 1
    assert result.version and result.target == target


def test_setup_main_asks_when_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(setup_addon, "find_forever_installs", lambda: [])
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
