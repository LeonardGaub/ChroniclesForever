import os
from pathlib import Path

import pytest

os.environ["FOREVER_CHRONICLE_SILENT"] = "1"   # tests never play sounds (ui/sound.py still records them)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[2]
ADDON_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle.lua"   # written by tests/addon (npm test)
PROBE_SV = REPO / "probe-results" / "ForeverChronicle_Probe_SavedVariables_2026-10-14.lua"  # real client file


@pytest.fixture(autouse=True)
def own_maps_folder(tmp_path, monkeypatch):
    """Tests choose their own map images (tmp_path/maps); the images in git would give every map art."""
    from forever_chronicle.wow import map_art
    monkeypatch.setattr(map_art, "maps_dir", lambda: tmp_path / "maps")


@pytest.fixture(autouse=True)
def own_app_home(tmp_path, monkeypatch):
    """Tests never touch this PC's app folder (settings, the cloud backup's state, backups): tmp_path/home, unless a
    test sets its own."""
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path / "home"))


@pytest.fixture
def addon_fixture() -> Path:
    if not ADDON_FIXTURE.exists():
        pytest.skip("run `npm test` in tests/addon first to create the fixture")
    return ADDON_FIXTURE


@pytest.fixture
def sv_data(addon_fixture) -> dict:
    """The addon fixture's SavedVariables, parsed (a fresh copy per test, so tests may change it)."""
    from forever_chronicle.wow.lua_parser import parse_saved_variables
    return parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))


@pytest.fixture
def db(tmp_path):
    from forever_chronicle.storage.database import Database
    database = Database(tmp_path / "test.db", tmp_path / "backups")
    yield database
    database.close()


@pytest.fixture(scope="module")
def app():
    """The QApplication, with the Classic theme."""
    from PySide6.QtWidgets import QApplication
    from forever_chronicle.ui import theme
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


@pytest.fixture
def ctx(app, db, tmp_path, monkeypatch):
    """An empty app context: its home folder is tmp_path, and the real disk is never searched for the game."""
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.config import AppConfig
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    context = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    context._client_searched = True
    return context


@pytest.fixture
def imported(ctx, sv_data):
    """`ctx` with the addon fixture imported (request both: `def test_x(ctx, imported)`)."""
    ctx.importer.import_data(sv_data, "fixture")
    return ctx


def unpack_all(data: dict) -> dict:
    """The fixture is a real saved file with packed streams; tests that edit records work on unpacked ones."""
    from forever_chronicle.importing.sv_importer import unpack_stream
    for char in data["ForeverChronicleDB"]["characters"].values():
        char["streams"] = {name: unpack_stream(s) for name, s in char.get("streams", {}).items()}
    return data


def event(t: int, kind: str, **payload):
    """An event of the test character "c" at time t."""
    from forever_chronicle.storage.repository import EventRow
    return EventRow("c", f"e{t}", kind, t, None, None, None, None, None, payload)
