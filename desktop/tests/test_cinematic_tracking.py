"""What the addon records since 0.16.0 for the cinematic: riding and teleport casts on the route, how a death ended,
the hearthstone, mounts, notable loot, the player's own moments and who the player was grouped with."""

import copy
import os

import pytest
from conftest import event as E
from conftest import unpack_all

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from forever_chronicle.domain import event_types, maps  # noqa: E402
from forever_chronicle.domain.cinematic import Companions, build_cues, death_spans, teleports  # noqa: E402
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.i18n import tr  # noqa: E402
from forever_chronicle.importing.sv_importer import SavedVariablesImporter, parse_group_stretch  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint, Repository  # noqa: E402

EK, KAL = maps.EASTERN_KINGDOMS, maps.KALIMDOR
GIGEL = {"name": "Gigel", "class": "MAGE", "guid": "Player-4619-0AAAAAAA"}


def P(t, x, y=0.5, map_id=EK, until=None, taxi=False, mounted=False, cause=None):
    return PositionPoint(t, until, map_id, x, y, None, taxi, cause is not None, mounted, cause)


def test_route_flags_are_parsed():
    hearth = PositionPoint.parse("100,1413,0.2000,0.2000,,JH,")
    assert hearth.jump and hearth.cause == "hearth" and not hearth.mounted
    assert PositionPoint.parse("100,1413,0.2000,0.2000,,JP,").cause == "spell"
    ridden = PositionPoint.parse("100,1413,0.2000,0.2000,110,M,")
    assert ridden.mounted and ridden.cause is None and ridden.until == 110
    assert parse_group_stretch("10,70,Gigel/MAGE/Player-4619-0AAAAAAA;Thrall-Other Realm/SHAMAN/Player-1-0B") == (
        10, 70, [GIGEL, {"name": "Thrall-Other Realm", "class": "SHAMAN", "guid": "Player-1-0B"}])
    assert parse_group_stretch("10,70,") == (10, 70, [])
    assert parse_group_stretch("10,x,Gigel/MAGE/Player-1") is None and parse_group_stretch("1,2,a/b") is None


def test_a_cast_teleport_counts_even_across_the_sea():
    moving = [P(0, 0.30), P(10, 0.32), P(20, 0.34)]
    boat = moving + [P(50, 0.6, map_id=KAL)]
    assert teleports(Route(boat), [], 0, 100) == [], "without a recorded cast: a boat"
    cast = moving + [P(30, 0.6, map_id=KAL, cause="spell")]
    [tp] = teleports(Route(cast), [], 0, 100)
    assert tp.cause == "spell" and not tp.spirit


def test_deaths_as_the_addon_recorded_them():
    route = Route([P(0, 0.3), P(100, 0.3, until=400)])
    events = [E(50, "player_died", releasedAt=70, revivedAt=130, revive="corpse"),
              E(200, "player_died", revivedAt=215, revive="player", reviver="Gigel"),
              E(300, "player_died")]
    first, second, third = death_spans(events, route)
    assert (first.time, first.released, first.revived, first.revive) == (50, 70, 130, "corpse")
    assert first.ghost(100) and not first.ghost(60) and first.dead(60)
    assert (second.released, second.revived, second.reviver) == (None, 215, "Gigel")
    assert third.revive is None, "an older death is still read from the route"


