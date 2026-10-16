# Journey Forever – Session Handoff

Start here. "Current state" and "Open items" are kept up to date; "History" keeps the notes as they were written
at the time (older entries may describe things that changed later). Architecture and extension guide:
`ARCHITECTURE.md`. Player-facing addon changes for the next upload: `CHANGELOG.md`.

## Current state (2026-10-16)
- Main addon `addons/ForeverChronicle` 0.15.0, not uploaded yet (last CurseForge build 0.14.1; the changes are
  collected under "Unreleased" in `CHANGELOG.md`). Companion `addons/ForeverChronicle_Share` 0.14.1, distributed
  through the git repository (friends with repo access; the sync script installs it after a `git pull`). Release
  both together: since 0.15.0 the saved data is packed (see History).
- Addon window tabs: Übersicht, Chronik (screenshots shown with their entries), Karte, Berufe, Einstellungen,
  Diagnose. Slash commands `/fj` and `/fjshot`.
- Desktop app: starts on the home screen (Start). Tabs at the bottom: Start, Übersicht, Chronik, Galerie, Karte
  (with the cinematic mode), Berufe; the gear menu next to them opens Import, Einstellungen (sound), Diagnose. Start it with `desktop/Forever Chronicle.bat`; friends use `Journey Forever starten.bat` from the
  package built by `tools/package_for_friend.py`. The user is moving away from the desktop app: fixes and features
  go into the addon, except features that need the screenshot files (cinematic replay).
- Sharing with friends: the companion addon plus the cloud sync `sync/ForeverSync.ps1` (docs/Sharing_Design.md).
  The desktop share feature was removed. The OneDrive folder "Journey Forever Cloud" holds only `players\`; the
  addon and the sync script come from each PC's clone of the repository (setup: `sync\Einrichten.bat` there).
- Tests: `tests/addon` (`npm test`: queue tests and phases 1-14, writes the fixtures) first, then `desktop`
  (`pytest`, 119 tests). All pass.

## Open items
1. Dungeon maps: after the user's next dungeon, read `FC.db.dungeonProbe` from the saved file and decide the
   dungeon map per `docs/Dungeon_Maps.md` (real path if a position exists, boss-run view otherwise). Check there
   that the journal's encounter IDs match ENCOUNTER_END (probe field `encounters`).
2. Friends' routes on the map: designed in `docs/Friends_Map_Design.md`, not built.
3. Spec v1.4: the updates listed below are not written yet.
4. The friends' package is not yet tested end to end on a clean PC (Python install and pip download).
5. Gear: test whether `SetCustomRace` / `TryOn` work in Forever, for a dressed model of other characters.
6. Short in-game checks for the user: open each profession window once and look at the Berufe tab.
## Confirmed client facts
- Install: `C:\Program Files (x86)\World of Warcraft\_classic_beta_\` (`WowB.exe`, client 1.60.1). TOC Interface 16001.
- SavedVariables: `WTF\Account\131324136#1\SavedVariables\` plus `.lua.bak`.

## Decisions made
- WoW Forever = Blizzard Classic+ on the Mainline API with Midnight addon rules.
- Published on CurseForge as "Journey Forever" (main addon only); the companion stays private. Internal names
  keep "ForeverChronicle" (folders, SavedVariables, paths) so existing data survives. Map images for the desktop
  app come from the game client (tools/extract_maps.py) and live only in `desktop/forever_chronicle/maps/`.
- UI: German default and switchable. Classic look: Blizzard templates in game, Classic theme on desktop.
- Modular architecture: new stats arrive as new addon modules and desktop registry entries (see ARCHITECTURE.md).
- Screenshots: shared delay after the event (user request, default 5 s), on-screen countdown (not chat: chat would be in
  the screenshot), cooldown bypass for level/achievement, and the test screenshot follows the delay.
- After every addon change: copy to the game folder and hash-verify. Mirror the main addon completely; in the
  companion keep `Friends\FriendsData.lua` (the sync script writes it).
- Saved files must stay below ~262k distinct constants: pack large data (`Core/Storage.lua`, "Packing").
- The user prefers short in-game test sessions.

## Spec updates still to write (v1.4)
- F-003: the per-type delays were replaced by one shared delay. Max age counts from when a request becomes due.
  Countdown indicator; the test screenshot uses the delay.
- F-005: playback speed base (1× = 60 s of play per second). Position format and implicit seq.
  Map art location and naming.
