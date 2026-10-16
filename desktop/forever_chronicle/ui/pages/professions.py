"""Professions (spec F-008), as cards: a card per profession (game icon, name, skill bar, rank, recipe list status)
and the known recipes as a card list grouped by profession and category, each with its game icon and its name in
the colour of the item it creates. Clicking a profession card shows only its recipes (again: all). Both are
snapshots from the addon; a recipe list is only called complete when the addon read the unfiltered list without
errors."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...domain.event_types import rank_name
from ...i18n import format_datetime, tr
from .. import icons, theme
from ..cards import ICON_SIZE, CardList
from ..widgets import Page, heading, muted

STATUS_COLORS = {"complete": theme.TEXT, "partial": theme.GOLD, None: theme.MUTED}
PROF_ICON = 40


def skill_text(row) -> str:
    rank, max_rank, modifier = row["rank"] or 0, row["max_rank"] or 0, row["modifier"] or 0
    return f"{rank} (+{modifier}) / {max_rank}" if modifier > 0 else f"{rank} / {max_rank}"


def status_text(row) -> str:
    status = row["recipe_status"]
    if status not in ("complete", "partial"):
        return tr("prof.status.none")
    return tr(f"prof.status.{status}", when=format_datetime(row["recipes_updated_at"]))


class SkillBar(QWidget):
    """The game's skill bar: a dark track, a bronze-gold fill and the skill as text on it."""

    def __init__(self):
        super().__init__()
        self.rank, self.max_rank, self.text = 0, 1, ""
        self.setFixedHeight(16)

    def set_value(self, rank: int, max_rank: int, text: str) -> None:
        self.rank, self.max_rank, self.text = rank, max(1, max_rank), text
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(QColor("#0b0907"))
        painter.drawRoundedRect(r, 3, 3)
        share = max(0.0, min(1.0, self.rank / self.max_rank))
        if share > 0:
            fill = QLinearGradient(0, r.top(), 0, r.bottom())
            fill.setColorAt(0, QColor("#c9a24a"))
            fill.setColorAt(1, QColor("#7a5a1c"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(r.left() + 1, r.top() + 1, (r.width() - 2) * share, r.height() - 2), 2, 2)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("black"))
        painter.drawText(r.translated(1, 1), Qt.AlignmentFlag.AlignCenter, self.text)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text)
        painter.end()


class ProfessionCard(QFrame):
    """One profession: icon, name, skill bar, rank and the recipe list's status. Clicking selects it."""

    clicked = Signal(int)

    def __init__(self, row):
        super().__init__()
        self.skill_line = row["skill_line"]
        self.setObjectName("Card")
        self.setProperty("clickable", True)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(200)
        self.setMaximumWidth(330)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(PROF_ICON, PROF_ICON)
        self.icon.setStyleSheet(f"background: #000; border: 1px solid {theme.BORDER};")
        pix = icons.small(row["icon"], PROF_ICON)
        if pix is not None:
            self.icon.setPixmap(pix)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.name = QLabel(row["name"])
        self.name.setStyleSheet(theme.font_css(12, theme.GOLD))
        kind = tr(f"prof.kind.{row['kind']}") if row["kind"] in ("primary", "secondary") else ""
        self.name.setToolTip(kind)
        self.bar = SkillBar()
        self.skill = skill_text(row)
        self.bar.set_value(row["rank"] or 0, row["max_rank"] or 0, self.skill)
        self.rank = rank_name(row["max_rank"])
        recipes = tr("recipes.count", n=row["recipe_count"]) if row["recipe_status"] else ""
        self.detail = muted("  ·  ".join(p for p in (self.rank, recipes) if p))
        self.status = QLabel(status_text(row))
        self.status.setStyleSheet(f"color: {STATUS_COLORS.get(row['recipe_status'], theme.MUTED)}; font-size: 8pt;")
        for widget in (self.name, self.bar, self.detail, self.status):
            text.addWidget(widget)
        layout.addLayout(text, 1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.skill_line)
        super().mouseReleaseEvent(event)


class ProfessionsPage(Page):
    title_key = "tab.professions"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.prof_heading = heading()
        root.addWidget(self.prof_heading)
        # The profession cards share the width (a character has at most a handful of professions).
        self.card_row = QHBoxLayout()
        self.card_row.setSpacing(10)
        self.card_area = QWidget()
        self.card_area.setObjectName("CardArea")
        self.card_area.setLayout(self.card_row)
        self.card_row.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.card_area)
        self.empty = muted()
        root.addWidget(self.empty)

        bar = QHBoxLayout()
        self.recipe_heading = heading()
        self.filter = QComboBox()
        self.filter.setMinimumWidth(200)
        self.filter.currentIndexChanged.connect(self._filter_changed)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._reload_recipes)
        self.count = muted()
        self.count.setWordWrap(False)
        bar.addWidget(self.recipe_heading)
        bar.addSpacing(10)
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        root.addLayout(bar)
        self.recipes = CardList()
        root.addWidget(self.recipes, 1)
        self.hint = muted()
        root.addWidget(self.hint)

        self.cards: list[ProfessionCard] = []
        self._professions = []

    def refresh(self) -> None:
        self.prof_heading.setText(tr("prof.group"))
        self.recipe_heading.setText(tr("recipes.group"))
        self.search.setPlaceholderText(tr("recipes.search"))
        self.hint.setText(tr("prof.hint"))
        self._professions = self.ctx.repo.professions(self.character_id) if self.character_id else []

        for card in self.cards:
            card.deleteLater()
        self.cards = []
        while self.card_row.count():
            self.card_row.takeAt(0)
        for p in self._professions:
            card = ProfessionCard(p)
            card.clicked.connect(self._card_clicked)
            self.card_row.addWidget(card)
            self.cards.append(card)
        self.card_row.addStretch(1)
        self.card_area.setVisible(bool(self._professions))
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
        self._filter_changed()

    def _card_clicked(self, skill_line: int) -> None:
        """A profession card shows only its recipes; clicking it again shows all."""
        same = self.filter.currentData() == skill_line
        self.filter.setCurrentIndex(0 if same else max(0, self.filter.findData(skill_line)))

    def _filter_changed(self) -> None:
        selected = self.filter.currentData()
        for card in self.cards:
            card.set_selected(card.skill_line == selected)
        self._reload_recipes()

    def _reload_recipes(self) -> None:
        self.recipes.clear()
        if not self.character_id:
            self.count.setText("")
            return
        skill_line = self.filter.currentData()
        rows = self.ctx.repo.recipes(self.character_id, skill_line, self.search.text().strip() or None)
        group = None
        for r in rows:
            key = (r["profession"], r["category"] or "")
            if key != group:
                group = key
                self.recipes.add_header("  ·  ".join(p for p in key if p))
            self.recipes.add_entry(r["name"], "  ·  ".join(p for p in (r["category"], r["profession"]) if p),
                                   icons.small(r["icon"], ICON_SIZE), title_color=theme.QUALITY_COLORS.get(r["quality"]),
                                   data=r["recipe_id"], tooltip=f"{r['name']}  (#{r['recipe_id']})")
        shown = [p for p in self._professions if skill_line is None or p["skill_line"] == skill_line]
        partial = any(p["recipe_status"] == "partial" for p in shown)
        self.count.setText(tr("recipes.count", n=len(rows)) + (tr("recipes.partial_note") if partial else ""))
