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
- **Desktop:** the icon overhaul was reverted at the user's request; text UI stays.
  - Shows the full name. Kill/XP counters are imported (`character_stats`, migration 4) and replace "Stufenaufstiege".
  - Open question for the user: real WoW icons for the desktop. Options: export from the local client with
    wow.export, or the Wowhead icon CDN.
- **Desktop** (`desktop/`, start with `desktop/Forever Chronicle.bat`). Tabs: Übersicht, Chronik, Karte,
  Screenshots, Import, Diagnose.
  - The Karte tab shows your map art with the route, event markers, a time slider, play/pause and 1×/2×/4×/10× speeds
    (1× = 1 min of play per second), session filter, continent view, follow map, and an instance notice.
    Selecting an event in the Chronik moves the map there.
  - Map art: the user's 52 explored-zone maps were imported into `%APPDATA%\ForeverChronicle\maps\<uiMapID>.jpg`.
    The Import tab has "Kartenbilder importieren …". Coordinates were verified against real probe data
    (Orgrimmar/Cleft of Shadow, Kalimdor rectangle).
- Tests: `tests/addon` (`npm test`: 14 queue tests and 6 phases) and `desktop` (`pytest`, 60 tests). All pass.
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

## Next steps
1. User: quick check: `/reload`, walk a bit, `/reload`, then open the desktop Karte tab.
2. Spec §10 step 9: profession and recipe snapshots (F-008).
3. Then JSONL export/import and backups (F-011), QA and packaging.
