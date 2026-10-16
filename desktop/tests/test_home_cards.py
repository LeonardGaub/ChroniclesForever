"""Home screen, card lists, favourites and the game's fonts."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle.app_context import AppContext  # noqa: E402
from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.storage.jsonl import export_jsonl, import_jsonl  # noqa: E402
from forever_chronicle.ui import theme  # noqa: E402
from forever_chronicle.ui.cards import KIND, CardList  # noqa: E402
from forever_chronicle.ui.main_window import MainWindow  # noqa: E402
from forever_chronicle.wow import game_fonts  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


@pytest.fixture
def ctx(app, db, tmp_path, monkeypatch, addon_fixture):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    context = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    context._client_searched = True
    context.importer.import_data(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")), "fixture")
    return context


def test_card_list_rows_and_thumbnail_click(app):
    cards = CardList(thumbs=True)
    cards.resize(600, 400)
    cards.add_header("Donnerstag, 15.10.2026")
    plain = cards.add_entry("Quest abgeschlossen", "18:40  ·  Mulgore")
    shot = cards.add_entry("Stufe 7 erreicht", "18:12", accent="milestone", thumb=True)
    assert [cards.item(i).data(KIND) for i in range(3)] == ["header", "entry", "entry"]
    assert cards.entries() == [plain, shot] and not cards.item(0).flags() & Qt.ItemFlag.ItemIsSelectable
    assert cards.thumb_rect(1) is None and cards.thumb_rect(2) is not None
    cards.show()
    clicked = []
    cards.thumb_clicked.connect(clicked.append)
    QTest.mouseClick(cards.viewport(), Qt.MouseButton.LeftButton, pos=cards.thumb_rect(2).center())
    QTest.mouseClick(cards.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(40, cards.visualItemRect(plain).center().y()))
    assert clicked == [2], "only a click on the thumbnail opens the picture"
    pix = QPixmap(cards.viewport().size())
    cards.viewport().render(pix)            # the delegate paints all three kinds of rows
    cards.close()


def test_home_screen_cards(ctx):
    window = MainWindow(ctx)
    home = window.page("tab.home")
    assert window.current_page() is home
    assert home.welcome.text().startswith("Willkommen zurück")
    session = ctx.repo.sessions(window.current_character_id())[0]
    if session is not None:
        assert hasattr(home, "recap_button"), "the last session can be played back"
        cinematic = home.play(session["started_at"], session["started_at"] + 600)
        assert cinematic is not None and cinematic.start == session["started_at"]
        cinematic.close()
    rows = [w for w in home.characters_card.findChildren(type(home.recap_button)) if w.objectName() == "CharacterRow"]
    assert rows and rows[0].isChecked(), "the shown character is marked"
    rows[0].click()
    assert window.current_page() is window.page("tab.overview"), "a character row opens its overview"
    window.close()


def test_favorites_travel_with_the_export(ctx, tmp_path, db):
    cid = ctx.repo.list_characters()[0].character_id
    shot = ctx.repo.screenshots(cid)[0]
    ctx.repo.set_favorite(cid, shot["screenshot_id"], True)
    ctx.repo.set_favorite(cid, shot["screenshot_id"], True)            # twice: still one
    assert ctx.repo.favorite_screenshots(cid) == {shot["screenshot_id"]}
    path = tmp_path / "export.jsonl"
    export_jsonl(db, path)
    assert '"screenshot_favorite"' in path.read_text(encoding="utf-8")
    ctx.repo.set_favorite(cid, shot["screenshot_id"], False)
    assert not ctx.repo.favorite_screenshots(cid)
    import_jsonl(db, path)
    assert ctx.repo.favorite_screenshots(cid) == {shot["screenshot_id"]}, "restored from the export"


def test_game_fonts_cache(tmp_path, monkeypatch, app):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    assert game_fonts.missing() == list(game_fonts.FILES)
    assert game_fonts.extract_missing(None) == 0, "without the game nothing is taken"
    assert game_fonts.HEADING in theme.HEADING_FONTS[:1] and theme.TITLE_FONTS[0] == game_fonts.TITLE, \
        "the theme asks for the game's fonts first"
    font = (game_fonts.cache_dir())
    font.mkdir(parents=True)
    (font / "FRIZQT__.TTF").write_bytes(b"not a font")
    assert game_fonts.missing() == ["MORPHEUS.TTF"]
    game_fonts.load()                       # a broken file is skipped, nothing fails
