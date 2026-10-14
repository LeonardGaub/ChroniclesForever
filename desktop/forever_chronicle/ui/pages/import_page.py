"""Import: client folder, found SavedVariables files, import button and history."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
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
        self._fill_history()

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

    def _set_auto(self, checked: bool) -> None:
        self.ctx.config.auto_import = checked
        self.ctx.config.save()
