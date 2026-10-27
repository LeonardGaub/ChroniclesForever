# Journey Forever – Session Handoff

Start here. "Current state" and "Open items" are kept up to date; `docs/History.md` keeps the session notes as they
were written at the time (older entries may describe things that changed later). Architecture and extension guide:
`ARCHITECTURE.md`. Player-facing addon changes for the next upload: `CHANGELOG.md`.

## Current state (2026-10-27)
- Main addon `addons/ForeverChronicle` 0.15.0, packaged on 2026-10-20 (`dist/curseforge/JourneyForever-0.15.0.zip`,
  changelog section "0.15.0" in `CHANGELOG.md`, description in `docs/CurseForge.md`), not uploaded yet (last
  CurseForge upload 0.14.1). The friends companion `ForeverChronicle_Share` was removed on 2026-10-27; the
  desktop app installs a newer main addon from the repository at start (WoW closed) and deletes the companion folder.
- Addon window tabs: Übersicht, Chronik (screenshots shown with their entries), Karte, Berufe, Einstellungen,
  Diagnose. Slash commands `/fj` and `/fjshot`.
- Desktop app: starts on the home screen (Start). Tabs at the bottom: Start, Übersicht, Chronik, Galerie, Karte
  (with the cinematic mode), Berufe; the gear menu next to them opens Import, Einstellungen (sound), Diagnose.
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
4. Short in-game checks for the user: open each profession window once and look at the Berufe tab.
5. Death cause (2026-10-16): the addon reads `C_DeathRecap.GetRecapEvents()` (no ID = newest recap) at
   `PLAYER_DEAD`, retrying for 5 s, and stores the killing blow (killer, npcID, spell, spellID, environment,
   damage, overkill) in the `player_died` event. Unverified in Forever: whether the recap exists there and is
   readable (not secret). After the next death, check the Chronik entry; if it still says "Gestorben in ...",
   the recap is missing or hidden.
6. Release (2026-11-04), prepared on 2026-10-24: the live client's product flavor and folder were unknown, so the
   desktop app (`wow/paths.py`) and the CASC tools accept any client whose `.build.info` version
   is 1.60 or newer (Classic Era is 1.15) and prefer a live client over the beta (a saved beta folder moves to the
   live client next to it). A folder the user picks counts whatever its flavor. The TOCs list Interface 16001,
   16002, 16003 and 16100. The live client was installed on 2026-10-27: `_forever_\`, flavor `wowf` (now in
   `FOREVER_FLAVORS`), version 1.60.1.70634; at release check its Interface number (1.60.1 suggests 16001). Before
   deleting the beta folder: copy `_classic_beta_\Screenshots` out (30 screenshot records link there; the cloud has
   only 1920 px copies of 23) and run the settings port. `tools/build_world_map.py --openmap` still defaults to
   the beta folder's OpenMap; the other CASC tools find the install as the app does (`--install` to choose,
   `tools/db2.py`).
   Settings port (`tools/port_settings.py`, built 2026-10-24, dry run unless `--apply`, WoW closed, backups in
   `<live>\PortBackup\`): `account` (keybinds, macros, interface settings, Edit Mode, other addons and their
   SavedVariables, Config.wtf without portal/login/cache lines), then log in once with each new character and
   `characters --map OLD=NEW`. Unverified: whether the first login keeps the copied `-cache` files or replaces them
   with the server's (Blizzard syncs bindings/macros/settings); if replaced, `server-sync off`, copy again, log in,
   `server-sync on`. The `synchronize*` CVar names are from retail and unconfirmed in Forever. Edit Mode's own
   export/import is the fallback for the layout. Beta addons whose TOC lacks the live Interface number load as out
   of date.
## Confirmed client facts
- Install: `C:\Program Files (x86)\World of Warcraft\_classic_beta_\` (`WowB.exe`, client 1.60.1). TOC Interface 16001.
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
- F-008: recipe/profession events were added to the chronicle (the spec said snapshots only). The compact recipe
  format and `snapshots` area.

## History

Moved to `docs/History.md` (session notes, newest first; new entries go there).
