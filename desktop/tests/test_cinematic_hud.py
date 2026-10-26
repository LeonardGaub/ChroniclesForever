"""Cinematic HUD: the experience bar's fill from the addon's samples, and the game's XP bar."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QWidget  # noqa: E402

from forever_chronicle.domain.cinematic import Levels  # noqa: E402
from forever_chronicle.domain.experience import XP_TO_NEXT, Experience  # noqa: E402
from forever_chronicle.storage.repository import EventRow  # noqa: E402


def up(t, level):
    return EventRow("c", f"e{t}", "level_up", t, None, None, None, None, None, {"level": level})


LEVELS = Levels([up(1000, 5), up(2000, 6)])
SAMPLES = [(500, 100, 4), (1000, 400, 5), (1500, 1400, 5), (2000, 2400, 6), (2500, 2900, 6)]


def test_experience_from_samples():
    xp = Experience(LEVELS, SAMPLES)
    assert xp.at(1500) == (5, pytest.approx(0.5)), "the level's size: experience between its level-ups"
    assert xp.values(1500) == (5, pytest.approx(0.5), 2000), "and the points: the level's size"
    assert xp.at(2500) == (6, pytest.approx(500 / XP_TO_NEXT[6])), "the level still going: the table's size"
    assert xp.at(700) == (4, pytest.approx((220 + XP_TO_NEXT[4] - 400) / XP_TO_NEXT[4])), \
        "a level begun before tracking starts where the next level-up says"
    assert xp.at(400)[1] is None, "before the first sample nothing is known"
    assert xp.at(9000) == (6, pytest.approx(500 / XP_TO_NEXT[6])), "after the last sample nothing changed"

    anchored = Experience(LEVELS, SAMPLES, anchor=(2500, 500, 3000))
    assert anchored.at(2500) == (6, pytest.approx(500 / 3000)), "the bar as the game showed it sizes the level"
    alone = Experience(Levels([], 9), [(0, 0, 9), (100, 600, 9)], anchor=(100, 1000, 4000))
    assert alone.at(0) == (9, pytest.approx(400 / 4000)) and alone.at(100) == (9, pytest.approx(0.25)), \
        "without any level-up the anchor alone places the bar"


def test_experience_by_playing_time():
    xp = Experience(LEVELS, [])
    assert xp.at(1500) == (5, pytest.approx(0.5)), "without samples: playing time between the level-ups"
    assert xp.values(1500)[2] is None, "no points without samples"
    assert xp.at(2500) == (6, None), "the level still going is unknown"
    assert Experience(Levels([up(10, 60)])).at(20) == (60, None), "the highest level has no bar"
    assert Experience(Levels([])).at(5) == (None, None)


def test_xp_bar_fills_up_at_a_level_up(app):
    from forever_chronicle.ui.cinematic_hud import XpBar

    parent = QWidget()
    bar = XpBar(parent)
    bar.resize(600, 24)
    bar.set_target(5, 0.9)
    assert (bar.level, bar.share) == (5, 0.9), "the first target is taken at once"
    bar.set_target(5, 0.95)
    bar.advance(0.05)
    assert 0.9 < bar.share < 0.95, "glides towards the experience"
    bar.set_target(6, 0.05)
    for _ in range(20):
        bar.advance(0.05)
        if bar.level == 6:
            break
    assert bar.level == 6 and bar.flash > 0.5, "fills up, then flashes on the new level"
    for _ in range(40):
        bar.advance(0.05)
    assert bar.share == pytest.approx(0.05, abs=0.01) and bar.flash == 0
    assert bar.text() == "EP: 5 %", "without the level's size: the share"
    bar.set_target(6, 0.5, 3600)
    bar.snap()
    assert bar.text() == "EP: 1800 / 3600", "the points, as the game shows them"
    assert not bar.frame.isNull() and not bar.fill.isNull(), "the game's frame and fill (the skin, in git)"
    bar.resize(bar.WIDTH, bar.height_for(bar.WIDTH))
    assert bar.height() == 15
    bar.grab()
    bar.set_target(3, None)
    bar.advance(0.05)
    assert (bar.level, bar.share, bar.text()) == (3, None, ""), "a jump back shows the level at once"
    bar.grab()                                   # paints without the share


def test_metrics_and_bar_imported(ctx, imported):
    char = ctx.repo.list_characters()[0]
    samples = ctx.repo.metrics(char.character_id)
    assert samples and all(a[0] <= b[0] for a, b in zip(samples, samples[1:])), "the minute samples, in order"
    assert char.xp is not None and char.xp[1:] == (1000, 5000), "the bar as the addon last saw it"