def test_cues_for_the_new_events_and_companions():
    events = [E(10, "mount_learned", name="Brown Horse", first=True, icon=132261),
              E(20, "hearth_set", place="Razor Hill"),
              E(30, "item_obtained", name="Epic Reward", quality=4, source="quest"),
              E(40, "item_obtained", name="Quest Belt", quality=2, equipped=True),
              E(50, "moment", text="Gigel dances on the table"),
              E(60, "moment"),
              E(70, "boss_killed", name="Bazzalan", instance="Ragefire Chasm"),
              E(80, "player_died", revivedAt=90, revive="player", reviver="Gigel")]
    group = Companions([(65, 100, [GIGEL]), (200, 300, [])])
    cues = build_cues(events, [], 0, 100, group)
    by_type = {c.event_type: c for c in cues}
    assert (by_type["mount_learned"].heading, by_type["mount_learned"].title) == (
        tr("cine.banner.first_mount"), "Brown Horse")
    assert by_type["mount_learned"].icon == 132261, "the mount's own game icon"
    assert by_type["hearth_set"].title == "Razor Hill"
    loot = [c for c in cues if c.event_type == "item_obtained"]
    assert [c.heading for c in loot] == [tr("cine.banner.item_epic"), tr("cine.banner.item_equipped")]
    moments = [c for c in cues if c.event_type == "moment"]
    assert [c.title for c in moments] == ["Gigel dances on the table", tr("cine.moment_untitled")]
    assert by_type["boss_killed"].place.endswith(tr("cine.with", names="Gigel")), "the boss fell with Gigel"
    revived = by_type["player_revived"]
    assert (revived.time, revived.title, revived.heading) == (90, "Gigel", tr("cine.banner.player_revived"))
    assert event_types.describe(events[-1]) and "Gigel" in event_types.detail(events[-1])
    assert group.at(250) == [] and group.at(66) == [GIGEL]


def test_import_keeps_flags_group_and_later_data(db, sv_data):
    data = unpack_all(sv_data)
    char = data["ForeverChronicleDB"]["characters"]["Player-4619-0112A417"]
    char["streams"]["positions"]["records"].append("1792000000,1413,0.2000,0.2000,,JHM,")
    char["streams"]["group"] = {"nextSeq": 2, "records": ["1792000000,1792000300,Gigel/MAGE/Player-4619-0AAAAAAA"]}
    death = next(r for r in char["streams"]["events"]["records"] if r["type"] == "player_died")
    importer = SavedVariablesImporter(db)
    importer.import_data(copy.deepcopy(data), "first")
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id
    last = next(p for p in repo.positions(cid) if p.time == 1792000000)
    assert last.mounted and last.cause == "hearth" and last.jump
    assert repo.group_stretches(cid) == [(1792000000, 1792000300, [GIGEL])]

    # Later the addon fills in the revival and moves the group's end on: the next import takes both.
    death["data"].update(revivedAt=death["time"] + 60, revive="corpse")
    char["streams"]["group"]["records"][0] = "1792000000,1792000900,Gigel/MAGE/Player-4619-0AAAAAAA"
    again = importer.import_data(data, "second")
    assert again.imported == 0
    stored = next(e for e in repo.events(cid) if e.event_type == "player_died")
    assert stored.payload["revive"] == "corpse" and stored.payload["killer"] == death["data"]["killer"]
    assert repo.group_stretches(cid)[0][1] == 1792000900


def test_window_shows_the_mount_and_a_friend_walking_along(app, ctx, imported):
    repo = ctx.repo
    cid = repo.list_characters()[0].character_id
    points = repo.positions(cid)
    start, end = points[0].time, max(p.end for p in points)
    outdoor = next(p for p in points if p.x is not None and not p.taxi)
    ctx.db.conn.execute("UPDATE positions SET mounted = 1 WHERE character_id = ? AND occurred_at = ?",
                        (cid, outdoor.time))
    friend = repo.upsert_character("Player-4619-0AAAAAAA", {"guid": "Player-4619-0AAAAAAA", "name": "Gigel",
                                                            "classFile": "MAGE"}, None)
    for p in points:
        if p.x is not None:
            repo.upsert_position(friend, PositionPoint(p.time, p.until, p.map_id, min(1, p.x + 0.01), p.y, None,
                                                       p.taxi))
    repo.upsert_group_stretch(cid, start, end, [GIGEL])
    ctx.db.conn.commit()
    from forever_chronicle.ui.cinematic import CinematicWindow

    window = CinematicWindow(ctx, cid, start, end, speed=10)
    window.resize(1000, 700)
    window.show()
    window.timer.stop()
    window.seek(outdoor.time)
    window._render(jump=True)
    assert window.marker.mode == "mount" and window.marker.mount_icon is not None
    [(times, route, item)] = window.companion_marks
    assert item.name == "Gigel" and item.isVisible() and item.scene() is window.view.scene()
    window.close()
