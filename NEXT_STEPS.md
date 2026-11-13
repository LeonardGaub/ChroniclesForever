# Journey Forever – Session Handoff

Start here. "Current state" and "Open items" are kept up to date; `docs/History.md` keeps the session notes as they
were written at the time (older entries may describe things that changed later). Architecture and extension guide:
`ARCHITECTURE.md`. Player-facing addon changes for the next upload: `CHANGELOG.md`.

## Current state (2026-11-13)
- Main addon `addons/ForeverChronicle` 0.17.0 (changelog section "0.17.0" in `CHANGELOG.md`, with a "Desktop app"
  part that is not for CurseForge). The repository is public since 2026-11-13. 0.17.0 is the first version
  published as a GitHub release (`tools/package_for_friends.py --release`); friends on 0.16.0 install its zip once
  by hand, later releases reach their apps by themselves (open item 10). 0.16.0 was shared on 2026-11-04 as
  `dist/friends/JourneyForever-0.16.0-Komplett.zip` (addon + desktop app; `Journey Forever starten.bat`
  installs everything, README "Install and run").
  CurseForge: 0.15.0 was packaged on 2026-10-20 but never uploaded (last upload 0.14.1; description in
  `docs/CurseForge.md`). The friends companion `ForeverChronicle_Share` was removed on 2026-10-27; the
  desktop app installs a newer main addon from the repository at start (WoW closed) and deletes the companion folder.
