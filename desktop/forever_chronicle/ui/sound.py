"""Sound: button clicks, event alerts and the cinematic music (QtMultimedia).

- Effects are WAV files played with QSoundEffect (low latency). The built-in ones are in ui/assets/sounds and are
  made by tools/generate_sounds.py; a file of the same name in %APPDATA%\\ForeverChronicle\\sounds replaces one.
- The game's own sounds (wow/game_sounds.py: level-up, quest complete, achievement, discovery, button click,
  resurrection, teleport, the flight sounds and the wind) are taken from the install once and turned into WAV
  (install_game_sounds, a background thread); they play instead of the built-in ones while the option
  "game_sounds" is on (the default). Effects without a built-in file of their own (achievement, discovery, revive,
  teleport) fall back to the built-in alert.
- Clicks: an application-wide event filter plays "click" when a button, tab, drop-down or menu entry is clicked.
- Music: the built-in theme, or the player's own file, or a folder of files (shuffled), with fades and ducking
  under big moments. QMediaPlayer plays MP3, OGG, FLAC, WAV and M4A. The cinematic mode switches to the adventure
  music from the game (MusicPlayer.play: the old music fades out, the new one in).
- Sound beds under the music (LoopPlayer, cinematic mode): the zone's ambience from the game and the wind on a
  flight path. They loop at the effects' volume while sound effects are on; what plays is the cinematic's choice.
- Flight sounds (the game's, no built-in ones): the gryphon's or wind rider's call at take-off, wing flaps and
  a glide at landing.
- Settings are in AppConfig (click_sounds, event_sounds, music, effects_volume, music_volume, music_path).
- FOREVER_CHRONICLE_SILENT=1 keeps everything quiet (tests); what would have played is still recorded in `played`.
- QtMultimedia comes with PySide6-Addons. With PySide6-Essentials alone the app runs without sound (AUDIO is False).
"""

from __future__ import annotations

import os
import random
import threading
import wave
from collections import deque
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QEventLoop, QObject, Qt, QTimer, QUrl
from PySide6.QtWidgets import QAbstractButton, QComboBox, QMenu, QTabBar

from ..config import AppConfig, app_home
from ..wow import game_sounds

try:
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat, QAudioOutput, QMediaPlayer, QSoundEffect
    AUDIO = True
except ImportError:
    AUDIO = False

ASSETS = Path(__file__).resolve().parent / "assets" / "sounds"
EFFECTS = ("click", "screenshot", "level_up", "event", "death")       # each has a built-in file
MORE_EFFECTS = ("achievement", "discovery", "revive", "teleport")   # the game's, else the built-in alert
ALL_EFFECTS = EFFECTS + MORE_EFFECTS
FALLBACK = {name: "event" for name in MORE_EFFECTS}
# The cinematic's flight sounds: the game's only (silent without them), not in the settings' test buttons.
FLIGHT_EFFECTS = ("gryphon_call", "wind_rider_call", "wing_flap", "wing_flap_soft", "wing_glide")
WAV_RATE = 44100
BUILTIN_MUSIC = ASSETS / "cinematic_theme.ogg"
MUSIC_SUFFIXES = (".mp3", ".ogg", ".flac", ".wav", ".m4a", ".opus")
TRIM = {"click": 0.55,            # the click is heard very often: quieter than the alerts
        "gryphon_call": 0.7, "wind_rider_call": 0.6, "wing_flap": 0.55, "wing_flap_soft": 0.25}
MIN_GAP = {"click": 0.03, "wing_flap": 0.3, "wing_flap_soft": 0.3}   # seconds before it may start again
DEFAULT_GAP = 0.35

FADE_IN = 3.0                     # seconds
FADE_OUT = 1.2
SWITCH_OUT, SWITCH_IN = 1.6, 2.2  # seconds: other music (a zone change) fades the old one out, the new one in
DUCK = 0.35                       # music level under a big moment
DUCK_IN, DUCK_OUT = 0.25, 1.2
AMBIENCE_LEVEL = 0.9              # the zone's ambience, a share of the effects' volume (the game's files are quiet)
AMBIENCE_FADES = (2.5, 2.5, 2.5, 3.5)   # seconds: fade in, fade out, switch out, switch in (a slow crossfade)
WIND_LEVEL = 0.32                 # the wind on a flight path (the game's wind loops are loud)
WIND_FADES = (0.5, 1.6, 0.5, 0.5)       # quick in, a gust's tail out
STEP_MS = 30


