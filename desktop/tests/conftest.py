import os
from pathlib import Path

import pytest

os.environ["FOREVER_CHRONICLE_SILENT"] = "1"   # tests never play sounds (ui/sound.py still records them)

REPO = Path(__file__).resolve().parents[2]
ADDON_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle.lua"   # written by tests/addon (npm test)
PROBE_SV = REPO / "probe-results" / "ForeverChronicle_Probe_SavedVariables_2026-10-14.lua"  # real client file


@pytest.fixture(autouse=True)
def own_maps_folder(tmp_path, monkeypatch):
    """Tests choose their own map images (tmp_path/maps); the images in git would give every map art."""
    from forever_chronicle.wow import map_art
    monkeypatch.setattr(map_art, "maps_dir", lambda: tmp_path / "maps")


@pytest.fixture(autouse=True)
def own_sync_folder(tmp_path, monkeypatch):
    """Tests never see or start this PC's real cloud sync: its folder is tmp_path/sync, empty unless a test fills it,
    and there is no sync script unless a test gives a stand-in."""
    from forever_chronicle import cloud_sync
    monkeypatch.setattr(cloud_sync, "sync_dir", lambda: tmp_path / "sync")
    monkeypatch.setattr(cloud_sync, "sync_script", lambda: None)


@pytest.fixture
def addon_fixture() -> Path:
    if not ADDON_FIXTURE.exists():
        pytest.skip("run `npm test` in tests/addon first to create the fixture")
    return ADDON_FIXTURE


@pytest.fixture
def db(tmp_path):
    from forever_chronicle.storage.database import Database
    database = Database(tmp_path / "test.db", tmp_path / "backups")
    yield database
    database.close()


def unpack_all(data: dict) -> dict:
    """The fixture is a real saved file with packed streams; tests that edit records work on unpacked ones."""
    from forever_chronicle.importing.sv_importer import unpack_stream
    for char in data["ForeverChronicleDB"]["characters"].values():
        char["streams"] = {name: unpack_stream(s) for name, s in char.get("streams", {}).items()}
    return data
