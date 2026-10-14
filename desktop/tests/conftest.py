from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ADDON_FIXTURE = REPO / "tests" / "fixtures" / "ForeverChronicle.lua"   # written by tests/addon (npm test)
PROBE_SV = REPO / "probe-results" / "ForeverChronicle_Probe_SavedVariables_2026-10-14.lua"  # real client file


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