- F-009: settings sections; screenshots are shown with their Chronicle entries (no Screenshots tab).
- F-008: recipe/profession events were added to the chronicle (the spec said snapshots only). The compact recipe
  format and `snapshots` area.

## History

### Desktop UI: home screen, gallery, card lists, the game's fonts (2026-10-16)
- User request after the brainstorm. Home screen (`ui/pages/home.py`) with four cards: last session (time, levels,
  a game icon with a count per kind of moment, its screenshots, ▶ Rückblick and ⤓ Video), gallery (newest
  pictures, favourites first), map & replay (the last session's route drawn on its zone map, ▶ everything),
  characters (mine and friends'; a click shows that character). The tab wall became a page stack: tabs Start,
  Übersicht, Chronik, Galerie, Karte, Berufe at the bottom (Ctrl+1 ... 6), Import/Einstellungen/Diagnose in the
  gear menu (the Import tab was mostly redundant with auto-import). Cards use `ctx.navigate` / `select_character`.
- Gallery (`ui/pages/gallery.py`): tiles grouped by session (default), zone, level or type; stars for favourites
  (new table `screenshot_favorites`, database migration 10, also in JSONL exports); only-favourites filter. The
  viewer (`ui/screenshots.py`) is shared with the Chronik: full picture under the cinematic's achievement banner,
  ← →, F star, Enter / "Wiedergabe ab hier" (cinematic from 2 min before the picture to the end of its session).
- Chronik and Berufe are card lists (`ui/cards.py`, a delegate-drawn QListWidget): day headings, game icon, gold
  title, grey detail, thumbnail on the right, gold/red bar for milestones/deaths. Berufe: a card per profession
  (icon, skill bar, rank, recipe status; click filters), recipes grouped by profession and category with their
  game icons (profession and recipe icons are now extracted after each import too).
- Fonts: `wow/game_fonts.py` takes Fonts\FRIZQT__.TTF and MORPHEUS.TTF (named in the root file) into
  `%APPDATA%\ForeverChronicle\fonts` and loads them at start; Friz Quadrata for headings, buttons, tabs, lists;
  Morpheus for titles. Labels need `theme.font_css` (the app style sheet wins over setFont).

### Cinematic mode: deaths, camera, zone music, standstills, video export (2026-10-16)
- User requests after a brainstorm. Deaths: the replay slows down before a death and holds 1.4 s on a dark red
  title (name, "Gestorben", place) while the world turns grey-blue (`CinemaView`, a QGraphicsColorizeEffect;
  Qt has no saturation blend mode). The body is a headstone, the ghost a wisp, the corpse run a pale dotted line;
  rising light at the graveyard and when coming back to life. The addon records only `player_died`, so
  `domain/cinematic.death_spans` reads release (first teleport within 6 min, or leaving the dungeon) and revival
  (back within ~60 yards of the body; spirit healer: 30 s; resurrected in place: when moving on) from the route.
  On the user's data: release ~8 s after dying, back 20–80 s later.
- Camera: calmer follow (time constant 0.45 s, marker kept within 30 % of the middle) and a slight automatic zoom
  (0.86× on flight paths, ≤0.9× when racing, 1.07× near moments/standing/dead; 2.6 s time constant). The user
  asked for "not too much".
- Zone music from the game: `tools/extract_zone_music.py` writes `desktop/forever_chronicle/zone_music.json`
  (UiMapAssignment → AreaTable[9] ZoneMusic → ZoneMusic.Sounds day/night → SoundKitEntry; fileDataIDs 1957219,
  1353545, 1310254, 1237435). Those tables have encrypted sections of unreleased rows: `casc.read_fdid(...,
  zero_encrypted=True)` and `db2.py` skip them. 52 zones, 34 dungeons, 125 MP3 files (~114 MB in total); the app
  takes the ones a replay needs into `%APPDATA%\ForeverChronicle\music\` (background thread). Ironforge and
  Undercity have no zone music in the table (keep the previous music). Switch after 2.5 s in a zone. Option in
  Settings ("Musik der Gebiete aus dem Spiel", `extra.cine_music`). Rerun the tool after a client patch.
- Standstills (`still_spans`: ≥90 s within ~25 yards): normal, 8× faster (default) or skipped; button and key S,
  `extra.cine_still`. Moments inside them are always shown. The user's main character has 4.7 h of them.
- Video export (`ui/cinematic_export.py`): "⤓ Video" in the cinematic controls and on the map page. Renders the
  window off screen frame by frame (30 fps, 720p/1080p, ~25–30 ms per frame) into ffmpeg (H.264), mixes music and
  effects with numpy (AAC). ffmpeg from `imageio-ffmpeg` (new dependency); the dialog offers to install it where
  missing, since the friends' launcher was being changed by another session at the time.

### Game icons on the desktop (2026-10-16)
- User request: the desktop shows events with the addon's icons. `EventType` got the addon's `icon`, `highlight`
  and `pin_icon`; `event_types.icon_of` prefers the fileDataID recorded with the event, as the addon's `getIcon`.
- Shown in Chronik and Übersicht (20 px), as round map pins with the addon's looks (`ui/icons.py` PIN_LOOKS) and
  in the replay's pins and achievement banner. Map pins grow on hover and show a small card (icon, event, place,
  time; `map_page.event_tooltip`). The symbols stay as the fallback.
- The 13 type icons are PNGs in `desktop/forever_chronicle/icons/` (`tools/extract_icons.py`). Per-event icons
  go to `%APPDATA%\ForeverChronicle\icons\` after each import (`AppContext.extract_icons`, `wow/game_icons.py`);
  the user's 7 took 1.6 s, including Forever's own recipe icon 7808148.
- `casc.py` moved from `tools/` into `desktop/forever_chronicle/wow/`. numpy and Pillow are now main dependencies;
  `Journey Forever starten.bat` installs them once on friends' existing setups (marker `.ready2`), and starts the
  app anyway if that download fails.

### Map images from the game client (2026-10-16)
- Cause of the offset routes (Dorgar's Mulgore, 2026-10-15): the coordinates were right, the desktop art was
  wrong. Forever reworked Mulgore, so the Classic image differs from what the game draws (lake shape, roads,
  labels; not a shift or scale). Confirmed with the user's own character there.
- New `tools/extract_maps.py` (with `desktop/forever_chronicle/wow/casc.py` for the local CASC storage and `tools/db2.py` for WDC5
  tables) draws every map with art as the game does: base tiles (UiMapXMapArt -> UiMapArtTile) plus all
  exploration overlays (WorldMapOverlay/WorldMapOverlayTile, cut like Blizzard's MapExplorationPin). The DB2
  files have no names in the root file; their fileDataIDs are constants in the tool. Product
  `wow_classic_beta`, build 1.60.1.70425.
- The 60 images replaced the 52 Classic ones in `desktop/forever_chronicle/maps/`, now the only map folder (user
  decision): the app no longer looks in `%APPDATA%\ForeverChronicle\maps`, and the Import tab's
  "Kartenbilder importieren" (Classic zip) is gone, with the art names in `domain/maps.py`. Old copies left in
  that AppData folder (the user's, friends') are ignored and can be deleted. Background: Claude's shell runs inside
  the Claude app package, so its writes to AppData are redirected and never reach the user's programs. Changed against Classic: Mulgore, Stormwind,
  Eastern Plaguelands, Redridge, Alterac (Dalaran), Undercity. New: Zephras Isle (2521), Darkspear Islands
  (2524), 2482, 2548, 2652, 2665, and the extra continent maps 1463/1464. World and continents match Classic,
  so `CONTINENT_ON_WORLD` stays valid. Rerun the tool after a client patch.

### Cloud folder holds player data only (2026-10-15)
- User decision: the code lives in git, so the OneDrive cloud folder keeps only `players\`. The `addon\` and
  `tools\` folders there and `tools/publish_to_cloud.py` were removed.
- Sync script version 2: `config.json` has a `repo` field (the local clone). Each run updates the script from
  `<repo>\sync` and installs a newer addon from `<repo>\addons`, so a `git pull` is the whole release step for
  the friend group. Setup runs from `<repo>\sync\Einrichten.bat`; it reuses the old cloud folder or finds
  "Journey Forever Cloud" in OneDrive (also under `Shortcuts\`), else asks, and stops an older running loop.
- A config without `repo` (set up with version 1) keeps syncing player data but looks for no updates: Gigel has to
  run `sync\Einrichten.bat` from his clone once.

### Map route work, addon 0.15.0 and dungeons (2026-10-14/15)
- Slash command `/fj` (was `/fc`), `/fjshot` (was `/fcshot`).
- Map page: the route is painted up to the shown moment, with a "last 15 minutes" toggle (fading trail), colours
  by level / session / one colour plus a legend, a timeline slider (zone bands, event ticks, breaks collapsed),
  a gliding marker, and route detail that follows the zoom (canvas draws again for the visible area).
- Route archive: when `positions` is full, the oldest points go through `Route.Thin` into `routeArchive`
  (400 points per record). Thinning keeps every dropped sample within 0.0005 map units of where the replay shows
  the player, so replays look the same. The desktop importer reads the archive too.
- Desktop: cinematic mode (`ui/cinematic.py`, `domain/cinematic.py`) with screenshots, opened from the map
  page. The desktop route now breaks at teleports like the addon. The user wants screenshot features in the
  desktop app because the addon cannot load the image files.
- **Load test result (2026-10-14): the client refuses saved files with too many distinct constants.**
  400,000 unique strings failed with "constant table overflow" (Lua limit ~262,143 per chunk), and the whole
  file is dropped. Fix: schema 2, streams are packed in the saved file (`Core/Storage.lua`, "Packing"): compact
  records 400 per string, table records 100 per string as Lua text, which is only compiled after a plain-data
  check, in an empty environment. Unpacked on load (own characters) or on first use (friends, `ViewStream`),
  packed after every PLAYER_LOGOUT handler (`Core.lua`). The friends share is packed the same way
  (share format 2). Desktop importer: `unpack_stream`, SUPPORTED_SCHEMA = 2. The test addons are deleted.
  Backups of the saved files before the first packed save: `SavedVariables\*.lua.before-0.15.0`.
- Friends with an older companion see packed data as empty until they get the new companion: release the main
  addon and the companion together.
- Friends' routes on the map: written down in `docs/Friends_Map_Design.md`, not built.
- Dungeons (2026-10-15): `Modules/Dungeons.lua` records `boss_killed` and `dungeon_completed` (first kill of the
  last boss: journal's last encounter, else the dungeon finder's boss list) with a screenshot trigger
  "dungeon". It also probes each dungeon passively into `FC.db.dungeonProbe` (`/fj dungeon`).
  **Open:** after the user's next dungeon, read the probe from the saved file and decide the dungeon map per
  `docs/Dungeon_Maps.md` (option 1 real path if a position exists, option 2 boss-run view otherwise).
  Check there that the journal's encounter IDs match ENCOUNTER_END (probe field `encounters`).
- The desktop cinematic mode has a timeline bar (mouse-activated), speeds, and slows down before screenshots.

### Version notes up to 0.14 (2026-10-14)
- Spec: `ForeverChronicle_Feature_Spec_v1.3.docx`. Architecture and extension guide: `ARCHITECTURE.md`.
  Phase 0 results: `docs/Phase0_Compatibility_Report.md`.
- **Addon v0.3.1** (`addons/ForeverChronicle/`), installed and hash-verified in
  `_classic_beta_\Interface\AddOns\ForeverChronicle`. Modules:
  - Character, Session (silent /played) and Progress (level, quest, death, achievement)
  - Travel (known zones and discovery after dwell)
  - Positions (route points every 2 s by default, choices 1/2/5/10 s, cap 100k; old default 10 s migrated once via settings rev; map geometry)
  - Screenshots (queue, shared delay default 5 s, cooldown, on-screen countdown hidden before capture,
    test screenshot follows the delay, `/fcshot`)
  - Window tabs: Übersicht, Chronik, Screenshots (list), Einstellungen (sections: Allgemein, Route, Screenshots), Diagnose.
- **Addon v0.4.0: in-game map (user request "map part inside the game"):** a new Karte tab in the addon window
  (820×700; the window resizes per page).
  - Map art comes from the client (`C_Map.GetMapArtLayerTextures`) plus explored overlays (`C_MapExplorationInfo`).
    These APIs have NOT been verified in Forever yet; if missing, a plain area with the map name is shown.
  - Route lines use `CreateLine` with decimation. There are event icons, a marker, map and session cyclers,
    a slider, play/pause, 1/2/4/10× speeds and Live mode (follows the newest point; a map picked by hand stays).
  - Clicking a Chronik row jumps the map to that moment (`UI:FocusMap`).
  - Shared route logic lives in `Core/Route.lua` (cached incremental parsing, same rules as `desktop/domain/route.py`).
  - The desktop app stays for the full history (the addon keeps ~55 h of route) and for screenshots.
- **Addon v0.5.0: UI overhaul (user: "use icons more, reduce text"):**
  - One fixed window size, 820×670, for all pages (user request).
  - Icon tabs on the right edge (`page.icon`; "portrait" = player portrait). Names are in tooltips.
  - Übersicht uses tiles (icon + value, name in tooltip); stat icons come from `RegisterStat{icon}`,
    stream icons from `DefineStream(name, cap, icon)`.
  - Screenshots and Diagnose use status icons (ReadyCheck textures). Settings section headers get icons.
  - Map: page-arrow cyclers, icon toggles, play arrow with glow, live eye.
    Zoom: mouse wheel at the cursor up to 6×, drag to pan, right-click to reset (`MapCanvas` content layer).
  - New option "Interface für Screenshots ausblenden" (default off; `SetUIVisibility`/`UIParent:Hide`;
    skipped in combat; always restored on confirmation, failure or after 1.5 s).
  - Not yet seen in game: whether all icon/texture paths exist in Forever (missing ones show a question mark).
- **Addon v0.6.0: overview reworked after user feedback ("only icons is not readable"):**
  - Full name with last name ("Blind Bullseye" = `UnitName` second value), XP bar with rested XP, gold.
  - Stat groups with heading and short description (`FC:RegisterStatGroup`): Aktuelle Sitzung, Spielzeit,
    Fortschritt. Tiles show icon, name and value.
  - Reloads and levels-gained tiles removed. New stats: kills (`PARTY_KILL`, counts group killing blows too)
    and XP earned (`PLAYER_XP_UPDATE` deltas, wraps across level-ups). Neither event is verified in Forever yet.
  - Character model (PlayerModel, drag to rotate) with 19 gear slots like the Classic character window
    (quality borders, item tooltips).
  - Storage bars moved to Einstellungen (own section).
- **Addon v0.7.0: rare kills (user request).**
  - The `Rares` module remembers rares and rare elites seen as target, mouseover or nameplate, by GUID.
    `PARTY_KILL` of one of them records a `rare_killed` event (name, NPC ID). If the GUIDs are secret, the dead
    rare target is used instead.
  - New stat "Seltene Gegner". New screenshot trigger "rare" (on by default, priority 3, skips the cooldown like
    level/achievement; `/fcshot rare on|off`). The desktop shows the event and the stat.
  - `PARTY_KILL` is still unverified in Forever.
- **Addon v0.8.0: graphs under the character (user request).**
  - The `Metrics` module writes the compact `metrics` stream (time,xp,kills,money,level), sampled every 60 s
    and only when something changed.
  - The graph registry `FC:RegisterGraph` provides XP / kills / quests / gold per hour over the last 12
    played hours (taken from sessions). Bar graph widget in `UI/Graph.lua`; switch with the arrows; the choice is
    saved in `settings.overviewGraph`.
  - The screenshots stat tile was removed (addon and desktop). Storage bars are in 3 columns on the settings page.
  - The desktop app does not import the metrics stream yet (possible later: graphs over the full history).
- **Addon v0.9.0: minimap button (user request).**
  - Classic round button (`UI/MinimapButton.lua`). Left-click opens the window, right-click the settings; drag
    to move it (the angle is saved). Option under Allgemein (on by default).
  - The settings page is now scrollable (content height computed from the last storage bar).
- **Addon v0.10.0: professions and recipes (spec F-008).**
  - New module `Modules/Professions.lua` and the new snapshot area `char.snapshots` (`Storage:GetSnapshot`).
  - New in-game tab "Berufe": professions with skill bar and rank, plus recipes grouped by category with search
    and capture status. The command `/fc professions` refreshes and lists them.
  - Chronicle events: profession learned, rank trained (e.g. Experte), recipe learned (`NEW_RECIPE_LEARNED`).
    Overview stat "Bekannte Rezepte".
  - Desktop: migration 5 (`professions`, `recipes`, `recipe_categories`), import of the snapshot, and a new
    "Berufe" tab with a profession table and a recipe table (profession filter and search). Stat "Bekannte Rezepte".
  - Not yet seen in game: `NEW_RECIPE_LEARNED`, `SKILL_LINES_CHANGED`, `C_TradeSkillUI.GetCategoryInfo`, and
    whether `GetBaseProfessionInfo` reports the window's profession. To check, open the Lederverarbeitung window
    once and look at the Berufe tab.
- **Addon v0.10.1 (user requests).**
  - Recipe names are shown in the item quality colour of what they create (in game and desktop). The recipe format
    is now v2 `recipeID,categoryID,icon,quality,name` (`recipes.format = 2`). Quality comes from the output
    item's hyperlink colour or from `C_Item.GetItemQualityByID`, and is empty for enchants. Desktop migration 6
    adds `recipes.quality`. v0.10.0 data (format 1) is still readable.
  - Map replay always opens the zone, not the continent. The real data had a few points with continent IDs
    (1414/1415, recorded between zones). `Route.ZoneFor` / `Route.view_for` map them to the smallest known zone
    containing them. Projection now also works from continent to zone, and following switches whenever the zone
    changes. A map picked by hand stays until then.
- **Addon v0.10.2: dungeon moments at the entrance (user request).** The client gives no position inside
  instances, so dungeon points and events (Chronicle click, pins, playback marker) are shown at the dungeon
  entrance, with the notice "am Eingang gezeigt". Entrances are kept in `FC.db.entrances`:
  - `journal`: `C_EncounterJournal.GetDungeonEntrancesForMap` and `EJ_GetInstanceInfo` (10th value = instance
    ID), queried once per zone. Not yet confirmed to exist in Forever.
  - `walked`: the last outdoor sample at most 60 s before entering, skipped for dungeon-finder groups.
  - Older data: derived from the route by the same rule (`Route.DerivedEntrances` / `Route.entrance`).
  - Desktop: migration 7 `instance_entrances`; `EventRow.instance_id`.
  - Dungeon maps: art can be shown later (the Classic dungeon maps have uiMapIDs), but without positions inside
    instances only as a picture with the dungeon's events listed, not with a route.
- **Addon v0.10.3: line graph (user request).** The overview graph is now a line over the last 2 hours of
  played time (`Metrics:PlayedWindow`; time between sessions is skipped and marked with a faint line). XP, kills
  and quests show what was gained in the window (`relative`); quests are drawn as steps at the exact times; gold
  shows the money held. Clock times along the bottom, and hovering shows the time and value of the nearest point.
  Graph defs now provide `series(since)` instead of hourly values (`UI:LineGraph` replaces the bar graph).
- **Desktop v0.2.0: JSONL export/import and backups (spec F-011).**
  - `storage/jsonl.py` exports the whole database as JSON Lines: a header line (`format: "forever-chronicle"`,
    `format_version` 1, app version, DB schema), then one line per record with `record_type`. Character
    records are referenced by their natural key (GUID), never by the local UUID. Local-only columns (IDs,
    import bookkeeping, screenshot file paths) are not exported.
  - Import is a merge: idempotent, row by row, and invalid rows are reported with their line numbers. Unknown
    record types are skipped and counted. Merge rule per type (`RECORD_TYPES`): events are immutable; sessions,
    positions, professions, characters and counters take the more complete or newer version. It runs in one
    transaction, recorded in `import_runs` (`source_type` jsonl), with a DB backup first.
  - Backups: before migrations (as before), before every JSONL import, daily at app start, and on demand. The
    newest 5 are kept. The Import tab has a "Datensicherung" section: Exportieren, Export importieren,
    Jetzt sichern, Sicherungsordner öffnen.
  - Checked against a copy of the real database: 175 records round-trip; re-import changes nothing.
- **Desktop v0.2.1: restore a backup (user request).** "Wiederherstellen …" on the Import tab: choose a backup
  (newest first, with its time and kind), confirm, then all data is replaced (`Database.restore`, SQLite backup API
  into the live connection). The current state is backed up first ("vor Wiederherstellen"), and the chosen file
  is protected from the 5-copy rotation. Older backups are migrated afterwards. Backups from newer versions and
  files that are not Journey Forever databases are refused. Backup file names are unique (counter when two
  are made in the same second).
- **Desktop v0.3.0: friends' characters, phase 1 (see docs/Sharing_Design.md).**
  - New tab "Freunde": your name (free text), "Teilen …" (dialog: own characters, categories per character, and
    screenshots picked one by one with thumbnails, none pre-selected), import a friend's `.fcshare`, and the
    friend list with remove.
  - `storage/share.py`: a ZIP with `share.jsonl` (JSONL with `kind: share`, `share_id`, `sender`, `created_at`,
    categories) plus picked pictures scaled to 1600 px. Import: the newest file of a friend replaces everything
    they shared before (characters and categories no longer shared disappear). It never touches my own
    characters or another friend's, and ignores older files. ZIP member names are never used as paths; record
    types are restricted. Pictures are stored in `%APPDATA%\ForeverChronicle\friends\<share_id>\`, staged and
    swapped after the commit.
  - Migration 8: `owners`, `characters.owner_id`. Friends' characters are never exported again (JSONL backup
    or share), and backup imports cannot write to them. The screenshot matcher only handles my own
    characters.
  - Sidebar: "Meine Charaktere", then one group per friend; the app starts on my own character.
  - Next (phase 2): the in-game character layer around the whole addon window (user decision): default is the
    played character, with a choice of all characters of the account and all friends' characters, fed by
    `Friends\FriendsData.lua`, which the desktop app writes.
- **Phase 2 of sharing: friends in game (addon v0.11.0, desktop v0.4.0).**
  - Desktop finds the game through Battle.net (`wow/battlenet.py`): product.db (generic protobuf decoding),
    Battle.net.config, and the Windows uninstall entries; then the drive scan. `client_from_path` only checks the
    chosen folder.
  - Desktop writes `Interface\AddOns\ForeverChronicle\Friends\FriendsData.lua` (`wow/friends_data.py`) at
    start and after every friend import or removal. Friend characters use the addon's own record shape, trimmed
    (200 events, routes of the last 3 sessions, at most 60,000 points in total). It uses a strict literal-only
    serializer: plain ASCII, \ddd escapes, one function per character. The real-Lua test is
    `tests/addon/dump_friends.js`. The Freunde tab shows the in-game status.
  - Addon: `Core/View.lua` (FC:ViewChar/ViewStream/ViewSnapshot/MapInfo/InstanceName/StoredEntrance) and
    `UI/ViewBar.lua`, a character chooser under the title (scrollable list: played character, account alts,
    friends grouped by name). Every tab shows the chosen character, with the banner "nur lesen" and
    "Zurück zu mir". Live-only parts of the overview (model, gear, XP, gold, graph) only show for the played
    character. Recording always goes to the played character.
  - **Install rule changed:** mirror with `robocopy /MIR /XF FriendsData.lua`, place the placeholder only if
    missing, and compare hashes without that file (the desktop app owns it in the game folder).
  - Tests: desktop `test_battlenet`, `test_friends_data` (writes `tests/fixtures/FriendsData.lua`); addon
    phase 12 loads that fixture.
- **Split for CurseForge (addon v0.14.0).** `addons/ForeverChronicle` is the standalone public addon.
  `addons/ForeverChronicle_Share` is the private companion for the friend group (Share module, `Friends.lua` view
  source, `Friends/FriendsData.lua`, its strings, `## Dependencies: ForeverChronicle`), distributed only through
  the cloud folder.
  - Main addon extension points: `FC:RegisterViewSource{ entries, data(kind), emptyNoteKey }` (characters for the
    chooser), and modules from later-loading addons get their default settings in `FC:NewModule`.
  - Player-visible texts no longer mention the desktop app.
  - `tools/package_curseforge.py` checks the main addon (file types, .toc and files in sync, no links, donation
    or ad words, no references to desktop, cloud or companion in visible texts; code without companion data or
    runtime code loading), then builds `dist/curseforge/ForeverChronicle/` and `ForeverChronicle-<version>.zip`.
  - The sync script writes `ForeverChronicle_Share/Friends/FriendsData.lua`. The test runner loads the
    companion after the main addon's ADDON_LOADED (like the game); phase 14 runs the main addon alone.
  - Install rule: the main addon is mirrored completely; in the companion, keep `Friends\FriendsData.lua`.
  - Incident: installing removed the old `ForeverChronicle\Friends\FriendsData.lua` in the game folder, which held
    the friend "Gigel" (character Zitter) imported with the old desktop share. It was regenerated from the desktop
    database (writer from commit 6a79977, read-only) into the companion folder. The cloud sync replaces it as soon
    as it runs, so Gigel needs the cloud setup.
- **Cloud sync, in-game first (user decision; docs/Sharing_Design.md version 2).**
  - Addon v0.13.0: the data-only addon `ForeverChronicle_Share` plus `Modules/Share.lua` (written on logout and
    /reload) and the settings section "Mit Freunden teilen" (name, characters, categories; default everything on).
  - `sync/ForeverSync.ps1` (PowerShell only), `ForeverSync.vbs` (hidden start from the Startup folder; no admin
    rights needed) and `Einrichten.bat` (lives in `<cloud>/tools`; setup from there). Each run: self-update,
    addon update from `<cloud>/addon` (WoW closed), upload of `ForeverChronicle_Share.lua` to `<cloud>/players`,
    download with a strict plain-data check (one linear regex), then `Friends/FriendsData.lua` with each friend
    loaded on its own in an empty environment, a daily backup (10 days), and `sync.log`. Settings live in
    `%LOCALAPPDATA%/ForeverChronicle/sync`.
  - `tools/publish_to_cloud.py` copies the addons and the sync files into the cloud folder; every PC installs them.
  - The desktop share feature is removed (Freunde tab, share dialog, `.fcshare` files, the desktop
    FriendsData writer). The `owners` table and `characters.owner_id` stay (migration 8). `test_sync.py` now writes
    `tests/fixtures/FriendsData.lua` from the script's real output, and addon phase 12 loads it.
  - To start: create a shared cloud folder, run `tools/publish_to_cloud.py <folder>`, then on every PC
    `<folder>/tools/Einrichten.bat`.
  - Tests: `desktop/tests/test_sync.py` runs the real script against temporary folders.
- **Addon v0.12.0: gear for other characters (user request).** The `Modules/Gear.lua` snapshot `snapshots.gear` (slot,
  slotName, link, item, icon, quality) is taken at login and on `PLAYER_EQUIPMENT_CHANGED`. The overview shows alts'
  and friends' gear slots from it (icon, quality border, tooltip via `SetHyperlink`); only the 3D model stays for
  the played character. Desktop: migration 9 `gear`, import, JSONL type `gear`, share category "Ausrüstung", the
  friends file (`snapshots.gear`) and an "Ausrüstung" list on the overview. Next (open): test whether
  `SetCustomRace` / dressing a model (`TryOn`) work in Forever, for a dressed model of other characters.
  The addon test runner now writes `tests/fixtures/ForeverChronicle.lua` right after phase 3. When the shared data
  changes, run npm test, pytest, then npm test again (phase 12 needs the friends file that pytest writes).
- **Package for friends (user request).** `tools/package_for_friend.py` builds `dist/ForeverChronicle-<version>.zip`
  (about 28 MB; too big for Discord's free 10 MB limit, so share it via OneDrive, Google Drive or similar). It
  contains the addon, the desktop app source, `Journey Forever starten.bat`, `LIES MICH.txt` and the 52 map images
  in `desktop/forever_chronicle/maps/` (in git since 2026-10-15, about 29 MB; `map_art` uses the user's own
  images in `%APPDATA%\ForeverChronicle\maps` first, then the bundled ones).
  - The batch finds Python 3.11+ (py launcher, PATH or the per-user install folder), offers
    `winget install Python.Python.3.12 --scope user`, and creates the venv in `%LOCALAPPDATA%\ForeverChronicle\venv`
    (short path; a deep unzip folder hit the 260-character limit). It installs `PySide6-Essentials` once (the
    app only uses QtCore, QtGui and QtWidgets), runs `python -m forever_chronicle.setup_addon` (finds the game via
    the settings, Battle.net or the drive scan; asks for the folder otherwise; mirrors the addon and keeps
    `Friends\FriendsData.lua`), then starts the app. `FC_SETUP_ONLY=1` skips the start (for testing).
  - Not yet tested end to end on a clean PC (Python install and pip download). The Python parts are covered by
    `tests/test_package.py`.
- **Desktop:** the icon overhaul was reverted at the user's request; text UI stays.
  - Shows the full name. Kill/XP counters are imported (`character_stats`, migration 4) and replace "Stufenaufstiege".
  - Open question for the user: real WoW icons for the desktop. Options: export from the local client with
    wow.export, or the Wowhead icon CDN.
- **Desktop** (`desktop/`, start with `desktop/Journey Forever.bat`). Tabs: Übersicht, Chronik, Karte,
  Berufe, Screenshots, Import, Diagnose.
  - The Karte tab shows your map art with the route, event markers, a time slider, play/pause and 1×/2×/4×/10× speeds
    (1× = 1 min of play per second), session filter, continent view, follow map, and an instance notice.
    Selecting an event in the Chronik moves the map there.
  - Map art: the user's 52 explored-zone maps were imported into `%APPDATA%\ForeverChronicle\maps\<uiMapID>.jpg`.
    The Import tab has "Kartenbilder importieren …". Coordinates were verified against real probe data
    (Orgrimmar/Cleft of Shadow, Kalimdor rectangle).
- Tests: `tests/addon` (`npm test`: 14 queue tests and 13 phases) and `desktop` (`pytest`, 93 tests). All pass.
- In-game confirmed by the user: window, import, Screenshots tab (v0.2.0). Not yet seen in game: v0.2.1 and v0.3.0 changes.
