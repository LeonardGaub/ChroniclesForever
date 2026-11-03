# Journey Forever

A personal adventure history for **World of Warcraft: Forever** (Blizzard's Classic+), private use.

- **Addon** (`addons/ForeverChronicle`, TOC Interface 16001, 16002, 16003 and 16100): records sessions, level-ups,
  quests, deaths, achievements, discovered zones, routes, professions and recipes, and automatic screenshots. It has its own window (`/fj`) with
  Übersicht, Chronik, Karte (route replay on the game's map), Berufe, Einstellungen and Diagnose tabs.
- **Desktop app** (`desktop/`, Python 3.12 + PySide6): imports the addon's SavedVariables into SQLite and keeps
  the full history. It shows statistics, the chronicle, professions and recipes, and plays the journey back in a full-screen cinematic mode on the game's own world map (the Kino tab: the whole journey or chosen sessions); screenshots appear right in the chronicle with the entry that triggered them.
  It backs up the addon file, the screenshots and its database to a cloud folder you choose (when WoW starts and
  closes, or by hand) and shows the friends who back up into the same folder.

German UI by default, English switchable.

## Install and run

- Addon: copy `addons/ForeverChronicle` into `<WoW>\<client folder>\Interface\AddOns\` (the live client's is
  `_forever_`). The desktop app installs newer versions from the repository at start.
- Desktop: `cd desktop`, `python -m venv .venv`, `.venv\Scripts\pip install -e .[dev]`, then start
  `desktop\Forever Chronicle.bat` (or `.venv\Scripts\python -m forever_chronicle`). Without a dev venv (friends'
  clones), `Journey Forever starten.bat` in the repository root sets up Python, installs the addon and starts the app.

## Tests

```bash
cd tests/addon && npm install && npm test      # addon in a mocked WoW client; writes tests/fixtures
cd desktop && .venv/Scripts/python -m pytest   # parser, importer, map, screenshots, UI
```

## Documentation

- `ARCHITECTURE.md`: structure and how to add new stats, pages and event types
- `ForeverChronicle_Feature_Spec_v1.3.docx`: feature specification (regenerate with `docs/spec-tools/build_spec.js`)
- `docs/Phase0_Compatibility_Report.md`: what the Forever client supports
- `docs/Cloud_Backup.md`, `docs/Dungeon_Maps.md`: designs for the cloud backup with friends and for dungeon maps
- `docs/CurseForge.md`: the CurseForge project texts; `CHANGELOG.md`: player-facing changes for the next upload
- `NEXT_STEPS.md`: current state and next steps; `docs/History.md`: the session notes so far
