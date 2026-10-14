"""Main window: character list on the left, character header and bottom tabs on the right."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import i18n
from ..app_context import AppContext
from ..i18n import format_datetime, tr
from ..storage.repository import Character
from . import theme
from .pages import PAGES
from .widgets import heading, muted, panel


class CharacterItem(QWidget):
    """Two-line list entry: class-coloured name, then level and realm."""

    def __init__(self, char: Character):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)
        name = QLabel(char.name)
        name.setFont(theme.heading_font(12))
        name.setStyleSheet(f"color: {theme.class_color(char.class_file)}; background: transparent;")
        details = muted()
        details.setText(tr("sidebar.char_line", level=char.level or "?", realm=char.realm or ""))
        details.setStyleSheet("background: transparent;")
        layout.addWidget(name)
        layout.addWidget(details)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.resize(1100, 720)
        self.setMinimumSize(900, 560)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self.setCentralWidget(central)

        # Sidebar
        side = panel()
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 10, 10, 10)
        self.side_heading = heading()
        self.characters = QListWidget()
        self.characters.currentItemChanged.connect(self._character_selected)
        self.side_empty = muted()
        sl.addWidget(self.side_heading)
        sl.addWidget(self.characters, 1)
        sl.addWidget(self.side_empty)
        root.addWidget(side)

        # Character header and pages
        right = QVBoxLayout()
        right.setSpacing(8)
        header = panel()
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(2)
        self.char_name = QLabel()
        self.char_name.setObjectName("Title")
        self.char_details = muted()
        hl.addWidget(self.char_name)
        hl.addWidget(self.char_details)
        right.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        self.tabs.setDocumentMode(False)
        self.pages = [page_cls(ctx) for page_cls in PAGES]
        for page in self.pages:
            self.tabs.addTab(page, "")
        self.tabs.currentChanged.connect(lambda _: self._refresh_current())
        right.addWidget(self.tabs, 1)
        root.addLayout(right, 1)

        self._build_menu()
        ctx.data_changed.connect(self.reload)
        i18n.on_language_changed(self.retranslate)
        self.retranslate()
        self.reload()

    # -- menu -------------------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = self.menuBar()
        self.file_menu = bar.addMenu("")
        self.import_action = QAction(self)
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.import_action.triggered.connect(self._import_now)
        self.quit_action = QAction(self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.import_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)

        self.lang_menu = bar.addMenu("")
        group = QActionGroup(self)
        for code, name in i18n.LANGUAGES.items():
            action = QAction(name, self, checkable=True)
            action.setChecked(code == i18n.language())
            action.triggered.connect(lambda _=False, c=code: self._set_language(c))
            group.addAction(action)
            self.lang_menu.addAction(action)

    def _set_language(self, code: str) -> None:
        self.ctx.config.language = code
        self.ctx.config.save()
        i18n.set_language(code)

    def _import_now(self) -> None:
        import_page = next(p for p in self.pages if p.title_key == "tab.import")
        self.tabs.setCurrentWidget(import_page)
        import_page.run_import()

    # -- data -------------------------------------------------------------------------

    def reload(self) -> None:
        """Reload the character list (after an import) and keep the selection."""
        selected = self.current_character_id() or self.ctx.config.last_character
        self.characters.blockSignals(True)
        self.characters.clear()
        chars = self.ctx.repo.list_characters()
        for char in chars:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, char)
            item.setSizeHint(QSize(200, 52))
            self.characters.addItem(item)
            self.characters.setItemWidget(item, CharacterItem(char))
        self.characters.blockSignals(False)
        self.side_empty.setVisible(not chars)
        target = next((i for i in range(self.characters.count())
                       if self.characters.item(i).data(Qt.ItemDataRole.UserRole).character_id == selected), 0)
        if chars:
            self.characters.setCurrentRow(target)
            self._character_selected(self.characters.currentItem())
        else:
            self._show_character(None)
        self._update_status()

    def current_character_id(self) -> str | None:
        item = self.characters.currentItem()
        return item.data(Qt.ItemDataRole.UserRole).character_id if item else None

    def _character_selected(self, item: QListWidgetItem | None, _previous=None) -> None:
        char = item.data(Qt.ItemDataRole.UserRole) if item else None
        if char:
            self.ctx.config.last_character = char.character_id
        self._show_character(char)

    def _show_character(self, char: Character | None) -> None:
        if char:
            self.char_name.setText(char.name)
            self.char_name.setStyleSheet(f"color: {theme.class_color(char.class_file)};")
            details = tr("char.details", level=char.level or "?", race=char.race_name or "", cls=char.class_name or "")
            self.char_details.setText(f"{details}  ·  {char.realm or ''}  ·  {char.faction or ''}")
        else:
            self.char_name.setText(tr("char.none"))
            self.char_name.setStyleSheet(f"color: {theme.MUTED};")
            self.char_details.setText("")
        for page in self.pages:
            page.character_id = char.character_id if char else None
        self._refresh_current()

    def _refresh_current(self) -> None:
        page = self.tabs.currentWidget()
        if page:
            page.refresh()

    def _update_status(self) -> None:
        runs = self.ctx.repo.import_runs(1)
        text = tr("statusbar.last_import", when=format_datetime(runs[0]["started_at"])) if runs \
            else tr("statusbar.never")
        self.statusBar().showMessage(text)

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.title"))
        self.file_menu.setTitle(tr("menu.file"))
        self.import_action.setText(tr("menu.import"))
        self.quit_action.setText(tr("menu.quit"))
        self.lang_menu.setTitle(tr("menu.language"))
        self.side_heading.setText(tr("sidebar.characters"))
        self.side_empty.setText(tr("sidebar.empty"))
        for i, page in enumerate(self.pages):
            self.tabs.setTabText(i, tr(page.title_key))
        if not self.current_character_id():
            self._show_character(None)
        else:
            self._character_selected(self.characters.currentItem())
        self._update_status()

    def closeEvent(self, event) -> None:
        self.ctx.config.save()
        i18n.remove_listener(self.retranslate)
        super().closeEvent(event)
