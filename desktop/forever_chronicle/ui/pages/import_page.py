"""Import: client folder, found SavedVariables files, import button, the friends' cloud sync (run it now),
backups/JSONL transfer and history."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QPushButton, QTableWidgetItem, QVBoxLayout)

from ... import cloud_sync
from ...i18n import format_datetime, tr
from .. import theme
from ..widgets import Page, muted, table, value_label


def backup_label(path: Path) -> str:
    """'14.10.2026 15:30  ·  täglich' from chronicle-20261014-153000-daily.db."""
    parts = path.stem.split("-", 3)
    try:
        when = format_datetime(int(time.mktime(time.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S"))))
    except (IndexError, ValueError):
        return path.name
    label = re.sub(r"-\d+$", "", parts[3]) if len(parts) > 3 else ""  # "manual-2": second in the same second
    kind = tr("backup.kind.migration") if label.startswith("before-migration") else tr(f"backup.kind.{label}")
    return f"{when}  ·  {kind if not kind.startswith('backup.kind.') else label}"


class ImportPage(Page):
    title_key = "tab.import"
    needs_character = False

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.client_box = QGroupBox()
        cl = QHBoxLayout(self.client_box)
        self.client_label = value_label()
        self.client_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.choose = QPushButton()
        self.choose.clicked.connect(self._choose_client)
        cl.addWidget(self.client_label, 1)
        cl.addWidget(self.choose)
        root.addWidget(self.client_box)

        self.files_box = QGroupBox()
        fl = QVBoxLayout(self.files_box)
        self.files_label = QLabel()
        self.files_label.setWordWrap(True)
        fl.addWidget(self.files_label)
        actions = QHBoxLayout()
        self.run = QPushButton()
        self.run.clicked.connect(self.run_import)
        self.auto = QCheckBox()
        self.auto.toggled.connect(self._set_auto)
        actions.addWidget(self.run)
        actions.addSpacing(12)
        actions.addWidget(self.auto)
        actions.addStretch(1)
        fl.addLayout(actions)
        self.message = muted()
        fl.addWidget(self.message)
        root.addWidget(self.files_box)

        # The friends' cloud sync (sync/ForeverSync.ps1): one run now instead of waiting for the next one.
        self.sync_box = QGroupBox()
        sl = QVBoxLayout(self.sync_box)
        self.sync_label = QLabel()
        self.sync_label.setWordWrap(True)
        sl.addWidget(self.sync_label)
        sync_actions = QHBoxLayout()
        self.sync_button = QPushButton()
        self.sync_button.clicked.connect(self.run_sync)
        sync_actions.addWidget(self.sync_button)
        sync_actions.addStretch(1)
        sl.addLayout(sync_actions)
        self.sync_message = muted()
        self.sync_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sl.addWidget(self.sync_message)
        root.addWidget(self.sync_box)
        self.sync_process: QProcess | None = None
        self._sync_log_start = 0

        # Backups and JSONL export/import (spec F-011).
        self.backup_box = QGroupBox()
        bl = QVBoxLayout(self.backup_box)
        self.backup_label = QLabel()
        self.backup_label.setWordWrap(True)
        bl.addWidget(self.backup_label)
        buttons = QHBoxLayout()
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._export)
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self._import_jsonl)
        self.backup_button = QPushButton()
        self.backup_button.clicked.connect(self._backup_now)
        self.restore_button = QPushButton()
        self.restore_button.clicked.connect(self._restore)
        self.folder_button = QPushButton()
        self.folder_button.clicked.connect(self._open_backups)
        for b in (self.export_button, self.import_button, self.backup_button, self.restore_button,
                  self.folder_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        bl.addLayout(buttons)
        self.backup_hint = muted()
        bl.addWidget(self.backup_hint)
        self.backup_message = muted()
        bl.addWidget(self.backup_message)
        root.addWidget(self.backup_box)

        self.history_box = QGroupBox()
        hl = QVBoxLayout(self.history_box)
        self.history = table(4, 3)
        hl.addWidget(self.history)
        root.addWidget(self.history_box, 1)

    def refresh(self) -> None:
        self.client_box.setTitle(tr("import.client"))
        self.files_box.setTitle(tr("import.files"))
        self.history_box.setTitle(tr("import.history"))
        self.choose.setText(tr("import.choose"))
        self.run.setText(tr("import.run"))
        self.auto.setText(tr("import.auto"))
        self.auto.blockSignals(True)
        self.auto.setChecked(self.ctx.config.auto_import)
        self.auto.blockSignals(False)

        client = self.ctx.client()
        self.client_label.setText(str(client.path) if client else tr("import.client_none"))
        files = self.ctx.saved_variables()
        if files:
            lines = []
            for sv in files:
                try:
                    when = format_datetime(int(sv.path.stat().st_mtime))
                except OSError:
                    when = tr("common.unknown")
                lines.append(tr("import.file_line", account=sv.account, when=when))
            self.files_label.setText("\n".join(lines))
        else:
            self.files_label.setText(tr("import.files_none"))
        self.run.setEnabled(bool(files))
        self._refresh_sync()
        self._refresh_backups()
        self._fill_history()

    def _refresh_sync(self) -> None:
        self.sync_box.setTitle(tr("sync.group"))
        running = self.sync_process is not None
        setup = cloud_sync.find_setup()
        self.sync_button.setText(tr("sync.running") if running else tr("sync.run") if setup else tr("sync.setup_run"))
        self.sync_button.setEnabled(not running and cloud_sync.sync_script() is not None)
        if cloud_sync.sync_script() is None:
            self.sync_label.setText(tr("sync.no_script"))
            return
        if setup is None:
            self.sync_label.setText(tr("sync.none"))
            return
        # What is where: my upload (push), friends' files in the cloud and what the game got of them (pull).
        files = cloud_sync.player_files(setup)
        mine = [f for f in files if f.mine]
        friends = [f for f in files if not f.mine]
        lines = [tr("sync.cloud", cloud=setup.cloud),
                 tr("sync.pushed", files=self._player_list(mine)) if mine else tr("sync.pushed_none"),
                 tr("sync.pulled", files=self._player_list(friends)) if friends else tr("sync.pulled_none")]
        game = cloud_sync.friends_in_game(setup)
        lines.append(tr("sync.in_game", n=game[0], when=format_datetime(int(game[1]))) if game
                     else tr("sync.in_game_none"))
        last = cloud_sync.log_lines(setup.folder)[-1:]
        if last:
            lines.append(tr("sync.last", line=last[0]))
        self.sync_label.setText("\n".join(lines))

    @staticmethod
    def _player_list(files: list[cloud_sync.PlayerFile]) -> str:
        return ", ".join(f"{f.name} ({format_datetime(int(f.modified))})" for f in files)

    def run_sync(self) -> None:
        """Starts one sync run (the setup first, when there is none yet): it uploads my share file and pulls
        friends' files into the game. The window keeps working while it runs."""
        script = cloud_sync.sync_script()
        if script is None or self.sync_process is not None:
            self._refresh_sync()
            return
        folder = cloud_sync.sync_dir()
        self._sync_log_start = cloud_sync.log_size(folder)
        command = cloud_sync.run_command if cloud_sync.find_setup(folder) else cloud_sync.setup_command
        program, args = command(script, folder)
        self.sync_process = QProcess(self)
        self.sync_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.sync_process.finished.connect(self._sync_finished)
        self.sync_process.errorOccurred.connect(self._sync_failed)
        self.sync_message.setText("")
        self.sync_process.start(program, args)
        self._refresh_sync()

    def _sync_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        process, self.sync_process = self.sync_process, None
        if process is None:
            return
        output = bytes(process.readAll()).decode("utf-8", errors="replace").strip()
        process.deleteLater()
        new = cloud_sync.log_lines(cloud_sync.sync_dir(), self._sync_log_start)
        if code != 0 or status != QProcess.ExitStatus.NormalExit:
            self.sync_message.setText(tr("sync.failed", message=output or code))
            self._refresh_sync()
            return
        self.run_import()  # into the app too: my newest data and friends' characters from the cloud folder
        lines = [tr("sync.failed", message="") if any(" failed: " in line for line in new) else tr("sync.done")]
        lines += new
        friends = self.ctx.last_friend_import
        if friends.imported:
            lines.append(tr("sync.app_friends", names=", ".join(friends.imported)))
        if friends.removed:
            lines.append(tr("sync.app_removed", names=", ".join(friends.removed)))
        shots = self.ctx.last_friend_screenshots
        if shots.copied or shots.removed:
            lines.append(tr("sync.app_shots", copied=shots.copied, removed=shots.removed))
        if friends.failed:
            lines.append(tr("sync.app_failed", message="; ".join(friends.failed)))
        self.sync_message.setText("\n".join(lines))
        self._refresh_sync()

    def _sync_failed(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart or self.sync_process is None:
            return  # a crash also ends in finished()
        process, self.sync_process = self.sync_process, None
        self.sync_message.setText(tr("sync.failed", message=process.errorString()))
        process.deleteLater()
        self._refresh_sync()

    def _refresh_backups(self) -> None:
        self.backup_box.setTitle(tr("backup.group"))
        self.export_button.setText(tr("backup.export"))
        self.import_button.setText(tr("backup.import"))
        self.backup_button.setText(tr("backup.now"))
        self.restore_button.setText(tr("backup.restore"))
        self.folder_button.setText(tr("backup.folder"))
        self.backup_hint.setText(tr("backup.hint"))
        backups = self.ctx.db.backups()
        if backups:
            when = format_datetime(int(backups[-1].stat().st_mtime))
            self.backup_label.setText(tr("backup.status", when=when, n=len(backups)))
        else:
            self.backup_label.setText(tr("backup.none"))
        self.backup_button.setEnabled(self.ctx.db.backup_dir is not None)
        self.restore_button.setEnabled(bool(backups))

    def _fill_history(self) -> None:
        self.history.setHorizontalHeaderLabels([tr("import.col.when"), tr("import.col.source"),
                                                tr("import.col.status"), tr("import.col.result")])
        runs = self.ctx.repo.import_runs()
        self.history.setRowCount(len(runs))
        for i, r in enumerate(runs):
            source = r["account"] or Path(r["source_path"]).name
            if r["used_backup"]:
                source += " (.bak)"
            result = tr("import.result", imported=r["rows_imported"], duplicates=r["rows_duplicate"],
                        invalid=r["rows_invalid"], gaps=r["gaps_detected"])
            if r["status"] in ("rejected", "failed"):
                result = r["message"] or ""
            cells = [format_datetime(r["started_at"]), source, tr(f"status.{r['status']}"), result]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 2 and r["status"] in ("rejected", "failed"):
                    item.setForeground(QColor(theme.RED))
                if col == 3 and r["message"]:
                    item.setToolTip(r["message"])
                self.history.setItem(i, col, item)

    def run_import(self) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            results = self.ctx.import_all()
        finally:
            QGuiApplication.restoreOverrideCursor()
        failed = [r for r in results if r.status in ("failed", "rejected")]
        if failed:
            self.message.setText(tr("import.failed", message="; ".join(failed[0].messages)))
        else:
            self.message.setText(tr("import.done", imported=sum(r.imported for r in results)))
        self.refresh()

    def _choose_client(self) -> None:
        start = str(self.ctx.client().path) if self.ctx.client() else "C:\\"
        path = QFileDialog.getExistingDirectory(self, tr("import.choose_title"), start)
        if not path:
            return
        if not self.ctx.set_client_dir(Path(path)):
            QMessageBox.warning(self, tr("app.title"), tr("import.invalid_dir"))
        self.refresh()

    def _export(self) -> None:
        name = f"ForeverChronicle-Export-{time.strftime('%Y%m%d-%H%M')}.jsonl"
        path, _ = QFileDialog.getSaveFileName(self, tr("backup.export_title"), str(Path.home() / "Documents" / name),
                                              "JSON Lines (*.jsonl)")
        if not path:
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.ctx.export_jsonl(Path(path))
        except (OSError, sqlite3.Error) as exc:
            self.backup_message.setText(tr("backup.failed", message=str(exc)))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.backup_message.setText(tr("backup.exported", records=result.records, characters=result.characters,
                                       path=str(result.path)))

    def _import_jsonl(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("backup.import_title"), str(Path.home() / "Documents"),
                                              "JSON Lines (*.jsonl)")
        if not path:
            return
        if QMessageBox.question(self, tr("app.title"), tr("backup.import_confirm")) != QMessageBox.StandardButton.Yes:
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.ctx.import_jsonl(Path(path))
        except (OSError, sqlite3.Error) as exc:
            self.backup_message.setText(tr("backup.import_failed", message=str(exc)))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        if result.status in ("rejected", "failed"):
            self.backup_message.setText(tr("backup.import_failed", message="; ".join(result.messages)))
        else:
            text = tr("backup.imported", inserted=result.inserted, updated=result.updated,
                      unchanged=result.unchanged, invalid=result.invalid)
            self.backup_message.setText(text)
            self.backup_message.setToolTip("\n".join(result.messages))
        self.refresh()

    def _backup_now(self) -> None:
        try:
            target = self.ctx.db.backup("manual")
        except (OSError, sqlite3.Error) as exc:
            self.backup_message.setText(tr("backup.failed", message=str(exc)))
            return
        self.backup_message.setText(tr("backup.done", name=target.name) if target else "")
        self._refresh_backups()

    def _restore(self) -> None:
        backups = list(reversed(self.ctx.db.backups()))  # newest first
        if not backups:
            return
        labels = [backup_label(p) for p in backups]
        choice, ok = QInputDialog.getItem(self, tr("backup.restore_title"), tr("backup.restore_choose"), labels, 0,
                                          False)
        if not ok:
            return
        path = backups[labels.index(choice)]
        if QMessageBox.question(self, tr("app.title"), tr("backup.restore_confirm", backup=choice)) \
                != QMessageBox.StandardButton.Yes:
            return
        self.restore_selected(path)

    def restore_selected(self, path: Path) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.ctx.restore_backup(path)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self.backup_message.setText(tr("backup.restore_failed", message=str(exc)))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.backup_message.setText(tr("backup.restored", backup=backup_label(path)))
        self.refresh()

    def _open_backups(self) -> None:
        folder = self.ctx.db.backup_dir
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _set_auto(self, checked: bool) -> None:
        self.ctx.config.auto_import = checked
        self.ctx.config.save()
