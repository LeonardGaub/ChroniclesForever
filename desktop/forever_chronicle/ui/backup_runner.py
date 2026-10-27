"""Runs the cloud backup (cloud_backup.py) without blocking the window, and watches the game so a backup runs when
WoW starts and after it was closed (only while the app is open).

BackupRunner: one run at a time; a request during a run is done right after it. The database copy is made here in
the main thread (the connection lives here), the file copies in a worker thread.
GameWatcher: looks every few seconds whether a program from the client folder runs (wow/processes.py). Closed counts
only after it stayed closed for a while, so the game has written its saved file and a restart is not an end.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .. import cloud_backup
from ..config import app_home
from ..wow.processes import game_running


class BackupRunner(QObject):
    started = Signal()
    finished = Signal(object)          # cloud_backup.BackupResult
    _done = Signal(object)             # from the worker thread

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.running = False
        self._again = False
        self._done.connect(self._finish)

    def run(self) -> bool:
        """Starts a backup; False when the cloud folder or the name is not set."""
        s = self.ctx.backup_settings()
        if s is None:
            return False
        if self.running:
            self._again = True
            return True
        self.running = True
        self.started.emit()
        snapshot, problems = None, []
        try:
            snapshot = cloud_backup.database_snapshot(self.ctx.db, app_home() / "backups" / "cloud-upload.db")
        except Exception as exc:  # the files still go up
            problems.append(f"database: {exc}")
        client = self.ctx.client()

        def work():
            try:
                result = cloud_backup.upload(s, client, snapshot)
            except Exception as exc:   # never leave the runner stuck
                result = cloud_backup.BackupResult()
                problems.append(str(exc))
            result.errors[:0] = problems
            self._done.emit(result)

        threading.Thread(target=work, name="cloud-backup", daemon=True).start()
        return True

    def _finish(self, result) -> None:
        self.running = False
        self.finished.emit(result)
        if self._again:
            self._again = False
            self.run()


class GameWatcher(QObject):
    game_started = Signal()
    game_closed = Signal()
    INTERVAL_MS = 5000
    CLOSED_CHECKS = 3                  # 15 s without the game

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.running = False
        self._gone = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(self.INTERVAL_MS)

    def check(self) -> None:
        client = self.ctx.client()
        now = game_running(client.path if client else None)
        if now:
            self._gone = 0
            if not self.running:
                self.running = True
                self.game_started.emit()
        elif self.running:
            self._gone += 1
            if self._gone >= self.CLOSED_CHECKS:
                self.running = False
                self._gone = 0
                self.game_closed.emit()
