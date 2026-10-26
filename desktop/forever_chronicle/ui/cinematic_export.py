"""Video export of the cinematic mode: the replay as an MP4 file (H.264 picture, AAC sound), made frame by frame.

- A CinematicWindow runs off screen at the video's size and is moved on by exactly one frame at a time; every
  frame is grabbed and piped into ffmpeg. So the video shows what the cinematic mode shows: the same speed,
  standstills, pauses at screenshots, titles and music.
- Sound: a Recorder stands in for the app's sound (ui/sound.py). It keeps the music's state with a silent
  MusicPlayer (playlist, fades, ducking) frame by frame and notes each effect with its moment. After the pictures,
  music and effects are mixed as they would have played (numpy, 48 kHz stereo) and added to the video. This
  needs no QtMultimedia, so it works where the app itself plays no sound.
- ffmpeg comes from the pip package imageio-ffmpeg (the program is inside), else from the PATH. Where it is
  missing (friends' setups from "Journey Forever starten.bat"), the dialog offers to install it.
- Takes about as long as the video plays, or longer at 1080p; the progress dialog can cancel it.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import wave
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressDialog, QPushButton, QVBoxLayout)

from ..i18n import format_datetime, tr
from .sound import TRIM, EffectGate, MusicPlayer, effect_path, gain, game_sounds_on
from .widgets import busy

FPS = 30
RATE = 48000
SAMPLES = RATE // FPS          # audio samples per frame
SIZES = {"720p": (1280, 720), "1080p": (1920, 1080)}
TAIL = 4.0                     # seconds after the replay at least (the end title; the credits take longer)
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class ExportError(Exception):
    pass


class Cancelled(Exception):
    pass


FFMPEG_PACKAGE = "imageio-ffmpeg>=0.5"


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # not installed, or its program is missing
        return shutil.which("ffmpeg")


def install_ffmpeg() -> bool:
    """Installs imageio-ffmpeg into the running Python environment (pip, about 30 MB). It can be used at once,
    without a restart. Returns whether ffmpeg is there now."""
    result = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
                             FFMPEG_PACKAGE], capture_output=True, creationflags=NO_WINDOW)
    importlib.invalidate_caches()
    return result.returncode == 0 and ffmpeg_exe() is not None


class Recorder(EffectGate):
    """Stands in for ui.sound.Sound during an export: effects are noted with their moment (clock, in seconds of
    video), the music's state is kept by a silent MusicPlayer and logged per frame by step()."""

    def __init__(self, config):
        super().__init__(config)
        self.clock = 0.0
        self.effects: list[tuple[float, str]] = []
        self.music = MusicPlayer(config, self, audible=False)
        self.music_log: list[tuple[tuple[Path, ...], float]] = []   # per frame: playlist, volume at its end

    def now(self) -> float:
        return self.clock

    def play(self, name: str, force: bool = False) -> bool:
        if not self.admit(name, force):
            return False
        self.effects.append((self.clock, name))
        return True

    def step(self, dt: float) -> None:
        """One frame of video time: the music fades and ducks on, and its state is logged."""
        self.music.step(dt)
        self.clock += dt
        level = self.music.level()
        self.music_log.append((tuple(self.music.tracks) if level > 0 else (), level))


# -- sound mix ------------------------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def decode(ffmpeg: str, path: str) -> np.ndarray:
    """An audio file as 16-bit stereo samples at RATE, shape (n, 2)."""
    result = subprocess.run([ffmpeg, "-v", "error", "-i", path, "-f", "s16le", "-ac", "2", "-ar", str(RATE), "-"],
                            capture_output=True, creationflags=NO_WINDOW)
    if result.returncode != 0:
        return np.zeros((0, 2), np.int16)
    return np.frombuffer(result.stdout, np.int16).reshape(-1, 2)


