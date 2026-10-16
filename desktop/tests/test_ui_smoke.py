"""Builds the main window headless, imports the fixture and walks through all pages and languages."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
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
    entries = [timeline.table.item(r, 1) for r in range(6)]
    quest = next(e for e in entries if e.text() == "Quest abgeschlossen: The Runaway Shipment")
    assert not quest.data(Qt.ItemDataRole.DecorationRole).isNull(), "the event type's game icon (bundled in forever_chronicle/icons)"
    overview = window.pages[0]
    assert overview.rows["quests"][1].text() == "1"
    assert overview.rows["kills"][1].text() == "2" and overview.rows["xp_earned"][1].text() == "4.200"
    assert overview.rows["played_total"][1].text() == "20 Std. 35 Min."
    gear = [overview.gear.item(i) for i in range(overview.gear.count())]
    assert [g.text() for g in gear] == ["Kopf:  Green Tinted Goggles", "Waffenhand:  Dwarven Hand Cannon"]
    assert gear[0].foreground().color().name() == "#0070dd"                   # rare = blue

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

    import_page = next(p for p in window.pages if p.title_key == "tab.import")
    window.tabs.setCurrentWidget(import_page)
    assert import_page.backup_box.title() == "Datensicherung" and import_page.backup_label.text()
    import_page._backup_now()
    assert import_page.backup_message.text().startswith("Gesichert: ") and "Letzte Sicherung" in import_page.backup_label.text()
    assert import_page.restore_button.isEnabled()
    import_page.restore_selected(db.backups()[-1])
    assert import_page.backup_message.text().startswith("Wiederhergestellt: ") and "manuell" in import_page.backup_message.text()
    assert window.characters.count() == 1

    settings = next(p for p in window.pages if p.title_key == "tab.settings")
    window.tabs.setCurrentWidget(settings)
    assert settings.music.isChecked() and settings.effects_volume.value() == config.effects_volume
    settings.clicks.setChecked(False)
    settings.music_volume.setValue(30)
    saved = AppConfig.load()
    assert not saved.click_sounds and saved.music_volume == 30, "sound settings are kept"
    settings.preview.setChecked(True)
    assert ctx.sound.music.active and settings.preview.text() == "■ Stopp"
    window.tabs.setCurrentIndex(0)
    assert not ctx.sound.music.active, "the preview ends when the page is left"

    i18n.set_language("en")
    assert window.tabs.tabText(0) == "Overview"
    window.tabs.setCurrentIndex(0)  # pages refresh when shown
    assert overview.rows["played_total"][1].text() == "20h 35m"
    i18n.set_language("de")
    window.close()
