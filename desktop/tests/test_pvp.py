"""PvP for the chronicle and the cinematic (addon Modules/PvP.lua): enemy players defeated, killed by a player,
duels, and battleground matches that the replay jumps over."""

import os

from conftest import event as E

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from forever_chronicle.domain import event_types  # noqa: E402
from forever_chronicle.domain.cinematic import (MATCH_AFTER, banner, build_cues, death_spans,  # noqa: E402
                                                match_spans)
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.i18n import tr  # noqa: E402
from forever_chronicle.storage.repository import PositionPoint  # noqa: E402

WSG = 1460
ROGUE = dict(name="Gankzor", guid="Player-4619-0BADF00D", **{"class": "ROGUE"}, className="Rogue", race="Human",
             raceName="Human", level=31, guild="Deathwatch", faction="Alliance")


def P(t, map_id=1413, x=0.5):
    return PositionPoint(t, None, map_id, x, 0.5, None, False)


def test_pvp_events_are_named():
    kill = E(100, "pvp_kill", blow="self", rank="Private", honor=12, **ROGUE)
    assert event_types.describe(kill) == tr("evt.pvp_kill.text", name="Gankzor")
    who = tr("evt.pvp.level", level=31) + " Human Rogue <Deathwatch>"
    assert event_types.detail(kill) == who + "  ·  " + tr("evt.pvp_kill.honor_rank", rank="Private", honor=12)
    assert tr("evt.pvp_kill.blow_pet") in event_types.detail(E(100, "pvp_kill", name="X", blow="pet"))
    skull = E(100, "pvp_kill", name="Boss", level=-1)
    assert event_types.detail(skull) == tr("evt.pvp.level", level="??"), "a level too high to see"

    death = E(200, "player_died", killer="Gankzor", killerType="player", killerLevel=31, killerRaceName="Human",
              killerClassName="Rogue", killerGuild="Deathwatch", spell="Eviscerate", damage=300)
    assert who in event_types.detail(death), "the death names who the killer was"

    assert event_types.describe(E(1, "duel", name="Frosty", won=True)) == tr("evt.duel.won", name="Frosty")
    assert event_types.describe(E(1, "duel", name="Frosty", won=True, fled=True)) == tr("evt.duel.won_fled", name="Frosty")
    assert event_types.describe(E(1, "duel", name="Frosty", won=False)) == tr("evt.duel.lost", name="Frosty")
    assert event_types.describe(E(1, "duel", name="Frosty", won=False, fled=True)) == tr("evt.duel.fled", name="Frosty")

    won = E(900, "battleground", name="Warsong Gulch", result="won", killingBlows=4, honorableKills=11, deaths=2,
            honor=250, faction="Horde")
    assert event_types.describe(won) == tr("evt.battleground.won", name="Warsong Gulch")
    assert event_types.detail(won) == (tr("evt.battleground.score", kb=4, hk=11, deaths=2) + "  ·  "
                                       + tr("evt.battleground.honor", honor=250))
    assert event_types.describe(E(1, "battleground", name="Arathi Basin")) == \
        tr("evt.battleground.played", name="Arathi Basin")
    alliance = E(1, "battleground", name="X", faction="Alliance")
    assert event_types.icon_of(won).endswith("INV_BannerPVP_01") and event_types.icon_of(alliance).endswith("02")
    assert event_types.icon_of(won, pin=True).endswith("INV_BannerPVP_01"), "the map pin keeps the faction"
    assert all(i in event_types.all_icons() for i in event_types.BANNERS.values())

    heading, title, _ = banner(won, None)
    assert heading == tr("cine.banner.battleground.won") and title == "Warsong Gulch"
    assert banner(E(1, "duel", name="Frosty", won=False), None)[0] == tr("cine.banner.duel.lost")


def test_battleground_deaths_get_no_death_scene():
    route = Route([P(t) for t in range(0, 400, 10)])
    world = E(100, "player_died", killer="Gankzor", killerType="player")
    match = E(200, "player_died", killer="Frosty", killerType="player", battleground="pvp")
    kill = E(300, "pvp_kill", **ROGUE)
    cues = build_cues([world, match, kill], [], 0, 1000)
    assert [c.event_type for c in cues] == ["player_died", "pvp_kill"], "no toast for a death inside a match"
    assert [d.time for d in death_spans([world, match], route)] == [100]


def test_matches_are_jumped_over():
    # Queued in the Barrens, 15 minutes in Warsong Gulch, 90 seconds at the score board, then back outside.
    route = Route([P(t) for t in range(0, 100, 10)] + [P(t, WSG) for t in range(100, 1090, 10)]
                  + [P(t) for t in range(1090, 1200, 10)])
    bg = E(1000, "battleground", name="Warsong Gulch", mapID=WSG, instanceID=489, startedAt=100, duration=900,
           result="won")
    assert match_spans([bg], route, 0, 2000) == [(100.0, 1090.0, "Warsong Gulch")], "until the first point outside"
    assert match_spans([bg], route, 500, 800) == [(500.0, 800.0, "Warsong Gulch")], "cut to the range"

    no_start = E(1000, "battleground", name="Warsong Gulch", mapID=WSG, duration=900)
    assert match_spans([no_start], route, 0, 2000)[0][0] == 100.0, "the start from the duration"
    alone = Route([P(t, WSG) for t in range(100, 1010, 10)])
    assert match_spans([bg], alone, 0, 5000)[0][1] == 1000 + MATCH_AFTER, "no later point: a while after the end"
    inside = Route([P(t, None) for t in range(0, 50, 10)]
                   + [PositionPoint(t, None, None, None, None, 489, False) for t in range(100, 1100, 10)]
                   + [P(t) for t in range(1100, 1200, 10)])
    no_map = E(1000, "battleground", name="Warsong Gulch", instanceID=489, startedAt=100)
    assert match_spans([no_map], inside, 0, 2000)[0][1] == 1100.0, "no position inside: the instance tells"

    cues = build_cues([bg], [], 0, 2000)
    assert len(cues) == 1 and cues[0].event_type == "battleground", "the match's result is shown"


def test_cinematic_skips_a_match(app, ctx, imported):
    """The window jumps from the match's start to just before its result, then past its end."""
    from forever_chronicle.ui.cinematic import CinematicWindow
    w = CinematicWindow.__new__(CinematicWindow)
    w.match_spans = [(100.0, 1090.0, "Warsong Gulch")]
    w.match_starts = [100.0]
    cue = build_cues([E(1000, "battleground", name="Warsong Gulch", result="won")], [], 0, 2000)
    w.cues, w.cue_index, w.still_note = cue, 0, 0.0

    class Label:
        def setText(self, text): self.text = text
    w.still_label = Label()
    w._layout_still = lambda: None
    assert w._skip_match(50.0) == 50.0, "outside a match"
    assert w._skip_match(101.0) == 999.0, "up to just before the result"
    assert "Warsong Gulch" in w.still_label.text and w.still_note > 0
    w.cue_index = 1                                          # the result was shown
    assert w._skip_match(1001.0) == 1090.0, "then past the end of the match"
