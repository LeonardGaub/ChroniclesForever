"""The settings port from the beta to the live client (tools/port_settings.py), against fake client folders."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ACC = "131324136#1"


@pytest.fixture
def port():
    spec = importlib.util.spec_from_file_location("port_settings", REPO / "tools" / "port_settings.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["port_settings"] = module      # dataclasses look the module up while the class is made
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("port_settings", None)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def wow(tmp_path):
    """A World of Warcraft folder with the beta (as on the user's PC) and a freshly installed live client."""
    root = tmp_path / "World of Warcraft"
    write(root / ".build.info", "Branch!STRING:0|Version!STRING:0|Product!STRING:0\n"
                                "us|1.60.1.70532|wow_classic_beta\neu|1.60.2.71000|wow_forever\n")
    beta, live = root / "_classic_beta_", root / "_forever_"
    write(beta / ".flavor.info", "Product Flavor!STRING:0\nwow_classic_beta\n")
    write(live / ".flavor.info", "Product Flavor!STRING:0\nwow_forever\n")
    wtf = beta / "WTF"
    write(wtf / "Config.wtf", 'SET uiScale "0.8"\nSET portal "test"\nSET agentUID "wow_classic_beta"\n'
                              'SET lastCharacterIndex "6"\nSET CACHE-WQST-QuestV2RecordCount "7777"\n'
                              'SET Sound_MasterVolume "0.35"\nSET textLocale "enUS"\n')
    acc = wtf / "Account" / ACC
    for name in ("bindings-cache.wtf", "macros-cache.txt", "config-cache.wtf", "edit-mode-cache-account.txt"):
        write(acc / name, f"beta {name}")
    write(acc / "cache.md5", "hashes")
    write(acc / "bindings-cache.old", "old")
    for name in ("Questie", "Bagnon", "Blizzard_CombatLog", "Blizzard_PTRFeedback", "ForeverChronicle",
                 "ForeverChronicle_Share", "Baganator", "JF_LoadTest1M"):
        write(acc / "SavedVariables" / f"{name}.lua", f"{name} = {{}}")
        write(acc / "SavedVariables" / f"{name}.lua.bak", "backup")
    for name in ("Questie", "Bagnon", "ForeverChronicle", "ForeverChronicle_Share", "OpenMap"):
        write(beta / "Interface" / "AddOns" / name / f"{name}.toc", "## Interface: 16001\n")
    char = acc / "70" / "Blind-Bullseye"
    for name in ("bindings-cache.wtf", "layout-local.txt", "AddOns.txt", "chat-cache.txt"):
        write(char / name, f"Blind {name}")
    write(char / "SavedVariables" / "Questie.lua", "QuestieChar = {}")
    write(char / "SavedVariables" / "ForeverChronicle.lua", "chronicle")
    write(acc / "Classic Beta PvP" / "Gagel" / "AddOns.txt", "Gagel")
    # Live: started once, logged in with a new character; OpenMap already installed from CurseForge.
    write(live / "WTF" / "Config.wtf", 'SET portal "eu"\nSET agentUID "wow_forever"\nSET uiScale "1"\n'
                                       'SET gxWindow "1"\n')
    write(live / "WTF" / "Account" / ACC / "bindings-cache.wtf", "live default bindings")
    write(live / "WTF" / "Account" / ACC / "71" / "Blind-Liveserver" / "layout-local.txt", "live default layout")
    write(live / "Interface" / "AddOns" / "OpenMap" / "OpenMap.toc", "## Interface: 16002\n")
    return {"root": root, "beta": beta, "live": live, "acc": acc, "live_acc": live / "WTF" / "Account" / ACC}


def run(port, wow, *args):
    return port.main([*args, "--from", str(wow["beta"]), "--to", str(wow["live"])])


def test_dry_run_writes_nothing(port, wow, capsys):
    before = sorted(p for p in wow["live"].rglob("*"))
    assert run(port, wow, "account") == 0
    out = capsys.readouterr().out
    assert "addon  Interface\\AddOns\\Questie" in out or "addon  Interface/AddOns/Questie" in out
    assert "Nothing written" in out
    assert sorted(p for p in wow["live"].rglob("*")) == before


def test_account_settings_addons_and_config(port, wow, monkeypatch):
    monkeypatch.setattr(port, "running_exes", lambda clients: [])
    assert run(port, wow, "account", "--apply") == 0
    live, live_acc = wow["live"], wow["live_acc"]
    addons = live / "Interface" / "AddOns"
    # Addons the live client lacks; never the chronicle (sync/CurseForge), never over an installed one.
    assert (addons / "Questie" / "Questie.toc").is_file() and (addons / "Bagnon").is_dir()
    assert not (addons / "ForeverChronicle").exists() and not (addons / "ForeverChronicle_Share").exists()
    assert (addons / "OpenMap" / "OpenMap.toc").read_text() == "## Interface: 16002\n"
    # Account files; not the server hashes or the .old copies.
    assert (live_acc / "bindings-cache.wtf").read_text() == "beta bindings-cache.wtf"
    assert (live_acc / "edit-mode-cache-account.txt").read_text() == "beta edit-mode-cache-account.txt"
    assert not (live_acc / "cache.md5").exists() and not (live_acc / "bindings-cache.old").exists()
    # SavedVariables: Blizzard UI and installed addons; not the chronicle, PTR feedback, removed addons or .bak.
    saved = sorted(p.name for p in (live_acc / "SavedVariables").iterdir())
    assert saved == ["Bagnon.lua", "Blizzard_CombatLog.lua", "Questie.lua"]
    # Config.wtf: the player's settings from the beta, the client's own lines from the live client.
    config = (live / "WTF" / "Config.wtf").read_text()
    assert 'SET uiScale "0.8"' in config and 'SET Sound_MasterVolume "0.35"' in config
    assert 'SET portal "eu"' in config and 'SET agentUID "wow_forever"' in config and 'SET gxWindow "1"' in config
    assert "test" not in config and "lastCharacterIndex" not in config and "CACHE-" not in config
    # The replaced files are backed up.
    [backup] = (live / "PortBackup").iterdir()
    assert (backup / "WTF" / "Account" / ACC / "bindings-cache.wtf").read_text() == "live default bindings"
    assert 'SET uiScale "1"' in (backup / "WTF" / "Config.wtf").read_text()


def test_account_folder_created_before_the_first_login(port, wow, monkeypatch):
    import shutil
    shutil.rmtree(wow["live"] / "WTF" / "Account")
    monkeypatch.setattr(port, "running_exes", lambda clients: [])
    assert run(port, wow, "account", "--apply") == 0
    assert (wow["live_acc"] / "macros-cache.txt").read_text() == "beta macros-cache.txt"


def test_characters_listed_then_mapped(port, wow, monkeypatch, capsys):
    assert run(port, wow, "characters") == 0
    out = capsys.readouterr().out
    assert "70/Blind-Bullseye" in out and "Classic Beta PvP/Gagel" in out and "71/Blind-Liveserver" in out
    monkeypatch.setattr(port, "running_exes", lambda clients: [])
    assert run(port, wow, "characters", "--map", "blind-bullseye=Blind-Liveserver", "--apply") == 0
    char = wow["live_acc"] / "71" / "Blind-Liveserver"
    assert (char / "layout-local.txt").read_text() == "Blind layout-local.txt"
    assert (char / "AddOns.txt").read_text() == "Blind AddOns.txt"
    assert [p.name for p in (char / "SavedVariables").iterdir()] == ["Questie.lua"]
    [backup] = (wow["live"] / "PortBackup").iterdir()
    assert (backup / "WTF" / "Account" / ACC / "71" / "Blind-Liveserver" / "layout-local.txt").is_file()


def test_unknown_character_is_an_error(port, wow, capsys):
    assert run(port, wow, "characters", "--map", "Nobody=Blind-Liveserver") == 1
    assert "Beta character 'Nobody' not found" in capsys.readouterr().out


def test_server_sync_off_and_on(port, wow, monkeypatch):
    monkeypatch.setattr(port, "running_exes", lambda clients: [])
    config = wow["live"] / "WTF" / "Config.wtf"
    assert run(port, wow, "server-sync", "off", "--apply") == 0
    assert 'SET synchronizeBindings "0"' in config.read_text() and 'SET portal "eu"' in config.read_text()
    assert run(port, wow, "server-sync", "on", "--apply") == 0
    text = config.read_text()
    assert 'SET synchronizeBindings "1"' in text and text.count("synchronizeBindings") == 1


def test_refuses_while_wow_runs(port, wow, monkeypatch, capsys):
    monkeypatch.setattr(port, "running_exes", lambda clients: ["WowB.exe"])
    assert run(port, wow, "account", "--apply") == 1
    assert "close it first" in capsys.readouterr().out
    assert not (wow["live"] / "Interface" / "AddOns" / "Questie").exists()


def test_clients_found_without_folders(port, wow, monkeypatch):
    monkeypatch.setattr(port.paths, "candidate_roots", lambda: [wow["root"]])
    monkeypatch.setattr(port.paths.battlenet, "install_roots", lambda: [])
    src, dst = port.find_clients(None, None)
    assert (src.path, dst.path) == (wow["beta"], wow["live"])
