import io
import os
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle.domain.route import GAP_SECONDS, Route  # noqa: E402
from forever_chronicle.importing.sv_importer import SavedVariablesImporter  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint, Repository  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402
from forever_chronicle.wow.map_art import available_art, find_art, import_map_art  # noqa: E402


def P(t, map_id=1413, x=0.5, y=0.5, until=None, taxi=False, instance=None):
    return PositionPoint(t, until, map_id, x, y, instance, taxi)


@pytest.mark.parametrize("text,ok", [
    ("1791960000,1413,0.4403,0.5913,,,", True),
    ("1791960000,1413,0.4403,0.5913,1791960600,T,", True),
    ("1791960000,,,,,,389", True),
    ("1791960000,1413,0.44,,,,", False),        # x without y
    ("1791960000,,,,,,", False),                 # neither map nor instance
    ("1791960000,1413,1.5,0.5,,,", False),       # outside the map
    ("abc,1413,0.4,0.5,,,", False),
    ("1,2,3", False),
])
def test_parse_position(text, ok):
    assert (PositionPoint.parse(text) is not None) == ok


def test_parse_flags():
    p = PositionPoint.parse("100,1413,0.1,0.2,160,T,")
    assert p.taxi and p.until == 160 and p.end == 160


def test_import_positions_and_geometry(db, addon_fixture):
    data = parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))
    importer = SavedVariablesImporter(db)
    result = importer.import_data(data, "fixture")
    assert result.positions >= 12 and result.invalid == 0
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id
    points = repo.positions(cid)
    assert len(points) == result.positions
    assert points[-1].until is not None, "standing still at the end extends the last point"
    info = repo.map_infos()[1413]
    assert info["continent_id"] == 1414 and info["min_x"] == 0.4
    again = importer.import_data(data, "fixture")
    assert len(repo.positions(cid)) == len(points) and again.gaps == 0


def test_segments_break_on_gaps_taxi_map_and_instance():
    route = Route([P(0, x=0.1), P(10, x=0.2), P(20 + GAP_SECONDS + 1, x=0.3), P(200, x=0.4, taxi=True),
                   P(210, x=0.5, taxi=True), P(220, instance=389, map_id=None, x=None, y=None),
                   P(230, x=0.6), P(240, map_id=1411, x=0.7)])
    segs = route.segments(1413)
    assert [len(s.points) for s in segs] == [2, 1, 2, 1]
    assert [s.taxi for s in segs] == [False, False, True, False]


def test_projection_onto_continent():
    infos = {1413: {"continent_id": 1414, "min_x": 0.4, "max_x": 0.6, "min_y": 0.5, "max_y": 0.7}}
    route = Route([P(0, x=0.5, y=0.5)], infos)
    assert route.project(1413, 0.5, 0.5, 1414) == pytest.approx((0.5, 0.6))
    assert route.project(1413, 0.5, 0.5, 1415) is None
    assert route.available_views() == [1413, 1414]


def test_point_at_uses_stationary_span_and_nearest():
    route = Route([P(0, x=0.1, until=100), P(200, x=0.2), P(300, x=0.3)])
    assert route.point_at(50).x == 0.1      # inside the stationary span
    assert route.point_at(140).x == 0.1     # nearer to the span end (100) than to 200
    assert route.point_at(170).x == 0.2
    assert route.point_at(999).x == 0.3
    assert route.next_time_after(210) == 300


def _jpeg_bytes(color="#335577") -> bytes:
    image = QImage(1002, 668, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "JPG")
    return bytes(buf.data())


def test_import_map_art_takes_only_known_images(tmp_path):
    QApplication.instance() or QApplication([])
    archive = tmp_path / "maps.zip"
    jpg = _jpeg_bytes()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("WoW Classic Maps/Explored zones/barrens.jpg", jpg)
        z.writestr("WoW Classic Maps/Explored zones/kalimdor.jpg", jpg)
        z.writestr("WoW Classic Maps/Explored zones/silithus_old.jpg", jpg)        # unknown name
        z.writestr("__MACOSX/WoW Classic Maps/Explored zones/._barrens.jpg", b"junk")
        z.writestr("WoW Classic Maps/Explored zones/durotar.jpg", b"not an image")  # rejected
        z.writestr("WoW Classic Maps/Sprite assets/Barrens/Barrens1.png", jpg)    # not a full map
        z.writestr("../../evil/Explored zones/mulgore.jpg", jpg)                   # stored by map ID only
    dest = tmp_path / "art"
    assert import_map_art(archive, dest) == 3
    assert available_art(dest) == {1413, 1414, 1412}
    assert find_art(1413, dest).name == "1413.jpg"
    assert not (tmp_path / "evil").exists()


