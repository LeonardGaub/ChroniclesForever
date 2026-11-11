"""Import: client folder, found SavedVariables files, import button, the cloud backup (folder, name, back up now,
restore), local backups/JSONL transfer and history."""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QTableWidgetItem, QVBoxLayout)

from ... import cloud_backup
from ...i18n import format_datetime, tr
from .. import theme
from ..widgets import Page, busy, choose_client_dir, muted, run_import, table, value_label


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
    scrollable = True

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
        self.auto.toggled.connect(lambda on: ctx.config.set("auto_import", on))
        actions.addWidget(self.run)
        actions.addSpacing(12)
        actions.addWidget(self.auto)
        actions.addStretch(1)
        fl.addLayout(actions)
        self.message = muted()
        fl.addWidget(self.message)
        root.addWidget(self.files_box)

        # The cloud backup (cloud_backup.py): where, under which name, and the two buttons.
        self.cloud_box = QGroupBox()
        cb = QVBoxLayout(self.cloud_box)
        self.cloud_explain = muted()
        cb.addWidget(self.cloud_explain)
        folder_row = QHBoxLayout()
        self.cloud_folder_caption = QLabel()
        self.cloud_folder = value_label()
        self.cloud_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cloud_choose = QPushButton()
        self.cloud_choose.clicked.connect(self._choose_cloud)
        folder_row.addWidget(self.cloud_folder_caption)
        folder_row.addWidget(self.cloud_folder, 1)
        folder_row.addWidget(self.cloud_choose)
        cb.addLayout(folder_row)
        name_row = QHBoxLayout()
        self.cloud_name_caption = QLabel()
        self.cloud_name = QLineEdit()
        self.cloud_name.setMaxLength(40)
        self.cloud_name.editingFinished.connect(self._name_changed)
        name_row.addWidget(self.cloud_name_caption)
        name_row.addWidget(self.cloud_name, 1)
        cb.addLayout(name_row)
        self.cloud_status = QLabel()
        self.cloud_status.setWordWrap(True)
        cb.addWidget(self.cloud_status)
        cloud_actions = QHBoxLayout()
        self.cloud_button = QPushButton()
        self.cloud_button.clicked.connect(self.run_backup)
        self.restore_cloud_button = QPushButton()
        self.restore_cloud_button.clicked.connect(lambda: self.open_restore())
        cloud_actions.addWidget(self.cloud_button)
        cloud_actions.addWidget(self.restore_cloud_button)
        cloud_actions.addStretch(1)
        cb.addLayout(cloud_actions)
        self.cloud_message = muted()
        self.cloud_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cb.addWidget(self.cloud_message)
        root.addWidget(self.cloud_box)
        ctx.backup.started.connect(self._refresh_cloud)
        ctx.backup.finished.connect(self._backup_finished)

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
        self._refresh_cloud()
        self._refresh_backups()
        self._fill_history()

    def _refresh_cloud(self) -> None:
        self.cloud_box.setTitle(tr("cloud.group"))
        self.cloud_explain.setText(tr("cloud.explain"))
        self.cloud_folder_caption.setText(tr("cloud.folder"))
        self.cloud_choose.setText(tr("cloud.choose"))
        self.cloud_name_caption.setText(tr("cloud.name"))
        self.cloud_name.setPlaceholderText(tr("cloud.name_hint"))
        self.cloud_name.setToolTip(tr("cloud.name_hint"))
        self.restore_cloud_button.setText(tr("cloud.restore"))
        folder = self.ctx.config.extra.get("cloud_folder")
        self.cloud_folder.setText(folder or tr("cloud.folder_none"))
        if not self.cloud_name.hasFocus():
            self.cloud_name.setText(self.ctx.config.extra.get("cloud_name") or "")
        running = self.ctx.backup.running
        s = self.ctx.backup_settings()
        self.cloud_button.setText(tr("cloud.running") if running else tr("cloud.run"))
        self.cloud_button.setEnabled(s is not None and not running)
        self.restore_cloud_button.setEnabled(s is not None and not running)
        if s is None:
            self.cloud_status.setText(tr("cloud.not_set"))
            return
        addon, db, shots = cloud_backup.summary(s)
        last = cloud_backup.load_state().get("last_upload")
        friends = [f.name for f in cloud_backup.friend_folders(s.cloud, s.name)]
        self.cloud_status.setText("\n".join([
            tr("cloud.status", addon=addon, db=db, shots=shots),
            tr("cloud.last", when=format_datetime(int(last))) if last else tr("cloud.last_none"),
            tr("cloud.friends", names=", ".join(friends)) if friends else tr("cloud.friends_none")]))

    def _choose_cloud(self) -> None:
        start = self.ctx.config.extra.get("cloud_folder") or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, tr("cloud.choose_title"), start)
        if folder:
            self.ctx.config.set("cloud_folder", str(Path(folder)))
            self.ctx.import_friends()
            self._refresh_cloud()

    def _name_changed(self) -> None:
        name = self.cloud_name.text().strip()
        if name != (self.ctx.config.extra.get("cloud_name") or ""):
            self.ctx.config.set("cloud_name", name)
            self.ctx.import_friends()
        self._refresh_cloud()

    def run_backup(self) -> None:
        """Backs up now (the button, F5): what changed goes up as new copies, the window keeps working."""
        self.cloud_message.setText("")
        if not self.ctx.backup.run():
            self.cloud_message.setText(tr("cloud.not_set"))
        self._refresh_cloud()

    def _backup_finished(self, result) -> None:
        if result.errors:
            self.cloud_message.setText(tr("cloud.failed", message="; ".join(result.errors)))
        elif result.changed:
            self.cloud_message.setText(tr("cloud.done", addon=result.addon, shots=result.screenshots,
                                          db=tr("cloud.done_db") if result.database else ""))
        else:
            self.cloud_message.setText(tr("cloud.unchanged"))
        self._refresh_cloud()

    def open_restore(self, preselect=None) -> None:
        from ..restore_dialog import RestoreDialog
        RestoreDialog(self, self.ctx, preselect).exec()
        self.refresh()

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
        # Columns sized to their contents are measured once at the end, not again after every cell.
        header = self.history.horizontalHeader()
        fitted = [c for c in range(self.history.columnCount())
                  if header.sectionResizeMode(c) == QHeaderView.ResizeMode.ResizeToContents]
        for c in fitted:
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
        self.history.setUpdatesEnabled(False)
        try:
            self._fill_history_rows(runs)
        finally:
            for c in fitted:
                header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
            self.history.setUpdatesEnabled(True)

    def _fill_history_rows(self, runs) -> None:
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
        results, failure = run_import(self.ctx)
        self.message.setText(failure or tr("import.done", imported=sum(r.imported for r in results)))
        self.refresh()

    def _choose_client(self) -> None:
        chosen = choose_client_dir(self, self.ctx, tr("import.choose_title"))
        if chosen is None:
            return
        if not chosen:
            QMessageBox.warning(self, tr("app.title"), tr("import.invalid_dir"))
        self.refresh()

    def _export(self) -> None:
        name = f"ForeverChronicle-Export-{time.strftime('%Y%m%d-%H%M')}.jsonl"
        path, _ = QFileDialog.getSaveFileName(self, tr("backup.export_title"), str(Path.home() / "Documents" / name),
                                              "JSON Lines (*.jsonl)")
        if not path:
            return
        try:
            with busy():
                result = self.ctx.export_jsonl(Path(path))
        except (OSError, sqlite3.Error) as exc:
            self.backup_message.setText(tr("backup.failed", message=str(exc)))
            return
        self.backup_message.setText(tr("backup.exported", records=result.records, characters=result.characters,
                                       path=str(result.path)))

    def _import_jsonl(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("backup.import_title"), str(Path.home() / "Documents"),
                                              "JSON Lines (*.jsonl)")
        if not path:
            return
        if QMessageBox.question(self, tr("app.title"), tr("backup.import_confirm")) != QMessageBox.StandardButton.Yes:
            return
        try:
            with busy():
                result = self.ctx.import_jsonl(Path(path))
        except (OSError, sqlite3.Error) as exc:
            self.backup_message.setText(tr("backup.import_failed", message=str(exc)))
            return
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
        try:
            with busy():
                self.ctx.restore_backup(path)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self.backup_message.setText(tr("backup.restore_failed", message=str(exc)))
            return
        self.backup_message.setText(tr("backup.restored", backup=backup_label(path)))
        self.refresh()

    def _open_backups(self) -> None:
        folder = self.ctx.db.backup_dir
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
