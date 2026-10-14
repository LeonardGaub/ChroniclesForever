"""Shared application state: configuration, database, importer and the data-changed signal."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import AppConfig
from .importing.screenshot_matcher import match_screenshots
from .importing.sv_importer import ImportResult, SavedVariablesImporter
from .storage.database import Database
from .storage.repository import Repository
from .wow.paths import ClientInstall, SavedVariablesFile, client_from_path, find_forever_installs, find_saved_variables


class AppContext(QObject):
    data_changed = Signal()
    focus_time = Signal(str, int)  # (character_id, epoch seconds): show this moment, e.g. on the map

    def __init__(self, config: AppConfig, db: Database):
        super().__init__()
        self.config = config
        self.db = db
        self.repo = Repository(db.conn)
        self.importer = SavedVariablesImporter(db)
        self._client: ClientInstall | None = None
        self._client_searched = False

    def client(self) -> ClientInstall | None:
        if self._client or self._client_searched:
            return self._client
        self._client_searched = True
        if self.config.client_dir:
            self._client = client_from_path(Path(self.config.client_dir))
        if not self._client:
            installs = find_forever_installs()
            self._client = installs[0] if installs else None
        return self._client

    def set_client_dir(self, path: Path) -> ClientInstall | None:
        client = client_from_path(path)
        if client:
            self._client = client
            self.config.client_dir = str(client.path)
            self.config.save()
        return client

    def saved_variables(self) -> list[SavedVariablesFile]:
        client = self.client()
        return find_saved_variables(client) if client else []

    def import_all(self, skip_unchanged: bool = False) -> list[ImportResult]:
        results = [self.importer.import_file(sv.path, sv.account, skip_unchanged=skip_unchanged)
                   for sv in self.saved_variables()]
        matched = self.match_screenshots()
        if matched or any(r.status != "unchanged" for r in results):
            self.data_changed.emit()
        return results

    def match_screenshots(self) -> int:
        """Links screenshot records to files in the client's Screenshots folder."""
        client = self.client()
        with self.db.transaction():
            return match_screenshots(self.repo, client.screenshots_dir if client else None)
