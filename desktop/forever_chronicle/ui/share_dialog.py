"""Share dialog: pick my characters, the categories per character and the screenshots to share
(docs/Sharing_Design.md). Nothing is pre-selected for screenshots; they can show chat."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QListView, QListWidget, QListWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..i18n import format_datetime, tr
from ..storage.share import CATEGORIES
from .widgets import heading, muted

THUMB = QSize(160, 100)
ROLE = Qt.ItemDataRole.UserRole


class ShareDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("share.title"))
        self.resize(760, 640)
        layout = QVBoxLayout(self)

        layout.addWidget(heading(tr("share.characters")))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        remembered = ctx.config.extra.get("share_selection") or {}
        for char in ctx.repo.list_characters():
            if char.is_friend:
                continue
            key = ctx.db.conn.execute("SELECT natural_key FROM characters WHERE character_id = ?",
                                      (char.character_id,)).fetchone()[0]
            top = QTreeWidgetItem([tr("share.char_line", name=char.full_name, level=char.level or "?",
                                      realm=char.realm or "")])
            top.setData(0, ROLE, (char.character_id, key))
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            chosen = set(remembered.get(key, ()))
            for cat in CATEGORIES:
                child = QTreeWidgetItem([tr(f"share.cat.{cat}")])
                child.setData(0, ROLE, cat)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked if cat in chosen else Qt.CheckState.Unchecked)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.itemChanged.connect(self._tree_changed)
        layout.addWidget(self.tree, 2)

        layout.addWidget(heading(tr("share.screenshots")))
        self.shots_hint = muted(tr("share.screenshots_hint"))
        layout.addWidget(self.shots_hint)
        self.shots = QListWidget()
        self.shots.setViewMode(QListView.ViewMode.IconMode)
        self.shots.setIconSize(THUMB)
        self.shots.setResizeMode(QListView.ResizeMode.Adjust)
        self.shots.setSpacing(6)
        self.shots.setMovement(QListView.Movement.Static)
        self.shots.itemChanged.connect(lambda _item: self._update_summary())
        layout.addWidget(self.shots, 3)

        self.summary = QLabel()
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        layout.addWidget(buttons)
        self._thumbs: dict[str, QIcon] = {}
        self._tree_changed()

    # -- selection ------------------------------------------------------------------------

    def _tree_changed(self, _item: QTreeWidgetItem | None = None, _column: int = 0) -> None:
        # Ticking a character ticks all its categories; screenshots still have to be picked one by one.
        self._fill_screenshots()
        self._update_summary()

    def selection(self) -> dict[str, set[str]]:
        """character_id -> chosen categories (characters with at least one category)."""
        out = {}
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            cats = {top.child(j).data(0, ROLE) for j in range(top.childCount())
                    if top.child(j).checkState(0) == Qt.CheckState.Checked}
            if cats:
                out[top.data(0, ROLE)[0]] = cats
        return out

    def remembered_selection(self) -> dict[str, list[str]]:
        out = {}
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            out[top.data(0, ROLE)[1]] = sorted(top.child(j).data(0, ROLE) for j in range(top.childCount())
                                               if top.child(j).checkState(0) == Qt.CheckState.Checked)
        return out

    def picked_screenshots(self) -> set[tuple[str, str]]:
        return {tuple(self.shots.item(i).data(ROLE)) for i in range(self.shots.count())
                if self.shots.item(i).checkState() == Qt.CheckState.Checked}

    def _fill_screenshots(self) -> None:
        picked = self.picked_screenshots()
        self.shots.blockSignals(True)
        self.shots.clear()
        with_shots = [cid for cid, cats in self.selection().items() if "screenshots" in cats]
        for cid in with_shots:
            for row in self.ctx.repo.screenshots(cid, only_files=True):
                path = row["file_path"]
                item = QListWidgetItem(self._thumb(path), format_datetime(row["captured_at"] or row["requested_at"]))
                item.setData(ROLE, (cid, row["screenshot_id"]))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if (cid, row["screenshot_id"]) in picked
                                   else Qt.CheckState.Unchecked)
                item.setToolTip(Path(path).name)
                self.shots.addItem(item)
        self.shots.blockSignals(False)
        self.shots.setEnabled(bool(with_shots))
        self.shots_hint.setText(tr("share.screenshots_hint") if with_shots else tr("share.screenshots_off"))

    def _thumb(self, path: str) -> QIcon:
        if path not in self._thumbs:
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            self._thumbs[path] = QIcon(QPixmap.fromImage(image)) if not image.isNull() else QIcon()
        return self._thumbs[path]

    def _update_summary(self) -> None:
        sel = self.selection()
        self.summary.setText(tr("share.summary", characters=len(sel), pictures=len(self.picked_screenshots())))
        self.save_button.setEnabled(bool(sel))
