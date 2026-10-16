"""Game icons for events (wow/game_icons.py, domain/event_types.icon_of): names, folders and the fallback."""

from pathlib import Path

import pytest

from forever_chronicle.domain import event_types
from forever_chronicle.storage.repository import Repository
from forever_chronicle.wow import game_icons
from forever_chronicle.wow.paths import ClientInstall


@pytest.fixture(autouse=True)
def fresh_session(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    monkeypatch.setattr(game_icons, "_failed", set())


def event(event_type: str, payload: dict | None = None):
    return type("E", (), {"event_type": event_type, "payload": payload or {}})()


def test_names_of_textures_and_ids():
    assert game_icons.name_of("Interface\\Icons\\INV_Misc_Note_01") == "inv_misc_note_01"
    assert game_icons.name_of("Interface/Icons/INV_Misc_Note_01.BLP") == "inv_misc_note_01"
    assert game_icons.name_of(136243) == game_icons.name_of("136243") == "136243"
    assert game_icons.name_of(0) is game_icons.name_of(True) is game_icons.name_of("") is game_icons.name_of(None)
    assert game_icons.game_path("INV_Misc_Note_01") == "Interface\\Icons\\INV_Misc_Note_01.blp"


def test_every_event_type_icon_is_kept_in_git():
    """Rerun tools/extract_icons.py after giving an event type a new icon."""
    missing = [i for i in event_types.all_icons() if game_icons.find(i) is None]
    assert not missing
    assert game_icons.find(event_types.SCREENSHOT_ICON).parent == game_icons.BUNDLED


def test_recorded_icon_wins_and_death_pins_are_skulls():
    assert event_types.icon_of(event("achievement_earned", {"icon": 136243})) == 136243
    assert event_types.icon_of(event("achievement_earned", {"icon": True})).endswith("INV_Misc_Book_09")
    assert event_types.icon_of(event("quest_completed")).endswith("INV_Misc_Note_01")
    assert event_types.icon_of(event("player_died"), pin=True).endswith("UI-TargetingFrame-Skull")
    assert event_types.icon_of(event("something_new")) == ""


def test_cache_folder_and_missing(tmp_path):
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "136243.png").write_bytes(b"png")
    assert game_icons.find(136243) == tmp_path / "icons" / "136243.png"
    todo = game_icons.missing([136243, 7808148, "7808148", event_types.SCREENSHOT_ICON, None, 0])
    assert todo == [7808148]   # one per name; bundled and cached ones are there already


def test_without_the_game_the_app_keeps_its_symbols(tmp_path):
    assert game_icons.extract_missing(None, [7808148]) == 0
    nowhere = ClientInstall(tmp_path / "World of Warcraft" / "_classic_beta_", "wow_classic_beta")
    before = game_icons.generation
    assert game_icons.extract_missing(nowhere, [7808148]) == 0
    assert game_icons.missing([7808148]) == [] and game_icons.generation == before  # not tried again


def test_repository_lists_recorded_icons(db):
    repo = Repository(db.conn)
    char = repo.upsert_character("Forever-Realm-Hero", {"name": "Hero"}, None)
    run = repo.start_import("test", "saved_variables", None, None, None)
    for i, data in enumerate([{"icon": 136243}, {"icon": 136243}, {"icon": "x"}, {}, {"icon": 133971}]):
        repo.insert_event(char, {"id": f"e{i}", "seq": i, "type": "achievement_earned", "time": 100 + i, "data": data},
                          run, 1)
    assert sorted(repo.event_icons()) == [133971, 136243]


def test_pictures_fall_back_to_the_type_icon(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    from forever_chronicle.ui import icons
    QGuiApplication.instance() or QGuiApplication([])
    lost = event("recipe_learned", {"icon": 7808148})   # recorded, but not taken from the game
    assert icons.event_small(lost) is not None and icons.event_pin(lost) is not None
    assert icons.of_event(7808148, "recipe_learned") is not None
    skull = icons.event_pin(event("player_died"))
    assert skull.width() / skull.devicePixelRatio() == icons.PIN_LOOKS["danger"][1]
    assert icons.event_small(event("something_new")) is None   # unknown types keep their symbol


def test_map_pin_tooltip_and_hover(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QGraphicsSceneHoverEvent
    from forever_chronicle.ui import icons
    from forever_chronicle.ui.pages.map_page import EventPin, event_tooltip
    QApplication.instance() or QApplication([])
    quest = event("quest_completed", {"title": "Fish & <Chips>"})
    quest.zone_name, quest.subzone_name, quest.occurred_at = "Mulgore", "Bloodhoof Village", 1_760_000_000
    tip = event_tooltip(quest)
    assert "inv_misc_note_01.png" in tip and "Fish &amp; &lt;Chips&gt;" in tip and "Bloodhoof Village, Mulgore" in tip
    pin = EventPin(icons.event_pin(quest), 5)
    pin.hoverEnterEvent(QGraphicsSceneHoverEvent(QEvent.Type.GraphicsSceneHoverEnter))
    assert pin.scale() == EventPin.HOVER_SCALE and pin.zValue() == 6
    pin.hoverLeaveEvent(QGraphicsSceneHoverEvent(QEvent.Type.GraphicsSceneHoverLeave))
    assert pin.scale() == 1 and pin.zValue() == 5


def test_bundled_folder_is_in_the_package():
    assert game_icons.BUNDLED == Path(game_icons.__file__).resolve().parents[1] / "icons"
