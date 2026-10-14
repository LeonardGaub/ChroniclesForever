# Forever Chronicle – Architecture

```
addons/ForeverChronicle/      in-game addon (Lua, Interface 16001)
desktop/                      desktop app (Python 3.12 + PySide6 + SQLite)
tests/addon/                  addon tests in a mocked WoW client (Node + fengari)
tests/fixtures/               SavedVariables written by the addon tests, used by desktop tests
docs/                         spec tools, Phase 0 report
probe-results/                raw Phase 0 data written by the real client (also used by a parser test)
```

## Data flow

```
game events ──► addon module ──► FC:Record() ──► "events" stream ─┐
                                 Storage:Append() ──► other streams ┤  ForeverChronicleDB (SavedVariables)
                                                                   │  written by the client on logout / reload
desktop: wow/paths ──► wow/lua_parser (literals only) ──► importing/sv_importer ──► SQLite ──► UI pages
```

- Every stream record has a per-stream `seq`. The importer compares it with the last imported `seq` to detect
  records dropped by the addon's retention cap (`data_gaps`).
- Events are immutable and de-duplicated by `(character, event id)`. Sessions are updated in place.
- Snapshots (`char.snapshots[name]`, via `Storage:GetSnapshot`) hold what the character has *now*
  (professions and recipes). They are replaced over time, and the desktop app mirrors the latest version.
- The character key is the player GUID (globally unique in Forever). The desktop app assigns its own UUID.

### Characters shown in the window (sharing, docs/Sharing_Design.md)
Recording always writes to the played character (`FC.char`). Pages read through `Core/View.lua`:
`FC:ViewChar()`, `FC:ViewStream(name)`, `FC:ViewSnapshot(name)`, `FC:IsViewingPlayed()`. Map, instance and
entrance lookups go through `FC:MapInfo`, `FC:InstanceName` and `FC:StoredEntrance`, so friends' data
counts as well. A new page that reads character data must use these helpers. A stat that needs live state can add
`fromRecord(char)` for other characters. `UI/ViewBar.lua` is the chooser; `FC_VIEW_CHANGED` calls
`page:OnViewChanged()` if a page has one.
Friends' characters come from `Friends/FriendsData.lua` (`ForeverChronicleFriends`), which the sync script
(`sync/ForeverSync.ps1`) writes from the friends' `ForeverChronicle_Share.lua` files. The game writes those files
from `Modules/Share.lua` into the data-only addon `ForeverChronicle_Share`, in the addon's own record shape. Each
friend is loaded on its own in an empty environment after a strict plain-data check.

### Backups and transfer (F-011)
`storage/jsonl.py`: the JSON Lines export/import. To include a new table, add a `RecordType` with its natural key
and merge rule. Columns come from the table itself, so new columns are exported automatically. Records of a
character carry the character's natural key, not the local UUID. `Database.backup` keeps the newest 5 copies
(before migrations, before JSONL imports, daily at start, on demand).

## Addon

| Layer | Files | Role |
|---|---|---|
| Core | `Core/*.lua` | namespace, module registry, event dispatch, storage, diagnostics, registries, `/fc` |
| Modules | `Modules/*.lua` | one file per feature: Character, Session, Progress |
| UI | `UI/*.lua` | Blizzard templates (ButtonFrameTemplate, PanelTabButtonTemplate); one file per page |
| Locales | `Locales/*.lua` | `deDE` (default) and `enUS` (fallback) |

Rules:
- All game API calls go through `FC.Util.SafeValue` / `SafeValues` / `Plain`. These guard against
  secret values (Midnight rules) and errors.
- Handlers run in `FC:SafeCall`. An error is logged and does not break other modules.
- Modules never talk to each other directly. They use `FC:SendMessage` / `module:RegisterMessage`.

### Adding a tracker (a new stat source)

Create `Modules/MyFeature.lua` and add it to the TOC under "Feature modules":

```lua
local ADDON, FC = ...
local L, Util = FC.L, FC.Util
local M = FC:NewModule("MyFeature", { order = 40, defaults = { enabled = true } })

FC:RegisterCapability("my_feature", "CAP_MY_FEATURE", function() return FC.eventStatus.SOME_EVENT == "registered" end)
FC:RegisterEventType("my_event", { icon = "Interface\\Icons\\INV_Misc_Note_01",
  format = function(r) return string.format(L.EVT_MY_EVENT, r.data.value) end })
FC:RegisterStat("my_count", { labelKey = "STAT_MY_COUNT", order = 30 })
FC:RegisterOption({ module = "MyFeature", key = "enabled", type = "toggle", labelKey = "OPT_MY_FEATURE" })

M:RegisterEvent("SOME_EVENT", function(self, _, value)
  if not self:GetSettings().enabled then return end
  FC:Record("my_event", { value = Util.Plain(value) })
  FC:IncrementStat("my_count")
  FC:ConfirmCapability("my_feature")
end)
```

Add the locale keys to `Locales/enUS.lua` and `Locales/deDE.lua`. The overview, chronicle, settings and
diagnostics pages pick everything up automatically. A high-volume data type, such as position samples, gets its
own stream with `FC.Storage:DefineStream(name, cap)`.

