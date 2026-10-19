"""Settings: sound effects (the game's own sounds, else the built-in ones), cinematic music (the game's zone music,
else the built-in theme, own file or folder), the cinematic mode's looks (time of day, end credits) and
own sound files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout)

from ...i18n import tr
from ..audio_setup import AudioInstallDialog
from ..sound import ALL_EFFECTS, AUDIO, MUSIC_SUFFIXES, game_sounds_on, music_tracks, user_sounds_dir
from ..widgets import Page, muted, value_label


def slider() -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(0, 100)
    s.setSingleStep(5)
    s.setPageStep(10)
    s.setFixedWidth(280)
    return s


class SettingsPage(Page):
    title_key = "tab.settings"
    scrollable = True
    needs_character = False

    def __init__(self, ctx):
        super().__init__(ctx)
        self.sound = ctx.sound
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        no_audio = QHBoxLayout()            # QtMultimedia missing (PySide6-Essentials only)
        self.no_audio = muted()
        self.install_audio = QPushButton()
        self.install_audio.clicked.connect(lambda: AudioInstallDialog(self.window(), ctx).exec())
        no_audio.addWidget(self.no_audio, 1)
        no_audio.addWidget(self.install_audio, 0, Qt.AlignmentFlag.AlignTop)
        for w in (self.no_audio, self.install_audio):
            w.setVisible(not AUDIO)
        root.addLayout(no_audio)

        # Effects
        self.effects_box = QGroupBox()
        el = QGridLayout(self.effects_box)
        self.clicks = QCheckBox()
        self.clicks.toggled.connect(lambda on: self._set("click_sounds", on))
        self.events = QCheckBox()
        self.events.toggled.connect(lambda on: self._set("event_sounds", on))
        self.game_sounds = QCheckBox()      # the game's own sounds (wow/game_sounds.py)
        self.game_sounds.toggled.connect(lambda on: self._set_extra("game_sounds", on))
        self.effects_label = QLabel()
        self.effects_volume = slider()
        self.effects_volume.valueChanged.connect(self._set_effects_volume)
        self.effects_value = value_label()
        self.effects_value.setMinimumWidth(44)
        self.test_buttons: list[tuple[str, QPushButton]] = []
        tests = QGridLayout()
        for i, name in enumerate(ALL_EFFECTS):
            button = QPushButton()
            button.clicked.connect(lambda _=False, n=name: self.sound.play(n, force=True))
            tests.addWidget(button, i // 5, i % 5)
            self.test_buttons.append((name, button))
        tests.setColumnStretch(5, 1)
        el.addWidget(self.clicks, 0, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)
        el.addWidget(self.events, 1, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)
        el.addWidget(self.game_sounds, 2, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)
        el.addWidget(self.effects_label, 3, 0)
        el.addWidget(self.effects_volume, 3, 1)
        el.addWidget(self.effects_value, 3, 2)
        el.addLayout(tests, 4, 0, 1, 4)
        el.setColumnStretch(3, 1)
        root.addWidget(self.effects_box)

        # Music
        self.music_box = QGroupBox()
        ml = QGridLayout(self.music_box)
        self.music = QCheckBox()
        self.music.toggled.connect(self._set_music)
        self.zone_music = QCheckBox()       # the game's zone music in the cinematic mode (wow/zone_music.py)
        self.zone_music.toggled.connect(self._set_zone_music)
        self.music_label = QLabel()
        self.music_volume = slider()
        self.music_volume.valueChanged.connect(self._set_music_volume)
        self.music_value = value_label()
        self.music_value.setMinimumWidth(44)
        self.source_label = QLabel()
        self.source = value_label()
        self.source.setWordWrap(True)
        self.source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        buttons = QHBoxLayout()
        self.choose_file = QPushButton()
        self.choose_file.clicked.connect(self._choose_file)
        self.choose_folder = QPushButton()
        self.choose_folder.clicked.connect(self._choose_folder)
        self.builtin = QPushButton()
        self.builtin.clicked.connect(lambda: self._set_music_path(None))
        self.preview = QPushButton()
        self.preview.setCheckable(True)
        self.preview.toggled.connect(self._preview)
        for b in (self.choose_file, self.choose_folder, self.builtin):
            buttons.addWidget(b)
        buttons.addSpacing(12)
        buttons.addWidget(self.preview)
        buttons.addStretch(1)
        self.music_hint = muted()
        ml.addWidget(self.music, 0, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)
        ml.addWidget(self.zone_music, 1, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)
        ml.addWidget(self.music_label, 2, 0)
        ml.addWidget(self.music_volume, 2, 1)
        ml.addWidget(self.music_value, 2, 2)
        ml.addWidget(self.source_label, 3, 0, Qt.AlignmentFlag.AlignTop)
        ml.addWidget(self.source, 3, 1, 1, 3)
        ml.addLayout(buttons, 4, 0, 1, 4)
        ml.addWidget(self.music_hint, 5, 0, 1, 4)
        ml.setColumnStretch(3, 1)
        root.addWidget(self.music_box)

        # Cinematic mode: time of day, end credits (ui/cinematic.py; on by default)
        self.cine_box = QGroupBox()
        cl = QVBoxLayout(self.cine_box)
        self.cine_options: list[tuple[str, QCheckBox]] = []
        for key in ("cine_daylight", "cine_credits"):
            box = QCheckBox()
            box.toggled.connect(lambda on, k=key: self._set_extra(k, on))
            cl.addWidget(box, 0, Qt.AlignmentFlag.AlignLeft)
            self.cine_options.append((key, box))
        root.addWidget(self.cine_box)

        # The app itself: motion (ui/motion.py)
        self.ui_box = QGroupBox()
        ul = QVBoxLayout(self.ui_box)
        self.motion = QCheckBox()
        self.motion.toggled.connect(lambda on: self._set_extra("ui_motion", on))
        ul.addWidget(self.motion, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.ui_box)

        # Own sound files
        self.own_box = QGroupBox()
        ol = QHBoxLayout(self.own_box)
        self.own_hint = muted()
        self.open_folder = QPushButton()
        self.open_folder.clicked.connect(self._open_sounds_folder)
        ol.addWidget(self.own_hint, 1)
        ol.addWidget(self.open_folder, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.own_box)
        root.addStretch(1)
        for box in (self.effects_box, self.music_box, self.own_box):
            box.setEnabled(AUDIO)

    def refresh(self) -> None:
        config = self.ctx.config
        self.no_audio.setText(tr("settings.no_audio"))
        self.install_audio.setText(tr("settings.install_audio"))
        self.effects_box.setTitle(tr("settings.effects"))
        self.clicks.setText(tr("settings.clicks"))
        self.events.setText(tr("settings.events"))
        self.game_sounds.setText(tr("settings.game_sounds"))
        self.game_sounds.setToolTip(tr("settings.game_sounds_tip"))
        self.cine_box.setTitle(tr("settings.cine_box"))
        for key, box in self.cine_options:
            box.setText(tr(f"settings.{key}"))
            box.setToolTip(tr(f"settings.{key}_tip"))
            with QSignalBlocker(box):
                box.setChecked(config.extra.get(key, True) is not False)
        self.ui_box.setTitle(tr("settings.ui_box"))
        self.motion.setText(tr("settings.ui_motion"))
        with QSignalBlocker(self.motion):
            self.motion.setChecked(config.extra.get("ui_motion", True) is not False)
        with QSignalBlocker(self.game_sounds):
            self.game_sounds.setChecked(game_sounds_on(config))
        self.effects_label.setText(tr("settings.volume"))
        for name, button in self.test_buttons:
            button.setText(tr(f"settings.test.{name}"))
        self.music_box.setTitle(tr("settings.music_box"))
        self.music.setText(tr("settings.music"))
        self.zone_music.setText(tr("settings.zone_music"))
        self.zone_music.setToolTip(tr("settings.zone_music_tip"))
        with QSignalBlocker(self.zone_music):
            self.zone_music.setChecked(config.extra.get("cine_music", "zone") == "zone")
        self.music_label.setText(tr("settings.volume"))
        self.source_label.setText(tr("settings.source"))
        self.choose_file.setText(tr("settings.choose_file"))
        self.choose_folder.setText(tr("settings.choose_folder"))
        self.builtin.setText(tr("settings.builtin"))
        self.music_hint.setText(tr("settings.music_hint"))
        self.own_box.setTitle(tr("settings.own_box"))
        self.own_hint.setText(tr("settings.own_hint", files=", ".join(f"{n}.wav" for n in ALL_EFFECTS)))
        self.open_folder.setText(tr("settings.open_folder"))
        for widget, value in ((self.clicks, config.click_sounds), (self.events, config.event_sounds),
                              (self.music, config.music), (self.effects_volume, config.effects_volume),
                              (self.music_volume, config.music_volume)):
            with QSignalBlocker(widget):
                if isinstance(widget, QSlider):
                    widget.setValue(value)
                else:
                    widget.setChecked(value)
        self.effects_value.setText(f"{config.effects_volume} %")
        self.music_value.setText(f"{config.music_volume} %")
        self._show_source()
        self._sync_preview()

    def _show_source(self) -> None:
        path = self.ctx.config.music_path
        tracks = music_tracks(path)
        if not path or tracks == music_tracks(None):
            text = tr("settings.source_builtin")
            if path:
                text += "  " + tr("settings.source_missing", path=path)
        elif Path(path).is_dir():
            text = tr("settings.source_folder", path=path, count=len(tracks))
        else:
            text = path
        self.source.setText(text)
        self.builtin.setEnabled(bool(path))

    def _sync_preview(self) -> None:
        playing = self.sound.music.active
        with QSignalBlocker(self.preview):
            self.preview.setChecked(playing)
        self.preview.setText(tr("settings.preview_stop") if playing else tr("settings.preview"))

    # -- changes --------------------------------------------------------------------------

    def _set(self, key: str, value) -> None:
        setattr(self.ctx.config, key, value)
        self.ctx.config.save()

    def _set_extra(self, key: str, value) -> None:
        self.ctx.config.extra[key] = value
        self.ctx.config.save()

    def _set_effects_volume(self, value: int) -> None:
        self._set("effects_volume", value)
        self.effects_value.setText(f"{value} %")

    def _set_music_volume(self, value: int) -> None:
        self._set("music_volume", value)
        self.music_value.setText(f"{value} %")
        self.sound.music.volume_changed()

    def _set_music(self, on: bool) -> None:
        self._set("music", on)

    def _set_zone_music(self, on: bool) -> None:
        self.ctx.config.extra["cine_music"] = "zone" if on else "chosen"
        self.ctx.config.save()

    def _set_music_path(self, path: str | None) -> None:
        self._set("music_path", path)
        self._show_source()
        if self.sound.music.active:          # the preview switches to the new music
            self.sound.music.stop_now()
            self.sound.music.start(force=True)

    def _choose_file(self) -> None:
        patterns = " ".join(f"*{s}" for s in MUSIC_SUFFIXES)
        path, _ = QFileDialog.getOpenFileName(self, tr("settings.choose_file"), self._start_dir(),
                                              f"{tr('settings.audio_files')} ({patterns})")
        if path:
            self._set_music_path(path)

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("settings.choose_folder"), self._start_dir())
        if path:
            self._set_music_path(path)

    def _start_dir(self) -> str:
        path = self.ctx.config.music_path
        if path:
            p = Path(path)
            return str(p if p.is_dir() else p.parent)
        return str(Path.home() / "Music")

    def _preview(self, on: bool) -> None:
        if on:
            self.sound.music.start(force=True)
        else:
            self.sound.music.stop()
        self._sync_preview()

    def _open_sounds_folder(self) -> None:
        folder = user_sounds_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def leave(self) -> None:
        """The preview ends when the page is left."""
        if self.preview.isChecked():
            self.sound.music.stop()
            self._sync_preview()

    def hideEvent(self, event) -> None:
        self.leave()
        super().hideEvent(event)
