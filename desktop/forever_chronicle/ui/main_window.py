"""Main window: character list on the left; on the right the character header, the shown page and, at the bottom
like the game's panels, a tab per main page (Start, Übersicht, Chronik, Galerie, Karte, Berufe) and a gear menu
with Import, Einstellungen and Diagnose. The app starts on the home screen. Ctrl+1 ... Ctrl+6 switch the tabs.

Pages ask for another page or character through AppContext.navigate / select_character (home screen cards).
The game's fonts (wow/game_fonts.py) are taken from the install and loaded before anything is built.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import i18n
from ..app_context import AppContext
from ..i18n import format_datetime, tr
from ..storage.repository import Character
from ..wow import game_fonts
from . import theme
from .pages import MAIN_PAGES, MENU_PAGES
from .widgets import Page, heading, muted, panel


class CharacterItem(QWidget):
    """Two-line list entry: class-coloured name, then level and realm."""

    def __init__(self, char: Character):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)
        name = QLabel(char.full_name)
        name.setStyleSheet(theme.font_css(12, theme.class_color(char.class_file)))
        details = muted()
        details.setText(tr("sidebar.char_line", level=char.level or "?", realm=char.realm or ""))
        details.setStyleSheet("background: transparent;")
        layout.addWidget(name)
        layout.addWidget(details)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        try:
            game_fonts.install(ctx.client())
        except Exception:  # the game's fonts are a nicety: the app keeps its fallback fonts
            pass
        self.resize(1180, 780)
        self.setMinimumSize(980, 600)

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

        # Character header, the page, the tabs
        right = QVBoxLayout()
        right.setSpacing(0)
        header = panel()
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.setSpacing(0)
        self.char_name = QLabel()
        self.char_name.setObjectName("Title")
        self.char_details = muted()
        hl.addWidget(self.char_name)
        hl.addWidget(self.char_details)
        right.addWidget(header)
        right.addSpacing(8)

        self.pages: list[Page] = [page_cls(ctx) for page_cls in MAIN_PAGES + MENU_PAGES]
        self.menu_pages = self.pages[len(MAIN_PAGES):]
        self.stack = QStackedWidget()
        self.stack.setObjectName("Panel")
        for page in self.pages:
            self.stack.addWidget(page)
        right.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(6, 0, 6, 0)
        nav.setSpacing(3)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[Page, QPushButton] = {}
        for i, page in enumerate(self.pages[:len(MAIN_PAGES)]):
            button = QPushButton()
            button.setObjectName("NavTab")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, p=page: self.show_page(p))
            self.nav_group.addButton(button)
            self.nav_buttons[page] = button
            nav.addWidget(button)
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, lambda p=page: self.show_page(p))
        nav.addStretch(1)
        self.gear = QPushButton("⚙")
        self.gear.setObjectName("NavGear")
        self.gear.setCheckable(True)
        self.gear.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gear_menu = QMenu(self)
        self.gear_actions: dict[Page, QAction] = {}
        for page in self.menu_pages:
            action = self.gear_menu.addAction("")
            action.triggered.connect(lambda _=False, p=page: self.show_page(p))
            self.gear_actions[page] = action
        self.gear.clicked.connect(self._open_gear)
        nav.addWidget(self.gear)
        right.addLayout(nav)
        root.addLayout(right, 1)

        self._build_menu()
        ctx.data_changed.connect(self.reload)
        ctx.navigate.connect(self._navigate)
        ctx.select_character.connect(self.select_character)
        i18n.on_language_changed(self.retranslate)
        self.retranslate()
        self.reload()
        self.show_page(self.pages[0])

    # -- pages ------------------------------------------------------------------------

    def page(self, title_key: str) -> Page | None:
        return next((p for p in self.pages if p.title_key == title_key), None)

    def current_page(self) -> Page | None:
        return self.stack.currentWidget()

    def show_page(self, page: Page | None) -> None:
        """Shows a page (a tab's or the gear menu's) and loads its data."""
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(page)
        if button is not None:
            button.setChecked(True)
        else:                                # a gear page: no tab is selected
            self.nav_group.setExclusive(False)
            for b in self.nav_buttons.values():
                b.setChecked(False)
            self.nav_group.setExclusive(True)
        self.gear.setChecked(page in self.menu_pages)
        page.refresh()

    def _navigate(self, title_key: str) -> None:
        self.show_page(self.page(title_key))

    def _open_gear(self) -> None:
        """The gear menu opens above its button (the tabs sit at the bottom of the window)."""
        pos = self.gear.mapToGlobal(self.gear.rect().topRight())
        hint = self.gear_menu.sizeHint()
        pos.setX(pos.x() - hint.width())
        pos.setY(pos.y() - hint.height())
        self.gear_menu.exec(pos)
        self.gear.setChecked(self.current_page() in self.menu_pages)

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
        import_page = self.page("tab.import")
        self.show_page(import_page)
        import_page.run_import()

    # -- data -------------------------------------------------------------------------

    def reload(self) -> None:
        """Reload the character list (after an import) and keep the selection. My characters come first;
        friends' characters follow under a heading per friend. At start my own character is shown."""
        chars = self.ctx.repo.list_characters()
        selected = self.current_character_id()
        if selected is None:  # app start: the last character, if it is mine, else my most recent one
            own = [c.character_id for c in chars if not c.is_friend]
            last = self.ctx.config.last_character
            selected = last if last in own else (own[0] if own else None)
        self.characters.blockSignals(True)
        self.characters.clear()
        has_friends = any(c.is_friend for c in chars)
        group = object()
        for char in chars:
            if has_friends and char.owner_id != group:
                group = char.owner_id
                self._add_group_heading(tr("sidebar.mine") if char.owner_id is None
                                        else tr("sidebar.friend", name=char.owner_name or "?"))
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, char)
            item.setSizeHint(QSize(200, 52))
            self.characters.addItem(item)
            self.characters.setItemWidget(item, CharacterItem(char))
        self.characters.blockSignals(False)
        self.side_empty.setVisible(not chars)
        rows = [i for i in range(self.characters.count()) if self.characters.item(i).data(Qt.ItemDataRole.UserRole)]
        target = next((i for i in rows
                       if self.characters.item(i).data(Qt.ItemDataRole.UserRole).character_id == selected),
                      rows[0] if rows else 0)
        if chars:
            self.characters.setCurrentRow(target)
            self._character_selected(self.characters.currentItem())
        else:
            self._show_character(None)
        self._update_status()

    def _add_group_heading(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable
        item.setForeground(QColor(theme.GOLD))
        item.setFont(theme.heading_font(10))
        self.characters.addItem(item)

    def current_character_id(self) -> str | None:
        item = self.characters.currentItem()
        char = item.data(Qt.ItemDataRole.UserRole) if item else None
        return char.character_id if char else None

    def select_character(self, character_id: str) -> None:
        for i in range(self.characters.count()):
            char = self.characters.item(i).data(Qt.ItemDataRole.UserRole)
            if char and char.character_id == character_id:
                self.characters.setCurrentRow(i)
                return

    def _character_selected(self, item: QListWidgetItem | None, _previous=None) -> None:
        char = item.data(Qt.ItemDataRole.UserRole) if item else None
        if char:
            self.ctx.config.last_character = char.character_id
        self._show_character(char)

    def _show_character(self, char: Character | None) -> None:
        if char:
            self.char_name.setText(char.full_name)
            self.char_name.setStyleSheet(f"color: {theme.class_color(char.class_file)};")
            details = tr("char.details", level=char.level or "?", race=char.race_name or "", cls=char.class_name or "")
            text = f"{details}  ·  {char.realm or ''}  ·  {char.faction or ''}"
            if char.is_friend:
                text += "  ·  " + tr("char.friend", name=char.owner_name or "?")
            self.char_details.setText(text)
        else:
            self.char_name.setText(tr("char.none"))
            self.char_name.setStyleSheet(f"color: {theme.MUTED};")
            self.char_details.setText("")
        for page in self.pages:
            page.character_id = char.character_id if char else None
        self._refresh_current()

    def _refresh_current(self) -> None:
        page = self.current_page()
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
        for page, button in self.nav_buttons.items():
            button.setText(tr(page.title_key))
        for page, action in self.gear_actions.items():
            action.setText(tr(page.title_key))
        self.gear.setToolTip(tr("nav.gear_tip"))
        if not self.current_character_id():
            self._show_character(None)
        else:
            self._character_selected(self.characters.currentItem())
        self._update_status()

    def closeEvent(self, event) -> None:
        self.ctx.config.save()
        i18n.remove_listener(self.retranslate)
        super().closeEvent(event)
