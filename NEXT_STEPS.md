# Forever Chronicle – Session Handoff

## Current state (2026-10-14)
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
  files that are not Forever Chronicle databases are refused. Backup file names are unique (counter when two
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
- **Desktop:** the icon overhaul was reverted at the user's request; text UI stays.
  - Shows the full name. Kill/XP counters are imported (`character_stats`, migration 4) and replace "Stufenaufstiege".
  - Open question for the user: real WoW icons for the desktop. Options: export from the local client with
    wow.export, or the Wowhead icon CDN.
- **Desktop** (`desktop/`, start with `desktop/Forever Chronicle.bat`). Tabs: Übersicht, Chronik, Karte,
  Berufe, Screenshots, Import, Diagnose.
  - The Karte tab shows your map art with the route, event markers, a time slider, play/pause and 1×/2×/4×/10× speeds
    (1× = 1 min of play per second), session filter, continent view, follow map, and an instance notice.
    Selecting an event in the Chronik moves the map there.
  - Map art: the user's 52 explored-zone maps were imported into `%APPDATA%\ForeverChronicle\maps\<uiMapID>.jpg`.
    The Import tab has "Kartenbilder importieren …". Coordinates were verified against real probe data
    (Orgrimmar/Cleft of Shadow, Kalimdor rectangle).
- Tests: `tests/addon` (`npm test`: 14 queue tests and 11 phases) and `desktop` (`pytest`, 88 tests). All pass.
- In-game confirmed by the user: window, import, Screenshots tab (v0.2.0). Not yet seen in game: v0.2.1 and v0.3.0 changes.

## Confirmed client facts
- Install: `C:\Program Files (x86)\World of Warcraft\_classic_beta_\` (`WowB.exe`, client 1.60.1). TOC Interface 16001.
- SavedVariables: `WTF\Account\131324136#1\SavedVariables\` plus `.lua.bak`.

## Decisions made
- WoW Forever = Blizzard Classic+ on the Mainline API with Midnight addon rules.
- Private use. The user provides map artwork (done).
- UI: German default and switchable. Classic look: Blizzard templates in game, Classic theme on desktop.
- Modular architecture: new stats arrive as new addon modules and desktop registry entries (see ARCHITECTURE.md).
- Screenshots: shared delay after the event (user request, default 5 s), on-screen countdown (not chat: chat would be in
  the screenshot), cooldown bypass for level/achievement, and the test screenshot follows the delay.
- After every addon change: copy to the game folder and hash-verify.
- The user prefers short in-game test sessions.

## Spec updates still to write (v1.4)
- F-003: the per-type delays were replaced by one shared delay. Max age counts from when a request becomes due.
  Countdown indicator; the test screenshot uses the delay.
- F-005: playback speed base (1× = 60 s of play per second). Position format and implicit seq.
  Map art location and naming.
- F-009: settings sections; the Screenshots tab shows only the list.
- F-008: recipe/profession events were added to the chronicle (the spec said snapshots only). The compact recipe
  format and `snapshots` area.

## Next steps
1. User: quick check: `/reload`, walk a bit, `/reload`, then open the desktop Karte tab.
2. User: open each profession window once in game and check the Berufe tab (in game and desktop).
3. QA and packaging.
