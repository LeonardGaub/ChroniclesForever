"""Application settings and file locations (%APPDATA%\\ForeverChronicle)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def app_home() -> Path:
    """Data folder. FOREVER_CHRONICLE_HOME overrides it (used by tests)."""
    override = os.environ.get("FOREVER_CHRONICLE_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ForeverChronicle"


@dataclass
class AppConfig:
    language: str = "de"
    client_dir: str | None = None
    auto_import: bool = True
    last_character: str | None = None
    # Sound (ui/sound.py): volumes in percent; music_path is an own music file or folder, None the built-in theme.
    click_sounds: bool = True
    event_sounds: bool = True
    music: bool = True
    effects_volume: int = 70
    music_volume: int = 50
    music_path: str | None = None
    ask_audio_install: bool = True     # offer the missing sound part at start (ui/audio_setup.py)
    extra: dict = field(default_factory=dict)

    @property
    def database_path(self) -> Path:
        return app_home() / "chronicle.db"

    @property
    def backup_dir(self) -> Path:
        return app_home() / "backups"

    @classmethod
    def load(cls) -> "AppConfig":
        path = app_home() / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def flag(self, key: str, default: bool = True) -> bool:
        """An on/off option kept in `extra`: missing (or not a bool) means the default."""
        value = self.extra.get(key)
        return value if isinstance(value, bool) else default

    def set(self, key: str, value: Any) -> None:
        """Changes a setting and saves the file. Keys that are not fields of this class live in `extra`."""
        if key in self.__dataclass_fields__:
            setattr(self, key, value)
        else:
            self.extra[key] = value
        self.save()

    def save(self) -> None:
        home = app_home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.json").write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
