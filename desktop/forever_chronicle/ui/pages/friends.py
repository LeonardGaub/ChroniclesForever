"""Friends: share my characters as a .fcshare file, import friends' files, list and remove friends
(docs/Sharing_Design.md). Friends' characters appear in the sidebar and use the normal pages, read-only."""

from __future__ import annotations

import sqlite3
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidgetItem, QVBoxLayout)

from ...i18n import format_datetime, tr
from ..share_dialog import ShareDialog
from ..widgets import Page, muted, table

FILTER = "Forever Chronicle (*.fcshare)"


class FriendsPage(Page):
    title_key = "tab.friends"
    needs_character = False

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.share_box = QGroupBox()
        sl = QVBoxLayout(self.share_box)
        row = QHBoxLayout()
        self.name_label = QLabel()
        self.name = QLineEdit()
        self.name.setMaxLength(64)
        self.name.editingFinished.connect(self._save_name)
        self.share_button = QPushButton()
        self.share_button.clicked.connect(self.share)
        row.addWidget(self.name_label)
        row.addWidget(self.name, 1)
        row.addWidget(self.share_button)
        sl.addLayout(row)
        self.share_hint = muted()
        sl.addWidget(self.share_hint)
        root.addWidget(self.share_box)

        self.friends_box = QGroupBox()
        fl = QVBoxLayout(self.friends_box)
        actions = QHBoxLayout()
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self._choose_import)
        self.remove_button = QPushButton()
        self.remove_button.clicked.connect(self._remove_selected)
        actions.addWidget(self.import_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        fl.addLayout(actions)
        self.friends = table(4, 0)
        self.friends.itemSelectionChanged.connect(self._selection_changed)
        fl.addWidget(self.friends, 1)
        self.friends_hint = muted()
        fl.addWidget(self.friends_hint)
        root.addWidget(self.friends_box, 1)

        self.message = muted()
        root.addWidget(self.message)
        self._owners = []

    def refresh(self) -> None:
        self.share_box.setTitle(tr("friends.share_group"))
        self.name_label.setText(tr("friends.name"))
        self.name.setPlaceholderText(tr("friends.name_placeholder"))
        if not self.name.hasFocus():
            self.name.setText(self.ctx.config.share_name)
        self.share_button.setText(tr("friends.share"))
        self.share_hint.setText(tr("friends.share_hint"))
        self.friends_box.setTitle(tr("friends.group"))
        self.import_button.setText(tr("friends.import"))
        self.remove_button.setText(tr("friends.remove"))
        self.friends_hint.setText(tr("friends.hint"))
        self.friends.setHorizontalHeaderLabels([tr("friends.col.name"), tr("friends.col.characters"),
                                                tr("friends.col.shared"), tr("friends.col.imported")])
        self._owners = self.ctx.repo.owners()
        self.friends.setRowCount(len(self._owners))
        for i, o in enumerate(self._owners):
            cells = [o["display_name"], str(o["characters"]), format_datetime(o["shared_at"]),
                     format_datetime(o["imported_at"])]
            for col, text in enumerate(cells):
                self.friends.setItem(i, col, QTableWidgetItem(text))
        self._selection_changed()

    def _selection_changed(self) -> None:
        self.remove_button.setEnabled(bool(self.friends.selectedItems()))

    def _save_name(self) -> None:
        self.ctx.config.share_name = self.name.text().strip()

    # -- share ---------------------------------------------------------------------------

    def share(self) -> None:
        self._save_name()
        if not self.ctx.config.share_name:
            self.message.setText(tr("friends.name_missing"))
            self.name.setFocus()
            return
        dialog = ShareDialog(self.ctx, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.ctx.config.extra["share_selection"] = dialog.remembered_selection()
        self.ctx.config.save()
        safe = "".join(ch for ch in self.ctx.config.share_name if ch.isalnum() or ch in "-_") or "Freund"
        default = Path.home() / "Documents" / f"ForeverChronicle-{safe}-{time.strftime('%Y%m%d')}.fcshare"
        path, _ = QFileDialog.getSaveFileName(self, tr("friends.save_title"), str(default), FILTER)
        if not path:
            return
        self.export_to(Path(path), dialog.selection(), dialog.picked_screenshots())

    def export_to(self, path: Path, selection: dict[str, set[str]], screenshots: set[tuple[str, str]]) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.ctx.export_share(path, selection, screenshots)
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.message.setText(tr("friends.failed", message=str(exc)))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.message.setText(tr("friends.shared", characters=result.characters, pictures=result.images,
                                path=str(path)))

    # -- import --------------------------------------------------------------------------

    def _choose_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("friends.import_title"), str(Path.home() / "Downloads"),
                                              FILTER)
        if path:
            self.import_file(Path(path))

    def import_file(self, path: Path) -> None:
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.ctx.import_share(path)
        except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
            self.message.setText(tr("friends.failed", message=str(exc)))
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        if result.status in ("rejected", "failed"):
            self.message.setText(tr("friends.import_failed", message="; ".join(result.messages)))
        elif result.status == "unchanged":
            self.message.setText(tr("friends.unchanged", name=result.sender))
        else:
            text = tr("friends.imported", name=result.sender, characters=result.characters, pictures=result.images)
            if result.skipped_characters or result.invalid:
                text += "  " + tr("friends.import_notes", skipped=len(result.skipped_characters),
                                  invalid=result.invalid)
            self.message.setText(text)
            self.message.setToolTip("\n".join(result.messages))
        self.refresh()

    def _remove_selected(self) -> None:
        rows = {i.row() for i in self.friends.selectedItems()}
        if not rows:
            return
        owner = self._owners[min(rows)]
        if QMessageBox.question(self, tr("app.title"), tr("friends.remove_confirm", name=owner["display_name"])) \
                != QMessageBox.StandardButton.Yes:
            return
        self.ctx.remove_friend(owner["owner_id"])
        self.message.setText(tr("friends.removed", name=owner["display_name"]))
        self.refresh()
