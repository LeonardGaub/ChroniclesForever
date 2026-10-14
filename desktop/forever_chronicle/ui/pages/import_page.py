"""Import: client folder, found SavedVariables files, import button, map art, backups/JSONL transfer and history."""

from __future__ import annotations

import sqlite3
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTableWidgetItem, QVBoxLayout)

from ...i18n import format_datetime, tr
from ...wow.map_art import available_art, import_map_art
from .. import theme
from ..widgets import Page, muted, table, value_label


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

        self.art_box = QGroupBox()
        al = QHBoxLayout(self.art_box)
        self.art_label = QLabel()
        self.art_label.setWordWrap(True)
        self.art_button = QPushButton()
        self.art_button.clicked.connect(self._import_art)
        al.addWidget(self.art_label, 1)
        al.addWidget(self.art_button)
        root.addWidget(self.art_box)

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
        self.folder_button = QPushButton()
        self.folder_button.clicked.connect(self._open_backups)
        for b in (self.export_button, self.import_button, self.backup_button, self.folder_button):
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
        self.art_box.setTitle(tr("import.maps"))
        self.art_button.setText(tr("import.maps_button"))
        count = len(available_art())
        self.art_label.setText(tr("import.maps_count", n=count) if count else tr("import.maps_none"))
        self._refresh_backups()
        self._fill_history()

    def _refresh_backups(self) -> None:
        self.backup_box.setTitle(tr("backup.group"))
        self.export_button.setText(tr("backup.export"))
        self.import_button.setText(tr("backup.import"))
        self.backup_button.setText(tr("backup.now"))
        self.folder_button.setText(tr("backup.folder"))
        self.backup_hint.setText(tr("backup.hint"))
        backups = self.ctx.db.backups()
        if backups:
            when = format_datetime(int(backups[-1].stat().st_mtime))
            self.backup_label.setText(tr("backup.status", when=when, n=len(backups)))
        else:
            self.backup_label.setText(tr("backup.none"))
        self.backup_button.setEnabled(self.ctx.db.backup_dir is not None)

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

    def _import_art(self) -> None:
        start = str(Path.home() / "Downloads")
        path, _ = QFileDialog.getOpenFileName(self, tr("import.maps_title"), start, "ZIP (*.zip)")
        if not path:
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            count = import_map_art(Path(path))
        except (OSError, zipfile.BadZipFile) as exc:
            count, error = 0, str(exc)
        else:
            error = None
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.message.setText(tr("import.failed", message=error) if error else tr("import.maps_done", n=count))
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

    def _open_backups(self) -> None:
        folder = self.ctx.db.backup_dir
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _set_auto(self, checked: bool) -> None:
        self.ctx.config.auto_import = checked
        self.ctx.config.save()
