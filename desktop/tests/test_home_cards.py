"""Home screen, card lists, favourites and the game's fonts."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint  # noqa: E402
from forever_chronicle.ui.pages.home import session_range, session_stats, taxi_seconds, zone_times  # noqa: E402
from forever_chronicle.storage.jsonl import export_jsonl, import_jsonl  # noqa: E402
from forever_chronicle.ui import theme  # noqa: E402
from forever_chronicle.ui.cards import KIND, CardList  # noqa: E402
from forever_chronicle.ui.main_window import MainWindow  # noqa: E402
from forever_chronicle.wow import game_fonts  # noqa: E402


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


def test_home_screen_cards(ctx, imported):
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
    assert not hasattr(home, "characters_card"), "the characters are in the sidebar, not on a card"
    labels = [w.text() for w in home.session_card.findChildren(QLabel)]
    assert "Statistik" in labels and "Sitzungen" in labels, "the last session shows its statistics"
    window.close()


def test_the_shown_page_loads_once(ctx, imported, monkeypatch):
    """Start, an import (data_changed) and a language change each load the shown page once, for the chosen
    character."""
    from forever_chronicle import i18n
    from forever_chronicle.ui.pages.home import HomePage
    loads = []
    original = HomePage.refresh
    monkeypatch.setattr(HomePage, "refresh", lambda self: (loads.append((self, self.character_id)), original(self)))
    window = MainWindow(ctx)
    home, cid = window.page("tab.home"), window.current_character_id()
    assert cid is not None and [load for load in loads if load[0] is home] == [(home, cid)]
    ctx.data_changed.emit()
    i18n.set_language("en")
    i18n.set_language("de")
    assert [load for load in loads if load[0] is home] == [(home, cid)] * 4
    window.close()


def test_home_photos_arrive_in_the_background(app, tmp_path):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage
    from forever_chronicle.ui.pages.home import Photos, Thumb
    path = tmp_path / "shot.jpg"
    image = QImage(640, 400, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    assert image.save(str(path), "JPG")
    photos = Photos(None)
    thumb = Thumb(str(path), lambda: None, QSize(132, 82), photos)
    deadline = 200
    while photos.waiting and deadline:
        app.processEvents()
        QTest.qWait(10)
        deadline -= 1
    assert not thumb.pixmap().isNull() and thumb.pixmap().height() == 82, "read in a worker, shown when ready"
    again = Thumb(str(path), lambda: None, QSize(132, 82), photos)
    assert not again.pixmap().isNull(), "kept: shown at once"


def test_session_statistics(ctx, imported):
    cid = ctx.repo.list_characters()[0].character_id
    sessions = ctx.repo.sessions(cid)
    session = sessions[0]
    route = Route(ctx.repo.positions(cid), ctx.repo.map_infos(), ctx.repo.instance_names(), ctx.repo.entrances())
    start, end = session_range(session, route)
    events = [e for e in ctx.repo.events(cid, limit=100_000) if start <= e.occurred_at <= end]
    rows = dict(session_stats(session, len(sessions), [3600, 1800], events, route, start, end))
    assert rows["Sitzungen"] == str(len(sessions))
    assert rows["Durchschnittliche Sitzung"] == "45 Min."
    zones = zone_times(route, start, end)
    assert all(seconds >= 0 for _, seconds in zones)
    assert [s for _, s in zones] == sorted((s for _, s in zones), reverse=True), "the longest zone first"


def test_taxi_and_zone_times():
    def point(t, until, map_id=1429, taxi=False, instance=None):
        return PositionPoint(t, until, map_id, 0.5, 0.5, instance, taxi)
    route = Route([point(0, 100), point(100, 110, taxi=True), point(150, 400, taxi=True), point(400, 500),
                   point(600, 900, None, instance=36)], instance_names={36: "Die Todesminen"})
    assert taxi_seconds(route, 0, 1000) == 300, "the flight, including the step between its two points"
    assert taxi_seconds(route, 200, 300) == 100, "clipped to the asked range"
    assert taxi_seconds(None, 0, 1000) == 0
    zones = zone_times(route, 0, 900)
    assert len(zones) == 2 and zones[0][1] == 600, "the zone first, its break before the dungeon counted to it"
    assert zones[1] == ("Die Todesminen", 300)


def test_favorites_travel_with_the_export(ctx, imported, tmp_path, db):
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
