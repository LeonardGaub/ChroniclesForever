"""Sound: built-in files, own sounds and music, settings, the click filter, music fades and ducking."""

import os
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton, QTabBar  # noqa: E402

from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.ui import sound  # noqa: E402
from forever_chronicle.ui.sound import (BUILTIN_MUSIC, DUCK, EFFECTS, FADE_IN, FADE_OUT, MusicPlayer, Sound,  # noqa: E402
                                        effect_path, gain, music_tracks)


def test_built_in_sounds_exist():
    for name in EFFECTS:
        with wave.open(str(sound.ASSETS / f"{name}.wav")) as w:   # QSoundEffect plays WAV only
            assert w.getframerate() == 44100 and w.getnframes() > 0, name
    assert BUILTIN_MUSIC.is_file() and BUILTIN_MUSIC.stat().st_size > 100_000


def test_own_sounds_and_music(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    assert effect_path("click") == sound.ASSETS / "click.wav"
    own = tmp_path / "sounds" / "click.wav"
    own.parent.mkdir()
    own.write_bytes(b"RIFF")
    assert effect_path("click") == own and effect_path("death") == sound.ASSETS / "death.wav"

    assert music_tracks(None) == [BUILTIN_MUSIC]
    assert music_tracks(str(tmp_path / "missing.mp3")) == [BUILTIN_MUSIC]
    folder = tmp_path / "music"
    folder.mkdir()
    assert music_tracks(str(folder)) == [BUILTIN_MUSIC], "an empty folder plays the built-in theme"
    for name in ("b.ogg", "a.MP3", "cover.jpg"):
        (folder / name).write_bytes(b"x")
    assert [p.name for p in music_tracks(str(folder))] == ["a.MP3", "b.ogg"]
    assert music_tracks(str(folder / "b.ogg")) == [folder / "b.ogg"]


def test_play_follows_the_settings(app):
    config = AppConfig()
    s = Sound(config)
    assert s.play("level_up") and not s.play("level_up"), "the same alert does not stack within a moment"
    config.event_sounds = False
    assert not s.play("event") and s.play("event", force=True), "the settings' test button always plays"
    config.click_sounds = False
    assert not s.play("click")
    config.click_sounds, config.effects_volume = True, 0
    assert not s.play("click")
    assert list(s.played) == ["level_up", "event"]
    assert gain(0) == 0 and gain(100) == 1 and gain(50) == 0.25


def test_clicks_on_buttons_and_tabs(app):
    s = Sound(AppConfig())
    s.install_click_sounds(app)
    try:
        button, label, off = QPushButton("ok"), QLabel("text"), QPushButton("off")
        off.setEnabled(False)
        tabs = QTabBar()
        tabs.addTab("a")
        tabs.addTab("b")
        for w in (button, label, off, tabs):
            w.resize(300, 40)
            w.show()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert list(s.played) == ["click"]
        s._last.clear()
        QTest.mouseClick(label, Qt.MouseButton.LeftButton)
        QTest.mouseClick(off, Qt.MouseButton.LeftButton)
        QTest.mouseClick(button, Qt.MouseButton.RightButton)
        assert list(s.played) == ["click"], "only left clicks on things that can be clicked"
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(1).center())
        assert list(s.played) == ["click", "click"]
    finally:
        app.removeEventFilter(s)


def test_music_fades_and_ducks(app):
    config = AppConfig(music=False)
    music = MusicPlayer(config)
    music.start()
    assert not music.active, "music off: cinematic mode stays quiet"
    music.start(force=True)
    assert music.active and music.tracks == [BUILTIN_MUSIC]
    music.step(FADE_IN / 2)
    assert music.level() == pytest.approx(gain(config.music_volume) / 2)
    music.step(FADE_IN)
    assert music.fade == 1.0 and music.level() == pytest.approx(gain(50))

    music.duck(2.0)
    for _ in range(10):
        music.step(0.1)
    assert music.duck_level == pytest.approx(DUCK)
    for _ in range(40):
        music.step(0.1)
    assert music.duck_level == 1.0 and music.duck_left == 0

    music.stop()
    assert not music.active
    music.step(FADE_OUT)
    assert music.fade == 0.0 and not music.timer.isActive()


def test_music_switches_with_a_fade(app, tmp_path):
    from forever_chronicle.ui.sound import SWITCH_IN, SWITCH_OUT
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    music = MusicPlayer(AppConfig())
    music.start(tracks=[a])
    music.step(FADE_IN)
    assert music.tracks == [a] and music.fade == 1.0
    music.play([b])
    assert music.pending == [b] and music.tracks == [a], "the old music fades out first"
    music.step(SWITCH_OUT / 2)
    assert 0 < music.fade < 1 and music.tracks == [a]
    music.step(SWITCH_OUT)
    assert music.tracks == [b] and music.pending is None and music.fade < 0.5, "then the new one starts"
    music.step(SWITCH_IN)
    assert music.fade == 1.0 and not music.switched
    music.play([b])
    assert music.pending is None, "the same music again changes nothing"
    music.play(None, (4.0, 3.0))
    assert music.pending == [BUILTIN_MUSIC], "None: the music chosen in the settings"
    music.step(SWITCH_OUT)
    assert music.pending == [BUILTIN_MUSIC] and music.fade > 0, "a slower switch (the credits) fades out longer"
    music.step(4.0)
    music.step(3.0)
    assert music.tracks == [BUILTIN_MUSIC] and music.fade == 1.0 and music.switching is None

    quiet = MusicPlayer(AppConfig(), audible=False)
    quiet.start(tracks=[a])
    assert quiet.active and quiet.tracks == [a]
    assert not quiet.timer.receivers("2timeout()"), "a silent player is stepped by its owner (the export)"
    quiet.stop_now()
    quiet.play([b])
    assert quiet.tracks == [b] and quiet.pending is None, "not playing: loaded for the next start"


def test_loop_players_cross_over_and_follow_the_effects(app, tmp_path):
    from forever_chronicle.ui.sound import LoopPlayer
    a, b = tmp_path / "a.ogg", tmp_path / "b.ogg"
    config = AppConfig()
    bed = LoopPlayer(config, level=0.5, fades=(1.0, 2.0, 1.0, 1.5))
    bed.want([a])
    bed.step(1.0)
    assert bed.tracks == [a] and bed.fade == 1.0 and bed.level() == pytest.approx(gain(config.effects_volume) * 0.5)
    bed.set_under(0.4)
    assert bed.level() == pytest.approx(gain(config.effects_volume) * 0.2), "lower under another bed"
    bed.want([b])
    assert bed.pending == [b] and bed.tracks == [a], "the old sound fades out first"
    bed.step(1.0)
    assert bed.tracks == [b] and bed.fade == 0.0
    bed.step(1.5)
    assert bed.fade == 1.0, "then the new one fades in"
    bed.want(None)
    assert not bed.active
    bed.step(2.0)
    assert bed.fade == 0.0 and not bed.timer.isActive()
    config.event_sounds = False
    bed.want([a])
    assert not bed.active, "sound effects off: no beds"
