"""Main window: character list on the left; on the right the character header, the shown page and, at the bottom
like the game's panels, a tab per main page (Start, Übersicht, Chronik, Galerie, Karte, Berufe) and a gear menu
with Import, Einstellungen and Diagnose. The app starts on the home screen. Ctrl+1 ... Ctrl+6 switch the tabs.

Pages ask for another page or character through AppContext.navigate / select_character (home screen cards).
Motion (ui/motion.py): page changes crossfade, buttons and cards glow under the mouse, and an import that brought
new moments is announced by a toast per character at the top right.
Cloud backup (cloud_backup.py): while the window is open, WoW starting and closing start a backup (closing imports
first); at start, changes since the last backup go up, and a banner above the page says when my other PC has newer
addon data (it only offers the restore).
The game's fonts (wow/game_fonts.py) are taken from the install and loaded before anything is built; the game's
sounds (wow/game_sounds.py) are taken in the background.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import cloud_backup, i18n
from ..app_context import AppContext
from ..i18n import format_datetime, tr
from ..storage.repository import Character
from ..wow import game_fonts
from . import theme
from .pages import MAIN_PAGES, MENU_PAGES
from .backup_runner import GameWatcher
from .motion import HoverGlow, PageFader, ToastQueue
from .sound import install_game_sounds
from .widgets import ElidedLabel, Page, heading, muted, panel


class CharacterItem(QWidget):
    """Two-line list entry: class-coloured name, then level and realm."""

    def __init__(self, char: Character):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)
        name = ElidedLabel(char.full_name)
        name.setStyleSheet(theme.font_css(12, theme.class_color(char.class_file)))
        # One line, so a long realm name ends in "…" (full name on hover) instead of wrapping out of the row.
        details = ElidedLabel(tr("sidebar.char_line", level=char.level or "?", realm=char.realm or ""))
        details.setObjectName("Muted")
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
        try:
            install_game_sounds(ctx.client())       # in the background; the built-in sounds play meanwhile
        except Exception:  # the game's sounds are a nicety too
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

        # My other PC has newer addon data: offered, never done by itself.
        self.banner = panel()
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 6, 8, 6)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setStyleSheet(theme.font_css(11, theme.GOLD))
        self.banner_restore = QPushButton()
        self.banner_restore.clicked.connect(self._restore_from_banner)
        banner_close = QPushButton("✕")
        banner_close.setFixedWidth(32)
        banner_close.clicked.connect(self.banner.hide)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.banner_restore)
        bl.addWidget(banner_close)
        self.banner.hide()
        self.banner_version: cloud_backup.Version | None = None
        right.addWidget(self.banner)

        self.pages: list[Page] = [page_cls(ctx) for page_cls in MAIN_PAGES + MENU_PAGES]
        self.menu_pages = self.pages[len(MAIN_PAGES):]
        self.stack = QStackedWidget()
        self.stack.setObjectName("Panel")
        self.containers: dict[Page, QWidget] = {}   # the page itself, or the scroll area round a form page
        for page in self.pages:
            container: QWidget = page
            if page.scrollable:
                container = QScrollArea()
                container.setWidget(page)
                container.setWidgetResizable(True)
                container.setFrameShape(QFrame.Shape.NoFrame)
            self.containers[page] = container
            self.stack.addWidget(container)
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

        self.fader = PageFader(self.stack, ctx.config)
        self.glow = HoverGlow(self, ctx.config)
        self.toasts = ToastQueue(self.stack, ctx.config)
        ctx.imported.connect(self.announce)
        ctx.setup_requested.connect(self.open_setup)
        self.watcher = GameWatcher(ctx, self)
        self.watcher.game_started.connect(ctx.backup.run)
        self.watcher.game_closed.connect(self._game_closed)

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
        current = self.stack.currentWidget()
        return next((p for p, c in self.containers.items() if c is current), None)

    def show_page(self, page: Page | None) -> None:
        """Shows a page (a tab's or the gear menu's) and loads its data."""
        if page is None:
            return
        previous = self.current_page()
        if previous is not None and previous is not page:
            self.fader.fade()
            previous.leave()
        self.stack.setCurrentWidget(self.containers[page])
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
        self.sync_action = QAction(self)
        self.sync_action.setShortcut(QKeySequence("F5"))
        self.sync_action.triggered.connect(self._backup_now)
        self.quit_action = QAction(self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)
        self.setup_action = QAction(self)
        self.setup_action.triggered.connect(self.open_setup)
        self.file_menu.addAction(self.import_action)
        self.file_menu.addAction(self.sync_action)
        self.file_menu.addAction(self.setup_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)

        self.lang_menu = bar.addMenu("")
        group = QActionGroup(self)
        for code, name in i18n.LANGUAGES.items():
            action = QAction(name, self, checkable=True)
            action.setChecked(code == i18n.language())
            action.triggered.connect(lambda _=False, c=code: self.ctx.set_language(c))
            group.addAction(action)
            self.lang_menu.addAction(action)

    def open_setup(self) -> None:
        """The first-start wizard (ui/setup_wizard.py); the window shows what it brought afterwards."""
        from .setup_wizard import SetupWizard
        SetupWizard(self, self.ctx).exec()
        self.reload()

    def _import_now(self) -> None:
        import_page = self.page("tab.import")
        self.show_page(import_page)
        import_page.run_import()

    def _backup_now(self) -> None:
        import_page = self.page("tab.import")
        self.show_page(import_page)
        import_page.run_backup()

    # -- cloud backup -----------------------------------------------------------------

    def _game_closed(self) -> None:
        """WoW was closed: its saved file is new, so into the app first, then into the cloud."""
        self.ctx.import_all(skip_unchanged=True)
        self.ctx.backup.run()

    def start_backup(self) -> None:
        """At app start: the hint about my other PC, then a catch-up backup if something changed meanwhile."""
        s = self.ctx.backup_settings()
        if s is None:
            return
        client = self.ctx.client()
        try:
            self.show_newer_elsewhere(cloud_backup.newer_elsewhere(s, client))
            changed = cloud_backup.has_changes(s, client)
        except OSError:
            return
        if changed:
            self.ctx.backup.run()

    def show_newer_elsewhere(self, version: cloud_backup.Version | None) -> None:
        self.banner_version = version
        if version is None:
            self.banner.hide()
            return
        self.banner_text.setText(tr("cloud.newer", pc=version.pc, when=format_datetime(int(version.when.timestamp()))))
        self.banner_restore.setText(tr("cloud.newer_restore"))
        self.banner.show()

    def _restore_from_banner(self) -> None:
        import_page = self.page("tab.import")
        self.show_page(import_page)
        import_page.open_restore(self.banner_version)
        s = self.ctx.backup_settings()
        self.show_newer_elsewhere(cloud_backup.newer_elsewhere(s, self.ctx.client()) if s else None)

    # -- data -------------------------------------------------------------------------

    def announce(self, import_ids: list) -> None:
        """A toast per character (three at most) for what an import brought: the highest level reached, else
        an achievement, else a discovered zone, else the number of new entries."""
        from ..domain import event_types
        from . import icons
        events = [e for e in self.ctx.repo.events_of_imports(import_ids) if e.event_type != "session_started"]
        names = {c.character_id: c.name for c in self.ctx.repo.list_characters()}
        by_char: dict[str, list] = {}
        for e in events:
            by_char.setdefault(e.character_id, []).append(e)
        for cid, evs in list(by_char.items())[:3]:
            levels = [e for e in evs if e.event_type == "level_up" and isinstance(e.payload.get("level"), int)]
            special = next((e for e in reversed(evs) if e.event_type == "achievement_earned"), None) or \
                next((e for e in reversed(evs) if e.event_type in ("dungeon_completed", "rare_killed",
                                                                   "zone_discovered")), None)
            heading = tr("toast.new_for", name=names.get(cid, "?"))
            place = tr("toast.entries", n=len(evs))
            if levels:
                level = max(e.payload["level"] for e in levels)
                self.toasts.show(heading, tr("cine.level", level=level), place, str(level))
            elif special is not None:
                et = event_types.get(special.event_type)
                self.toasts.show(heading, event_types.describe(special), place, et.glyph, et.color,
                                 icons.of_event(event_types.icon_of(special), special.event_type))
            else:
                self.toasts.show(heading, tr("toast.entries", n=len(evs)), "", "✎")

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
        self.sync_action.setText(tr("menu.sync"))
        self.quit_action.setText(tr("menu.quit"))
        self.setup_action.setText(tr("menu.setup"))
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
