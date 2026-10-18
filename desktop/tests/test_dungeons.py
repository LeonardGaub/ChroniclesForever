"""Dungeon maps on the desktop (domain/dungeons.py, ui/dungeon_view.py, tools/build_dungeon_maps.py --desktop)."""

import importlib.util
import io
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import unpack_all  # noqa: E402
from forever_chronicle import i18n  # noqa: E402
from forever_chronicle.domain import dungeons  # noqa: E402
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.storage.repository import EventRow, PositionPoint  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RFC = 389                       # Ragefire Chasm, the fixture's dungeon
ENTER, LEAVE = 1791961075, 1791961120   # after the fixture's quest, which is outside
BOSSES = ((1791961080, "Oggleflint"), (1791961095, "Taragaman the Hungerer"))   # the death is at 1791961103


def P(t, map_id=1413, x=0.5, y=0.5, until=None, instance=None):
    return PositionPoint(t, until, map_id, x, y, instance, False)


def E(t, kind, instance=None, **payload):
    return EventRow("c", f"e{t}", kind, t, None, None, None, None, None, payload, instance)


def write_table(folder: Path, floors: int = 2) -> None:
    """dungeons.json and the floor pictures as tools/build_dungeon_maps.py writes them."""
    folder.mkdir(parents=True, exist_ok=True)
    names = [{"en": "Upper", "de": "Oben"}, {"en": "Lower", "de": "Unten"}][:floors] if floors > 1 else [None]
    table = {"dungeons": {str(RFC): {"name": {"en": "Ragefire Chasm", "de": "Flammenschlund"},
                                     "floors": [{"name": n} for n in names]},
                          "36": {"name": {"en": "Deadmines", "de": "Todesminen"}, "floors": [{"name": None}]}}}
    (folder / "dungeons.json").write_text(json.dumps(table), encoding="utf-8")
    for floor in range(1, floors + 1):
        image = QImage(1002, 668, QImage.Format.Format_RGB32)
        image.fill(QColor("#806040" if floor == 1 else "#405080"))
        image.save(str(folder / f"dungeon_{RFC}_{floor}.jpg"))


def test_table_names_views_and_art(tmp_path):
    assert dungeons.table() == {} and dungeons.view_key(RFC) is None, "without dungeons.json: no dungeon maps"
    write_table(tmp_path / "maps")
    rfc = dungeons.get(RFC)
    assert rfc.floors == 2 and dungeons.get(2999) is None
    assert rfc.art(1) == tmp_path / "maps" / "dungeon_389_1.jpg" and rfc.art(3) is None
    assert dungeons.get(36).art(1) is None, "a dungeon whose picture is missing"
    language = i18n.language()
    try:
        i18n.set_language("de")
        assert rfc.name() == "Flammenschlund" and rfc.floor_name(2) == "Unten"
        i18n.set_language("en")
        assert rfc.name() == "Ragefire Chasm" and rfc.floor_name(1) == "Upper" and rfc.floor_name(9) is None
    finally:
        i18n.set_language(language)
    assert dungeons.get(36).floor_name(1) is None
    assert dungeons.view_key(RFC) == "dungeon:389" and dungeons.view_key(2999) is None
    assert dungeons.dungeon_of("dungeon:389") == RFC
    assert dungeons.dungeon_of(1413) is None and dungeons.dungeon_of("dungeon:x") is None


def test_views_in_visiting_order(tmp_path):
    write_table(tmp_path / "maps")
    infos = {1413: {"continent_id": 1414, "min_x": 0.4, "max_x": 0.6, "min_y": 0.5, "max_y": 0.7},
             1454: {"continent_id": 1414, "min_x": 0.45, "max_x": 0.5, "min_y": 0.5, "max_y": 0.55}}
    route = Route([P(0), P(10, map_id=None, x=None, y=None, instance=RFC), P(50, map_id=1454),
                   P(60, map_id=None, x=None, y=None, instance=2999)], infos)
    assert dungeons.available_views(route) == [1413, "dungeon:389", 1454, 1414], \
        "dungeons with a map among the zones in the order of the first visit; Forever's own dungeons have none"
    assert dungeons.view_for(route, route.points[1]) == "dungeon:389"
    assert dungeons.view_for(route, route.points[0]) == 1413
    assert dungeons.view_for(route, route.points[3]) == route.view_for(route.points[3]), "no map: the entrance"
    assert dungeons.view_for(route, None) is None