def mix(recorder: Recorder, ffmpeg: str, out: Path) -> None:
    """Writes the export's sound as a WAV file: the logged music (the playlist's tracks one after the other, its
    volume ramping from frame to frame) and the noted effects."""
    effects = sorted(recorder.effects)
    next_effect = 0
    playing: list[list] = []            # [samples, position, gain]
    playlist: tuple[Path, ...] = ()
    index = position = 0
    level_before = 0.0
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        for frame, (tracks, level) in enumerate(recorder.music_log):
            chunk = np.zeros((SAMPLES, 2), np.float32)
            if tracks:
                if tracks != playlist:
                    playlist, index, position = tracks, 0, 0
                ramp = np.linspace(level_before, level, SAMPLES, endpoint=False, dtype=np.float32)[:, None]
                filled = 0
                for _ in range(len(playlist) + 1):           # a track may end within the frame
                    track = decode(ffmpeg, str(playlist[index]))
                    if len(track) == 0:
                        index = (index + 1) % len(playlist)
                        continue
                    take = min(SAMPLES - filled, len(track) - position)
                    chunk[filled:filled + take] += track[position:position + take] / 32768.0
                    filled += take
                    position += take
                    if position >= len(track):
                        index, position = (index + 1) % len(playlist), 0
                    if filled >= SAMPLES:
                        break
                chunk *= ramp
            level_before = level if tracks else 0.0
            start = frame / FPS
            while next_effect < len(effects) and effects[next_effect][0] < start + 1 / FPS:
                _, name = effects[next_effect]
                next_effect += 1
                path = effect_path(name, game_sounds_on(recorder.config))
                if path.is_file():
                    playing.append([decode(ffmpeg, str(path)), 0,
                                    gain(recorder.config.effects_volume) * TRIM.get(name, 1.0)])
            for sound in playing:
                samples, pos, g = sound
                take = min(SAMPLES, len(samples) - pos)
                if take > 0:
                    chunk[:take] += samples[pos:pos + take] / 32768.0 * g
                sound[1] = pos + take
            playing = [s for s in playing if s[1] < len(s[0])]
            wav.writeframes((np.clip(chunk, -1.0, 1.0) * 32767).astype("<i2").tobytes())


# -- export ---------------------------------------------------------------------------------------------------

def export_video(ctx, character_id: str, start: int, end: int, path: Path, size: str | tuple = "1080p", speed: int = 4,
                 colors: str = "level", still: str | None = None, with_sound: bool = True,
                 progress: Callable[[float], bool] | None = None) -> Path:
    """Renders the replay of [start, end] into path (MP4). progress(share 0..1) returning False cancels
    (Cancelled). Raises ExportError when ffmpeg is missing or fails."""
    from .cinematic import CinematicWindow

    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        raise ExportError(tr("export.no_ffmpeg"))
    width, height = size if isinstance(size, tuple) else SIZES.get(size, SIZES["1080p"])
    config = replace(ctx.config, click_sounds=False)
    if not with_sound:
        config = replace(config, music=False, event_sounds=False)
    recorder = Recorder(config)
    window = CinematicWindow(ctx, character_id, start, end, speed, colors, sound=recorder, exporting=True,
                             still=still)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    window.resize(round(width / ratio), round(height / ratio))
    window.show()

    path = Path(path)
    video = path.with_name(path.stem + ".video.mp4")
    audio = path.with_name(path.stem + ".audio.wav")
    command = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{width}x{height}",
               "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    total = window.bar.timeline.total
    tail = 0.0
    try:
        while tail < max(TAIL, window.credits_seconds()):
            window.advance(1 / FPS)
            recorder.step(1 / FPS)
            image = window.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
            if image.width() != width or image.height() != height:
                image = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            try:
                encoder.stdin.write(image.constBits().tobytes())
            except OSError:
                break                                       # ffmpeg stopped: its message is read below
            if window.ended:
                tail += 1 / FPS
            if progress and not progress(min(1.0, window.bar.timeline.to_value(window.t) / total)):
                raise Cancelled()
        encoder.stdin.close()
        error = encoder.stderr.read().decode("utf-8", "replace").strip()
        if encoder.wait() != 0:
            raise ExportError(error or f"ffmpeg {encoder.returncode}")
        if with_sound and recorder.music_log:
            if progress:
                progress(1.0)
            mix(recorder, ffmpeg, audio)
            result = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy",
                                     "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(path)],
                                    capture_output=True, creationflags=NO_WINDOW)
            if result.returncode != 0:
                raise ExportError(result.stderr.decode("utf-8", "replace").strip() or "ffmpeg")
        else:
            os.replace(video, path)
        return path
    finally:
        if encoder.poll() is None:
            encoder.kill()
            encoder.wait()
        window.close()
        decode.cache_clear()
        for temp in (video, audio):
            try:
                temp.unlink()
            except OSError:
                pass


