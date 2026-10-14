# Dungeon maps: exploration

Status: exploring (2026-10-15). The addon now probes every dungeon passively; the next dungeon visit answers the
open questions, then one of the options below gets built.

## What we know
- **No position inside dungeons (Phase 0, Ragefire Chasm):** `C_Map.GetBestMapForUnit("player")` and the
  coordinates of `UnitPosition("player")` are nil. Only the instance ID (4th value of `UnitPosition`) and the
  zone text are available. Routes therefore stop at the dungeon entrance, and dungeon moments are shown there.
- **The client has dungeon data:** the community addon "ForeverDungeonJournal" uses the client's encounter
  journal (`EJ_GetInstanceByIndex`, `EJ_GetEncounterInfoByIndex`, `EJ_SelectInstance`) and dungeon map art
  (`C_Map.GetMapArtLayerTextures`), and it shows boss pins on dungeon maps. It also ships its own boss and dungeon
  data, so the client's journal may not cover everything.
- `EJ_GetInstanceInfo(journalInstanceID)` returns the dungeon's map ID (7th value) and instance ID (10th).

## Probe results so far
- **Ruins of Lordaeron (instance 2999, a new Forever dungeon), 2026-10-15:** no map at all (no
  `GetBestMapForUnit`, no journal entry, no dungeon map of that name), no position, `UnitPosition` and
  `GetPlayerFacing` restricted, `GetUnitSpeed` available, no dungeon finder data. No boss fight was seen.
  Consequences: no path and no map art there; the last boss is unknown to the client, so "dungeon completed"
  needs a built-in last-boss entry for this dungeon (learn its encounter ID from a full run).
- **Ragefire Chasm (Phase 0):** no map ID, no position. Map art and journal not probed yet.
- Still open: a Classic dungeon with the probe (map art, journal, explicit-map position), the encounter IDs of a
  full run, and whether sub-area names exist inside dungeons (`areas`, added 2026-10-15).

## What the probe records (`FC.db.dungeonProbe[instanceID]`, `/fj dungeon`)
Once per dungeon and session, a few seconds after entering:

| Field | Question |
|---|---|
| `bestMap` | Does `GetBestMapForUnit` return a dungeon map in this client (it did not in Ragefire Chasm)? |
| `map`, `mapSource` | The dungeon's map ID, from the journal or found by name among Azeroth's dungeon maps. |
| `position`, `positionAfter30`, `positionAfter120` | Does `GetPlayerMapPosition(dungeonMap, "player")` give a position when the map ID is passed explicitly, right away and after moving? |
| `artTiles`, `floors` | Is there map art, and how many floors (map group members)? |
| `bossPins` | Boss positions on the dungeon map (`C_EncounterJournal.GetEncountersOnMap`). |
| `journalID`, `journalBosses`, `lastBoss`, `lastEncounterID` | The journal entry and its last boss (used for "dungeon completed"). |
| `finderBosses` | The dungeon finder's boss count (killed/total), the fallback for the last boss. |
| `unitPosition`, `facing` | Are `UnitPosition` and `GetPlayerFacing` restricted here as well? |
| `encounters` | Encounter starts and kills with their IDs, to check the IDs match the journal. |
| `areas` | Sub-area names passed inside (with time): a coarse "where in the dungeon" without a position. |

## Options, depending on the answers
1. **A real path (only if `position` is set).** If the position works when the dungeon map is passed explicitly,
   the Positions module records dungeon samples like outdoor ones (map ID = dungeon map, floors as separate
   maps). The map page then shows the dungeon like a zone: painted path, trail, colours, timeline. This is the
   best outcome; it needs no new drawing code.
2. **A "dungeon run" view (if there is no position, but map art and boss pins).** The dungeon map with the boss
   pins, numbered in the order you killed them, with the time of each kill, the time between bosses, deaths
   (count; no position) and the screenshots taken there. Lines between the bosses would only show the order and
   would be drawn clearly different (thin, dotted, numbered), because the real path inside is unknown. Runs are
   told apart by the time between kills and by entering the dungeon again.
3. **Not pursued: estimating a path** from facing and running speed (dead reckoning). Facing is most likely
   restricted inside instances too, the estimate drifts within seconds and walks through walls, and it would
   draw a route that was never recorded.

My recommendation: build option 2 regardless (it works without a position and makes boss kills visible), and
add option 1 on top if the probe finds a position.

## Dungeon completed (built)
- Every won boss encounter (`ENCOUNTER_END` with success, or `BOSS_KILL`) is a `boss_killed` event with the boss,
  the dungeon, whether it was this character's first kill of that boss, and whether it was the last boss.
- The last boss is the last encounter in the client's journal for that dungeon; without a journal entry, the
  dungeon finder's boss list (all bosses dead) decides. If neither is available, the last boss is unknown and no
  "dungeon completed" is recorded; the probe shows this.
- The first kill of a dungeon's last boss per character is a `dungeon_completed` event with its own screenshot
  trigger "On dungeon completion" (on by default, like level-ups it may skip the cooldown).
