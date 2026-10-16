"""The offer to install the missing sound part: when it asks, "don't ask again", install success and failure."""

import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QElapsedTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.ui import audio_setup  # noqa: E402
from forever_chronicle.ui.audio_setup import AudioInstallDialog  # noqa: E402


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    return SimpleNamespace(config=AppConfig())


def fake_pip(monkeypatch, code: int):
    monkeypatch.setattr(audio_setup, "pip_command",
                        lambda: (sys.executable, ["-c", f"print('pip says hi'); raise SystemExit({code})"]))


def wait_for(dialog: AudioInstallDialog) -> None:
    clock = QElapsedTimer()
    clock.start()
    while dialog.process is not None and clock.elapsed() < 20_000:
        QCoreApplication.processEvents()
    assert dialog.process is None, "pip did not finish"


def test_offered_only_without_sound(ctx, monkeypatch):
    monkeypatch.delenv("FOREVER_CHRONICLE_SILENT", raising=False)
    monkeypatch.setattr(audio_setup, "AUDIO", False)
    assert audio_setup.should_offer(ctx.config)
    ctx.config.ask_audio_install = False
    assert not audio_setup.should_offer(ctx.config), "the player said not to ask again"
    ctx.config.ask_audio_install = True
    monkeypatch.setattr(audio_setup, "AUDIO", True)
    assert not audio_setup.should_offer(ctx.config), "sound works"
    assert audio_setup.PACKAGE.startswith("PySide6-Addons==6.")


def test_dont_ask_again_is_kept(ctx):
    window = QWidget()
    dialog = AudioInstallDialog(window, ctx)
    dialog.dont_ask.setChecked(True)
    dialog.reject()
    assert not ctx.config.ask_audio_install and not AppConfig.load().ask_audio_install


def test_install_then_restart(ctx, monkeypatch):
    fake_pip(monkeypatch, 0)
    monkeypatch.setattr(audio_setup, "RESTART", False)
    window = QWidget()
    window.show()
    dialog = AudioInstallDialog(window, ctx)
    dialog.start_install()
    wait_for(dialog)
    assert "pip says hi" in dialog.output
    assert not dialog.restart_button.isHidden() and dialog.text.text() == "Fertig. Der Ton ist nach einem Neustart der App da."
    assert not AppConfig.load().ask_audio_install, "installed: no question at the next start"
    dialog.restart()
    QCoreApplication.processEvents()
    assert audio_setup.RESTART and not window.isVisible()


def test_failed_install_shows_the_command(ctx, monkeypatch):
    fake_pip(monkeypatch, 1)
    dialog = AudioInstallDialog(QWidget(), ctx)
    dialog.start_install()
    wait_for(dialog)
    assert dialog.restart_button.isHidden() and "pip install PySide6-Addons==" in dialog.text.text()
    assert ctx.config.ask_audio_install, "asks again next time"
