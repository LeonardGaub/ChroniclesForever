"""The desktop app's view of the cloud sync: finding the setup, what is in the cloud and in the game, and the Import
page's button running the sync script once, or the setup first (stand-in scripts that only write settings and log)."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QElapsedTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from forever_chronicle import cloud_sync  # noqa: E402
from forever_chronicle.app_context import AppContext  # noqa: E402
from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.ui.pages.import_page import ImportPage  # noqa: E402

needs_powershell = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"),
                                      reason="Windows PowerShell needed")


def install(folder):
    """A sync set up in ``folder``, with its cloud folder and game folder next to it."""
    folder.mkdir(parents=True, exist_ok=True)
    config = {"cloud": str(folder.parent / "Journey Forever Cloud"), "client": str(folder.parent / "WoW"),
              "repo": "C:\\Repo", "shareId": "a" * 32, "scriptVersion": 3}
    (folder / "config.json").write_text(json.dumps(config), encoding="utf-8-sig")
    return cloud_sync.find_setup(folder)


def test_find_setup_and_commands(tmp_path):
    assert cloud_sync.find_setup() is None, "conftest: no sync on a test PC"
    setup = install(tmp_path / "sync")
    assert cloud_sync.find_setup() == setup and setup.share_id == "a" * 32
    assert setup.friends_file == tmp_path / "WoW" / "Interface" / "AddOns" / "ForeverChronicle_Share" / "Friends" / \
        "FriendsData.lua"
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "config.json").write_text("{", encoding="utf-8")
    assert cloud_sync.find_setup(tmp_path / "broken") is None

    script = Path("C:/Repo/sync/ForeverSync.ps1")
    program, args = cloud_sync.run_command(script, setup.folder)
    assert program == "powershell.exe" and args[-4:] == [str(script), "-Once", "-DataDir", str(setup.folder)]
    assert cloud_sync.setup_command(script, setup.folder)[1][-3:] == ["-Setup", "-DataDir", str(setup.folder)]


def test_log_lines_from_an_offset(tmp_path):
    folder = tmp_path / "sync"
    folder.mkdir()
    (folder / "sync.log").write_text("2026-10-16 09:22:18 sync started\n", encoding="utf-8-sig")  # with a BOM
    assert cloud_sync.log_lines(folder) == ["2026-10-16 09:22:18 sync started"]
    start = cloud_sync.log_size(folder)
    with (folder / "sync.log").open("a", encoding="utf-8") as f:
        f.write("2026-10-16 13:42:19 friends file written: 1 friend file(s)\n")
    assert cloud_sync.log_lines(folder, start) == ["2026-10-16 13:42:19 friends file written: 1 friend file(s)"]


def share(name):
    return f'\nForeverChronicleShareDB = {{\n\t["maps"] = {{\n\t\t\t["name"] = "Kalimdor",\n\t}},\n' \
           f'\t["name"] = "{name}",\n}}\n'


def fill_cloud(setup):
    """My uploads (two WoW accounts), two friends' (one without a name) and stray files."""
    players = Path(setup.cloud) / "players"
    players.mkdir(parents=True)
    (players / "Blind-aaaaaaaa-282b7857.lua").write_text(share("Blind"), encoding="utf-8")
    (players / "Level-aaaaaaaa-00000001.lua").write_text(share("Level"), encoding="utf-8")
    (players / "Jonas-00ba3518-a093e141.lua").write_text(share('Jonas \\"J\\" Fr\u00e4nd'), encoding="utf-8")
    (players / "Spieler-bbbbbbbb-0000000c.lua").write_text("ForeverChronicleShareDB = {}", encoding="utf-8")
    (players / f"{'b' * 32}-0000000d.lua").write_text(share("Old"), encoding="utf-8")
    (players / "readme.lua").write_text(share("Nobody"), encoding="utf-8")


def test_player_files_and_friends_in_game(tmp_path):
    setup = install(tmp_path / "sync")
    assert cloud_sync.player_files(setup) == [] and cloud_sync.friends_in_game(setup) is None
    fill_cloud(setup)
    files = cloud_sync.player_files(setup)
    assert [(f.name, f.mine) for f in files] == [("Blind", True), ("Level", True), ("?", False),
                                                 ('Jonas "J" Fr\u00e4nd', False)]
    setup.friends_file.parent.mkdir(parents=True)
    setup.friends_file.write_text('ForeverChronicleFriends = {}\nadd("a.lua", [[\n]])\nadd("b.lua", [=[\n]=])\n',
                                  encoding="utf-8")
    assert cloud_sync.friends_in_game(setup)[0] == 2