def test_map_page_replay_and_timeline_focus(db, tmp_path, monkeypatch, addon_fixture):
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.config import AppConfig
    from forever_chronicle.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "1413.jpg").write_bytes(_jpeg_bytes())

    ctx = AppContext(AppConfig(), db)
    ctx._client_searched = True
    ctx.importer.import_data(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")), "fixture")
    window = MainWindow(ctx)
    page = next(p for p in window.pages if p.title_key == "tab.map")
    window.tabs.setCurrentWidget(page)

    assert page.route and page.view_map == 1413
    assert page.map_select.count() == 2                      # The Barrens and its continent
    assert page._art_notice is None, "artwork found"
    start = page.current_t
    page._toggle_play()
    for _ in range(5):
        page._tick()
    assert page.current_t > start and page.marker.isVisible()
    page._toggle_play()

    page.map_select.setCurrentIndex(1)                         # continent view
    assert page.view_map == 1414 and page._art_notice      # no Kalimdor artwork in this test -> schematic
    page.map_select.setCurrentIndex(0)

    # Selecting the death (in Ragefire Chasm, no position) in the timeline moves the map there.
    timeline = next(p for p in window.pages if p.title_key == "tab.timeline")
    window.tabs.setCurrentWidget(timeline)
    death_row = next(r for r in range(timeline.table.rowCount()) if "Gestorben" in timeline.table.item(r, 1).text())
    death_time = timeline.table.item(death_row, 0).data(0x0100)
    timeline.table.setCurrentCell(death_row, 1)
    window.tabs.setCurrentWidget(page)
    assert page.current_t == death_time
    window.close()


def test_continent_points_open_the_zone():
    """The client reports only the continent between zones; the map still shows the zone (user request)."""
    infos = {1413: {"continent_id": 1414, "min_x": 0.4, "max_x": 0.6, "min_y": 0.5, "max_y": 0.7},     # Barrens
             1454: {"continent_id": 1414, "min_x": 0.45, "max_x": 0.5, "min_y": 0.5, "max_y": 0.55},  # Orgrimmar
             1414: {"continent_id": None, "min_x": None, "max_x": None, "min_y": None, "max_y": None}}
    route = Route([P(0, map_id=1413), P(10, map_id=1414, x=0.5, y=0.6), P(20, map_id=1414, x=0.46, y=0.52),
                   P(30, map_id=1414, x=0.9, y=0.9), P(400, map_id=None, x=None, y=None, instance=389)], infos)
    assert route.view_for(route.points[0]) == 1413
    assert route.view_for(route.points[1]) == 1413          # continent point inside the Barrens
    assert route.view_for(route.points[2]) == 1454          # smallest zone wins (city inside the zone)
    assert route.view_for(route.points[3]) == 1414          # over the sea: no zone contains it
    assert route.view_for(route.points[4]) is None
    assert route.project(1414, 0.5, 0.6, 1413) == pytest.approx((0.5, 0.5))
    assert route.project(1414, 0.9, 0.9, 1413) is None
    # Continent points are drawn on the zone map (a map change still starts a new line, as everywhere).
    assert [[t for t, _, _ in seg.points] for seg in route.segments(1413)] == [[0], [10, 20]]


def test_dungeon_moments_use_the_entrance():
    """No positions inside instances: dungeon points and events are shown at the entrance (user request)."""
    infos = {1458: {"continent_id": 1415, "min_x": 0.4, "max_x": 0.5, "min_y": 0.3, "max_y": 0.4}}
    points = [P(0, map_id=1458, x=0.7256, y=0.1130), P(4, map_id=None, x=None, y=None, instance=2999),
              P(100, map_id=1458, x=0.6790, y=0.1528),
              P(500, map_id=1458, x=0.5, y=0.5), P(700, map_id=None, x=None, y=None, instance=389)]  # too late
    route = Route(points, infos)
    assert route.entrance(2999) == (1458, 0.7256, 0.1130)          # derived: walked in 4 s later
    assert route.entrance(389) is None                              # last outdoor point 200 s earlier
    assert route.view_for(points[1]) == 1458
    assert route.locate(None, None, None, 2999) == (1458, 0.7256, 0.1130)
    recorded = Route(points, infos, entrances={389: (1454, 0.52, 0.49)})
    assert recorded.entrance(389) == (1454, 0.52, 0.49) and recorded.view_for(points[4]) == 1454


def test_import_entrances(db, addon_fixture):
    data = parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))
    data["ForeverChronicleDB"]["entrances"] = {
        "389": {"mapID": 1454, "x": 0.5195, "y": 0.4911, "source": "journal", "name": "Ragefire Chasm"},
        "2999": {"mapID": 1458, "x": 0.7256, "y": 0.113, "source": "walked"},
        "bad": {"mapID": 1, "x": 0.1, "y": 0.1}, "5": {"mapID": 1, "x": 3, "y": 0.1}}
    SavedVariablesImporter(db).import_data(data, "fixture")
    assert Repository(db.conn).entrances() == {389: (1454, 0.5195, 0.4911), 2999: (1458, 0.7256, 0.113)}


def test_map_page_shows_dungeon_death_at_entrance(db, addon_fixture, tmp_path, monkeypatch):
    """The fixture's death in Ragefire Chasm (instance 389) is pinned at the entrance once it is known."""
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.config import AppConfig
    from forever_chronicle.ui.pages.map_page import MapPage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    data = parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))
    data["ForeverChronicleDB"]["entrances"] = {"389": {"mapID": 1413, "x": 0.45, "y": 0.6, "source": "walked"}}
    ctx = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    ctx._client_searched = True
    ctx.importer.import_data(data, "fixture")
    page = MapPage(ctx)
    page.set_character(Repository(db.conn).list_characters()[0].character_id)
    death = next(e for e in ctx.repo.events(page.character_id) if e.event_type == "player_died")
    assert death.instance_id == 389 and death.map_id is None
    assert page.view_map == 1413
    tips = [item.toolTip() for item in page.view.scene().items() if item.toolTip()]
    assert any("Ragefire" in tip for tip in tips), tips
