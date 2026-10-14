"""Professions: skill and rank per profession, and the known recipes with search and profession filter
(spec F-008). Both are snapshots from the addon; a recipe list is only called complete when the addon
read the unfiltered list without errors."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLineEdit, QTableWidgetItem, QVBoxLayout

from ...domain.event_types import rank_name
from ...i18n import format_datetime, tr
from .. import theme
from ..widgets import Page, muted, table

STATUS_COLORS = {"complete": theme.TEXT, "partial": theme.GOLD, None: theme.MUTED}


def skill_text(row) -> str:
    rank, max_rank, modifier = row["rank"] or 0, row["max_rank"] or 0, row["modifier"] or 0
    return f"{rank} (+{modifier}) / {max_rank}" if modifier > 0 else f"{rank} / {max_rank}"


def status_text(row) -> str:
    status = row["recipe_status"]
    if status not in ("complete", "partial"):
        return tr("prof.status.none")
    return tr(f"prof.status.{status}", when=format_datetime(row["recipes_updated_at"]))


class ProfessionsPage(Page):
    title_key = "tab.professions"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.prof_box = QGroupBox()
        prof_layout = QVBoxLayout(self.prof_box)
        self.prof_table = table(5, 4)
        self.prof_table.setMaximumHeight(210)
        self.prof_table.currentCellChanged.connect(self._profession_selected)
        prof_layout.addWidget(self.prof_table)
        self.empty = muted()
        prof_layout.addWidget(self.empty)
        root.addWidget(self.prof_box)

        self.recipe_box = QGroupBox()
        recipe_layout = QVBoxLayout(self.recipe_box)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.setMinimumWidth(200)
        self.filter.currentIndexChanged.connect(self._reload_recipes)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._reload_recipes)
        self.count = muted()
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        recipe_layout.addLayout(bar)
        self.recipe_table = table(4, 0)
        recipe_layout.addWidget(self.recipe_table, 1)
        self.hint = muted()
        recipe_layout.addWidget(self.hint)
        root.addWidget(self.recipe_box, 1)

        self._professions = []

    def refresh(self) -> None:
        self.prof_box.setTitle(tr("prof.group"))
        self.recipe_box.setTitle(tr("recipes.group"))
        self.search.setPlaceholderText(tr("recipes.search"))
        self.hint.setText(tr("prof.hint"))
        self.prof_table.setHorizontalHeaderLabels([tr("prof.col.name"), tr("prof.col.skill"), tr("prof.col.rank"),
                                                   tr("prof.col.recipes"), tr("prof.col.status")])
        self.recipe_table.setHorizontalHeaderLabels([tr("recipes.col.name"), tr("recipes.col.category"),
                                                     tr("recipes.col.profession"), tr("recipes.col.id")])
        self._professions = self.ctx.repo.professions(self.character_id) if self.character_id else []

        self.prof_table.blockSignals(True)
        self.prof_table.setRowCount(len(self._professions))
        for i, p in enumerate(self._professions):
            kind = tr(f"prof.kind.{p['kind']}") if p["kind"] in ("primary", "secondary") else ""
            cells = [p["name"], skill_text(p), rank_name(p["max_rank"]),
                     str(p["recipe_count"]) if p["recipe_status"] else "–", status_text(p)]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QColor(theme.GOLD))
                    item.setToolTip(kind)
                elif col == 4:
                    item.setForeground(QColor(STATUS_COLORS.get(p["recipe_status"], theme.MUTED)))
                self.prof_table.setItem(i, col, item)
        self.prof_table.blockSignals(False)
        self.empty.setText(tr("prof.none") if self.character_id and not self._professions else "")
        self.empty.setVisible(bool(self.character_id) and not self._professions)

        current = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem(tr("recipes.all"), None)
        for p in self._professions:
            self.filter.addItem(p["name"], p["skill_line"])
        self.filter.setCurrentIndex(max(self.filter.findData(current), 0))
        self.filter.blockSignals(False)
        self._reload_recipes()

    def _profession_selected(self, row: int, *_args) -> None:
        """Selecting a profession filters the recipe list to it."""
        if 0 <= row < len(self._professions):
            index = self.filter.findData(self._professions[row]["skill_line"])
            if index >= 0:
                self.filter.setCurrentIndex(index)

    def _reload_recipes(self) -> None:
        self.recipe_table.setRowCount(0)
        if not self.character_id:
            self.count.setText("")
            return
        skill_line = self.filter.currentData()
        rows = self.ctx.repo.recipes(self.character_id, skill_line, self.search.text().strip() or None)
        self.recipe_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = [r["name"], r["category"] or "", r["profession"], str(r["recipe_id"])]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    # Name in the colour of the item it creates (default text colour when unknown).
                    color = theme.QUALITY_COLORS.get(r["quality"])
                    if color:
                        item.setForeground(QColor(color))
                else:
                    item.setForeground(QColor(theme.MUTED))
                if col == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.recipe_table.setItem(i, col, item)
        shown = [p for p in self._professions if skill_line is None or p["skill_line"] == skill_line]
        partial = any(p["recipe_status"] == "partial" for p in shown)
        self.count.setText(tr("recipes.count", n=len(rows)) + (tr("recipes.partial_note") if partial else ""))