def test_visits_entries_and_times(tmp_path):
    write_table(tmp_path / "maps")
    inside = lambda t, until: P(t, None, None, None, until, RFC)  # noqa: E731
    gap = dungeons.VISIT_GAP
    route = Route([P(0, until=90), inside(100, 400), P(410, until=500),      # a corpse run outside ...
                   inside(600, 900),                                          # ... belongs to the same visit
                   P(910, until=900 + gap + 50), inside(900 + gap + 100, 900 + gap + 200)])
    found = dungeons.visits(route, RFC, 0, 10**6)
    assert [(v.start, v.end) for v in found] == [(100, 910), (900 + gap + 100, 900 + gap + 200)], \
        "a visit lasts until the next place begins (as the timeline's zone bands)"
    assert [(v.start, v.end) for v in dungeons.visits(route, RFC, 0, 300)] == [(100, 300)], "only the shown range"
    assert dungeons.visits(route, 36, 0, 10**6) == []
    assert dungeons.visit_at(found, 50) == 0 and dungeons.visit_at(found, 700) == 0
    assert dungeons.visit_at(found, 10**6) == 1 and dungeons.visit_at([], 5) is None

    events = [E(450, "player_died", RFC), E(300, "boss_killed", RFC, name="Oggleflint"), E(50, "level_up"),
              E(800, "boss_killed", RFC, name="Taragaman"), E(700, "quest_completed")]
    entries = dungeons.visit_entries(events, found[0])
    assert [(e.event.event_type, e.offset, e.boss) for e in entries] == [
        ("boss_killed", 200, 1), ("player_died", 350, None), ("quest_completed", 600, None),
        ("boss_killed", 700, 2)], "every event of the visit in time order, bosses numbered in kill order"
    assert dungeons.visit_entries(events, found[1]) == []
    assert [dungeons.since_entering(s) for s in (0, 65, 3600 + 125, -3)] == ["+0:00", "+1:05", "+1:02:05", "+0:00"]


