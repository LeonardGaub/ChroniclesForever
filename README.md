# Journey Forever

A personal adventure history for **World of Warcraft: Forever** (Blizzard's Classic+), private use.

- **Addon** (`addons/ForeverChronicle`, Interface 16001): records sessions, level-ups, quests, deaths,
  achievements, discovered zones, routes, professions and recipes, and automatic screenshots. It has its own window (`/fj`) with
  Übersicht, Chronik, Karte (route replay on the game's map), Berufe, Einstellungen and Diagnose tabs.
- **Friends companion** (`addons/ForeverChronicle_Share`, private, not on CurseForge): shares characters with a
  small friend group through a cloud folder (`sync/ForeverSync.ps1`) and shows the friends' characters.
- **Desktop app** (`desktop/`, Python 3.12 + PySide6): imports the addon's SavedVariables into SQLite and keeps
  the full history. It shows statistics, the chronicle, the route map on the game's own map images, professions and recipes; screenshots appear right in the chronicle with the entry that triggered them.

German UI by default, English switchable.

## Install and run

- Addon: copy `addons/ForeverChronicle` (and, for the friend group, `addons/ForeverChronicle_Share`) into
  `<WoW>\_classic_beta_\Interface\AddOns\`.
- Desktop: `cd desktop`, `python -m venv .venv`, `.venv\Scripts\pip install -e .[dev]`, then start
  `desktop\Forever Chronicle.bat` (or `.venv\Scripts\python -m forever_chronicle`). Friends use
  `Journey Forever starten.bat` from the package built by `tools/package_for_friend.py`.

## Tests

```bash
cd tests/addon && npm install && npm test      # addon in a mocked WoW client; writes tests/fixtures
cd desktop && .venv/Scripts/python -m pytest   # parser, importer, map, screenshots, UI
```

## Documentation

- `ARCHITECTURE.md`: structure and how to add new stats, pages and event types
- `ForeverChronicle_Feature_Spec_v1.3.docx`: feature specification (regenerate with `docs/spec-tools/build_spec.js`)
- `docs/Phase0_Compatibility_Report.md`: what the Forever client supports
- `docs/Sharing_Design.md`, `docs/Friends_Map_Design.md`, `docs/Dungeon_Maps.md`: designs for sharing, friends'
  routes and dungeon maps
- `docs/CurseForge.md`: the CurseForge project texts; `CHANGELOG.md`: player-facing changes for the next upload
- `NEXT_STEPS.md`: current state and next steps
