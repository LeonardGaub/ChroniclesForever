import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from forever_chronicle.domain.route import GAP_SECONDS, Route  # noqa: E402
from forever_chronicle.importing.sv_importer import SavedVariablesImporter  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint, Repository  # noqa: E402
from forever_chronicle.wow.map_art import find_art  # noqa: E402


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
    assert p.taxi and not p.jump and p.until == 160 and p.end == 160
    assert PositionPoint.parse("100,1413,0.1,0.2,,J,").jump


def test_loading_screen_breaks_the_route(db):
    """The addon's "J" flag (first point after a loading screen) survives the import and ends the line, even for a
    step too short and slow to look like a teleport."""
    repo = Repository(db.conn)
    cid = repo.upsert_character("P-1", {"name": "Leon"}, None)
    repo.upsert_position(cid, PositionPoint.parse("100,1413,0.5000,0.5000,,,"))
    repo.upsert_position(cid, PositionPoint.parse("140,1413,0.5050,0.5000,,,"))   # imported before the fix
    repo.upsert_position(cid, PositionPoint.parse("140,1413,0.5050,0.5000,,J,"))  # the same point again
    route = Route(repo.positions(cid))
    assert route.points[1].jump and [len(s.points) for s in route.segments(1413)] == [1, 1]


def test_import_positions_and_geometry(db, sv_data):
    importer = SavedVariablesImporter(db)
    result = importer.import_data(sv_data, "fixture")
    assert result.positions >= 12 and result.invalid == 0
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id
    points = repo.positions(cid)
    assert len(points) == result.positions
    assert points[-1].until is not None, "standing still at the end extends the last point"
    info = repo.map_infos()[1413]
    assert info["continent_id"] == 1414 and info["min_x"] == 0.4
    again = importer.import_data(sv_data, "fixture")
    assert len(repo.positions(cid)) == len(points) and again.gaps == 0


def test_import_route_archive(db, sv_data):
    """Thinned old points from the addon's route archive fill in what was not imported in time."""
    char = next(iter(sv_data["ForeverChronicleDB"]["characters"].values()))
    char["streams"]["routeArchive"] = {"nextSeq": 2, "records": ["1000,1413,0.3000,0.5000,,,;1020,1413,0.3200,0.5000,1030,,"]}
    result = SavedVariablesImporter(db).import_data(sv_data, "fixture")
    repo = Repository(db.conn)
    points = repo.positions(repo.list_characters()[0].character_id)
    assert result.invalid == 0 and points[0].time == 1000 and points[1].time == 1020 and points[1].until == 1030


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


def test_map_images_come_from_one_folder(tmp_path):
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "1413.jpg").write_bytes(b"x")
    assert find_art(1413) == tmp_path / "maps" / "1413.jpg"
    assert find_art(9999) is None and find_art(None) is None


def test_cinema_page_chapters_and_play(ctx, imported, tmp_path):
    """The Kino tab replaced the map page (user decision 2026-11-02): the journey, its chapters, and the way into
    the cinematic mode."""
    from forever_chronicle.ui.main_window import MainWindow
    from forever_chronicle.ui.cards import DATA

    window = MainWindow(ctx)
    page = window.page("tab.cinema")
    assert window.page("tab.map") is None, "the map page is gone"
    window.show_page(page)
    cid = window.current_character_id()
    sessions = ctx.repo.sessions(cid)
    assert page.chapters and len(page.chapters) <= len(sessions)
    assert [c.number for c in page.chapters] == list(range(1, len(page.chapters) + 1))
    entries = page.list.entries()
    assert len(entries) == len(page.chapters) and entries[0].data(DATA)[0] == page.chapters[-1].start  # newest first
    assert not page.play_chosen.isEnabled() and page.banner.span is None
    assert page.banner.texts[1] == "Die Reise von Blind"

    page.list.setCurrentItem(entries[0])
    chosen = entries[0].data(DATA)
    assert page.play_chosen.isEnabled() and page.banner.span == chosen
    cinematic = page.play_selected()
    assert cinematic is not None and (cinematic.start, cinematic.end) == chosen
    cinematic.close()
    if len(entries) > 1:            # several chapters play as one, from the first start to the last end
        entries[1].setSelected(True)
        span = page.selected_span()
        assert span == (entries[1].data(DATA)[0], chosen[1]) and "2" in page.play_chosen.text()
    whole = page.play_all()
    route = Route.load(ctx.repo, cid)
    assert whole.start == route.start
    whole.close()
    window.close()