- Addon window tabs: Übersicht, Chronik (screenshots shown with their entries), Karte, Einstellungen, Diagnose. Slash commands `/fj` and `/fjshot`.
- Desktop app: starts on the home screen (Start). Tabs at the bottom: Start, Übersicht, Chronik, Galerie, Kino
  (the way into the cinematic mode: the whole journey and its chapters); the gear menu next to them opens
  Import, Einstellungen (sound, route colours), Diagnose. The desktop's map page was removed on 2026-11-02 (user
  decision): the addon's map is the place to browse the route.
  Start it with `desktop/Forever Chronicle.bat`; without a dev venv (friends' clones) `Journey Forever starten.bat`
  in the repository root sets up Python, installs the addon and starts the app. The user is moving away from the
  desktop app: fixes and features go into the addon, except features that need the screenshot files (cinematic
  replay).
- Removed on 2026-10-26: the dungeon probe (`/fj dungeon`, `FC.db.dungeonProbe`; boss and dungeon-completed
  tracking stay), the cinematic's "zones" map mode (the seamless world map is the only one), the friends' zip
  package (`tools/package_for_friend.py`), the sync's turn-off of the old automatic sync (versions 1 and 2) and
  the old player file names, and the desktop's legacy share IDs and recipe format 1.
- Cloud backup and friends (2026-10-27, docs/Cloud_Backup.md), replacing the friends sync: the desktop app backs up
  the addon file, the screenshots (full size) and its database into `<cloud>\<name>\` (dated copies, newest 30,
  nothing overwritten) when WoW starts and closes, at app start if something changed, and with "In die Cloud
  sichern" (F5); "Aus der Cloud wiederherstellen …" brings copies back, and a banner says when my other PC has
  newer addon data. Every other player folder in the cloud is a friend, shown in the desktop app only. Cloud folder
  and name are set on the Import page (taken over from the old sync on first start).
- Tests: `tests/addon` (`npm test`: queue tests and phases 1-15, writes the fixtures) first, then `desktop`
  (`pytest`). All pass.

## Open items
1. Cloud backup, not tried for real yet: start the app (it takes over the old cloud folder; check the name on the
   Import page), play once, check `<cloud>\Leon\`. Friends: `git pull`, start the app, set folder and name. Once
   all have backed up, delete the old `players\`, `screenshots\` (and `roaming\` if any) in the cloud folder.
   The friends' characters disappear from the app until each friend has backed up once.
2. `Journey Forever starten.bat` is not yet tested end to end on a clean PC (Python install and pip download).
3. Gear: test whether `SetCustomRace` / `TryOn` work in Forever, for a dressed model of other characters.
5. Death cause (2026-10-16): the addon reads `C_DeathRecap.GetRecapEvents()` (no ID = newest recap) at
   `PLAYER_DEAD`, retrying for 5 s, and stores the killing blow (killer, npcID, spell, spellID, environment,
   damage, overkill) in the `player_died` event. Unverified in Forever: whether the recap exists there and is
   readable (not secret). After the next death, check the Chronik entry; if it still says "Gestorben in ...",
   the recap is missing or hidden.
6. Release (2026-11-04): the live client is installed (2026-10-27: `_forever_\`, flavor `wowf` in
   `FOREVER_FLAVORS`, version 1.60.1.70634); the desktop app and the CASC tools also accept any client whose
   `.build.info` version is 1.60 or newer. The TOCs list Interface 16001, 16002, 16003 and 16100; at release check
   the live Interface number (1.60.1 suggests 16001). The beta was uninstalled on 2026-10-27 after its screenshots
   were copied to `_forever_\Screenshots` (app links moved there) and to the cloud, and the account settings and 23
   addons were ported (`tools/port_settings.py account`, backups in `_forever_\PortBackup\`). Its WTF folder is
   gone, so per-character settings can no longer be ported. Unverified: whether the first live login keeps the
   copied `-cache` files or replaces them with Blizzard's server copies; if keybinds are gone, set them again in game
   (`port_settings.py server-sync off|on` only helps while a source exists). Battle.net left about 1 GB in
   `_classic_beta_\` (no WTF, no `.flavor.info`); the user may delete it.
7. Cinematic tracking (2026-10-30, addon "Unreleased", desktop schema 13), untested in game. Check in a short
   session: mount and ride a bit (route flag `M`), use the hearthstone (`JH` on the point after it), bind the
   hearthstone at an inn (Chronik: "Ruhestein gebunden"), die once and come back (hover the death: how), group
   with a friend for a few minutes (stream `group` on the Einstellungen storage bars), loot a blue item (Chronik
   "Beute"), `/fj moment Test` (screenshot at once, entry with the text) and the key binding "Moment festhalten".
   APIs to confirm in Forever: `UnitCastingInfo` timing and `UNIT_SPELLCAST_SUCCEEDED` spell IDs (not secret?),
   `PLAYER_ALIVE`/`PLAYER_UNGHOST`/`RESURRECT_REQUEST`/`CONFIRM_XP_LOSS`, `C_MountJournal` (or no mount events),
   `HEARTHSTONE_BOUND` + `GetBindLocation`, group units' names and GUIDs inside dungeons, `C_Container` and
   `C_Item.GetItemInfoInstant`/`GetItemMaxStackSizeByID`, and whether the moment popup's edit box is found
   (`StaticPopup` changed in 11.x; Modules/Moments.lua tries `GetEditBox`, `editBox` and `EditBox`).
   Friends' apps install the new addon only after the TOC version is raised (`setup_addon.update_addon`).
8. Kills and level-up snapshots (2026-11-02, addon "Unreleased", data only: nothing shows them yet, the desktop
   app ignores the `kills` stream). Ideas taken from the Road to Sixty addon (rewritten, not copied: it has no
   licence). Check in game: kill a few enemies, `/reload`, and look for the `kills` bar under Einstellungen (storage);
   after the next level-up the `level_up` event in the saved file should hold `stats`, `money`, `gear`,
   `playedTotal` and `levelPlayed`. Unverified: whether `CHAT_MSG_COMBAT_XP_GAIN` text is readable
   (not secret) in Forever, in instances too, and whether German clients use `COMBATLOG_XPGAIN_EXHAUSTION1` for the
   rested bonus. Still missing for the "records" (slowest level, nemesis, most killed, best session, ...): only
   the gear-worn record, which needs an event per gear change. Also new: the in-game map draws the route as curves
   from zoom 1.5 on (`Route.CurvePoint`, `UI/MapCanvas.lua`); check in game that zooming stays smooth on a long
   route and that the replay marker sits on the curve. The desktop app still draws straight lines.
9. PvP (2026-11-04, addon "Unreleased" `Modules/PvP.lua`, desktop: chronicle entries and cinematic), built
   without any check in game: the user could not test, and asked for the data to be recorded already. Events
   `pvp_kill`, `duel`, `battleground`; deaths get `killerType = "player"` and the killer's class/race/level/guild,
   and `battleground = "pvp" | "arena"` inside a match. The desktop cinematic shows kills, duels and the match
   result as toasts, gives match deaths no death scene and jumps over the match time (`match_spans`).
   Passive check: after some PvP, read `ForeverChronicleDB.diagnostics.pvp` in the saved file (`counts` per
   signal, up to 40 `samples`; first sightings also in the Diagnose log as "pvp signal: ..."). Unverified in
   Forever: `PARTY_KILL` arguments (player GUIDs readable or secret; does it fire for the whole battleground raid,
   which would inflate the "kills" statistic?), `CHAT_MSG_COMBAT_HONOR_GAIN` and the `COMBATLOG_HONORGAIN*`
   formats (honor per kill may not exist in Forever), the death recap's `sourceGUID` for players,
   `GetPlayerInfoByGUID`, the duel strings `DUEL_WINNER_KNOCKOUT`/`DUEL_WINNER_RETREAT` in `CHAT_MSG_SYSTEM`,
   `IsInInstance` = "pvp"/"arena", positions inside battlegrounds (`match_position` sample), `PVP_MATCH_COMPLETE`
   (winner index vs. `C_PvP.GetScoreInfoByPlayerGuid(...).faction`) and the score fields. Ideas not built yet:
   one "skirmish" cue for several kills and deaths close together, a revenge banner, PvP lines in the credits
   (ask first: credits are long-term stats only).

10. Self-update of the desktop app (2026-11-09, `updater.py`, `ui/update_dialog.py`, ARCHITECTURE "Self-update"):
   the installed app offers newer GitHub releases at start and swaps itself. Tested with unit tests and one real
   apply run on this PC (detached process, folder swap, relaunch); not yet with a real release. Done on
   2026-11-13: repository public, 0.17.0 prepared (version, CHANGELOG, tests, a test zip staged by the updater),
   committed and pushed. Left: (3) run `desktop\.venv\Scripts\python tools\package_for_friends.py --release`,
   (4) friends install that zip once by hand (0.16.0 has no updater); from then on releases arrive by themselves.
   The first real check is 0.17.1: does an installed 0.17.0 offer it and swap cleanly? Release routine: raise
   "## Version:" in the TOC, turn CHANGELOG "Unreleased" into the version, commit, push, run `--release`.
   Optional: a credit line for OpenMap (MIT) in the README for the world map tiles.
11. Cinematic screenshots at the side (2026-11-09, design in `docs/Cinematic_Side_Pictures.md`, option
   "cine_side_photos", on by default): the replay no longer stops for screenshots; they land in a pile of up to five
   over the map's right edge, and only big moments slow it to half speed. Tested with unit tests and rendered frames
   from a copy of the real database; not yet watched by the user in the app. Values to tune after watching:
   `SIDE_GAP`, `SIDE_SLOW`, `SIDE_KEEP_INSIDE` (ui/cinematic.py) and `SIDE_WIDTH`, `SIDE_LIFE`,
   `SIDE_STEP_*` (ui/cinematic_fx.py). The 3D branch (`investigate/3d-map-viewer`) picks it up when merged.

## Confirmed client facts
- Install: `C:\Program Files (x86)\World of Warcraft\_forever_\` (`Wow.exe`, flavor `wowf`, client 1.60.1). The beta
  (`_classic_beta_\`, `WowB.exe`, TOC Interface 16001) was uninstalled on 2026-10-27.
- SavedVariables: `WTF\Account\131324136#1\SavedVariables\` plus `.lua.bak`.

## Decisions made
- WoW Forever = Blizzard Classic+ on the Mainline API with Midnight addon rules.
- Published on CurseForge as "Journey Forever" (the only addon since 2026-10-27). Internal names
  keep "ForeverChronicle" (folders, SavedVariables, paths) so existing data survives. Map images for the desktop
  app come from the game client (tools/extract_maps.py) and live only in `desktop/forever_chronicle/maps/`.
- UI: German default and switchable. Classic look: Blizzard templates in game, Classic theme on desktop.
- Modular architecture: new stats arrive as new addon modules and desktop registry entries (see ARCHITECTURE.md).
- Screenshots: shared delay after the event (user request, default 5 s), on-screen countdown (not chat: chat would be in
  the screenshot), cooldown bypass for level/achievement, and the test screenshot follows the delay.
- After every addon change: copy to the game folder and hash-verify (mirror the addon completely).
- Cloud backup (2026-10-27): backups only add dated copies, never overwrite; restore is manual (no merge between
  PCs); friends only in the desktop app; full-size screenshots for everyone; the app watches WoW only while open.
- Saved files must stay below ~262k distinct constants: pack large data (`Core/Storage.lua`, "Packing").
- Dungeon maps: built on 2026-10-18 in the addon and the desktop app and removed again the same day (the user did
  not like them; `docs/Dungeon_Maps.md`). Do not bring them back without asking. Dungeon moments stay at the
  entrance. The dungeon probe that checked positions and encounter IDs inside was removed on 2026-10-26.
- The user prefers short in-game test sessions.

## Spec updates still to write (v1.4)
- F-003: the per-type delays were replaced by one shared delay. Max age counts from when a request becomes due.
  Countdown indicator; the test screenshot uses the delay.
- F-005: playback speed base (1× = 60 s of play per second). Position format and implicit seq.
  Map art location and naming.
- F-009: settings sections; screenshots are shown with their Chronicle entries (no Screenshots tab).
- F-008: professions are only events now (learned, new rank); the recipe list, the skill and both profession pages
  were removed on 2026-11-04.

## History

Moved to `docs/History.md` (session notes, newest first; new entries go there).
