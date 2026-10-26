# Journey Forever – Architecture

```
addons/ForeverChronicle/        in-game addon (Lua, TOC Interface 16001, 16002, 16003, 16100), the CurseForge upload
addons/ForeverChronicle_Share/  private friends companion (sharing through a cloud folder)
desktop/                        desktop app (Python 3.12 + PySide6 + SQLite)
sync/                           cloud sync script for the friend group (PowerShell)
tools/                          CurseForge packaging; extract/build from the game files (maps, world map, icons, UI
                                skin, zone music; shared setup in db2.py); beta-to-live settings port; sound generation
tests/addon/                    addon tests in a mocked WoW client (Node + fengari)
tests/fixtures/                 SavedVariables written by the addon tests, used by desktop tests
docs/                           designs, spec tools, Phase 0 report, CurseForge texts
probe-results/                  raw Phase 0 data written by the real client (also used by a parser test)
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
`FC:ViewChar()`, `FC:ViewStream(name)`, `FC:IsViewingPlayed()`. Map, instance and
entrance lookups go through `FC:MapInfo`, `FC:InstanceName` and `FC:StoredEntrance`, so friends' data
counts as well. A new page that reads character data must use these helpers. A stat that needs live state can add
`fromRecord(char)` for other characters. `UI/ViewBar.lua` is the chooser; `FC_VIEW_CHANGED` calls
`page:OnViewChanged()` if a page has one.
Other addons add characters with `FC:RegisterViewSource` (entries, map/instance/entrance data). The private
companion addon `ForeverChronicle_Share` (not part of the CurseForge upload) does this for friends: their
characters come from its `Friends/FriendsData.lua` (`ForeverChronicleFriends`), which the sync script
(`sync/ForeverSync.ps1`) writes from the friends' `ForeverChronicle_Share.lua` files. The game writes those files
from the companion's `Share.lua` (SavedVariables `ForeverChronicleShareDB`), in the addon's own record shape. Each
friend is loaded on its own in an empty environment after a strict plain-data check.

### Backups and transfer (F-011)
`storage/jsonl.py`: the JSON Lines export/import. To include a new table, add a `RecordType` with its natural key
and merge rule. Columns come from the table itself, so new columns are exported automatically. Records of a
character carry the character's natural key, not the local UUID. `Database.backup` keeps the newest 5 copies
(before migrations, before JSONL imports, daily at start, on demand).

## Addon

| Layer | Files | Role |
|---|---|---|
| Core | `Core/*.lua` | namespace, module registry, event dispatch, storage, diagnostics, registries, view (which character is shown), route rules, `/fj` |
| Modules | `Modules/*.lua` | one file per feature: Character, Session, Travel, Positions, Progress, Rares, Pastimes (jumps, fish), Dungeons, Professions, Gear, Metrics, Screenshots (+ the pure ScreenshotQueue) |
| UI | `UI/*.lua` | Blizzard templates (ButtonFrameTemplate) with icon tabs on the right edge; shared widgets in `UI/Widgets.lua`; one file per page in `UI/Pages/` |
| Locales | `Locales/*.lua` | `deDE` (default) and `enUS` (fallback) |

Rules:
- All game API calls go through `FC.Util.SafeValue` / `SafeValues` / `Plain`. These guard against
  secret values (Midnight rules) and errors. Shared readers: `FC:PlayerMapPosition(mapID)`,
  `FC:CurrentInstanceID()`, `FC:GetLocation()` (Core/Recorder.lua), `Util.ClientBuild()`, `Util.MapType`.
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
`CHAT_MSG_SKILL` and via `/fj professions`. Recipes are only readable while a profession window is open. They are
captured from the unfiltered `C_TradeSkillUI.GetAllRecipeIDs` list (at most once per 5 s). Linked, guild and NPC
professions and skill lines the character does not have are skipped. Recipes use the compact format
`recipeID,categoryID,icon,quality,name` (recipe list format 2), and categories use
`id,parentID,name`. Status `complete` means every recipe info
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
`wow/map_art.py` finds map images in one place: `forever_chronicle/maps/<uiMapID>.jpg`, kept in git. They come from the game client itself: `tools/extract_maps.py` reads the local install (`desktop/forever_chronicle/wow/casc.py`, `tools/db2.py`) and draws each map
fully explored, as the game does. Rerun it after a client patch; Forever reworked several zones (Mulgore,
Stormwind, Eastern Plaguelands, ...), so the Classic images do not fit everywhere.
`ui/pages/map_page.py` is the map tab. All art uses the 1002×668 world-map canvas that game coordinates are
normalized to, which was verified against real Phase 0 coordinates.

### Adding an in-game page
Create `UI/Pages/MyPage.lua` with `FC.UI:RegisterPage({ id, labelKey, icon, order, Create = fn, Refresh = fn })` and
add it to the TOC. Build labels with `FC.UI:Label` / `Header` / `Button`, so they follow language changes, and reuse
the widgets in `UI/Widgets.lua` (icon buttons, toggles, lists, tooltips, `UI:SelectionBorder`, `UI:SearchBox`, `UI:Pool` for
reused regions; `Util.Fold` lowercases umlauts for searching). Read character data
through the view helpers (see above). `UI:ShowPage(id)` opens the window on a page.

### Changing the saved data format
Increase `FC.SCHEMA_VERSION` (Core.lua) and add a migration to `MIGRATIONS` in `Core/Storage.lua`. Then raise
`SUPPORTED_SCHEMA` in `desktop/forever_chronicle/importing/sv_importer.py`.

## Desktop

| Package | Role |
|---|---|
| `wow/` | locate client and SavedVariables (`paths.py`), safe Lua literal parser (`lua_parser.py`), game files (`casc.py`), the event, profession and recipe icons (`game_icons.py`), fonts (`game_fonts.py`: Friz Quadrata, Morpheus) and sound effects (`game_sounds.py`) from them (never in git), the cinematic's adventure music from the zones' music (`zone_music.py`, table `zone_music.json` from `tools/extract_zone_music.py`) |
| `importing/` | SavedVariables → SQLite, validation, gaps, `.bak` fallback |
| `storage/` | `database.py` (schema migrations + backups), `repository.py` (all SQL), `jsonl.py` (export/import) |
| `domain/` | pure logic, no Qt: registries `event_types.py` (how events are shown) and `stats.py` (overview statistics); `route.py`, `route_colors.py`, `maps.py` (the map); `cinematic.py` (what a replay announces, deaths, standstills and teleports), `daylight.py` (the light by time of day), `credits.py` (the end credits' numbers), `experience.py` (the XP bar's fill) |
| `ui/` | `theme.py` (Classic look, the game's fonts first; the skin from the game's UI textures in `assets/skin/`, built by `tools/build_ui_skin.py`), `motion.py` (page crossfade, hover glow, toasts), `setup_wizard.py` (first start), `widgets.py` (page base class), `cards.py` (home cards and the card list of Chronik and Berufe), `main_window.py` (page stack, tabs at the bottom, gear menu), `pages/` (one file per page; `home.py` is the start page, `gallery.py` the screenshots), `screenshots.py` (thumbnails, Shot, the viewer with banner, favourite and replay), `cinematic.py` + `cinematic_fx.py` (cinematic mode), `cinematic_credits.py` (end credits), `cinematic_hud.py` (the game's XP bar), `cinematic_export.py` (the replay as an MP4 video), `sound.py` (clicks, alerts, music) |
| `i18n.py` | German (default) / English strings |

### Sound

`ui/sound.py` holds `ctx.sound`: `play(name)` for effects (WAV via QSoundEffect), an app-wide click filter, and
`ctx.sound.music` (QMediaPlayer with fades and `duck(seconds)`). Cinematic mode starts and stops the music and plays
`level_up`, `screenshot`, `event`, `death`, `achievement`, `discovery`, `revive` and `teleport` (`sound.ALL_EFFECTS`;
the last four fall back to the built-in `event`). The Settings tab holds the switches, volumes and the music choice
(the game's adventure music, else the built-in theme, own file, or own folder as a shuffled playlist). The adventure
music is the outdoor themes of `zone_music.ADVENTURE` one after another; the cinematic mode switches playlists
(`music.play(tracks)`: fade out, fade in) at the level-up that begins a new chapter (`zone_music.CHAPTER_LEVELS`:
every 7 levels at first, every 3 at the end). The video
export drives a silent `MusicPlayer(audible=False)` frame by frame and mixes the logged music and effects itself.

- Built-in sounds in `ui/assets/sounds` are synthesized by `tools/generate_sounds.py` (original, no third-party
  audio; needs `pip install -e .[tools]`). Change the script and rerun it rather than editing the files.
- Players can replace an effect with a WAV of the same name in `%APPDATA%\ForeverChronicle\sounds`.
- The game's own sounds (`wow/game_sounds.py`, fileDataIDs from the community listfile) are taken from the install in a
  background thread at start and turned into WAV with `QAudioDecoder` (`sound.install_game_sounds`) into
  `%APPDATA%\ForeverChronicle\game_sounds`. Order: own file, game sound (option `game_sounds`), built-in.
- QtMultimedia ships in PySide6-Addons. Without it (`PySide6-Essentials` only) `sound.AUDIO` is False and the app
  runs silently. `Journey Forever starten.bat` installs PySide6-Addons of the installed PySide6 version once
  (marker `.ready_sound`, optional like the icon packages); if that failed, the app offers the same download at
  start and in Settings (`ui/audio_setup.py`) and restarts itself afterwards. Tests set `FOREVER_CHRONICLE_SILENT=1`; `ctx.sound.played` still records what would have played.

### Event icons

The desktop shows events with the addon's icons: in the Chronik and Übersicht lists, as round pins on the map
(the addon's pin looks: milestone, danger, normal; they grow on hover and show a small card with the icon, event,
place and time) and in the replay's pins and achievement banner.
`event_types.icon_of(event)` picks the icon as the addon does: the fileDataID recorded with the event
(achievements, professions, recipes), else the type's `icon`. `wow/game_icons.py` finds its PNG in two folders:
- `forever_chronicle/icons/`: the event types' icons, kept in git. `tools/extract_icons.py` writes them from the
  local game.
- `%APPDATA%\ForeverChronicle\icons\`: the per-event icons. After each import `AppContext.extract_icons` takes the
  missing ones out of the local game (`wow/casc.py`, about 2 s, only when one is missing).

`ui/icons.py` turns them into pixmaps. Without numpy and Pillow, or without the game, the per-event icons fall back
to the type's icon and unknown types to their symbol (`EventType.glyph`).

- **New statistic:** call `stats.register(Stat(key, label_key, order, compute, kind, group))` and add the label to
  `i18n.py`.
- **New event type:** call `event_types.register(EventType(...))` with the addon's icon of the type, then run
  `tools/extract_icons.py` so the icon is in `forever_chronicle/icons/` (`tests/test_icons.py` checks it).
- **New page** (for example the map): subclass `ui.widgets.Page`, then add it to `ui/pages/__init__.py`: `MAIN_PAGES`
  (a tab at the bottom) or `MENU_PAGES` (the gear menu). Other pages open it with `ctx.navigate.emit(title_key)`.
- **Database change:** append SQL to `MIGRATIONS` in `storage/database.py`. Never edit a released migration.
  A backup is made before every migration.

## Tests

```bash
cd tests/addon && npm install && npm test      # addon in a mocked client; also writes tests/fixtures
cd desktop && .venv/Scripts/python -m pytest   # parser, importer, UI smoke test
```

Run the addon tests first; the desktop tests read the fixture they produce.
