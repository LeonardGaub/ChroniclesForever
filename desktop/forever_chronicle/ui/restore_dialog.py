"""Restore from the cloud (cloud_backup.py): an addon copy (the newest preselected, any PC), the screenshots missing
here, and a copy of the app database. Each part has its own check box; what is replaced is saved locally first.
The addon file is only replaced while WoW is closed."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QLabel, QMessageBox,
                               QVBoxLayout)

from .. import cloud_backup
from ..config import app_home
from ..i18n import format_datetime, tr
from ..wow.processes import game_running
from .widgets import busy, muted


def _label(v: cloud_backup.Version) -> str:
    pc = tr("restore.this_pc") if v.mine else v.pc
    return tr("restore.addon_item", when=format_datetime(int(v.when.timestamp())), pc=pc)


class RestoreDialog(QDialog):
    def __init__(self, parent, ctx, preselect: cloud_backup.Version | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.settings = ctx.backup_settings()
        self.setWindowTitle(tr("restore.title"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(muted(tr("restore.intro", folder=str(app_home() / "backups"))))

        grid = QGridLayout()
        self.addon_versions = cloud_backup.addon_versions(self.settings) if self.settings else []
        self.db_versions = cloud_backup.database_versions(self.settings) if self.settings else []
        self.addon_box = QCheckBox(tr("restore.addon"))
        self.addon_list = QComboBox()
        for v in self.addon_versions:
            self.addon_list.addItem(_label(v))
        if preselect is not None and preselect in self.addon_versions:
            self.addon_list.setCurrentIndex(self.addon_versions.index(preselect))
        self.db_box = QCheckBox(tr("restore.db"))
        self.db_list = QComboBox()
        for v in self.db_versions:
            self.db_list.addItem(_label(v))
        missing = cloud_backup.missing_screenshots(self.settings, ctx.client()) if self.settings else 0
        self.shots_box = QCheckBox(tr("restore.shots", n=missing))
        for box, items in ((self.addon_box, self.addon_versions), (self.db_box, self.db_versions)):
            box.setEnabled(bool(items))
        self.addon_list.setEnabled(bool(self.addon_versions))
        self.db_list.setEnabled(bool(self.db_versions))
        if not self.addon_versions:
            self.addon_list.addItem(tr("restore.none"))
        if not self.db_versions:
            self.db_list.addItem(tr("restore.none"))
        self.addon_box.setChecked(preselect is not None)
        self.shots_box.setEnabled(missing > 0)
        self.shots_box.setChecked(missing > 0)
        grid.addWidget(self.addon_box, 0, 0)
        grid.addWidget(self.addon_list, 0, 1)
        grid.addWidget(self.shots_box, 1, 0, 1, 2)
        grid.addWidget(self.db_box, 2, 0)
        grid.addWidget(self.db_list, 2, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.run_button = buttons.addButton(tr("restore.run"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.restore)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def restore(self) -> None:
        client = self.ctx.client()
        if self.settings is None or client is None:
            self.reject()
            return
        if self.addon_box.isChecked() and game_running(client.path):
            QMessageBox.warning(self, tr("restore.title"), tr("restore.game_running"))
            return
        lines, changed = [], False
        with busy():
            if self.addon_box.isChecked() and self.addon_versions:
                try:
                    saved = cloud_backup.restore_addon(self.addon_versions[self.addon_list.currentIndex()], client)
                    lines.append(tr("restore.done_addon", path=str(saved.parent) if saved else "-"))
                    changed = True
                except OSError as exc:
                    lines.append(tr("restore.failed", message=str(exc)))
            if self.shots_box.isChecked():
                try:
                    lines.append(tr("restore.done_shots", n=cloud_backup.restore_screenshots(self.settings, client)))
                    changed = True
                except OSError as exc:
                    lines.append(tr("restore.failed", message=str(exc)))
            if self.db_box.isChecked() and self.db_versions:
                try:
                    cloud_backup.restore_database(self.db_versions[self.db_list.currentIndex()], self.ctx.db)
                    lines.append(tr("restore.done_db"))
                    changed = True
                except (OSError, ValueError) as exc:
                    lines.append(tr("restore.failed", message=str(exc)))
            if changed:
                self.ctx.import_all()
        self.result_lines = lines
        QMessageBox.information(self, tr("restore.title"), "\n".join(lines) or "-")
        self.accept()