def user_sounds_dir() -> Path:
    """Own sounds: click.wav, screenshot.wav, level_up.wav, event.wav, death.wav (and the other ALL_EFFECTS)
    replace the game's and the built-in ones."""
    return app_home() / "sounds"


def effect_path(name: str, game: bool = True) -> Path:
    """The file an effect plays: an own file, else the game's sound (game: option "game_sounds"), else the
    built-in one."""
    own = user_sounds_dir() / f"{name}.wav"
    if own.is_file():
        return own
    found = game_sounds.wav_path(name) if game else None
    return found or ASSETS / f"{FALLBACK.get(name, name)}.wav"


def game_sounds_on(config: AppConfig) -> bool:
    return config.flag("game_sounds")


def install_game_sounds(client) -> threading.Thread | None:
    """Takes the game's sounds out of the install and turns them into WAV, in a background thread (opening the
    game files takes a few seconds). Does nothing once they are all there."""
    if not AUDIO or client is None or not (game_sounds.missing() or game_sounds.missing_loops()):
        return None

    def work() -> None:
        for name in game_sounds.extract_missing(client):
            source, target = game_sounds.ogg_path(name), game_sounds.cache_dir() / f"{name}.wav"
            if decode_to_wav(source, target):
                _remove(source)
            else:
                game_sounds.mark_failed(name)
        for name in game_sounds.missing_loops():
            pieces = game_sounds.extract_loop_pieces(client, name)
            wavs = [piece.with_suffix(".wav") for piece in pieces]
            if not (pieces and all(decode_to_wav(a, b) for a, b in zip(pieces, wavs))
                    and game_sounds.join_loop(wavs, game_sounds.cache_dir() / f"{name}.wav")):
                game_sounds.mark_failed(name)
            for path in pieces + wavs:
                _remove(path)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def decode_to_wav(source: Path, target: Path, timeout_ms: int = 8000) -> bool:
    """Decodes an audio file (OGG, MP3) into a 16-bit stereo WAV at WAV_RATE with QtMultimedia. Runs its own
    event loop, so it works in any thread. Returns whether the WAV was written."""
    if not AUDIO:
        return False
    decoder = QAudioDecoder()
    fmt = QAudioFormat()
    fmt.setSampleRate(WAV_RATE)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    decoder.setAudioFormat(fmt)
    decoder.setSource(QUrl.fromLocalFile(str(source)))
    chunks: list[bytes] = []
    failed: list[bool] = []
    loop = QEventLoop()

    def ready() -> None:
        while decoder.bufferAvailable():
            chunks.append(decoder.read().data().tobytes())

    decoder.bufferReady.connect(ready)
    decoder.finished.connect(loop.quit)
    decoder.error.connect(lambda *_: (failed.append(True), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    decoder.start()
    loop.exec()
    ready()
    decoder.stop()
    data = b"".join(chunks)
    if failed or not data:
        return False
    part = target.with_name(target.name + ".part")
    with wave.open(str(part), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(WAV_RATE)
        out.writeframes(data)
    part.replace(target)
    return True


def music_tracks(music_path: str | None) -> list[Path]:
    """The music to play: the chosen file, the audio files of the chosen folder, else the built-in theme."""
    if music_path:
        path = Path(music_path)
        if path.is_file():
            return [path]
        if path.is_dir():
            tracks = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_SUFFIXES)
            if tracks:
                return tracks
    return [BUILTIN_MUSIC]


def gain(percent: int) -> float:
    """Slider percent to linear gain: a square curve, so the slider feels even to the ear."""
    return max(0.0, min(1.0, percent / 100)) ** 2


def silent() -> bool:
    return not AUDIO or bool(os.environ.get("FOREVER_CHRONICLE_SILENT"))


class EffectGate(QObject):
    """Decides whether an effect plays: its setting is on (or forced), the effects volume is up, and the same
    effect did not start within its MIN_GAP. Sound and the video export's Recorder differ only in their clock."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.played: deque[str] = deque(maxlen=50)     # most recent last; for tests and diagnostics
        self._last: dict[str, float] = {}               # when each effect last started (now())

    def now(self) -> float:
        """Seconds on the clock the gaps between effects are measured with."""
        raise NotImplementedError

    def enabled(self, name: str) -> bool:
        return self.config.click_sounds if name == "click" else self.config.event_sounds

    def admit(self, name: str, force: bool = False) -> bool:
        """True (and noted in played) when the effect may play now."""
        if not (force or self.enabled(name)) or self.config.effects_volume <= 0:
            return False
        now = self.now()
        if now - self._last.get(name, -1e9) < MIN_GAP.get(name, DEFAULT_GAP):
            return False
        self._last[name] = now
        self.played.append(name)
        return True


class Sound(EffectGate):
    """The app's sound effects and click filter. One instance lives in the AppContext (ctx.sound)."""

    def __init__(self, config: AppConfig):
        super().__init__(config)
        self._effects: dict = {}
        self._clock = QElapsedTimer()
        self._clock.start()
        self._music: MusicPlayer | None = None
        self._ambience: LoopPlayer | None = None
        self._wind: LoopPlayer | None = None

    # -- effects --------------------------------------------------------------------------

    def now(self) -> float:
        return self._clock.elapsed() / 1000

    def play(self, name: str, force: bool = False) -> bool:
        """Plays an effect if its setting is on (force: always, for the settings' test button). Returns whether
        it played."""
        if not self.admit(name, force):
            return False
        if silent():
            return True
        effect = self._effect(name)
        if effect is None:
            return False
        effect.setVolume(gain(self.config.effects_volume) * TRIM.get(name, 1.0))
        effect.play()
        return True

    def _effect(self, name: str):
        """The loaded effect; an own file added or removed meanwhile (or the game's sounds arriving) is picked
        up."""
        path = effect_path(name, game_sounds_on(self.config))
        cached = self._effects.get(name)
        if cached and cached[0] == path:
            return cached[1]
        if cached and cached[1] is not None:
            cached[1].deleteLater()
        effect = None
        if path.is_file():
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(str(path)))
        self._effects[name] = (path, effect)
        return effect

    # -- clicks ---------------------------------------------------------------------------

    def install_click_sounds(self, app) -> None:
        app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if is_click_target(obj, event.position().toPoint()):
                self.play("click")
        return False

    # -- music ----------------------------------------------------------------------------

    @property
    def music(self) -> "MusicPlayer":
        if self._music is None:
            self._music = MusicPlayer(self.config, self)
        return self._music

    @property
    def ambience(self) -> "LoopPlayer":
        if self._ambience is None:
            self._ambience = LoopPlayer(self.config, self, level=AMBIENCE_LEVEL, fades=AMBIENCE_FADES)
        return self._ambience

    @property
    def wind(self) -> "LoopPlayer":
        if self._wind is None:
            self._wind = LoopPlayer(self.config, self, level=WIND_LEVEL, fades=WIND_FADES)
        return self._wind

    def volume_changed(self) -> None:
        for player in (self._music, self._ambience, self._wind):
            if player is not None:
                player.volume_changed()


def is_click_target(widget, pos) -> bool:
    """Whether a left-button release at pos (widget coordinates) clicks something."""
    if isinstance(widget, QAbstractButton):
        return widget.isEnabled() and widget.rect().contains(pos)
    if isinstance(widget, QTabBar):
        return widget.isEnabled() and widget.tabAt(pos) >= 0
    if isinstance(widget, QComboBox):
        return widget.isEnabled()
    if isinstance(widget, QMenu):
        action = widget.actionAt(pos)
        return bool(action and action.isEnabled() and not action.isSeparator() and not action.menu())
    return False


class MusicPlayer(QObject):
    """Background music with fade in/out and ducking. Plays only while someone asked for it (start/stop).
    audible=False keeps the same state (playlist, fades, ducking) without playing anything: the video export
    records it frame by frame and mixes the music itself."""

    def __init__(self, config: AppConfig, parent=None, audible: bool = True):
        super().__init__(parent)
        self.config = config
        self.audible = audible
        self.tracks: list[Path] = []
        self.index = 0
        self.pending: list[Path] | None = None   # music to switch to once the current one has faded out
        self.switched = False     # fading in after a switch (SWITCH_IN instead of FADE_IN)
        self.fade = 0.0           # 0..1, follows `target`
        self.target = 0.0
        self.duck_level = 1.0
        self.duck_left = 0.0      # seconds the music stays ducked
        self.fade_in, self.fade_out, self.switch_out, self.switch_in = FADE_IN, FADE_OUT, SWITCH_OUT, SWITCH_IN
        self._player = None
        self._output = None
        self.timer = QTimer(self)
        self.timer.setInterval(STEP_MS)
        if audible:                 # a silent player is stepped by its owner (the export, frame by frame)
            self.timer.timeout.connect(lambda: self.step(STEP_MS / 1000))

    @property
    def active(self) -> bool:
        """Playing or fading in (not fading out or stopped)."""
        return self.target > 0

    def start(self, force: bool = False, tracks: list[Path] | None = None) -> None:
        """Fades the music in (from where it is): the given tracks, else the music chosen in the settings. Does
        nothing if music is off, unless forced (preview)."""
        if not (force or self.config.music):
            return
        if not self.active or not self.tracks:
            self.pending = None
            self._use(self._playlist(tracks))
        self.target = 1.0
        if not self._quiet():
            self._ensure_player()
            if self._player.playbackState() != self._player.PlaybackState.PlayingState:
                self._player.play()
        self.timer.start()

    def play(self, tracks: list[Path] | None) -> None:
        """Switches to other music (None: the music chosen in the settings). While music plays, the current one
        fades out and the new one fades in; otherwise the new one is only loaded for the next start."""
        new = self._playlist(tracks)
        if sorted(new) == sorted(self.pending if self.pending is not None else self.tracks):
            return
        if self.active and self.fade > 0:
            self.pending = new
            self.timer.start()
        else:
            self.pending = None
            self._use(new)

    def stop(self) -> None:
        """Fades out, then stops."""
        self.target = 0.0
        self.timer.start()

    def stop_now(self) -> None:
        self.target = self.fade = 0.0
        self.pending = None
        self.timer.stop()
        if self._player:
            self._player.stop()

    def duck(self, seconds: float) -> None:
        """Lowers the music for `seconds` (e.g. under the level-up fanfare)."""
        self.duck_left = max(self.duck_left, seconds)
        if self.active:
            self.timer.start()

    def volume_changed(self) -> None:
        self._apply()

    def step(self, dt: float) -> None:
        self.duck_left = max(0.0, self.duck_left - dt)
        duck_target = DUCK if self.duck_left > 0 else 1.0
        self.duck_level = _approach(self.duck_level, duck_target,
                                    dt * (1 - DUCK) / (DUCK_IN if duck_target < self.duck_level else DUCK_OUT))
        if self.pending is not None:
            self.fade = _approach(self.fade, 0.0, dt / self.switch_out)
            if self.fade == 0:
                new, self.pending = self.pending, None
                self.switched = True
                self._use(new)
        elif self.target > self.fade:
            self.fade = _approach(self.fade, self.target, dt / (self.switch_in if self.switched else self.fade_in))
        else:
            self.fade = _approach(self.fade, self.target, dt / self.fade_out)
        if self.fade >= self.target:
            self.switched = False
        self._apply()
        if (self.pending is None and self.fade == self.target and self.duck_level == duck_target
                and self.duck_left == 0):
            self.timer.stop()
            if self.target == 0 and self._player:
                self._player.stop()

    def level(self) -> float:
        """The linear volume the music has now."""
        return gain(self.config.music_volume) * self.fade * self.duck_level

    def _apply(self) -> None:
        if self._output:
            self._output.setVolume(self.level())

    # -- playlist -------------------------------------------------------------------------

    def _quiet(self) -> bool:
        return silent() or not self.audible

    def _playlist(self, tracks: list[Path] | None) -> list[Path]:
        """The tracks to play, shuffled: the given ones, else the music chosen in the settings."""
        new = list(tracks) if tracks else music_tracks(self.config.music_path)
        if len(new) > 1:
            random.shuffle(new)
        return new

    def _use(self, tracks: list[Path]) -> None:
        """Makes tracks the playlist, from its first track (playing on if the music is wanted)."""
        changed = tracks != self.tracks
        self.tracks, self.index = tracks, 0
        if changed and self._player:
            self._set_source()
            if self.active:
                self._player.play()

    def _ensure_player(self) -> None:
        if self._player:
            return
        self._output = QAudioOutput(self)
        self._output.setVolume(0.0)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.mediaStatusChanged.connect(self._status_changed)
        self._player.errorOccurred.connect(self._error)
        self._set_source()

    def _set_source(self) -> None:
        track = self.tracks[self.index]
        self._player.setLoops(QMediaPlayer.Loops.Infinite if len(self.tracks) == 1 else 1)
        self._player.setSource(QUrl.fromLocalFile(str(track)))

    def _next(self) -> None:
        self.index = (self.index + 1) % len(self.tracks)
        self._set_source()
        if self.active:
            self._player.play()

    def _status_changed(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and len(self.tracks) > 1:
            self._next()

    def _error(self, *_args) -> None:
        """A file that cannot be played is left out; with none left, the built-in theme plays."""
        bad = self.tracks.pop(self.index) if self.tracks else None
        if not self.tracks:
            self.tracks = [BUILTIN_MUSIC] if bad != BUILTIN_MUSIC else []
        if not self.tracks:
            self.stop_now()
            return
        self.index = self.index % len(self.tracks)
        self._set_source()
        if self.active:
            self._player.play()


class LoopPlayer(MusicPlayer):
    """A sound bed under the music (the zone's ambience, the wind on a flight path): files on a loop at the
    effects' volume times level, only while sound effects are on. Its owner says what it wants (want), and how far
    another bed covers it (set_under: the ambience under the wind). fades: seconds to fade in, out, and to cross
    from one sound to another (out, in)."""

    def __init__(self, config: AppConfig, parent=None, audible: bool = True, level: float = 1.0,
                 fades: tuple[float, float, float, float] = (FADE_IN, FADE_OUT, SWITCH_OUT, SWITCH_IN)):
        super().__init__(config, parent, audible)
        self.base = level
        self.under = 1.0
        self.fade_in, self.fade_out, self.switch_out, self.switch_in = fades

    def want(self, tracks: list[Path] | None) -> None:
        """Plays these files (crossing over from the ones playing), or fades out (None, or sound effects off)."""
        if not tracks or not self.config.event_sounds or self.config.effects_volume <= 0:
            if self.target > 0 or self.fade > 0:
                self.stop()
            return
        new = list(tracks)
        if self.fade > 0:
            if sorted(new) != sorted(self.pending if self.pending is not None else self.tracks):
                self.pending = new          # the old sound fades out first, then the new one in (step)
        else:
            self.pending = None
            self._use(new)
        self.target = 1.0
        if not self._quiet():
            self._ensure_player()
            if self._player.playbackState() != self._player.PlaybackState.PlayingState:
                self._player.play()
        self.timer.start()

    def set_under(self, share: float) -> None:
        if share != self.under:
            self.under = share
            self._apply()

    def level(self) -> float:
        return gain(self.config.effects_volume) * self.base * self.under * self.fade * self.duck_level

    def _playlist(self, tracks: list[Path] | None) -> list[Path]:
        return list(tracks or [])

    def _error(self, *_args) -> None:
        """A file that cannot be played is left out; with none left the bed is silent (never the music)."""
        if self.tracks:
            self.tracks.pop(self.index)
        if not self.tracks:
            self.stop_now()
            return
        self.index %= len(self.tracks)
        self._set_source()
        if self.active:
            self._player.play()


def _approach(value: float, target: float, step: float) -> float:
    if value < target:
        return min(target, value + step)
    return max(target, value - step)
