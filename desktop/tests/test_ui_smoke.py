"""Builds the main window headless, imports the fixture and walks through all pages and languages."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle import i18n  # noqa: E402
from forever_chronicle.app_context import AppContext  # noqa: E402
from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.ui import theme  # noqa: E402
from forever_chronicle.ui.main_window import MainWindow  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


def test_main_window_with_data(app, db, tmp_path, monkeypatch, addon_fixture):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    config = AppConfig(client_dir=str(tmp_path / "missing"))
    ctx = AppContext(config, db)
    ctx._client_searched = True  # do not scan the real disk in tests

    window = MainWindow(ctx)
    assert window.characters.count() == 0

    ctx.importer.import_data(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")), "fixture")
    ctx.data_changed.emit()
    assert window.characters.count() == 1
    assert window.char_name.text() == "Blind Bullseye"  # Forever characters have a last name

    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
    timeline = window.pages[1]
    assert timeline.table.rowCount() == 6
    assert "Quest abgeschlossen: The Runaway Shipment" in [timeline.table.item(r, 1).text().split("  ", 1)[1]
                                                          for r in range(6)]
    overview = window.pages[0]
    assert overview.rows["quests"][1].text() == "1"
    assert overview.rows["kills"][1].text() == "2" and overview.rows["xp_earned"][1].text() == "4.200"
    assert overview.rows["played_total"][1].text() == "20 Std. 35 Min."

    professions = next(p for p in window.pages if p.title_key == "tab.professions")
    window.tabs.setCurrentWidget(professions)
    assert professions.prof_table.rowCount() == 4 and professions.recipe_table.rowCount() == 4
    assert professions.prof_table.item(1, 1).text() == "126 / 150" and professions.prof_table.item(1, 2).text() == "Geselle"
    cloak = professions.recipe_table.item(0, 0)
    assert cloak.text() == "Handstitched Leather Cloak" and cloak.foreground().color().name() == "#1eff00"
    professions.search.setText("hide")
    assert professions.recipe_table.rowCount() == 2 and professions.count.text() == "2 Rezepte"
    professions.prof_table.setCurrentCell(0, 0)  # Herbalism: gathering, no recipes
    assert professions.recipe_table.rowCount() == 0
    professions.search.clear()

    i18n.set_language("en")
    assert window.tabs.tabText(0) == "Overview"
    window.tabs.setCurrentIndex(0)  # pages refresh when shown
    assert overview.rows["played_total"][1].text() == "20h 35m"
    i18n.set_language("de")
    window.close()
