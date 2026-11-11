"""The self-update from GitHub releases (updater.py, ui/update_dialog.py) and the release side of the packager."""

import hashlib
import importlib.util
import json
import time
import zipfile
from pathlib import Path

import pytest

from forever_chronicle import updater

REPO = Path(__file__).resolve().parents[2]


def fake_release_zip(path: Path, version: str) -> Path:
    """A small friends' zip: launcher, readme, addon (with its version) and app, plus one hostile name."""
    top = "Journey Forever/"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(top + "Journey Forever starten.bat", "@echo off\r\n")
        zf.writestr(top + "LIES MICH.txt", "readme")
        zf.writestr(top + "addons/ForeverChronicle/ForeverChronicle.toc", f"## Title: x\n## Version: {version}\n")
        zf.writestr(top + "addons/ForeverChronicle/Core/New.lua", "-- new")
        zf.writestr(top + "desktop/forever_chronicle/__main__.py", "# new app")
        zf.writestr(top + "desktop/forever_chronicle/../../../evil.txt", "outside")
    return path


def release_for(folder: Path, version: str, checksum: str | None = None) -> updater.Release:
    archive = fake_release_zip(folder / updater.zip_name(version), version)
    digest = checksum or hashlib.sha256(archive.read_bytes()).hexdigest()
    check = folder / (archive.name + ".sha256")
    check.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return updater.Release(version, "notes", archive.name, archive.as_uri(), archive.stat().st_size, check.as_uri())


def installed_app(base: Path, version: str) -> Path:
    root = base / "ForeverChronicle" / "app"
    (root / "addons" / "ForeverChronicle").mkdir(parents=True)
    (root / "addons" / "ForeverChronicle" / "ForeverChronicle.toc").write_text(f"## Version: {version}\n")
    (root / "addons" / "ForeverChronicle" / "Old.lua").write_text("-- stale")
    (root / "desktop" / "forever_chronicle").mkdir(parents=True)
    (root / "desktop" / "forever_chronicle" / "__main__.py").write_text("# old app")
    return root


def api_json(version: str, **extra) -> dict:
    name = updater.zip_name(version)
    return {"tag_name": f"v{version}", "body": "## Changes\n- more", **extra, "assets": [
        {"name": name, "size": 123, "browser_download_url": f"https://x/{name}"},
        {"name": name + ".sha256", "size": 80, "browser_download_url": f"https://x/{name}.sha256"},
        {"name": "other.txt", "browser_download_url": "https://x/other"}]}


def test_parse_release_needs_tag_zip_and_checksum():
    release = updater.parse_release(api_json("0.17.0"))
    assert release.version == "0.17.0" and release.zip_size == 123
    assert release.zip_url.endswith("JourneyForever-0.17.0-Komplett.zip") and release.sha256_url.endswith(".sha256")
    assert updater.parse_release(api_json("0.17.0", draft=True)) is None
    assert updater.parse_release(api_json("0.17.0", prerelease=True)) is None
    assert updater.parse_release({**api_json("0.17.0"), "tag_name": "latest"}) is None
    no_checksum = api_json("0.17.0")
    no_checksum["assets"] = no_checksum["assets"][:1]
    assert updater.parse_release(no_checksum) is None


def test_fetch_latest_reads_the_api_and_is_quiet_without_it(tmp_path):
    answer = tmp_path / "latest.json"
    answer.write_text(json.dumps(api_json("0.18.1")), encoding="utf-8")
    assert updater.fetch_latest(answer.as_uri()).version == "0.18.1"
    assert updater.fetch_latest((tmp_path / "missing.json").as_uri()) is None
    answer.write_text("not json", encoding="utf-8")
    assert updater.fetch_latest(answer.as_uri()) is None


def test_is_newer():
    assert updater.is_newer("0.17.0", "0.16.0") and updater.is_newer("0.16.0.1", "0.16.0")
    assert updater.is_newer("0.10.0", "0.9.9")
    assert not updater.is_newer("0.16.0", "0.16.0") and not updater.is_newer("0.15.9", "0.16.0")
    assert not updater.is_newer("dev", "0.16.0") and updater.is_newer("0.1.0", None)


def test_only_the_launchers_install_updates_itself(tmp_path, monkeypatch):
    root = installed_app(tmp_path, "0.16.0")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(updater, "app_root", lambda: root)
    assert updater.installed_root() == root
    (root / ".git").mkdir()
    assert updater.installed_root() is None, "a git checkout never replaces itself"
    monkeypatch.setattr(updater, "app_root", lambda: REPO)
    assert updater.installed_root() is None
    monkeypatch.delenv("LOCALAPPDATA")
    assert updater.installed_root() is None


