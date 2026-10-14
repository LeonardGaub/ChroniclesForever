"""Shared widgets and the page base class."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QTableWidget, QAbstractItemView, QHeaderView, QWidget

from ..app_context import AppContext


def heading(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Heading")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def value_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Value")
    return label


def panel() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Panel")
    return frame


def table(columns: int, stretch_column: int) -> QTableWidget:
    t = QTableWidget(0, columns)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.verticalHeader().setVisible(False)
    header = t.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    return t


class Page(QWidget):
    """A tab of the main window. Pages are listed in ``ui.pages.PAGES``."""

    title_key = ""
    needs_character = True

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.character_id: str | None = None

    def set_character(self, character_id: str | None) -> None:
        self.character_id = character_id
        self.refresh()

    def refresh(self) -> None:
        """Reload data from the database."""

    def retranslate(self) -> None:
        """Re-apply texts after a language change."""
        self.refresh()