def _dungeon_data(addon_fixture):
    """The fixture with a visit to Ragefire Chasm: its death there, and two boss kills."""
    data = unpack_all(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")))
    char = next(iter(data["ForeverChronicleDB"]["characters"].values()))
    positions = char["streams"]["positions"]["records"]
    assert positions[0].startswith("1791961001,1413,")
    positions[0:1] = ["1791961001,1413,0.4403,0.5913,1791961074,,", f"{ENTER},,,,{LEAVE},,{RFC}",
                      "1791961122,1413,0.4403,0.5913,1791961132,,"]
    events = char["streams"]["events"]["records"]
    session = events[0]["session"]
    for i, (t, name) in enumerate(BOSSES):
        events.append({"data": {"name": name, "instance": "Ragefire Chasm", "encounterID": 1000 + i},
                       "id": f"boss{i}", "location": {"instanceID": RFC, "quality": "zone_only",
                                                      "zone": "Ragefire Chasm"},
                       "seq": 500 + i, "serverTime": t, "session": session, "time": t, "type": "boss_killed"})
    events.sort(key=lambda r: r["time"])
    return data


def _ctx(db, tmp_path, monkeypatch, addon_fixture):
    from forever_chronicle.app_context import AppContext
    from forever_chronicle.config import AppConfig
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    ctx = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    ctx._client_searched = True
    ctx.importer.import_data(_dungeon_data(addon_fixture), "fixture")
    return ctx


def test_map_page_shows_the_dungeon_and_its_visit(db, tmp_path, monkeypatch, addon_fixture):
    from forever_chronicle.ui.pages.map_page import MapPage
    QApplication.instance() or QApplication([])
    write_table(tmp_path / "maps")
    ctx = _ctx(db, tmp_path, monkeypatch, addon_fixture)
    page = MapPage(ctx)
    page.resize(1200, 800)
    page.show()
    page.set_character(ctx.repo.list_characters()[0].character_id)
    views = [page.map_select.itemData(i) for i in range(page.map_select.count())]
    assert views == [1413, "dungeon:389", 1414], views
    assert page.view_map == 1413

    page._set_time(BOSSES[0][0] + 1)                        # the replay walks into the dungeon: the map follows
    assert page.view_map == "dungeon:389"
    assert not page.marker.isVisible(), "no position inside dungeons"
    assert page.visit_panel.isVisible() and page.floor_bar.isVisible()
    assert page.notice.text() == i18n.tr("map.dungeon_no_position")
    rows = [r for r in page.visit_panel.rows if not r.isHidden()]
    texts = [r.full for r in rows]
    assert texts[0] == "1. Oggleflint" and texts[1] == "2. Taragaman the Hungerer" and len(rows) == 3, texts
    assert rows[0].when.text() == f"+0:{BOSSES[0][0] - ENTER:02d}"
    assert rows[0].fade.opacity() == 1.0 and rows[2].fade.opacity() < 1.0, "later moments are grey"
    assert page.visit_panel.title.text() == "Ragefire Chasm"
    assert not [i for i in page.view.scene().items() if i.toolTip()], "no pins on a dungeon map"

    page.floor_bar.stepped.emit(1)                          # the second floor
    assert page._floor(dungeons.get(RFC)) == 2 and "Lower" in page.floor_bar.label.text()
    page.floor_bar.stepped.emit(1)
    assert page._floor(dungeons.get(RFC)) == 1, "the arrows go round"

    page.visit_panel.jump.emit(BOSSES[1][0])                # a click on an entry jumps there
    assert page.current_t == BOSSES[1][0] and rows[1].fade.opacity() == 1.0

    page._set_time(LEAVE + 20)                              # out again: back to the zone
    assert page.view_map == 1413 and not page.visit_panel.isVisible() and page.marker.isVisible()

    page.map_select.setCurrentIndex(1)                      # picked by hand while outside: it stays
    assert page.view_map == "dungeon:389" and page.visit_panel.isVisible()
    assert page.notice.text() == i18n.tr("map.elsewhere", name=page._view_name(1413))
    page.close()


def test_map_page_without_dungeon_maps_keeps_the_entrance(db, tmp_path, monkeypatch, addon_fixture):
    from forever_chronicle.ui.pages.map_page import MapPage
    QApplication.instance() or QApplication([])
    ctx = _ctx(db, tmp_path, monkeypatch, addon_fixture)
    page = MapPage(ctx)
    page.set_character(ctx.repo.list_characters()[0].character_id)
    page._set_time(BOSSES[0][0] + 1)
    assert page.view_map == 1413 and not page.visit_panel.isVisible()


def test_cinematic_shows_the_dungeon_map_with_the_visit_so_far(db, tmp_path, monkeypatch, addon_fixture):
    from forever_chronicle.ui import theme
    from forever_chronicle.ui.cinematic import CinematicWindow
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    write_table(tmp_path / "maps", floors=1)
    ctx = _ctx(db, tmp_path, monkeypatch, addon_fixture)
    cid = ctx.repo.list_characters()[0].character_id
    window = CinematicWindow(ctx, cid, 1791961001, 1791962120, speed=1)
    window.resize(1200, 800)
    window.show()
    window.timer.stop()
    overlay = window.dungeon_overlay
    assert not overlay.isVisible()

    window.seek(BOSSES[0][0] + 1)
    assert overlay.isVisible() and overlay.opacity == 1.0, "a seek into the dungeon shows it at once"
    assert overlay.title == "Ragefire Chasm" and overlay.pixmap is not None
    assert [e.boss for e in overlay.entries] == [1], "only what has happened so far"
    for _ in range(400):
        window.advance(0.05)
        if window.t >= BOSSES[1][0] + 1:
            break
    assert [e.boss for e in overlay.entries][:2] == [1, 2]
    assert overlay.ages["boss1"] < 5, "the new entry glows"
    image = window.grab().toImage()
    assert not image.isNull()

    window.seek(LEAVE + 30)
    assert not overlay.isVisible() and overlay.opacity == 0.0
    window.close()


def test_tool_writes_the_desktop_pictures(tmp_path):
    from PIL import Image
    spec = importlib.util.spec_from_file_location("build_dungeon_maps", REPO / "tools" / "build_dungeon_maps.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    def tile(color):
        out = io.BytesIO()
        Image.new("RGB", (256, 256), color).save(out, "PNG")
        return out.getvalue()

    class Storage:
        files = {1: tile("red"), 2: tile("blue")}

        def read_fdid(self, fdid):
            return self.files[fdid]

    layer = (1002, 668, 256, 256)
    names = {"enUS": "Hall", "deDE": None}
    dungeons_in = {
        RFC: {"names": {"enUS": "Ragefire Chasm", "deDE": "Ragefireabgrund"},
              "floors": [{"uiMap": 1, "layer": layer, "tiles": [1] * 12, "names": {"enUS": "x", "deDE": "y"}}]},
        36: {"names": {"enUS": "Deadmines", "deDE": "Todesminen"},
             "floors": [{"uiMap": 2, "layer": layer, "tiles": [1] * 12, "names": names},
                        {"uiMap": 3, "layer": (512, 512, 256, 256), "tiles": [2] * 4,
                         "names": {"enUS": None, "deDE": None}}]}}
    folder = tmp_path / "maps"
    folder.mkdir()
    (folder / "dungeon_999_1.jpg").write_bytes(b"old")
    tool.write_desktop(dungeons_in, Storage(), folder)
    assert sorted(p.name for p in folder.glob("dungeon_*.jpg")) == ["dungeon_36_1.jpg", "dungeon_36_2.jpg",
                                                                     "dungeon_389_1.jpg"]
    for path in folder.glob("dungeon_*.jpg"):
        assert Image.open(path).size == (1002, 668), "the zone maps' canvas"
    assert Image.open(folder / "dungeon_36_2.jpg").getpixel((500, 300))[2] > 200, "a smaller layer is scaled up"
    table = json.loads((folder / "dungeons.json").read_text(encoding="utf-8"))["dungeons"]
    assert table["389"] == {"name": {"en": "Ragefire Chasm", "de": "Ragefireabgrund"}, "floors": [{"name": None}]}
    assert table["36"]["floors"] == [{"name": {"en": "Hall", "de": "Hall"}}, {"name": None}]


def test_shipped_dungeon_maps_are_complete():
    """The pictures in git match their table (rerun tools/build_dungeon_maps.py after a client patch)."""
    folder = REPO / "desktop" / "forever_chronicle" / "maps"
    table = json.loads((folder / "dungeons.json").read_text(encoding="utf-8"))["dungeons"]
    assert len(table) >= 20
    expected = {f"dungeon_{i}_{n}.jpg" for i, d in table.items() for n in range(1, len(d["floors"]) + 1)}
    assert {p.name for p in folder.glob("dungeon_*.jpg")} == expected
    assert all(d["name"]["en"] and d["name"]["de"] for d in table.values())
    assert "36" in table and "389" in table, "Deadmines and Ragefire Chasm"


@pytest.fixture(autouse=True)
def _english():
    language = i18n.language()
    i18n.set_language("en")
    yield
    i18n.set_language(language)