def test_download_stage_and_apply(tmp_path):
    root = installed_app(tmp_path, "0.16.0")
    served = tmp_path / "served"
    served.mkdir()
    release = release_for(served, "0.17.0")
    seen = []
    archive = updater.download(release, updater.update_dir(root), lambda done, total: seen.append((done, total)))
    assert archive.read_bytes() == (served / release.zip_name).read_bytes()
    assert seen and seen[-1][0] == archive.stat().st_size
    staging = updater.stage(archive, "0.17.0", root)
    assert staging == tmp_path / "ForeverChronicle" / "app.new"
    assert (staging / "addons" / "ForeverChronicle" / "Core" / "New.lua").is_file()
    assert not (staging / "Journey Forever starten.bat").exists() and not (staging / "LIES MICH.txt").exists()
    assert not any(p.name == "evil.txt" for p in tmp_path.rglob("*")), "names leaving the app folder are skipped"
    assert updater.current_version(root) == "0.16.0", "the running app stays untouched until it closes"

    launched = []
    assert updater.apply(0, root, launch=launched.append)
    assert launched == [root]
    assert updater.current_version(root) == "0.17.0"
    assert (root / "desktop" / "forever_chronicle" / "__main__.py").read_text() == "# new app"
    assert not (root / "addons" / "ForeverChronicle" / "Old.lua").exists(), "stale files go with the old folder"
    assert not updater.old_dir(root).exists() and not staging.exists()
    assert updater.take_result(root) == {"ok": True, "version": "0.17.0", "error": ""}
    assert updater.take_result(root) is None, "shown once"
    updater.clean_up(root)
    assert not list(updater.update_dir(root).glob("*.zip*"))


def test_download_rejects_a_wrong_checksum(tmp_path):
    served = tmp_path / "served"
    served.mkdir()
    release = release_for(served, "0.17.0", checksum="0" * 64)
    with pytest.raises(updater.UpdateError):
        updater.download(release, tmp_path / "update")
    assert not list((tmp_path / "update").iterdir()), "no half or broken file stays"
    with pytest.raises(updater.UpdateError):
        updater.download(release_for(served, "0.17.0"), tmp_path / "update", cancelled=lambda: True)


def test_stage_rejects_another_version(tmp_path):
    root = installed_app(tmp_path, "0.16.0")
    archive = fake_release_zip(tmp_path / "x.zip", "0.16.5")
    with pytest.raises(updater.UpdateError):
        updater.stage(archive, "0.17.0", root)
    assert not updater.staging_dir(root).exists()


def test_failed_swap_keeps_the_old_version(tmp_path):
    root = installed_app(tmp_path, "0.16.0")
    launched = []
    assert not updater.apply(0, root, launch=launched.append)      # nothing staged: the second rename fails
    assert updater.current_version(root) == "0.16.0" and launched == [root]
    result = updater.take_result(root)
    assert result["ok"] is False and result["error"]


def test_dialog_downloads_and_unpacks(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from forever_chronicle.ui import update_dialog

    root = installed_app(tmp_path, "0.16.0")
    served = tmp_path / "served"
    served.mkdir()
    window = QWidget()
    dialog = update_dialog.UpdateDialog(window, root, release_for(served, "0.17.0"), "0.16.0")
    assert "0.17.0" in dialog.text.text() and "0.16.0" in dialog.text.text()
    monkeypatch.setattr(update_dialog, "APPLY", False)
    dialog.start()
    end = time.monotonic() + 15
    while dialog.running and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert update_dialog.APPLY, dialog.text.text()
    assert updater.current_version(updater.staging_dir(root)) == "0.17.0"
    dialog.close()
    window.close()


def test_packager_writes_checksum_and_finds_release_notes(tmp_path):
    spec = importlib.util.spec_from_file_location("package_for_friends", REPO / "tools" / "package_for_friends.py")
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    path = package.build(tmp_path / f"JourneyForever-{package.version()}-Komplett.zip")
    digest, name = package.checksum_file(path).read_text(encoding="ascii").split()
    assert name == path.name and digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert updater.zip_name(package.version()) == path.name, "the name the app looks for"
    changelog = "# Log\n\n## Unreleased\n\n- next\n\n## 0.16.0 – 2026-11-04\n\nIntro\n\n- a\n- b\n\n## 0.16.1\n\n- no\n"
    assert package.release_notes("0.16.0", changelog) == "Intro\n\n- a\n- b"
    assert package.release_notes("0.16", changelog) == ""
    assert package.release_notes("0.17.0", changelog) == ""
