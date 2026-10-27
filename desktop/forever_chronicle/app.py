"""Application entry point: ``python -m forever_chronicle``."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import cloud_backup, i18n
from .app_context import AppContext
from .config import AppConfig
from .setup_addon import update_addon
from .storage.database import Database
from .ui import audio_setup, theme
from .ui.main_window import MainWindow

DAILY = 24 * 3600


ICON = Path(__file__).with_name("app.ico")   # the addon's icon (icons/inv_misc_book_09.png), 16-256 px
APP_ID = "JourneyForever.Desktop"


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":   # own taskbar entry with the app's icon, not grouped under pythonw.exe
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Journey Forever")
    app.setWindowIcon(QIcon(str(ICON)))
    theme.apply(app)

    config = AppConfig.load()
    i18n.set_language(config.language)
    db = Database(config.database_path, config.backup_dir)
    try:
        db.backup_if_older(DAILY, "daily")  # spec F-011: regular local backups (newest 5 are kept)
    except Exception:  # a failed backup must not stop the app; the import page shows the backup state
        pass
    cloud_backup.adopt_old_settings(config)  # the removed friends sync's cloud folder, the old share name
    ctx = AppContext(config, db)
    ctx.sound.install_click_sounds(app)
    try:
        update_addon(ctx.client())           # a newer addon from the repository (WoW closed); the old companion goes
    except OSError:
        pass

    window = MainWindow(ctx)
    window.show()
    if config.auto_import:
        QTimer.singleShot(200, lambda: ctx.import_all(skip_unchanged=True))
    QTimer.singleShot(1500, window.start_backup)   # the other-PC hint, then what changed since the last backup
    def first_steps() -> None:
        if ctx.needs_setup():                # first start: the wizard first, the sound offer after it
            window.open_setup()
        audio_setup.offer_at_start(window, ctx)

    QTimer.singleShot(800, first_steps)
    code = app.exec()
    db.close()
    if audio_setup.RESTART:                  # the sound part was just installed: it loads in a new process
        audio_setup.start_again()
    return code


if __name__ == "__main__":
    sys.exit(main())
