"""Shared application state: configuration, database, importer and the data-changed signal."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import cloud_sync
from .config import AppConfig
from .importing.friend_importer import FriendImportResult, import_friends
from .importing.screenshot_matcher import match_screenshots
from .importing.sv_importer import ImportResult, SavedVariablesImporter
from .storage.database import Database
from .storage.jsonl import ExportResult, JsonlImportResult, export_jsonl, import_jsonl
from .storage.repository import Repository
from .ui.sound import Sound
from .wow import game_icons
from .wow.paths import ClientInstall, SavedVariablesFile, client_from_path, find_forever_installs, find_saved_variables


class AppContext(QObject):
    data_changed = Signal()
    focus_time = Signal(str, int)  # (character_id, epoch seconds): show this moment, e.g. on the map
    navigate = Signal(str)         # show a page (its title_key), e.g. from a card on the home screen
    select_character = Signal(str)  # make this character the shown one (character_id)

    def __init__(self, config: AppConfig, db: Database):
        super().__init__()
        self.config = config
        self.db = db
        self.repo = Repository(db.conn)
        self.importer = SavedVariablesImporter(db)
        self.sound = Sound(config)
        self._client: ClientInstall | None = None
        self._client_searched = False
        self.last_friend_import = FriendImportResult()

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
        friends = self.import_friends(notify=False)
        matched = self.match_screenshots()
        new_icons = self.extract_icons()
        if matched or new_icons or friends.changed or any(r.status != "unchanged" for r in results):
            self.data_changed.emit()
        return results

    def import_friends(self, notify: bool = True) -> FriendImportResult:
        """Friends' characters from the cloud folder of this PC's sync (importing/friend_importer.py)."""
        setup = cloud_sync.find_setup()
        self.last_friend_import = import_friends(self.db, setup) if setup else FriendImportResult()
        if notify and self.last_friend_import.changed:
            self.data_changed.emit()
        return self.last_friend_import

    def extract_icons(self) -> int:
        """Takes the icons recorded with events, professions and recipes that have no picture yet out of the local
        game (wow/game_icons.py). Opens the game files only when one is missing; returns how many were added."""
        return game_icons.extract_missing(self.client(), self.repo.event_icons() + self.repo.profession_icons())

    # -- backups and JSONL transfer (spec F-011) ------------------------------------------

    def export_jsonl(self, path: Path) -> ExportResult:
        return export_jsonl(self.db, path)

    def import_jsonl(self, path: Path) -> JsonlImportResult:
        """Merges an export into the database (a backup is made first) and links screenshots on this computer."""
        result = import_jsonl(self.db, path)
        if result.status in ("ok", "partial"):
            self.match_screenshots()
            self.extract_icons()
            self.data_changed.emit()
        return result

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
