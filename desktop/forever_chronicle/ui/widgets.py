"""Shared widgets and the page base class."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QTableWidget, QAbstractItemView, QHeaderView, QWidget

from ..app_context import AppContext
from ..i18n import tr


@contextmanager
def busy() -> Iterator[None]:
    """The wait cursor while the block runs."""
    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QGuiApplication.restoreOverrideCursor()


def choose_client_dir(parent, ctx: AppContext, title: str) -> bool | None:
    """Lets the player pick the game folder. None: cancelled, False: not a WoW folder (nothing changed)."""
    start = str(ctx.client().path) if ctx.client() else "C:\\"
    path = QFileDialog.getExistingDirectory(parent, title, start)
    if not path:
        return None
    return ctx.set_client_dir(Path(path)) is not None


def run_import(ctx: AppContext) -> tuple[list, str | None]:
    """ctx.import_all under the wait cursor: (the results, the first failed file's message or None)."""
    with busy():
        results = ctx.import_all()
    failed = [r for r in results if r.status in ("failed", "rejected")]
    return results, tr("import.failed", message="; ".join(failed[0].messages)) if failed else None


def heading(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Heading")
    return label


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


class ElidedLabel(QLabel):
    """One line that ends in "…" when it does not fit; the hover shows the whole text."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt name)
        self._full = text
        self._elide()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - may shrink below the text's width
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self._full), super().sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:  # noqa: N802 - the style sheet's font arrives after construction
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width) if width > 0 else self._full
        QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


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
    """A tab of the main window. Pages are listed in ``ui.pages``."""

    title_key = ""
    scrollable = False      # a form that may be taller than the window: the main window puts it in a scroll area

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.character_id: str | None = None

    def refresh(self) -> None:
        """Reload data from the database."""

    def leave(self) -> None:
        """The main window shows another page (also when this one sits in a scroll area and gets no hide event)."""

    def retranslate(self) -> None:
        """Re-apply texts after a language change."""
        self.refresh()