class ExportDialog(QDialog):
    """Options for a video export (size, speed, standstills, sound, file), then the export with a progress
    dialog. The choices are kept in the settings (extra: video_size, video_dir)."""

    def __init__(self, parent, ctx, character_id: str, start: int, end: int, speed: int, colors: str):
        super().__init__(parent)
        from .cinematic import SPEEDS, STILL_MODES
        self.ctx, self.character_id, self.start, self.end, self.colors = ctx, character_id, start, end, colors
        self.setWindowTitle(tr("export.title"))
        extra = ctx.config.extra
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.size = QComboBox()
        for key in SIZES:
            self.size.addItem(key, key)
        self.size.setCurrentIndex(max(0, self.size.findData(extra.get("video_size", "1080p"))))
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s}×", s)
        self.speed.setCurrentIndex(max(0, self.speed.findData(speed)))
        self.still = QComboBox()
        for mode in STILL_MODES:
            self.still.addItem(tr(f"cine.still.{mode}"), mode)
        self.still.setCurrentIndex(max(0, self.still.findData(extra.get("cine_still", "fast"))))
        self.sound = QCheckBox(tr("export.sound"))
        self.sound.setChecked(ctx.config.music or ctx.config.event_sounds)
        self.file = QLineEdit(str(self._default_path()))
        choose = QPushButton(tr("export.choose"))
        choose.clicked.connect(self._choose)
        row = QHBoxLayout()
        row.addWidget(self.file, 1)
        row.addWidget(choose)
        form.addRow(tr("export.size"), self.size)
        form.addRow(tr("export.speed"), self.speed)
        form.addRow(tr("export.still"), self.still)
        form.addRow("", self.sound)
        form.addRow(tr("export.file"), row)
        root.addLayout(form)
        hint = QLabel(tr("export.hint"))
        hint.setWordWrap(True)
        root.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton(tr("export.start"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._run)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.resize(560, self.sizeHint().height())

    def _default_path(self) -> Path:
        folder = self.ctx.config.extra.get("video_dir") or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.MoviesLocation) or str(Path.home())
        char = self.ctx.repo.character(self.character_id)
        stamp = format_datetime(self.start).replace(":", "-").replace(".", "-").replace(" ", "_")
        name = f"Journey Forever - {char.name if char else 'Replay'} - {stamp}.mp4"
        return Path(folder) / "".join(c for c in name if c not in '<>:"/\\|?*')

    def _choose(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("export.title"), self.file.text(), tr("export.filter"))
        if path:
            self.file.setText(path if path.lower().endswith(".mp4") else path + ".mp4")

    def _ensure_ffmpeg(self) -> bool:
        """Offers to install ffmpeg when it is missing; True when it is there."""
        if ffmpeg_exe():
            return True
        answer = QMessageBox.question(self, tr("export.title"), tr("export.no_ffmpeg"))
        if answer != QMessageBox.StandardButton.Yes:
            return False
        with busy():
            ok = install_ffmpeg()
        if not ok:
            QMessageBox.warning(self, tr("export.title"),
                                tr("export.install_failed", command=f'pip install "{FFMPEG_PACKAGE}"'))
        return ok

    def _run(self) -> None:
        if not self._ensure_ffmpeg():
            return
        path = Path(self.file.text().strip())
        if path.suffix.lower() != ".mp4":
            path = path.with_suffix(".mp4")
        extra = self.ctx.config.extra
        extra["video_size"] = self.size.currentData()
        extra["video_dir"] = str(path.parent)
        self.ctx.config.save()
        self.hide()
        dialog = QProgressDialog(tr("export.progress"), tr("export.cancel"), 0, 1000, self.parentWidget())
        dialog.setWindowTitle(tr("export.title"))
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)

        def progress(share: float) -> bool:
            dialog.setValue(int(share * 999))
            return not dialog.wasCanceled()

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            export_video(self.ctx, self.character_id, self.start, self.end, path, self.size.currentData(),
                         self.speed.currentData(), self.colors, self.still.currentData(), self.sound.isChecked(),
                         progress)
        except Cancelled:
            dialog.close()
            self.reject()
            return
        except Exception as error:  # ffmpeg missing or failing, a full disk: shown, the app goes on
            dialog.close()
            QMessageBox.warning(self.parentWidget(), tr("export.title"), tr("export.failed", error=error))
            self.reject()
            return
        dialog.close()
        box = QMessageBox(QMessageBox.Icon.Information, tr("export.title"), tr("export.done", path=path),
                          QMessageBox.StandardButton.Ok, self.parentWidget())
        open_folder = box.addButton(tr("export.open_folder"), QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self.accept()
