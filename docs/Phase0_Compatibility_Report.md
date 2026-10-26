# Phase 0 – API Compatibility Report

**Client:** World of Warcraft: Forever beta, version 1.60.1, build 70374 (Oct 12 2026), TOC Interface **16001**, locale enUS
**Install:** `C:\Program Files (x86)\World of Warcraft\_classic_beta_\` (`WowB.exe`)
**Tested:** 2026-10-14 with ForeverChronicle_Probe v0.1.0, Tauren Hunter level 22 on realm "Classic Beta PvP"
**Raw data:** `probe-results/ForeverChronicle_Probe_SavedVariables_2026-10-14.lua` (at report time)
**Note:** the probe addon was removed after Phase 0. Its code is no longer in the project.

Status legend: **Confirmed** = observed working in game · **Present** = function/event exists but has not been observed yet · **Unsupported** = missing or invalid.

## Summary

| Area | Status | Key finding |
|---|---|---|
| Character identity | Confirmed | Modern GUID `Player-4619-0112A417` (server ID + character ID). |
| Reload vs. login | Confirmed | `PLAYER_ENTERING_WORLD(isInitialLogin, isReloadingUi)` is reliable. |
| SavedVariables | Confirmed | Survived /reload, logout and relog. The client keeps the previous file as `.lua.bak`. |
| Time | Confirmed | `time()` = `GetServerTime()` (0 s difference); `C_Timer` available. |
| Zone tracking | Confirmed | `ZONE_CHANGED_NEW_AREA` fires; 8 times in 20 s during a flight. |
| Taxi detection | Confirmed | `PLAYER_CONTROL_LOST` / `GAINED` at flight start/end; `UnitOnTaxi` present. |
| Loading screens | Confirmed | `LOADING_SCREEN_ENABLED` / `DISABLED` fire. |
| Position (open world) | Confirmed | `C_Map` works; Classic-style uiMapIDs (1454 Orgrimmar, 1413 Barrens, 1414 Kalimdor). |
| Position (instances) | Unsupported | In Ragefire Chasm, `GetBestMapForUnit` and `UnitPosition` return nil → zone-only. |
| Continent placement | Confirmed | `GetMapRectOnMap(zone, continent)` and continent positions work. |
| Screenshots | Confirmed | Works from slash command **and** from timers; `SCREENSHOT_STARTED` → `SUCCEEDED` in 0.3 s; never blocked. |
| Screenshot files | Confirmed | `Screenshots\WoWScrnShot_MMDDYY_HHMMSS.jpg`, exact to the second of the call. |
| Played time | Confirmed | `TIME_PLAYED_MSG(total, level)`; chat suppression by unregistering chat frames: 0 display calls. |
| Quests | Confirmed | `QUEST_TURNED_IN(questID, xp, money)`; titles via `C_QuestLog.GetTitleForQuestID`. |
| Deaths | Confirmed | `PLAYER_DEAD` fires. Note: `PLAYER_ALIVE` also fires at every login. |
| Professions | Confirmed | Mainline `GetProfessions` / `GetProfessionInfo` incl. skill line IDs. Classic-style APIs are absent. |
| Recipes | Confirmed | `GetAllRecipeIDs` (592 for Leatherworking) + `info.learned` → 15 learned. Linked check works. |
| Achievements | Present | System exists: 29 categories, 112 achievements, 6 completed, 0 points. `ACHIEVEMENT_EARNED` is valid but was not observed. |
| Level-up | Present | `PLAYER_LEVEL_UP` valid, not observed. |
| Secret values | Confirmed (open world) | In open-world combat only `UnitHealth` was secret. Boss encounters not tested. |

## Details and implementation notes

### Character (F-001)
- `UnitGUID("player")` = `Player-4619-0112A417`. The GUID contains the server ID, so it is unique across realms → use it as the natural key on its own and keep the realm as information only.
- `UnitName("player")` returns `"Blind", "Bullseye"` while `GetRealmName()` returns `"Classic Beta PvP"`. Store both (`realm` from `GetRealmName`, `name_suffix` from `UnitName`). Re-check on live servers.
  **Update:** the second value is the character's **last name** (Forever characters have one; confirmed by the user). Both apps show the full name "Blind Bullseye".
- `GetAddOnMetadata` is missing → use `C_AddOns.GetAddOnMetadata`.

### Sessions (F-004)
- Observed sequence: login `(true,false)`, dungeon loading screen `(false,false)`, /reload `(false,true)`, relog `(true,false)`.
- `PLAYER_LOGOUT` fires on /reload as well, so it cannot be used on its own to end a session.
- Played time: `RequestTimePlayed()` → `TIME_PLAYED_MSG(74113, 7574)`. Only `ChatFrame1` was registered for the event. Display functions in this client are `ChatFrame_DisplayTimePlayed` and `ChatFrameUtil.DisplayTimePlayed`. Unregistering the event on chat frames during the request suppressed output (0 display calls) and needs no change to Blizzard code.

### Travel and map (F-005)
- uiMapIDs are the familiar Classic IDs, so map artwork files can use them directly (`1454.png` etc.).
- The parent chain is zone (type 3) → continent (type 2) → Azeroth (type 1).
- In dungeons there is no map ID and no position. Record zone-only with `GetRealZoneText()` plus the instance ID (4th return of `UnitPosition`, here 389).
- A flight produced 8 `ZONE_CHANGED_NEW_AREA` events in 20 seconds. This confirms that zone screenshots must be suppressed on taxis and need the dwell time.

### Screenshots (F-003)
- `Screenshot()` works without a hardware event (from `C_Timer`), so event-triggered screenshots are possible.
- The probe's expected names `WoWScrnShot_101426_103333` / `_103336` matched the real files exactly. File matching can use ±2 s tolerance.
- Default format jpeg, quality 3.

### Quests, deaths, achievements (F-006, F-007)
- `QUEST_COMPLETE` fires when the reward dialog opens, before the turn-in. Only `QUEST_TURNED_IN` counts as completion.
- `C_QuestLog.GetAllCompletedQuestIDs()` returned 142 IDs (no dates). Not needed for MVP; it could later list "completed before tracking".
- Achievements exist in Forever. Keep F-003/achievement tracking and log the first real `ACHIEVEMENT_EARNED` as confirmation.

### Professions and recipes (F-008)
- `GetProfessions()` returned 7 slots (`6, 7, 5, nil, 8, nil, nil`). Iterate all slots and skip nil.
- `GetProfessionInfo` returns name, icon, skill, max, …, skillLine (165 Leatherworking, 182 Herbalism, 129 First Aid, 185 Cooking).
- Recipe info contains `recipeID`, `name`, `categoryID`, `learned`, `skillLineAbilityID`. Category names will need `C_TradeSkillUI.GetCategoryInfo` (verify during implementation).
- The search-box filter test was not done. This is low risk because learned recipes are taken from the unfiltered list.

### SavedVariables (F-013, F-014)
- Path: `WTF\Account\<account folder>\SavedVariables\<AddonName>.lua`. The account folder name is numeric with a suffix (here `131324136#1`).
- The client keeps the previous version as `<AddonName>.lua.bak`. The importer can fall back to it if the main file is truncated.
- File format: `Name = { ["key"] = value, ... }` with plain array items and escaped strings. This matches the planned literal-only parser.

## Not tested (no action needed now)
The real addon will record and report these the first time they happen:
- `ACHIEVEMENT_EARNED` and `PLAYER_LEVEL_UP` firing
- secret values during boss encounters
- recipe capture with an active search filter
- visual confirmation that no played-time line appeared (the instrumentation showed 0 display calls)
