# Journey Forever

A personal adventure history for **World of Warcraft: Forever** (Blizzard's Classic+), private use.

- **Addon** (`addons/ForeverChronicle`, Interface 16001): records sessions, level-ups, quests, deaths,
  achievements, discovered zones, routes, professions and recipes, and automatic screenshots. It has its own window (`/fj`) with
  Übersicht, Chronik, Karte (route replay on the game's map), Berufe, Screenshots, Einstellungen and Diagnose tabs.
- **Desktop app** (`desktop/`, Python 3.12 + PySide6): imports the addon's SavedVariables into SQLite and keeps
  the full history. It shows statistics, the chronicle, the route map on your own map art, professions and recipes; screenshots appear right in the chronicle with the entry that triggered them.

German UI by default, English switchable.

## Install and run

- Addon: copy `addons/ForeverChronicle` into `<WoW>\_classic_beta_\Interface\AddOns\`.
- Desktop: `cd desktop`, `python -m venv .venv`, `.venv\Scripts\pip install -e .[dev]`, then start
  `desktop\Journey Forever.bat` (or `.venv\Scripts\python -m forever_chronicle`).

## Tests

```bash
cd tests/addon && npm install && npm test      # addon in a mocked WoW client; writes tests/fixtures
cd desktop && .venv/Scripts/python -m pytest   # parser, importer, map, screenshots, UI
```

## Documentation

- `ARCHITECTURE.md`: structure and how to add new stats, pages and event types
- `ForeverChronicle_Feature_Spec_v1.3.docx`: feature specification
- `docs/Phase0_Compatibility_Report.md`: what the Forever client supports
- `NEXT_STEPS.md`: current state and next steps