@pytest.fixture
def page(db, tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("FOREVER_CHRONICLE_HOME", str(tmp_path))
    ctx = AppContext(AppConfig(client_dir=str(tmp_path / "missing")), db)
    ctx._client_searched = True
    page = ImportPage(ctx)
    page.refresh()
    return page


def stand_in(tmp_path, monkeypatch, body):
    """A stand-in for the repository's sync script; ``body`` runs with $Setup, $Once and $DataDir."""
    script = tmp_path / "repo" / "sync" / "ForeverSync.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("param([switch]$Setup, [switch]$Once, [string]$DataDir)\n"
                      "function Log($m) { Add-Content -Path (Join-Path $DataDir 'sync.log') -Value $m -Encoding UTF8 }\n"
                      + body, encoding="utf-8")
    monkeypatch.setattr(cloud_sync, "sync_script", lambda: script)
    return script


def wait_for(page: ImportPage) -> None:
    clock = QElapsedTimer()
    clock.start()
    while page.sync_process is not None and clock.elapsed() < 30_000:
        QCoreApplication.processEvents()
    assert page.sync_process is None, "the sync did not finish"


def test_no_script_no_button(page):
    assert not page.sync_button.isEnabled() and "ForeverSync.ps1" in page.sync_label.text()
    page.run_sync()
    assert page.sync_process is None


@needs_powershell
def test_sync_now_shows_push_and_pull(page, tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, "Log '2026-10-16 13:42:19 friends file written: 2 friend file(s), visible in "
                                    "game after /reload'\n")
    setup = install(tmp_path / "sync")
    fill_cloud(setup)
    page.refresh()
    label = page.sync_label.text()
    assert page.sync_button.text() == "Jetzt abgleichen" and page.sync_button.isEnabled() and setup.cloud in label
    assert "Von dir in der Cloud: Blind (" in label and ", Level (" in label
    assert 'Von Freunden in der Cloud: ? (' in label and 'Jonas "J" Fr\u00e4nd (' in label
    assert "Im Spiel sind noch keine Freunde-Daten." in label
    page.run_sync()
    assert not page.sync_button.isEnabled(), "one run at a time"
    wait_for(page)
    assert "friends file written: 2 friend file(s)" in page.sync_message.text()
    assert "/reload" in page.sync_message.text() and page.sync_button.isEnabled()
    assert 'In der App eingelesen: Jonas "J" Fränd' in page.sync_message.text(), "friends into the app too"
    assert "friends file written" in page.sync_label.text(), "the last log line"


@needs_powershell
def test_sync_now_reports_a_failed_step(page, tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, "Log '2026-10-16 13:42:19 Send-Own failed: access denied'\n")
    install(tmp_path / "sync")
    page.refresh()
    page.run_sync()
    wait_for(page)
    assert "fehlgeschlagen" in page.sync_message.text() and "access denied" in page.sync_message.text()


SETUP = r"""if (-not $Setup) { throw 'expected -Setup' }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$cloud = Join-Path (Split-Path $DataDir) 'Journey Forever Cloud'
@{ cloud = $cloud; client = 'C:\WoW'; shareId = ('c' * 32) } | ConvertTo-Json |
  Set-Content -Path (Join-Path $DataDir 'config.json') -Encoding UTF8
Log "setup: cloud $cloud"
"""


@needs_powershell
def test_without_setup_the_button_sets_up_first(page, tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, SETUP)
    page.refresh()
    assert page.sync_button.text() == "Einrichten und abgleichen" and page.sync_button.isEnabled()
    assert "Noch nicht eingerichtet" in page.sync_label.text()
    page.run_sync()
    wait_for(page)
    assert "setup: cloud" in page.sync_message.text(), page.sync_message.text()
    assert page.sync_button.text() == "Jetzt abgleichen" and cloud_sync.find_setup().share_id == "c" * 32
