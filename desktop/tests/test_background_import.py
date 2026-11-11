"""Work kept off the UI thread: the background import (AppContext.import_all_in_background) reads and parses in a
worker thread and imports in the main thread; the game watcher looks for the game in a worker thread."""

import os
import threading
import time

import pytest

from forever_chronicle import app_context
from forever_chronicle.ui import backup_runner
from forever_chronicle.ui.backup_runner import GameWatcher
from forever_chronicle.wow.paths import ClientInstall


def wait_until(condition, ms: int = 10_000) -> None:
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    clock = QElapsedTimer()
    clock.start()
    while not condition() and clock.elapsed() < ms:
        QCoreApplication.processEvents()
        time.sleep(0.001)
    assert condition()


@pytest.fixture
def client(ctx, tmp_path, addon_fixture):
    """`ctx` with a client whose one account holds the addon fixture (written a minute ago: no wait for the game)."""
    root = tmp_path / "WoW" / "_forever_"
    saved = root / "WTF" / "Account" / "123456#1" / "SavedVariables"
    saved.mkdir(parents=True)
    sv = saved / "ForeverChronicle.lua"
    sv.write_bytes(addon_fixture.read_bytes())
    os.utime(sv, (time.time() - 60, time.time() - 60))
    ctx._client = ClientInstall(root, "wowf")
    return ctx


def test_background_import_reads_in_a_worker_and_imports_here(app, client, monkeypatch):
    ctx = client
    threads = []
    real_read = app_context.read_saved_file
    monkeypatch.setattr(app_context, "read_saved_file",
                        lambda *a: threads.append(threading.current_thread()) or real_read(*a))
    changed, imported, results = [], [], []
    ctx.data_changed.connect(lambda: changed.append(1))
    ctx.imported.connect(imported.append)
    ctx.import_all_in_background(skip_unchanged=True, done=results.append)
    assert ctx.importing and not results, "returns at once"
    wait_until(lambda: results)
    assert threads and threads[0] is not threading.main_thread()
    [[result]] = results
    assert result.status == "ok" and result.imported == 6 and not ctx.importing
    assert changed and imported == [[result.import_id]]

    ctx.import_all_in_background(done=results.append)
    wait_until(lambda: len(results) == 2)
    assert results[1][0].status == "unchanged"


def test_a_request_during_a_run_runs_once_more(app, client):
    ctx = client
    calls = []
    ctx.import_all_in_background(skip_unchanged=False, done=lambda r: calls.append(("first", r)))
    ctx.import_all_in_background(skip_unchanged=False, done=lambda r: calls.append(("second", r)))
    ctx.import_all_in_background(skip_unchanged=False, done=lambda r: calls.append(("third", r)))
    wait_until(lambda: len(calls) == 3 and not ctx.importing)
    (first, [a]), (second, [b]), (third, [c]) = calls
    assert (first, second, third) == ("first", "second", "third")
    assert a.imported == 6 and b.duplicates == 6 and b is c, "the waiting requests share one more run"
    assert len(ctx.repo.import_runs()) == 2


def test_import_all_during_a_run_reads_the_files_again(app, client):
    """The worker's reads may be older than what import_all imported meanwhile: they are read again, not imported."""
    ctx = client
    results = []
    ctx.import_all_in_background(skip_unchanged=True, done=results.append)
    [now] = ctx.import_all(skip_unchanged=True)
    assert now.imported == 6
    wait_until(lambda: results and not ctx.importing)
    assert [r.status for r in results[0]] == ["unchanged"]
    assert len(ctx.repo.import_runs()) == 1


def test_unreadable_file_in_the_background(app, client):
    ctx = client
    sv = ctx.saved_variables()[0].path
    sv.write_text("ForeverChronicleDB = os.execute('x')", encoding="utf-8")
    os.utime(sv, (time.time() - 60, time.time() - 60))
    results = []
    ctx.import_all_in_background(done=results.append)
    wait_until(lambda: results)
    assert results[0][0].status == "failed" and ctx.repo.import_runs()[0]["status"] == "failed"


def test_game_watcher_looks_in_a_worker_thread(app, ctx, monkeypatch):
    seen = {"now": True, "threads": []}

    def running(_path):
        seen["threads"].append(threading.current_thread())
        if seen["now"] is None:
            raise OSError("no process list")
        return seen["now"]

    monkeypatch.setattr(backup_runner, "game_running", running)
    watcher = GameWatcher(ctx)
    watcher.timer.stop()
    started, closed = [], []
    watcher.game_started.connect(lambda: started.append(1))
    watcher.game_closed.connect(lambda: closed.append(1))
    watcher.look()
    watcher.look()                                   # one look at a time
    wait_until(lambda: started and not watcher._looking)
    assert watcher.running and len(seen["threads"]) == 1
    assert seen["threads"][0] is not threading.main_thread()

    seen["now"] = None                               # a failed look changes nothing
    watcher.look()
    wait_until(lambda: not watcher._looking)
    assert watcher.running and not closed

    seen["now"] = False
    for _ in range(GameWatcher.CLOSED_CHECKS):
        watcher.look()
        wait_until(lambda: not watcher._looking)
    assert closed == [1] and not watcher.running
