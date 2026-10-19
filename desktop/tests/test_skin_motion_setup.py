"""The Classic skin from the game's textures, motion in the main window (crossfade, hover glow, import toasts) and
the first-start wizard."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect  # noqa: E402

from forever_chronicle.app_context import AppContext  # noqa: E402
from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.ui import theme  # noqa: E402
from forever_chronicle.wow.lua_parser import parse_saved_variables  # noqa: E402
from forever_chronicle.wow.paths import ADDON_NAME, ClientInstall  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply(application)
    return application


@pytest.fixture
def ctx(db, tmp_path, monkeypatch):
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    context = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    context._client_searched = True
    return context


def test_skin_is_built_and_used(app):
    assert theme.skin_available(), "the skin pictures are kept in git (tools/build_ui_skin.py)"
    for name in ("panel", "card", "card_hover", "button_up", "button_hover", "button_selected", "tab", "tab_active",
                 "input", "check", "check_checked", "rock"):
        assert (theme.SKIN / f"{name}.png").is_file(), name
    sheet = theme.stylesheet()
    assert "panel.png" in sheet and "button_up.png" in sheet and sheet.startswith(theme.STYLESHEET)
    assert app.styleSheet() == sheet


def test_motion_in_the_main_window(app, ctx, addon_fixture):
    from forever_chronicle.ui.main_window import MainWindow

    window = MainWindow(ctx)
    window.resize(1100, 700)
    window.show()
    app.processEvents()
    window.show_page(window.page("tab.overview"))
    assert window.fader.running and window.fader.cover.isVisible(), "a page change crossfades"
    ctx.config.extra["ui_motion"] = False
    window.fader.animation.stop()
    window.fader.cover.hide()
    window.show_page(window.page("tab.home"))
    assert not window.fader.cover.isVisible(), "the option turns motion off"
    ctx.config.extra["ui_motion"] = True

    button = window.nav_buttons[window.page("tab.home")]
    window.glow.eventFilter(button, QEvent(QEvent.Type.Enter))
    effect = button.graphicsEffect()
    assert isinstance(effect, QGraphicsDropShadowEffect) and effect.isEnabled(), "buttons glow under the mouse"
    window.glow.animations[button].setCurrentTime(1000)
    assert effect.blurRadius() > 10
    window.glow.eventFilter(button, QEvent(QEvent.Type.Leave))
    window.glow.animations[button].setCurrentTime(1000)
    assert not effect.isEnabled(), "and the glow is switched off once it has faded"

    ids = []
    ctx.imported.connect(ids.extend)
    ctx.importer.import_data(parse_saved_variables(addon_fixture.read_text(encoding="utf-8")), "fixture")
    import_id = ctx.repo.import_runs(1)[0]["import_id"]
    assert ctx.repo.events_of_imports([import_id]), "the events an import added"
    window.announce([import_id])
    assert len(window.toasts.toasts) == 1 and window.toasts.toasts[0].isVisible(), "one toast per character"
    toast = window.toasts.toasts[0]
    toast.leave.start()
    toast.leave.setCurrentTime(toast.leave.duration())
    assert not window.toasts.toasts, "it leaves the queue once it has faded out"
    window.close()


def test_setup_wizard(app, ctx, tmp_path):
    from forever_chronicle.setup_addon import addon_version, bundled_addon
    from forever_chronicle.ui.setup_wizard import STEPS, SetupWizard

    assert ctx.needs_setup(), "a first start: no character, the wizard not done"
    wizard = SetupWizard(None, ctx)
    for i in range(len(STEPS)):
        wizard.go(i)
    assert wizard.index == len(STEPS) - 1 and wizard.next.text() == "Los geht's"
    wizard.go(1)
    assert "nicht automatisch gefunden" in wizard.game_status.text(), "no game found: choose the folder"

    game = tmp_path / "wow" / "_classic_beta_"
    (game / "Interface" / "AddOns").mkdir(parents=True)
    ctx._client = ClientInstall(game, "wow_classic_beta")
    wizard.go(2)
    assert bundled_addon() is not None and wizard.install.isVisibleTo(wizard), "the addon can be installed"
    wizard._install()
    target = game / "Interface" / "AddOns" / ADDON_NAME
    assert addon_version(target) == addon_version(bundled_addon()), "installed next to the game"
    assert not wizard.install.isVisibleTo(wizard), "up to date: nothing more to install"

    wizard._set_language("en")
    assert wizard.titles["addon"].text() == "The addon" and wizard.later.text() == "Later"
    wizard._set_language("de")
    wizard.finish()
    assert ctx.config.extra["setup_done"] and not ctx.needs_setup(), "finished: it does not open again by itself"
