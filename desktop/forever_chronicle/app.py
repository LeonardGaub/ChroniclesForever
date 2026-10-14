"""Application entry point: ``python -m forever_chronicle``."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import i18n
from .app_context import AppContext
from .config import AppConfig
from .storage.database import Database
from .ui import theme
from .ui.main_window import MainWindow

DAILY = 24 * 3600


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Forever Chronicle")
    theme.apply(app)

    config = AppConfig.load()
    i18n.set_language(config.language)
    db = Database(config.database_path, config.backup_dir)
    try:
        db.backup_if_older(DAILY, "daily")  # spec F-011: regular local backups (newest 5 are kept)
    except Exception:  # a failed backup must not stop the app; the import page shows the backup state
        pass
    ctx = AppContext(config, db)

    window = MainWindow(ctx)
    window.show()
    if config.auto_import:
        QTimer.singleShot(200, lambda: ctx.import_all(skip_unchanged=True))
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