### Screenshots
`Modules/Screenshots.lua` listens to `FC_EVENT_RECORDED`, not to game events. Any recorded event type can
request a screenshot through a trigger:

```lua
FC:GetModule("Screenshots"):RegisterTrigger("boss", { eventType = "boss_killed", priority = 3, maxAge = 30,
  identity = function(r) return "boss:" .. r.data.encounterID end })
```

The scheduling rules (priority, merging within 2 s, the shared delay (default 5 s), cooldown and bypass,
minimum gap, maximum age, zone left, taxi and loading screens, capacity) live in the pure
`Modules/ScreenshotQueue.lua` and are covered by `tests/addon/queue_tests.lua`. The desktop app links
records to files by their `fileStamp` (`importing/screenshot_matcher.py`, ±2 s, never guesses on a tie).

### Professions and recipes
`Modules/Professions.lua` keeps `snapshots.professions`: skill, maximum and kind (primary or secondary) per
skill line, read with the Mainline `GetProfessions`/`GetProfessionInfo` at login, on `SKILL_LINES_CHANGED` /
`CHAT_MSG_SKILL` and via `/fc professions`. Recipes are only readable while a profession window is open. They are
captured from the unfiltered `C_TradeSkillUI.GetAllRecipeIDs` list (at most once per 5 s). Linked, guild and NPC
professions and skill lines the character does not have are skipped. Recipes use the compact format
`recipeID,categoryID,icon,name`, and categories use `id,parentID,name`. Status `complete` means every recipe info
was readable. A `partial` capture never removes recipes, and the desktop app follows the same rule (`replace_recipes`).
Events: `profession_learned` and `profession_rank` come from the snapshot diff after a baseline, so professions
known at install are not reported; `recipe_learned` comes from `NEW_RECIPE_LEARNED`.

### Positions and maps
`Modules/Positions.lua` writes the compact `positions` stream: one string per point,
`time,mapID,x,y,until,flags,instanceID`. Its seq is implicit (`nextSeq - #records + index`), and the stream
uses `Storage:AppendRaw` / `ReplaceLast`. Standing still extends the last point (`until`). In dungeons the
client gives no position, so only the instance ID is stored. Map geometry (each map's rectangle on its
continent) is recorded once per map in `FC.db.maps`, and instance names in `FC.db.instances`.

Instances have no position. Dungeon moments are shown at the dungeon entrance (`FC.db.entrances`: from the
encounter journal, or the last outdoor sample at most 60 s before walking in; otherwise derived from the route by
the same rule: `Route.Entrance` / `Route.entrance`). Points the client reported only with a continent ID are
shown on the smallest known zone that contains them (`Route.ZoneFor` / `Route.view_for`).

Desktop: `domain/route.py` handles projection, segments and time lookup (pure, tested).
`domain/maps.py` holds the Classic uiMapID table: art name and German/English names.
`wow/map_art.py` imports the user's artwork into `%APPDATA%\ForeverChronicle\maps\<uiMapID>.jpg`.
`ui/pages/map_page.py` is the map tab. All art uses the 1002×668 world-map canvas that game coordinates are
normalized to, which was verified against real Phase 0 coordinates.

### Adding an in-game page
Create `UI/Pages/MyPage.lua` with `FC.UI:RegisterPage({ id, labelKey, order, Create = fn, Refresh = fn })` and add
it to the TOC. Build labels with `FC.UI:Label` / `Header` / `Button`, so they follow language changes.

### Changing the saved data format
Increase `FC.SCHEMA_VERSION` (Core.lua) and add a migration to `MIGRATIONS` in `Core/Storage.lua`. Then raise
`SUPPORTED_SCHEMA` in `desktop/forever_chronicle/importing/sv_importer.py`.

## Desktop

| Package | Role |
|---|---|
| `wow/` | locate client and SavedVariables (`paths.py`), safe Lua literal parser (`lua_parser.py`) |
| `importing/` | SavedVariables → SQLite, validation, gaps, `.bak` fallback |
| `storage/` | `database.py` (schema migrations + backups), `repository.py` (all SQL) |
| `domain/` | registries: `event_types.py` (how events are shown), `stats.py` (overview statistics) |
| `ui/` | `theme.py` (Classic look), `main_window.py`, `pages/` (one file per tab) |
| `i18n.py` | German (default) / English strings |

- **New statistic:** call `stats.register(Stat(key, label_key, order, compute, kind, group))` and add the label to
  `i18n.py`.
- **New event type:** call `event_types.register(EventType(...))`.
- **New page** (for example the map): subclass `ui.widgets.Page`, then add it to `ui/pages/__init__.py: PAGES`.
- **Database change:** append SQL to `MIGRATIONS` in `storage/database.py`. Never edit a released migration.
  A backup is made before every migration.

## Tests

```bash
cd tests/addon && npm install && npm test      # addon in a mocked client; also writes tests/fixtures
cd desktop && .venv/Scripts/python -m pytest   # parser, importer, UI smoke test
```

Run the addon tests first; the desktop tests read the fixture they produce.
