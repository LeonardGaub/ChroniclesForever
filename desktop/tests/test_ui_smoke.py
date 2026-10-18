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
from forever_chronicle.ui.cards import ICON, KIND, TITLE, TITLE_COLOR  # noqa: E402
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

    assert window.current_page() is window.page("tab.home"), "the app starts on the home screen"
    assert [b.text() for b in window.nav_buttons.values()] == ["Start", "Übersicht", "Chronik", "Galerie", "Karte",
                                                              "Berufe"]
    assert [a.text() for a in window.gear_actions.values()] == ["Import", "Einstellungen", "Diagnose"]
    for page in window.pages:
        window.show_page(page)
    timeline = window.page("tab.timeline")
    window.show_page(timeline)
    assert window.nav_buttons[timeline].isChecked() and not window.gear.isChecked()
    entries = timeline.list.entries()
    assert len(entries) == 6
    assert timeline.list.item(0).data(KIND) == "header", "a heading per day, as in the addon's Chronik"
    quest = next(e for e in entries if e.data(TITLE) == "Quest abgeschlossen: The Runaway Shipment")
    assert quest.data(ICON) is not None and not quest.data(ICON).isNull(), \
        "the event type's game icon (bundled in forever_chronicle/icons)"
    overview = window.page("tab.overview")
    assert overview.rows["quests"][1].text() == "1"
    assert overview.rows["kills"][1].text() == "2" and overview.rows["xp_earned"][1].text() == "4.200"
    assert overview.rows["played_total"][1].text() == "20 Std. 35 Min."
    gear = [overview.gear.item(i) for i in range(overview.gear.count())]
    assert [g.text() for g in gear] == ["Kopf:  Green Tinted Goggles", "Waffenhand:  Dwarven Hand Cannon"]
    assert gear[0].foreground().color().name() == "#0070dd"                   # rare = blue

    professions = window.page("tab.professions")
    window.show_page(professions)
    recipes = professions.recipes.entries()
    assert len(professions.cards) == 4 and len(recipes) == 4
    assert professions.cards[1].skill == "126 / 150" and professions.cards[1].rank == "Geselle"
    cloak = recipes[0]
    assert cloak.data(TITLE) == "Handstitched Leather Cloak" and cloak.data(TITLE_COLOR) == "#1eff00", \
        "a recipe's name in the colour of the item it makes"
    professions.search.setText("hide")
    assert len(professions.recipes.entries()) == 2 and professions.count.text() == "2 Rezepte"
    professions._card_clicked(professions.cards[0].skill_line)  # Herbalism: gathering, no recipes
    assert not professions.recipes.entries() and professions.cards[0].property("selected")
    professions._card_clicked(professions.cards[0].skill_line)  # again: all professions
    assert professions.filter.currentIndex() == 0 and not professions.cards[0].property("selected")
    professions.search.clear()

    import_page = window.page("tab.import")
    window.show_page(import_page)
    assert window.gear.isChecked() and not any(b.isChecked() for b in window.nav_buttons.values()), \
        "a gear page selects no tab"
    assert import_page.backup_box.title() == "Datensicherung" and import_page.backup_label.text()
    import_page._backup_now()
    assert import_page.backup_message.text().startswith("Gesichert: ") and "Letzte Sicherung" in import_page.backup_label.text()
    assert import_page.restore_button.isEnabled()
    import_page.restore_selected(db.backups()[-1])
    assert import_page.backup_message.text().startswith("Wiederhergestellt: ") and "manuell" in import_page.backup_message.text()
    assert window.characters.count() == 1

    settings = window.page("tab.settings")
    window.show_page(settings)
    assert settings.music.isChecked() and settings.effects_volume.value() == config.effects_volume
    settings.clicks.setChecked(False)
    settings.music_volume.setValue(30)
    saved = AppConfig.load()
    assert not saved.click_sounds and saved.music_volume == 30, "sound settings are kept"
    settings.preview.setChecked(True)
    assert ctx.sound.music.active and settings.preview.text() == "■ Stopp"
    window.show_page(overview)
    assert not ctx.sound.music.active, "the preview ends when the page is left"

    i18n.set_language("en")
    assert window.nav_buttons[overview].text() == "Overview"
    window.show_page(overview)  # pages refresh when shown
    assert overview.rows["played_total"][1].text() == "20h 35m"
    i18n.set_language("de")

    # Home screen: the cards lead to the other pages.
    home = window.page("tab.home")
    window.show_page(home)
    assert home.welcome.text() == "Willkommen zurück, Blind"
    assert home.session_card.title.text() == "Letzte Sitzung" and home.map_card.title.text() == "Karte & Wiedergabe"
    ctx.navigate.emit("tab.gallery")
    assert window.current_page() is window.page("tab.gallery") and window.nav_buttons[window.current_page()].isChecked()
    ctx.select_character.emit(window.current_character_id())
    window.close()