def test_cinema_banner_on_the_world_map(ctx, imported, tmp_path, app):
    """The banner paints the whole journey on the world map and lights up the chosen chapter."""
    from forever_chronicle.ui import journey_art
    from forever_chronicle.ui.pages.cinema import CinemaPage

    (tmp_path / "maps" / "world").mkdir(parents=True)
    (tmp_path / "maps" / "world" / "base.jpg").write_bytes(_jpeg_bytes())
    page = CinemaPage(ctx)
    page.resize(1100, 700)
    page.character_id = ctx.repo.list_characters()[0].character_id
    page.refresh()
    page.banner.resize(1100, 320)
    page.banner._rebuild()
    route = Route.load(ctx.repo, page.character_id)
    area = journey_art.bounds(route)
    assert area is not None and page.banner.layer is not None and page.banner.marker is not None
    assert 0 <= page.banner.marker.x() <= 1100 and 0 <= page.banner.marker.y() <= 320
    whole = page.banner.marker
    page.list.setCurrentItem(page.list.entries()[-1])          # the oldest chapter ends elsewhere
    assert page.banner.span is not None and page.banner.lit is not None
    page.banner.grab()                                          # paints without errors
    page.list.clearSelection()
    assert page.banner.span is None and page.banner.marker == whole
    home_picture = journey_art.picture(route, page.banner.colors, QSize(420, 236))
    assert home_picture is not None and home_picture.width() == 420


def test_chronicle_plays_from_the_chosen_moment(ctx, imported):
    from forever_chronicle.ui.cards import DATA, TITLE
    from forever_chronicle.ui.main_window import MainWindow

    window = MainWindow(ctx)
    timeline = window.page("tab.timeline")
    window.show_page(timeline)
    assert not timeline.play_here.isEnabled()
    death = next(item for item in timeline.list.entries() if "Getötet von" in item.data(TITLE))
    timeline.list.setCurrentItem(death)
    assert timeline.play_here.isEnabled()
    cinematic = timeline.play_selected()
    t = death.data(DATA)[0]
    assert cinematic.start <= t < cinematic.end and t - cinematic.start <= 30
    cinematic.close()
    window.close()


def test_route_colours_are_chosen_in_the_settings(ctx, app):
    from forever_chronicle.ui.pages.settings import SettingsPage

    page = SettingsPage(ctx)
    page.refresh()
    assert page.colors.currentData() == ctx.map_colors == "level"
    page.colors.setCurrentIndex(page.colors.findData("session"))
    assert ctx.map_colors == "session"


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


def test_import_entrances(db, sv_data):
    sv_data["ForeverChronicleDB"]["entrances"] = {
        "389": {"mapID": 1454, "x": 0.5195, "y": 0.4911, "source": "journal", "name": "Ragefire Chasm"},
        "2999": {"mapID": 1458, "x": 0.7256, "y": 0.113, "source": "walked"},
        "bad": {"mapID": 1, "x": 0.1, "y": 0.1}, "5": {"mapID": 1, "x": 3, "y": 0.1}}
    SavedVariablesImporter(db).import_data(sv_data, "fixture")
    assert Repository(db.conn).entrances() == {389: (1454, 0.5195, 0.4911), 2999: (1458, 0.7256, 0.113)}
