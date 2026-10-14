"""Shared application state: configuration, database, importer and the data-changed signal."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import AppConfig
from .importing.screenshot_matcher import match_screenshots
from .importing.sv_importer import ImportResult, SavedVariablesImporter
from .storage.database import Database
from .storage.jsonl import ExportResult, JsonlImportResult, export_jsonl, import_jsonl
from .storage.share import ShareExportResult, ShareImportResult, export_share, import_share, remove_friend
from .storage.repository import Repository
from .wow.friends_data import FriendsDataResult, write_friends_data
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
        self.friends_data: FriendsDataResult | None = None  # last write for the addon
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

    # -- backups and JSONL transfer (spec F-011) ------------------------------------------

    def export_jsonl(self, path: Path) -> ExportResult:
        return export_jsonl(self.db, path)

    def import_jsonl(self, path: Path) -> JsonlImportResult:
        """Merges an export into the database (a backup is made first) and links screenshots on this computer."""
        result = import_jsonl(self.db, path)
        if result.status in ("ok", "partial"):
            self.match_screenshots()
            self.data_changed.emit()
        return result

    # -- friends (docs/Sharing_Design.md) ------------------------------------------------

    def export_share(self, path: Path, selection: dict[str, set[str]],
                     screenshots: set[tuple[str, str]]) -> ShareExportResult:
        return export_share(self.db, path, self.config.share_id, self.config.share_name, selection, screenshots)

    def import_share(self, path: Path) -> ShareImportResult:
        result = import_share(self.db, path, self.config.share_id, self.config.friends_dir)
        if result.status in ("ok", "partial"):
            self.data_changed.emit()
        return result

    def remove_friend(self, owner_id: int) -> None:
        remove_friend(self.db, owner_id, self.config.friends_dir)
        self.data_changed.emit()

    def update_friends_data(self) -> FriendsDataResult:
        """Writes friends' characters into the addon folder (shown in game after /reload)."""
        self.friends_data = write_friends_data(self.db.conn, self.client())
        return self.friends_data

    def restore_backup(self, path: Path) -> Path | None:
        """Replaces all data with a backup (the current state is backed up first)."""
        before = self.db.restore(path)
        self.data_changed.emit()
        return before

    def match_screenshots(self) -> int:
        """Links screenshot records to files in the client's Screenshots folder."""
        client = self.client()
        with self.db.transaction():
            return match_screenshots(self.repo, client.screenshots_dir if client else None)
