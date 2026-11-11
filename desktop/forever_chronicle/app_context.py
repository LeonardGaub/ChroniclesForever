"""Shared application state: configuration, database, importer and the data-changed signal."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

from . import cloud_backup, i18n
from .config import AppConfig
from .domain.route_colors import MODES
from .importing.friend_importer import FriendImportResult, import_friends
from .importing.friend_screenshots import FriendScreenshotsResult, sync_friend_screenshots
from .importing.screenshot_matcher import match_screenshots
from .importing.sv_importer import ImportResult, SavedFile, SavedVariablesImporter, read_saved_file
from .storage.database import Database
from .storage.jsonl import ExportResult, JsonlImportResult, export_jsonl, import_jsonl
from .storage.repository import Repository
from .ui.backup_runner import BackupRunner
from .ui.sound import Sound
from .wow import game_icons
from .wow.paths import ClientInstall, SavedVariablesFile, client_from_path, find_saved_variables, pick_client


class AppContext(QObject):
    data_changed = Signal()
    navigate = Signal(str)         # show a page (its title_key), e.g. from a card on the home screen
    select_character = Signal(str)  # make this character the shown one (character_id)
    imported = Signal(list)        # import_ids of imports that brought new events (the main window announces them)
    setup_requested = Signal()     # open the first-start wizard (the home screen's first-steps card)
    _files_read = Signal(object)   # from import_all_in_background's worker thread

    def needs_setup(self) -> bool:
        """True on a first start: no character yet, and the wizard was neither finished nor skipped."""
        return not self.config.extra.get("setup_done") and not self.repo.list_characters()

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
        self.last_friend_screenshots = FriendScreenshotsResult()
        self.backup = BackupRunner(self)       # the cloud backup, off the main thread (ui/backup_runner.py)
        # import_all_in_background: a run is going on; one more is waiting (its skip_unchanged, None: none); the
        # callbacks for the next run; import_all ran during the run.
        self.importing = False
        self._import_again: bool | None = None
        self._import_waiting: list[Callable[[list[ImportResult]], None]] = []
        self._import_stale = False
        self._files_read.connect(self._import_read_files, Qt.ConnectionType.QueuedConnection)

    def set_language(self, code: str) -> None:
        """Switches the language (i18n tells its listeners) and keeps it in the settings."""
        self.config.set("language", code)
        i18n.set_language(code)

    @property
    def map_colors(self) -> str:
        """How routes are coloured (domain/route_colors.py MODES): chosen in the settings, used by the Kino page, the
        cinematic mode and the video."""
        mode = self.config.extra.get("map_colors")
        return mode if mode in MODES else MODES[0]

    def client(self) -> ClientInstall | None:
        if self._client or self._client_searched:
            return self._client
        self._client_searched = True
        self._client = pick_client(self.config.client_dir)
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
        if self.importing:
            self._import_stale = True   # the background run's files may be older than what this imports
        results = [self.importer.import_file(sv.path, sv.account, skip_unchanged=skip_unchanged)
                   for sv in self.saved_variables()]
        return self._after_import(results)

    def import_all_in_background(self, skip_unchanged: bool = True,
                                 done: Callable[[list[ImportResult]], None] | None = None) -> None:
        """import_all without blocking the window: the files are read and parsed in a worker thread, then imported
        here in the main thread (the database connection lives here). ``done`` gets the results afterwards. One run
        at a time: a request during a run makes one more run after it (unchanged files skipped only if every
        request said so), whose results go to the waiting ``done`` callbacks."""
        if done is not None:
            self._import_waiting.append(done)
        if self.importing:
            self._import_again = skip_unchanged and (self._import_again is not False)
            return
        files = [(sv.path, sv.account, self.importer.last_seen(sv.path) if skip_unchanged else None)
                 for sv in self.saved_variables()]
        self.importing = True
        self._import_stale = False
        callbacks, self._import_waiting = self._import_waiting, []

        def work() -> None:
            reads = []
            for path, account, last in files:
                try:
                    reads.append(read_saved_file(path, account, last))
                except Exception as exc:   # never leave the run unfinished
                    reads.append(SavedFile(path, account, error=f"file could not be read: {exc}"))
            self._files_read.emit((reads, callbacks, skip_unchanged))

        threading.Thread(target=work, name="import-read", daemon=True).start()

    def _import_read_files(self, payload: tuple[list[SavedFile], list[Callable], bool]) -> None:
        """Main thread: imports what the worker read, then tells the callbacks and starts a waiting run."""
        reads, callbacks, skip_unchanged = payload
        results: list[ImportResult] = []
        if self._import_stale:   # import_all ran meanwhile: read the files again rather than import older reads
            self._import_waiting[:0] = callbacks
            self._import_again = skip_unchanged and (self._import_again is not False)
            callbacks = []
        else:
            try:
                results = self._after_import([self.importer.import_read(read) for read in reads])
            except Exception as exc:   # e.g. a database error: reported like a failed file, the next run still starts
                results = [ImportResult(source=str(read.path), status="failed", messages=[str(exc)]) for read in reads]
        self.importing = False
        again, self._import_again = self._import_again, None
        if again is not None:
            self.import_all_in_background(again)
        for callback in callbacks:
            callback(results)

    def _after_import(self, results: list[ImportResult]) -> list[ImportResult]:
        """What follows the files' import: friends, screenshots, icons, and the signals."""
        friends = self.import_friends(notify=False)
        matched = self.match_screenshots()
        new_icons = self.extract_icons()
        if matched or new_icons or friends.changed or self.last_friend_screenshots.changed or any(r.status != "unchanged" for r in results):
            self.data_changed.emit()
        fresh = [r.import_id for r in results if r.imported and r.import_id is not None]
        if fresh:
            self.imported.emit(fresh)
        return results

    def backup_settings(self) -> cloud_backup.BackupSettings | None:
        """The cloud backup's folder and my name (cloud_backup.py); None until both are set."""
        return cloud_backup.settings(self.config)

    def import_friends(self, notify: bool = True) -> FriendImportResult:
        """Friends' characters from the other players' folders in my cloud folder (importing/friend_importer.py)."""
        s = self.backup_settings()
        cloud, name = (s.cloud, s.name) if s else (None, None)
        self.last_friend_import = import_friends(self.db, cloud, name) if s else FriendImportResult()
        # Their pictures (importing/friend_screenshots.py), linked to the records just read.
        self.last_friend_screenshots = sync_friend_screenshots(self.db, cloud, name) if s else FriendScreenshotsResult()
        if notify and (self.last_friend_import.changed or self.last_friend_screenshots.changed):
            self.data_changed.emit()
        return self.last_friend_import

    def extract_icons(self) -> int:
        """Takes the icons recorded with events that have no picture yet out of the local game
        (wow/game_icons.py). Opens the game files only when one is missing; returns how many were added."""
        return game_icons.extract_missing(self.client(), self.repo.event_icons())

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
