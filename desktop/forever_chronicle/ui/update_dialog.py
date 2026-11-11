"""The app's side of the self-update (updater.py): at start, the newest release is looked up in the background; a
newer one is offered in a dialog (Jetzt aktualisieren / Später). Updating downloads and unpacks it with a progress
bar, then closes the app; app.main hands over to the apply step (APPLY), which restarts the new version.

Only the launcher's install updates itself (updater.installed_root); git checkouts and tests never ask.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar,
                               QTextBrowser, QVBoxLayout)

from .. import updater
from ..i18n import tr

APPLY = False                 # set when the new version is unpacked; app.main starts the apply step on exit
_keep: list[QObject] = []     # the bridge must outlive check_at_start until the answer arrives


class _Bridge(QObject):
    """Carries results from worker threads into the GUI thread (queued signals)."""
    found = Signal(object)
    progress = Signal(int, int)
    finished = Signal(object)


def check_at_start(window) -> None:
    """Shows the last update's outcome, then looks for a newer release without holding up the start."""
    root = updater.installed_root()
    if root is None or os.environ.get("FOREVER_CHRONICLE_SILENT"):
        return
    report_last(window, root)
    updater.clean_up(root)
    current = updater.current_version(root)
    bridge = _Bridge()
    _keep.append(bridge)

    def offer(release) -> None:
        if release is None or not updater.is_newer(release.version, current):
            return
        if QApplication.activeModalWidget() is not None:  # the setup wizard or the sound offer first
            QTimer.singleShot(2000, lambda: offer(release))
            return
        if window.isVisible():
            UpdateDialog(window, root, release, current).exec()

    bridge.found.connect(offer)
    threading.Thread(target=lambda: bridge.found.emit(updater.fetch_latest()), daemon=True).start()


def report_last(window, root) -> None:
    result = updater.take_result(root)
    if not result:
        return
    if result.get("ok"):
        QMessageBox.information(window, tr("update.title"), tr("update.applied", version=result.get("version")))
    else:
        QMessageBox.warning(window, tr("update.title"), tr("update.apply_failed", error=result.get("error")))


class UpdateDialog(QDialog):
    """Offer → downloading (progress) → unpacked (the app restarts) or failed (the reason)."""

    def __init__(self, window, root, release: updater.Release, current: str | None):
        super().__init__(window)
        self.window_ = window
        self.root = root
        self.release = release
        self.cancel_flag = threading.Event()
        self.running = False
        self.bridge = _Bridge(self)
        self.bridge.progress.connect(self._progress)
        self.bridge.finished.connect(self._finished)
        self.setWindowTitle(tr("update.title"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        size = max(1, round(release.zip_size / (1024 * 1024)))
        self.text = QLabel(tr("update.ask", version=release.version, current=current or "?", mb=size))
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.text)
        self.notes = QTextBrowser()                       # the release notes: CHANGELOG.md's section
        self.notes.setMarkdown(release.notes)
        self.notes.setFixedHeight(170)
        self.notes.setVisible(bool(release.notes))
        layout.addWidget(self.notes)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.buttons = QDialogButtonBox()
        self.update_button = self.buttons.addButton(tr("update.now"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.later = self.buttons.addButton(tr("update.later"), QDialogButtonBox.ButtonRole.RejectRole)
        self.update_button.clicked.connect(self.start)
        self.later.clicked.connect(self.reject)
        layout.addWidget(self.buttons)
        self.update_button.setDefault(True)

    def start(self) -> None:
        self.running = True
        self.update_button.hide()
        self.later.setText(tr("update.cancel"))
        self.notes.hide()
        self.text.setText(tr("update.downloading", version=self.release.version))
        self.bar.show()
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        """Worker thread: download and unpack; the result goes back through the bridge."""
        try:
            archive = updater.download(self.release, updater.update_dir(self.root),
                                       lambda done, total: self.bridge.progress.emit(done, total),
                                       self.cancel_flag.is_set)
            updater.stage(archive, self.release.version, self.root)
            archive.unlink(missing_ok=True)
            self.bridge.finished.emit(None)
        except updater.UpdateError as exc:
            self.bridge.finished.emit(exc)
        except Exception as exc:                          # never leave the dialog hanging
            self.bridge.finished.emit(updater.UpdateError(str(exc)))

    def _progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(min(1000, done * 1000 // total))

    def _finished(self, error) -> None:
        self.running = False
        if self.cancel_flag.is_set():
            return
        if error is None:
            global APPLY
            APPLY = True
            self.text.setText(tr("update.restarting", version=self.release.version))
            self.bar.setRange(0, 0)
            self.later.hide()
            QTimer.singleShot(1200, self._close_app)
            return
        self.bar.hide()
        self.text.setText(tr("update.failed", error=str(error)))
        self.later.setText(tr("update.close"))

    def _close_app(self) -> None:
        self.accept()
        QTimer.singleShot(0, self.window_.close)

    def done(self, result: int) -> None:
        if self.running:                                  # "Abbrechen" or the window's close button
            self.cancel_flag.set()
        super().done(result)


def apply_on_exit() -> None:
    """Called by app.main after the window closed and the database is shut: hands over to the apply step."""
    root = updater.installed_root()
    if APPLY and root is not None:
        updater.start_apply(root)
