"""Offers to install the missing sound part (Qt Multimedia from PySide6-Addons) and restarts the app afterwards.

- The friends' launcher ("Journey Forever starten.bat") installs PySide6-Essentials and then, optionally,
  PySide6-Addons. If that download failed (or in another environment without it) the app has no sound
  (ui/sound.py: AUDIO is False). At start the app then asks whether to install it; "Nicht mehr fragen" keeps it
  quiet (AppConfig.ask_audio_install). The settings page offers the same dialog any time.
- pip installs PySide6-Addons of exactly the running PySide6 version into the running Python environment
  (sys.executable), in a QProcess so the window keeps working. The new module only loads in a new process:
  restart() closes the window and app.main starts the app again (RESTART).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QProgressBar,
                               QPushButton, QVBoxLayout)

from ..i18n import tr
from .sound import AUDIO

PACKAGE = f"PySide6-Addons=={PySide6.__version__}"   # must match PySide6-Essentials exactly
RESTART = False                                      # set by restart(); app.main starts the app again on exit


def pip_command() -> tuple[str, list[str]]:
    return sys.executable, ["-m", "pip", "install", "--disable-pip-version-check", PACKAGE]


def should_offer(config) -> bool:
    return not AUDIO and config.ask_audio_install and not os.environ.get("FOREVER_CHRONICLE_SILENT")


def offer_at_start(window, ctx) -> None:
    """At start: asks once, unless sound works or the player said not to ask again."""
    if should_offer(ctx.config):
        AudioInstallDialog(window, ctx).exec()


def start_again() -> None:
    """Starts a new app process (after the old one closed its window and database)."""
    package_root = Path(__file__).resolve().parents[2]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, "-m", "forever_chronicle"], cwd=package_root, creationflags=flags,
                     close_fds=True)


class AudioInstallDialog(QDialog):
    """Ask → installing (busy bar, pip output) → done (restart now?) or failed (pip's last lines)."""

    def __init__(self, window, ctx):
        super().__init__(window)
        self.window_ = window
        self.ctx = ctx
        self.process: QProcess | None = None
        self.output: list[str] = []
        self.setWindowTitle(tr("audio_setup.title"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        self.text = QLabel(tr("audio_setup.ask"))
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)                 # busy: pip reports no total
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setFixedHeight(120)
        self.log.hide()
        self.dont_ask = QCheckBox(tr("audio_setup.dont_ask"))
        self.dont_ask.setChecked(not ctx.config.ask_audio_install)
        self.buttons = QDialogButtonBox()
        self.install = self.buttons.addButton(tr("audio_setup.install"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.later = self.buttons.addButton(tr("audio_setup.later"), QDialogButtonBox.ButtonRole.RejectRole)
        self.restart_button = QPushButton(tr("audio_setup.restart"))
        self.buttons.addButton(self.restart_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.restart_button.hide()                   # after addButton, which shows it
        self.install.clicked.connect(self.start_install)
        self.later.clicked.connect(self.reject)
        self.restart_button.clicked.connect(self.restart)
        for w in (self.text, self.progress, self.log, self.dont_ask, self.buttons):
            layout.addWidget(w)
        self.install.setDefault(True)

    # -- steps ----------------------------------------------------------------------------

    def start_install(self) -> None:
        self.dont_ask.hide()
        self.install.hide()
        self.later.setText(tr("audio_setup.cancel"))
        self.text.setText(tr("audio_setup.installing"))
        self.progress.show()
        self.log.show()
        self.output.clear()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        program, args = pip_command()
        self.process.start(program, args)

    def _read(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if line.strip():
                self.output.append(line.rstrip())
                self.log.appendPlainText(line.rstrip())

    def _finished(self, code: int, status) -> None:
        self._read()
        self.process = None
        self.progress.hide()
        if code == 0 and status == QProcess.ExitStatus.NormalExit:
            self.ctx.config.ask_audio_install = False    # done: nothing to ask at the next start
            self.ctx.config.save()
            self.log.hide()
            self.text.setText(tr("audio_setup.done"))
            self.later.setText(tr("audio_setup.later"))
            self.restart_button.show()
            self.restart_button.setDefault(True)
        else:
            self._failed()

    def _error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.process = None
            self.progress.hide()
            self.output.append(str(error))
            self._failed()

    def _failed(self) -> None:
        self.text.setText(tr("audio_setup.failed", command=f"pip install {PACKAGE}"))
        self.later.setText(tr("audio_setup.close"))
        self.log.show()

    def restart(self) -> None:
        global RESTART
        RESTART = True
        self.accept()
        QTimer.singleShot(0, self.window_.close)

    # -- closing --------------------------------------------------------------------------

    def done(self, result: int) -> None:
        if self.process is not None:                     # "Abbrechen" or the window's close button
            self.process.finished.disconnect(self._finished)
            self.process.kill()
            self.process.waitForFinished(3000)
            self.process = None
        if not self.dont_ask.isHidden() and self.dont_ask.isChecked() == self.ctx.config.ask_audio_install:
            self.ctx.config.ask_audio_install = not self.dont_ask.isChecked()
            self.ctx.config.save()
        super().done(result)
