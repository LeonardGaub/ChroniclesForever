"""First-start wizard: five short steps from nothing to the first imported character.

1. Welcome: what the app does, and the language (German or English, switched at once).
2. The game: WoW Forever found automatically (wow/paths.py), or chosen by hand.
3. The addon: installed in the game, and its version against the one next to the app (addons\\ForeverChronicle
   beside the desktop folder); installs or updates it (setup_addon.install_addon, which also removes the old
   friends companion). Then: log in once, /fj opens the addon, logging out saves its data.
4. The data: the addon's saved files found per WoW account; imports them now; automatic import at start.
5. Done: what is ready, and where the cinematic mode is.

It opens by itself while no character exists and the wizard was not finished or skipped (extra.setup_done), and
again from the file menu ("Einrichtung ...") and the home screen's first-steps card.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import i18n
from ..i18n import format_datetime, tr
from ..setup_addon import addon_version, bundled_addon, install_addon
from ..wow.paths import ADDON_NAME
from . import theme
from .widgets import choose_client_dir, run_import

STEPS = ("welcome", "game", "addon", "data", "done")
OK, MISSING = "✔", "✘"
GREEN = "#40c040"


class StepDots(QWidget):
    """The steps as gold diamonds on a line: done filled, the current one larger and glowing."""

    def __init__(self):
        super().__init__()
        self.current = 0
        self.setFixedHeight(26)

    def set_current(self, index: int) -> None:
        self.current = index
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(STEPS)
        gap = min(70.0, (self.width() - 40) / max(1, n - 1))
        x0 = (self.width() - gap * (n - 1)) / 2
        y = self.height() / 2
        painter.setPen(QPen(QColor(201, 162, 74, 120), 1.4))
        painter.drawLine(QPointF(x0, y), QPointF(x0 + gap * (n - 1), y))
        for i in range(n):
            size = 7.5 if i == self.current else 5.0
            painter.save()
            painter.translate(x0 + gap * i, y)
            painter.rotate(45)
            if i == self.current:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 196, 60, 70))
                painter.drawRect(QRectF(-size * 1.8, -size * 1.8, size * 3.6, size * 3.6))
            painter.setPen(QPen(QColor("#c9a24a"), 1.4))
            painter.setBrush(QColor(theme.GOLD) if i <= self.current else QColor("#1a120a"))
            painter.drawRect(QRectF(-size, -size, 2 * size, 2 * size))
            painter.restore()
        painter.end()


def _label(css: str, wrap: bool = True) -> QLabel:
    label = QLabel()
    label.setStyleSheet(css)
    label.setWordWrap(wrap)
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _status(text: str, mark: str = MISSING, color: str = theme.RED) -> str:
    """A status line: the coloured mark (a red cross by default), then the text."""
    return f"<span style='color:{color}'>{mark}</span>&nbsp; {text}"


class SetupWizard(QDialog):
    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setMinimumSize(680, 500)
        self.index = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)
        self.brand = _label(theme.font_css(26, theme.GOLD, title=True), wrap=False)
        self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.brand)
        self.dots = StepDots()
        root.addWidget(self.dots)
        frame = QFrame()
        frame.setObjectName("Panel")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(22, 18, 22, 18)
        self.stack = QStackedWidget()
        frame_layout.addWidget(self.stack)
        root.addWidget(frame, 1)

        self.titles: dict[str, QLabel] = {}
        self.texts: dict[str, QLabel] = {}
        self.pages: dict[str, QVBoxLayout] = {}
        for step in STEPS:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            self.titles[step] = _label(theme.font_css(18, theme.GOLD, title=True))
            self.texts[step] = _label(f"color: {theme.TEXT}; font-size: 10pt; background: transparent;")
            layout.addWidget(self.titles[step])
            layout.addWidget(self.texts[step])
            self.pages[step] = layout
            self.stack.addWidget(page)

        # 1: language
        languages = QHBoxLayout()
        self.language_buttons = {}
        for code, name in i18n.LANGUAGES.items():
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, c=code: self._set_language(c))
            languages.addWidget(button)
            self.language_buttons[code] = button
        languages.addStretch(1)
        self.pages["welcome"].addLayout(languages)
        # 2: the game
        self.game_status = _label(theme.font_css(12))
        self.choose_game = QPushButton()
        self.choose_game.clicked.connect(self._choose_game)
        self.pages["game"].addWidget(self.game_status)
        self.pages["game"].addWidget(self.choose_game, 0, Qt.AlignmentFlag.AlignLeft)
        # 3: the addon
        self.addon_status = _label(theme.font_css(12))
        self.install = QPushButton()
        self.install.clicked.connect(self._install)
        self.addon_hint = _label(f"color: {theme.MUTED}; background: transparent;")
        self.pages["addon"].addWidget(self.addon_status)
        self.pages["addon"].addWidget(self.install, 0, Qt.AlignmentFlag.AlignLeft)
        self.pages["addon"].addWidget(self.addon_hint)
        # 4: the data
        self.data_status = _label(theme.font_css(11))
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self._import)
        self.import_result = _label(theme.font_css(12, theme.GOLD))
        self.auto_import = QCheckBox()
        self.auto_import.setChecked(ctx.config.auto_import)
        self.auto_import.toggled.connect(lambda on: ctx.config.set("auto_import", on))
        for widget in (self.data_status, self.import_button, self.import_result, self.auto_import):
            self.pages["data"].addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft if widget is not self.data_status
                                         else Qt.AlignmentFlag.AlignTop)
        # 5: done
        self.summary = _label(theme.font_css(12))
        self.pages["done"].addWidget(self.summary)
        for layout in self.pages.values():
            layout.addStretch(1)

        buttons = QHBoxLayout()
        self.later = QPushButton()
        self.later.clicked.connect(lambda: self.finish(accepted=False))
        self.back = QPushButton()
        self.back.clicked.connect(lambda: self.go(self.index - 1))
        self.next = QPushButton()
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        buttons.addWidget(self.later)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        root.addLayout(buttons)
        self.retranslate()
        self.go(0)

    # -- steps ------------------------------------------------------------------------

    def step(self) -> str:
        return STEPS[self.index]

    def go(self, index: int) -> None:
        self.index = max(0, min(len(STEPS) - 1, index))
        self.stack.setCurrentIndex(self.index)
        self.dots.set_current(self.index)
        self.refresh()

    def _next(self) -> None:
        if self.index == len(STEPS) - 1:
            self.finish()
        else:
            self.go(self.index + 1)

    def finish(self, accepted: bool = True) -> None:
        """Finished, or skipped with "Später": either way the wizard does not open again by itself."""
        self.ctx.config.set("setup_done", True)
        self.done(QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected)

    def refresh(self) -> None:
        """The current step's state (what was found, what can be done)."""
        last = self.index == len(STEPS) - 1
        self.back.setVisible(self.index > 0)
        self.later.setVisible(not last)
        self.next.setText(tr("setup.finish") if last else tr("setup.next"))
        client = self.ctx.client()
        if self.step() == "welcome":
            for code, button in self.language_buttons.items():
                button.setChecked(code == i18n.language())
        elif self.step() == "game":
            self.game_status.setText(_status(f"{tr('setup.game_found')}<br><span style='color:{theme.MUTED}'>"
                                             f"{client.path}</span>", OK, GREEN) if client else
                                     _status(tr("setup.game_missing")))
            self.choose_game.setText(tr("setup.choose_other") if client else tr("setup.choose"))
        elif self.step() == "addon":
            installed = addon_version(client.addons_dir / ADDON_NAME) if client else None
            source = bundled_addon()
            bundled = addon_version(source) if source else None
            if not client:
                text = _status(tr("setup.addon_no_game"))
            elif installed is None:
                text = _status(tr("setup.addon_missing"))
            elif bundled and bundled != installed:
                text = _status(tr("setup.addon_old", have=installed, new=bundled), "!", theme.GOLD)
            else:
                text = _status(tr("setup.addon_ok", version=installed), OK, GREEN)
            self.addon_status.setText(text)
            self.install.setText(tr("setup.install") if installed is None else tr("setup.update"))
            self.install.setVisible(bool(client and source and (installed is None or bundled != installed)))
        elif self.step() == "data":
            files = self.ctx.saved_variables()
            if files:
                rows = "<br>".join(f"{OK}&nbsp; {tr('setup.data_file', account=f.account or '?', when=format_datetime(int(f.path.stat().st_mtime)))}"
                                   for f in files)
                self.data_status.setText(rows)
            else:
                self.data_status.setText(f"<span style='color:{theme.MUTED}'>{tr('setup.data_missing')}</span>")
            self.import_button.setEnabled(bool(files))
        elif self.step() == "done":
            chars = [c for c in self.ctx.repo.list_characters() if not c.is_friend]
            lines = [f"{OK if client else MISSING}&nbsp; {tr('setup.sum_game')}",
                     f"{OK if chars else MISSING}&nbsp; {tr('setup.sum_chars', n=len(chars))}"]
            self.summary.setText("<br>".join(lines) + f"<br><br><span style='color:{theme.MUTED}'>"
                                 f"{tr('setup.sum_tip')}</span>")

    # -- actions ----------------------------------------------------------------------

    def _set_language(self, code: str) -> None:
        self.ctx.set_language(code)
        self.retranslate()

    def _choose_game(self) -> None:
        if choose_client_dir(self, self.ctx, tr("setup.choose")) is False:
            self.game_status.setText(_status(tr("import.invalid_dir")))
            return
        self.refresh()

    def _install(self) -> None:
        source, client = bundled_addon(), self.ctx.client()
        if not (source and client):
            return
        try:
            result = install_addon(source, client)
        except OSError as error:
            self.addon_status.setText(_status(tr("setup.install_failed", error=error)))
            return
        self.refresh()
        self.addon_hint.setText(tr("setup.addon_installed", version=result.version or "?") + "<br>" + tr("setup.addon_hint"))

    def _import(self) -> None:
        results, failure = run_import(self.ctx)
        chars = len([c for c in self.ctx.repo.list_characters() if not c.is_friend])
        self.import_result.setText(failure or tr("setup.imported", chars=chars, events=sum(r.imported for r in results)))

    def retranslate(self) -> None:
        self.setWindowTitle(tr("setup.window"))
        self.brand.setText("Journey Forever")
        for step in STEPS:
            self.titles[step].setText(tr(f"setup.{step}.title"))
            self.texts[step].setText(tr(f"setup.{step}.text"))
        self.import_button.setText(tr("setup.import"))
        self.auto_import.setText(tr("import.auto"))
        self.addon_hint.setText(tr("setup.addon_hint"))
        self.later.setText(tr("setup.later"))
        self.back.setText(tr("setup.back"))
        self.refresh()
