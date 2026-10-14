const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, LevelFormat,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, Footer, PageNumber,
} = require('docx');

const OUT = process.argv[2];
const CONTENT_W = 9026; // A4 with 1" margins

// ---------- inline markup: **bold**, `code` ----------
function runs(text, base = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    if (t.startsWith('**')) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: t.slice(1, -1), font: 'Consolas', size: 19, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

const body = [];
const H1 = t => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: runs(t) }));
const H2 = t => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: runs(t) }));
const H3 = t => body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: runs(t) }));
const P = t => body.push(new Paragraph({ spacing: { after: 120 }, children: runs(t) }));
const NOTE = t => body.push(new Paragraph({
  spacing: { after: 120 }, indent: { left: 284 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: '2E75B6', space: 8 } },
  children: runs(t, { italics: false }),
}));
const UL = (items, level = 0) => items.forEach(i => {
  if (Array.isArray(i)) return UL(i, level + 1);
  body.push(new Paragraph({ numbering: { reference: 'bullets', level }, spacing: { after: 40 }, children: runs(i) }));
});
let olCount = 0;
const OL = items => {
  const ref = `ol${olCount++}`;
  numberingConfigs.push({
    reference: ref,
    levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 567, hanging: 340 } } } }],
  });
  items.forEach(i => body.push(new Paragraph({ numbering: { reference: ref, level: 0 }, spacing: { after: 40 }, children: runs(i) })));
};
const AC = items => { body.push(new Paragraph({ spacing: { before: 120, after: 60 }, children: [new TextRun({ text: 'Acceptance criteria', bold: true })] })); UL(items); };
const HR = () => body.push(new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'A6A6A6', space: 1 } }, spacing: { after: 200 } }));

const border = { style: BorderStyle.SINGLE, size: 4, color: 'BFBFBF' };
const borders = { top: border, bottom: border, left: border, right: border };
function TABLE(widths, header, rows) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (t, w, head) => new TableCell({
    borders, width: { size: w, type: WidthType.DXA },
    shading: head ? { fill: 'DEEAF6', type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: runs(t, head ? { bold: true } : {}) })],
  });
  body.push(new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => cell(c, widths[i], false)) })),
    ],
  }));
  body.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
}
const ENTITY = (name, desc, fields) => {
  H3(name);
  if (desc) P(desc);
  TABLE([2600, 1700, 4726], ['Field', 'Type', 'Notes'], fields);
};

const numberingConfigs = [{
  reference: 'bullets',
  levels: [0, 1, 2].map(l => ({
    level: l, format: LevelFormat.BULLET, text: ['•', '–', '◦'][l], alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 567 + l * 397, hanging: 284 } } },
  })),
}];

// =====================================================================
// CONTENT
// =====================================================================
H1('Feature Specification: Forever Chronicle');
body.push(new Paragraph({ spacing: { after: 40 }, children: runs('**Version:** 1.3 (revision of 1.2, Phase 0 results)') }));
body.push(new Paragraph({ spacing: { after: 40 }, children: runs('**Status:** Product specification for AI-assisted implementation') }));
body.push(new Paragraph({ spacing: { after: 40 }, children: runs('**Target:** World of Warcraft: Forever (Blizzard Classic+, currently in beta) client/addon environment') }));
body.push(new Paragraph({ spacing: { after: 40 }, children: runs('**Primary language:** German UI, English identifiers in code') }));
body.push(new Paragraph({ spacing: { after: 40 }, children: runs('**Scope:** MVP (first usable release)') }));
body.push(new Paragraph({ spacing: { after: 40 }, children: runs('**Distribution:** private use only; not published') }));
HR();

// ---------------------------------------------------------------------
H2('0. Change history');
H3('Changes in v1.3');
P('Version 1.3 incorporates the Phase 0 results (probe run on 2026-10-14, client 1.60.1 build 70374). Details: docs/Phase0_Compatibility_Report.md.');
TABLE([800, 6126, 2100], ['ID', 'Change', 'Sections'], [
  ['E-01', 'Client facts confirmed: version 1.60.x, TOC Interface 16001, beta install folder `_classic_beta_`. All required Mainline APIs are present; Classic-style APIs are absent.', '3'],
  ['E-02', 'Player GUID includes the server ID and is used as the natural key on its own; realm is stored as information.', 'F-001, 6'],
  ['E-03', 'Screenshots confirmed from timers (no hardware event needed); confirmation via SCREENSHOT_SUCCEEDED; exact file naming confirmed.', 'F-003'],
  ['E-04', 'Played-time chat suppression changed to unregistering TIME_PLAYED_MSG on chat frames during the request (confirmed working, no Blizzard code replaced).', 'F-004'],
  ['E-05', 'Inside instances no map ID or position is available; zone-only records include the instance ID.', 'F-005'],
  ['E-06', 'Quest completion uses QUEST_TURNED_IN only. Achievements exist in Forever and stay in scope.', 'F-006, F-003'],
  ['E-07', 'SavedVariables importer may fall back to the client\u2019s .lua.bak copy.', 'F-014'],
  ['E-08', 'Open questions Q6\u2013Q8 resolved.', '12'],
]);
H3('Changes in v1.2');
P('Version 1.2 incorporates the product owner’s answers to the v1.1 open questions and research on the Forever platform.');
TABLE([800, 6126, 2100], ['ID', 'Change', 'Sections'], [
  ['D-01', 'Platform identified: Forever is Blizzard’s official Classic+ game. It uses the modern Mainline (retail 12.x-era) UI engine and addon API and follows the Midnight addon rules (secret values). Classic-era APIs and addons do not apply. Mainline APIs are the starting point; each one must still be verified in the Forever client, because Classic+ content may not use every Mainline system.', '3, F-012, 10'],
  ['D-02', 'Map artwork is provided by the product owner. The asset format is defined, and the addon records map geometry so routes can also be drawn on continent maps. Legal-source wording removed (private use).', '2, F-005, 6'],
  ['D-03', 'Cooldown bypass for level-up and achievement screenshots confirmed.', 'F-003'],
  ['D-04', 'Retention caps confirmed as configurable defaults; meaning clarified.', 'F-013'],
  ['D-05', 'Historical zone baseline removed. A first visit means the first visit since tracking began; the zone the character stands in at first run never triggers a screenshot.', 'F-003, F-005, 6'],
  ['D-06', 'Played-time approach defined: automatic request with flag-guarded chat suppression; falls back to manual `/fc played` if suppression cannot be verified.', 'F-004'],
  ['D-07', 'Recipe capture uses the unfiltered Mainline recipe API, so UI filters and collapsed headers no longer affect completeness. Professions of other players or NPCs viewed in the profession window are never recorded.', 'F-008'],
]);
H3('Changes in v1.1');
P('Version 1.1 resolved gaps found in a technical review of v1.0. The most important change is that the data path from the addon to the desktop application is defined explicitly (C-01).');
TABLE([800, 6126, 2100], ['ID', 'Change', 'Sections'], [
  ['C-01', 'SavedVariables is defined as the only addon-to-desktop transport. Addons cannot write files; JSONL is the desktop export/backup format only. Added a safe, non-executing SavedVariables parser.', '3, 4.3, F-011, F-014'],
  ['C-02', 'Added a SavedVariables size budget and retention policy (bounded ring buffers, compact position storage, stationary de-duplication, gap detection).', 'F-013, F-005, 6'],
  ['C-03', 'Documented that data since the last /reload or logout is lost on a client crash. Added an in-game save command and crash-marked sessions.', 'F-004, F-009, 7.1'],
  ['C-04', 'Character identity uses the player GUID (scoped by realm) as the natural key; local UUID stays the primary key. Renames and addon reinstalls no longer create duplicate characters.', 'F-001, 6'],
  ['C-05', 'Recipe capture is only performed while the profession window is open. Skill levels may be refreshed at login. UI filters and collapsed headers affect completeness and are recorded.', 'F-008'],
  ['C-06', 'Screenshot timing reworked: burst coalescing, per-type capture delay, maximum request age, zone dwell time, no capture on taxi or loading screens, cooldown bypass for level-up and achievement.', 'F-003'],
  ['C-07', 'Zone baseline on first install so existing characters do not trigger a "first visit" screenshot for every known zone.', 'F-003, F-005'],
  ['C-08', 'Screenshot confirmation via client success/failure events where available; desktop matches screenshot files to requests by the documented file naming pattern.', 'F-003, F-010, 6'],
  ['C-09', 'Server-reported played time (/played) recorded as authoritative observed value alongside estimated session time.', 'F-004, 6'],
  ['C-10', 'Locale handling: IDs are keys everywhere; names are stored together with the client locale.', '3, 6, F-008'],
  ['C-11', 'Data model extended: GUID, locale, snapshot links, screenshot-to-event links, zone baseline, import runs, session end reasons.', '6'],
  ['C-12', 'Time sources defined (wall clock, server time, monotonic time).', '3'],
  ['C-13', 'General /fc slash command for status, diagnostics, save, refresh and storage.', 'F-009'],
  ['C-14', 'Automated unit tests for pure logic outside the client (Lua and Python).', '9'],
  ['C-15', 'Implementation order revised: the end-to-end data pipeline is built and proven before the screenshot queue.', '10'],
  ['C-16', 'Clarified that the user’s own multiple WoW accounts on the same installation may be imported after explicit selection.', '2, F-014'],
  ['C-17', 'Added open questions that must be answered during Phase 0.', '12'],
]);

// ---------------------------------------------------------------------
H2('1. Product vision');
P('Forever Chronicle is a personal adventure history for WoW Forever. It records character progression and important events, visualizes where a character travelled over time, stores milestone screenshots, and shows professions and known recipes. A desktop application provides a searchable timeline and a navigable map. Users may optionally share selected character histories with friends who also use Forever Chronicle.');
P('The MVP must prioritize data correctness, compatibility with the actual WoW Forever client build, and a modular architecture that can be expanded later.');

// ---------------------------------------------------------------------
H2('2. Explicit MVP scope');
H3('Included');
UL([
  'Character identity and local character list.',
  'Automatic screenshots for level-ups, achievements, and first visits to zones, with user-configurable rules.',
  'A priority queue for screenshot requests with burst coalescing, a 30-second default cooldown for lower-priority requests, and stale-request handling.',
  'Session and playtime tracking, including server-reported played time where available.',
  'Zone visit history and position sampling where the client API supports it.',
  'Map view with user-provided map artwork, a time slider and route playback.',
  'Quest completion history.',
  'Death history.',
  'Profession overview: profession name and current skill/level.',
  'Recipe overview: recipes known by the character, grouped by profession.',
  'Desktop application for browsing the character timeline, map, screenshots, professions, and recipes.',
  'Import of the addon’s SavedVariables into the desktop database.',
  'Local JSONL export/import and backup.',
  'Bounded addon storage with retention policy and gap detection.',
  'Data model designed for optional future friend/account synchronization.',
]);
H3('Explicitly excluded from MVP');
UL([
  'Item/inventory/loot tracking.',
  'Crafting history (which recipes were crafted and when).',
  'Recipe acquisition source history.',
  'Profession progression timeline beyond current profession and current skill level, unless simple event capture is trivial and verified.',
  'Cloud sync, friend sharing, accounts, invitations, or public profiles. Design data structures so these can be added later, but do not implement them in MVP.',
  'Reading any files outside the user’s own selected WoW installation, or game data of other people. Multiple WoW accounts of the same user inside the selected installation are allowed, but only after the user explicitly selects them (see F-014).',
  'Writing to SavedVariables files from the desktop application.',
  'Any unsupported or undocumented game API assumptions.',
]);

// ---------------------------------------------------------------------
H2('3. Target platforms and technical assumptions');
UL([
  '**Game platform:** World of Warcraft: Forever is Blizzard’s official Classic+ game (beta since 2026-09-17, release planned for 2026-11-04). It runs on the modern Mainline UI engine and addon API and follows the Midnight addon rules. Classic-era APIs and addons do not apply.',
  '**Client (Phase 0):** version 1.60.1 (build 70374 at the time of testing), product `wow_classic_beta`, executable `WowB.exe`, installed in `World of Warcraft\\_classic_beta_\\`.',
  'In-game addon: Lua 5.1 (WoW dialect) and a .toc file with `## Interface: 16001` (confirmed in Phase 0; re-check after client updates). Use `C_AddOns.GetAddOnMetadata`; the old global `GetAddOnMetadata` does not exist.',
  'Desktop application: Python 3 with PySide6.',
  'Local database: SQLite.',
  '**Addon to desktop transport:** the addon’s SavedVariables file is the only transport. WoW addons cannot write arbitrary files. The client writes SavedVariables only on logout, /reload, and clean client exit. The desktop application reads these files; it never writes them in MVP.',
  '**Desktop export format:** versioned JSON Lines (.jsonl) is the canonical export, import and backup format of the desktop application (see F-011).',
  'The desktop application must not require internet access for core features.',
  'Before implementation, inspect the actual Forever client build and verify its addon API, event names, map APIs, screenshot behavior, and SavedVariables behavior.',
  'Mainline APIs are the starting point, but each function and event must be verified in the Forever client. A Mainline function may exist while the underlying game system (for example achievements) is not part of Classic+ content. Keep “function exists” separate from “feature confirmed working”.',
  'If a feature cannot be implemented using a verified API, report it as unsupported and degrade gracefully. Never fabricate data.',
]);
H3('Verified API family (Phase 0)');
P('All APIs and events below exist in the Forever client. Unless noted in the feature sections, each one was also observed working. Classic-style profession APIs (`GetNumSkillLines`, `GetNumTradeSkills`, `GetNumCrafts`) and the events `CRAFT_SHOW` / `LEARNED_SPELL_IN_TAB` do not exist.');
TABLE([2300, 6726], ['Area', 'APIs and events'], [
  ['Character', '`UnitGUID("player")`, `UnitName`, `GetRealmName`, `UnitClass`, `UnitRace`, `UnitLevel`, `UnitFactionGroup`, `GetLocale`, `GetBuildInfo`'],
  ['Session', '`PLAYER_LOGIN`, `PLAYER_ENTERING_WORLD` (isInitialLogin, isReloadingUi), `PLAYER_LOGOUT`, `RequestTimePlayed`, `TIME_PLAYED_MSG`'],
  ['Time', '`time()`, `GetServerTime()`, `GetTime()`, `C_Timer`'],
  ['Travel / map', '`ZONE_CHANGED_NEW_AREA`, `ZONE_CHANGED`, `PLAYER_CONTROL_LOST` / `PLAYER_CONTROL_GAINED`, `C_Map.GetBestMapForUnit`, `C_Map.GetPlayerMapPosition`, `C_Map.GetMapInfo`, `C_Map.GetMapRectOnMap`, `UnitOnTaxi`, `IsInInstance`, `LOADING_SCREEN_ENABLED` / `LOADING_SCREEN_DISABLED`'],
  ['Screenshots', '`Screenshot()`, `SCREENSHOT_STARTED`, `SCREENSHOT_SUCCEEDED`, `SCREENSHOT_FAILED`'],
  ['Progress', '`PLAYER_LEVEL_UP` (not yet observed), `ACHIEVEMENT_EARNED` (not yet observed), `QUEST_TURNED_IN`, `C_QuestLog.GetTitleForQuestID`, `PLAYER_DEAD`'],
  ['Professions', '`GetProfessions`, `GetProfessionInfo`, `SKILL_LINES_CHANGED`, `TRADE_SKILL_SHOW`, `TRADE_SKILL_LIST_UPDATE`, `TRADE_SKILL_CLOSE`, `C_TradeSkillUI.GetAllRecipeIDs`, `C_TradeSkillUI.GetRecipeInfo`, `C_TradeSkillUI.GetBaseProfessionInfo` / `GetProfessionInfoBySkillLineID`, `C_TradeSkillUI.IsTradeSkillLinked`, `IsTradeSkillGuild`, `IsNPCCrafting`'],
  ['Combat state', '`InCombatLockdown`, `PLAYER_REGEN_ENABLED`, `issecretvalue`'],
]);
H3('Midnight addon rules (secret values)');
UL([
  'Under the Midnight rules, some combat-related APIs return “secret values” to addon code, mainly during combat, boss encounters and similar content. Comparing or testing a secret value in addon code raises a Lua error.',
  'Forever Chronicle does not need combat data. It must not read the combat log.',
  'Phase 0: in open-world combat only `UnitHealth` returned a secret value; GUIDs, names, levels, zone and map positions stayed plain. Boss encounters were not tested, so the guards stay mandatory.',
  'Values from APIs that might be affected are checked with `issecretvalue` (where available) before any comparison. Secret or unavailable values are stored as unknown.',
  'Non-urgent work (profession snapshots, storage maintenance) is deferred until the player is out of combat.',
]);
H3('Time sources');
UL([
  '`occurred_at`: wall-clock Unix epoch seconds from `time()`, stored as UTC. The desktop app converts to the local time zone for display only.',
  '`server_time`: from `GetServerTime()` where available; stored in addition, never as a replacement.',
  'Durations inside one client run use the monotonic clock (`GetTime()`). Monotonic values are never compared across client restarts.',
]);
H3('Locale');
UL([
  'Zone, quest, profession and recipe names are localized by the client. IDs are the keys wherever the client exposes them.',
  'Every stored name is stored with the client locale (`GetLocale()`) that produced it.',
  'Name-based fallback keys are only valid within one locale.',
]);

// ---------------------------------------------------------------------
H2('4. Architecture');
H3('4.1 In-game addon');
P('Suggested modules:');
UL([
  '`Core.lua`: initialization, config, diagnostics, `/fc` command.',
  '`Events.lua`: event registration and normalization.',
  '`Character.lua`: character identity (GUID, name, realm, locale) and metadata.',
  '`SessionTracker.lua`: login/logout, reload detection, active-time estimates, server played time.',
  '`PositionTracker.lua`: periodic position samples when supported, stationary de-duplication.',
  '`TravelTracker.lua`: zone visits, known zones, map geometry, route events.',
  '`QuestTracker.lua`: quest events when supported.',
  '`DeathTracker.lua`: death events when supported.',
  '`AchievementTracker.lua`: achievement events when supported.',
  '`ProfessionTracker.lua`: current profession names and skill levels.',
  '`RecipeTracker.lua`: known recipes, captured while the profession window is open.',
  '`ScreenshotManager.lua`: screenshot rules, queue, priorities, coalescing, cooldown, confirmation, error handling.',
  '`Storage.lua`: SavedVariables, schema versioning, ring buffers, retention, size accounting.',
  '`UI/`: settings and in-game overview.',
]);
P('The addon collects data and provides lightweight in-game status/settings. Large-scale browsing and map playback belong in the desktop application. Pure logic (queue, coalescing, retention, serialization) must be written in modules without direct WoW API calls so it can be unit-tested outside the client.');

H3('4.2 Desktop application');
P('Suggested modules:');
UL([
  '`app.py`: application entry point.',
  '`database.py`: SQLite schema, migrations, transactions.',
  '`sv_locator.py`: locates WoW installation, account folders and the addon’s SavedVariables files.',
  '`sv_parser.py`: safe, non-executing parser for SavedVariables Lua table literals.',
  '`sv_importer.py`: validates parsed records and imports them idempotently.',
  '`importer.py` / `exporter.py`: validated JSONL data interchange.',
  '`character_list.py`: character selection.',
  '`timeline.py`: event timeline.',
  '`map_assets.py`: loads user-provided map artwork and map geometry.',
  '`world_map.py`: zone/continent map and position display.',
  '`route_player.py`: time slider, play/pause, speed controls.',
  '`screenshot_gallery.py`: browse linked screenshots, match files to requests.',
  '`professions.py`: profession overview per character.',
  '`recipe_book.py`: known recipes, search, profession filters.',
  '`diagnostics.py`: import errors, gaps, unsupported fields, data health.',
]);

H3('4.3 Data pipeline');
OL([
  'The addon records normalized records into bounded in-memory tables that are declared as SavedVariables.',
  'The client writes the SavedVariables file on logout, /reload or clean exit. Data recorded since the last write is lost if the client crashes.',
  'The desktop application detects a changed SavedVariables file (modification time and size), waits until the file is stable, and copies it to a temporary location before reading.',
  'The copy is parsed by `sv_parser.py`. The parser accepts only Lua table literals (tables, strings, numbers, booleans, nil) and never executes code. It enforces a file size limit and reports a truncated or malformed file without changing existing database contents.',
  'Parsed records are validated and imported in one transaction per file. Duplicate record IDs are skipped. The import result is stored as an `ImportRun`.',
  'Because the addon keeps bounded ring buffers, the importer checks whether the oldest record in the file is newer than the newest previously imported record for that character and stream. If so, it records a data gap and shows it in the UI.',
]);

H3('4.4 Optional future sync service');
P('Not part of MVP. Keep each character and event uniquely identifiable so a future authenticated HTTPS service can sync explicitly shared records. Never store game account passwords or Blizzard credentials.');

// ---------------------------------------------------------------------
H2('5. Feature requirements');

H3('F-001: Character identity');
UL([
  'Identify the current character using the fields actually exposed by the client: player GUID (`UnitGUID("player")`), character name, realm, and client locale where available.',
  '**Natural key:** player GUID. Forever uses the modern format `Player-<serverID>-<characterID>` (for example `Player-4619-0112A417`), which is unique across realms. Realm (`GetRealmName`) is stored as information only.',
  '`UnitName("player")` may return a second value that differs from `GetRealmName()` (beta: `"Bullseye"` vs. `"Classic Beta PvP"`). Store it separately as `name_suffix`; never use it as part of the key.',
  'If no GUID is available, fall back to realm + name and mark the identity quality as `name_based`.',
  'Do not use character name alone as a globally unique identifier.',
  'Assign a locally generated stable UUID to each character record as primary key. The desktop app maps incoming records to an existing character by natural key before creating a new one.',
  'When the same GUID appears with a new name, update the name and keep the old name in the character’s name history.',
  'Store client build, client locale, and schema version for diagnostics.',
  'Support multiple characters in one local database.',
]);
AC([
  'Characters with the same name but different realms do not collide.',
  'Reinstalling the addon or deleting its SavedVariables does not create a second record for the same character when a GUID is available.',
  'A renamed character keeps its history.',
  'A missing realm or other unavailable field is stored as unknown rather than guessed.',
]);

H3('F-002: Event log');
UL([
  'Normalize supported game events into records with a unique event ID, character ID, event type, timestamp, source, and payload.',
  'Event IDs are generated in the addon from wall-clock time, a per-session counter and a random component, so they stay unique across reloads.',
  'Record schema version.',
  'Use transactions and validate imported records.',
  'Detect duplicate event IDs on import.',
  'Keep raw source values when practical for debugging.',
]);
P('Event types: `level_up`, `achievement_earned`, `zone_entered`, `zone_left`, `quest_completed`, `player_died`, `session_started`, `session_ended`, `played_time_reported`, `profession_snapshot`, `recipe_snapshot`, `screenshot_result`, `data_gap`. Position samples are stored separately (see F-005).');
AC([
  'Invalid records do not crash the addon or desktop app.',
  'Duplicate imports do not create duplicate timeline entries.',
  'Unknown future event types can be preserved without crashing.',
]);

H3('F-003: Automatic screenshots');
P('**Default configuration:**');
TABLE([2400, 1300, 1700, 1700, 1926], ['Trigger', 'Enabled', 'Capture delay', 'Max age', 'Cooldown applies'], [
  ['Manual / test', 'always', '0 s', '30 s', 'no'],
  ['Level-up', 'yes', '1.0 s', '15 s', 'no (bypass)'],
  ['Achievement earned', 'yes', '1.0 s', '15 s', 'no (bypass)'],
  ['First visit to zone', 'yes', 'after dwell (5 s)', '60 s', 'yes'],
  ['Quest completion', 'no', '0.5 s', '60 s', 'yes'],
  ['Player death', 'no', '0.5 s', '30 s', 'yes'],
]);
UL([
  'Cooldown: 30 seconds (applies only to triggers marked "yes").',
  'Minimum gap between any two screenshots: 2 seconds (applies to all triggers).',
  'Coalescing window: 2 seconds.',
  'Queue capacity: configurable, default 50.',
]);
P('**Priority order (high to low):** 1. Manual test / user-requested screenshot. 2. Level-up. 3. Achievement. 4. First visit to zone. 5. Quest completion. 6. Death.');
P('**Rules:**');
UL([
  'Requests are queued and processed by priority; equal-priority requests preserve FIFO order.',
  '**Coalescing:** requests created within the coalescing window produce one screenshot. The screenshot is linked to all coalesced events and uses the highest priority among them. Example: a level-up and a level achievement fired together produce one screenshot linked to both events.',
  '**Duplicate coalescing:** duplicate queued requests with the same event type and event identity are merged.',
  '**Capture delay:** a request becomes eligible only after its capture delay, so that on-screen effects (for example the level-up notice) are visible.',
  '**Cooldown:** the cooldown delays eligible lower-priority requests; it never silently discards them. Level-up and achievement requests bypass the cooldown but respect the minimum gap.',
  '**Maximum age:** a request that could not be captured within its maximum age is dropped as `stale`, logged, and counted in diagnostics. A screenshot that no longer shows the moment it belongs to has no value.',
  '**Zone rules:** a first-visit zone request is created when the zone is entered, but only becomes eligible after the player has stayed in that zone for the dwell time. It is dropped as `stale` if the player leaves the zone before capture. No zone screenshots are taken while the player is on a taxi/flight path or during a loading screen; capture waits until the world has finished loading.',
  '**First visit:** a zone counts as visited from the first time it is entered after tracking began (see F-005). The zone the character is in when the addon first runs is recorded as known and never triggers a first-visit screenshot.',
  'Queue capacity is bounded. If full, a higher-priority request may replace the lowest-priority queued request; otherwise reject the new request and log the reason.',
  'The pending queue is held in memory only. Requests pending at logout or /reload are dropped and logged; they are not replayed later.',
  'Screenshot API must be feature-detected at runtime and validated in the actual client build. Wrap API calls in protected error handling.',
  '**Execution context (confirmed):** `Screenshot()` works when called from a timer, without a hardware event, and was never blocked. Event-triggered screenshots are therefore possible.',
  '**Confirmation (confirmed):** `SCREENSHOT_STARTED` and then `SCREENSHOT_SUCCEEDED` arrive about 0.3 s after the call. Use them to set status `confirmed` or `failed`. Without such events the status stays `api_called`. Never claim that a file was written without confirmation.',
  '**File linking:** the addon stores request time and status. The desktop application matches screenshot files in the client’s screenshot folder to requests by the client’s documented file naming pattern `Screenshots\\WoWScrnShot_MMDDYY_HHMMSS.jpg` (confirmed; the time is local wall-clock time of the call, exact to the second) within ±2 seconds. Ambiguous matches are left unlinked and flagged, never guessed.',
  'If screenshots are unsupported or blocked from the event context, show a diagnostic and provide a manual fallback if possible.',
  'Store metadata linking the screenshot to all triggering events.',
]);
AC([
  'Defaults match the table above.',
  'Level-up requests outrank zone requests.',
  'A level-up and achievement fired together produce one screenshot linked to both events.',
  'The cooldown does not delay level-up or achievement screenshots beyond the minimum gap.',
  'No request is lost silently: each request ends as confirmed, api_called, failed, stale, rejected or dropped_on_logout, and the outcome is logged.',
  'A zone left before its dwell time has passed produces no screenshot.',
  'No zone screenshot is taken while on a taxi or during a loading screen.',
  'Unsupported screenshot API is reported clearly.',
  'Repeated events do not create an infinite retry loop.',
]);
P('**Slash commands:** `/fcshot status`, `/fcshot api`, `/fcshot test`, `/fcshot on` / `/fcshot off`, `/fcshot level on|off`, `/fcshot achievement on|off`, `/fcshot zone on|off`, `/fcshot quest on|off`, `/fcshot death on|off`, `/fcshot cooldown <seconds>`, `/fcshot dwell <seconds>`, `/fcshot bypass on|off` (cooldown bypass for level-up and achievement).');

H3('F-004: Session and playtime tracking');
UL([
  'Record login and logout/session transitions when supported.',
  'Distinguish a /reload from a real logout using the `isInitialLogin` / `isReloadingUi` arguments of `PLAYER_ENTERING_WORLD` (confirmed: login `true,false`; reload `false,true`; loading screen `false,false`). `PLAYER_LOGOUT` also fires before a /reload, so it never ends a session on its own. A reload continues the current session and increments its reload count.',
  'Estimate active session time using monotonic time where available.',
  'Persist a session start marker and a heartbeat (last known active time). The heartbeat is written to SavedVariables whenever the client saves.',
  '**Crash handling:** on login, a previous session without an end marker is closed as `incomplete`, with its end time set to the last persisted heartbeat. Data recorded after the last SavedVariables write is lost. This limitation must be shown in the documentation and in the UI.',
  '**Server played time:** request the server’s played time once per login with `RequestTimePlayed()` and read the answer from `TIME_PLAYED_MSG`. Store total and current-level played time as an observed value.',
  '**Chat suppression (confirmed in Phase 0):** the client prints the played time through the chat frames that are registered for `TIME_PLAYED_MSG`. Immediately before its own request, the addon unregisters that event on every chat frame that has it registered. It re-registers them shortly after `TIME_PLAYED_MSG` has arrived, or after 10 seconds at the latest. No Blizzard function is replaced or wrapped, so no taint is caused. A manual `/played` by the user prints normally.',
  'If no chat frame is registered for the event, or the request fails, the automatic request is skipped and played time is recorded only when the user types `/played` or `/fc played`.',
  'Never send more than one automatic request per login.',
  'Distinguish observed time from estimates.',
  'Avoid claiming exact AFK-adjusted time unless AFK detection is reliable and enabled.',
]);
AC([
  'Sessions are not double-counted after reloads.',
  'An unclean shutdown is marked as estimated/incomplete.',
  'The UI labels estimated values and shows server played time as the authoritative total when available.',
]);

H3('F-005: Travel history and navigable map');
UL([
  'Record zone entry and exit transitions where available.',
  '**Known zones:** the addon keeps a per-character set of zones entered since tracking began. A zone not in the set is a first visit. The zone the character is in when the addon first runs is added without triggering a screenshot. No attempt is made to reconstruct visits from before installation; the timeline and map show history from the start of tracking.',
  'Sample character position periodically only when the client API exposes map ID and coordinates.',
  'Sampling interval is configurable; default 10 seconds.',
  '**Stationary de-duplication:** if the position has not changed by more than a small threshold (default 0.2% of map width) on the same map, do not store a new sample; extend the `last_seen_at` of the previous sample instead. This records real presence without inventing data.',
  'Store map/zone ID, zone name with locale, X/Y coordinates (normalized 0..1, rounded to 4 decimals), timestamp, and data-quality/source metadata. Mark samples taken on a taxi.',
  'Inside instances `C_Map.GetBestMapForUnit` and `UnitPosition` return no position (confirmed in a dungeon). Record zone-only presence with quality `zone_only`, the zone name and the instance ID (4th return value of `UnitPosition`).',
  'Forever uses the Classic uiMapIDs (for example 1454 Orgrimmar, 1413 The Barrens, 1414 Kalimdor). The parent chain is zone → continent → Azeroth.',
  'A flight path produced 8 `ZONE_CHANGED_NEW_AREA` events within 20 seconds. Taxi state comes from `UnitOnTaxi` and `PLAYER_CONTROL_LOST` / `PLAYER_CONTROL_GAINED`.',
  'Record key events on the route (level-up, quest completion, death, achievement) with their timestamps and location when available.',
]);
P('**Desktop map supports:**');
UL([
  'Character selector.',
  'Date/session filter.',
  'Time slider.',
  'Play/pause route replay.',
  'Playback speeds: 1x, 2x, 4x, 10x.',
  'Current-time marker and event markers.',
  'Toggle route trail on/off.',
  'Display zone-only events when exact coordinates are unavailable.',
  'Display known data gaps (from crashes or retention overflow).',
]);
UL([
  'Never invent interpolated coordinates. If samples are sparse, show a segmented route and clearly mark gaps.',
]);
P('**Map artwork and geometry:**');
UL([
  'Map artwork is provided by the product owner for private use and is not distributed with the application.',
  'Artwork is placed in a map asset folder configured in the desktop app. One image per map, named by its Forever `uiMapID` (for example `1429.png`; PNG, JPG and WebP accepted). Optional `maps.json` in the same folder may override the display name or crop per map.',
  'Coordinates from `C_Map.GetPlayerMapPosition` are normalized 0..1 over the full map image: x = 0 is the left edge, y = 0 the top edge. The image is drawn so that this mapping holds; aspect ratio is taken from the image.',
  'For each map the character visits, the addon records map geometry once: `C_Map.GetMapInfo` (name, map type, parent map ID) and `C_Map.GetMapRectOnMap` relative to the parent continent. The desktop app uses this to draw zone routes on continent maps as well as zone maps.',
  'The desktop app lists maps that have position data but no artwork. For those it shows a schematic view (route on a neutral grid with zone name) instead of failing.',
]);
AC([
  'Scrubbing the time slider updates the displayed location to the nearest recorded sample.',
  'Playback follows recorded points in timestamp order.',
  'Missing coordinates do not crash the map.',
  'Map and timeline filters remain synchronized.',
  'Standing still for one hour adds at most one position sample.',
  'The zone the character is in when the addon first runs does not trigger a first-visit screenshot.',
  'A route recorded in a zone appears both on the zone map and, using the recorded geometry, on its continent map.',
  'A map without artwork shows the schematic view and is listed as missing artwork.',
]);

H3('F-006: Quest history');
UL([
  'Capture quest completion from `QUEST_TURNED_IN(questID, xpReward, moneyReward)` (confirmed). `QUEST_COMPLETE` fires when the reward dialog opens and is not a completion.',
  'Read the title with `C_QuestLog.GetTitleForQuestID(questID)` at turn-in time.',
  'Quest screenshots remain disabled by default.',
  'Store quest ID, title with locale if available, timestamp, zone/location if available, and data source.',
  'If only quest ID is available, preserve it and show an unknown title rather than guessing.',
]);

H3('F-007: Death history');
UL([
  'Capture player-death events only if supported by the client build.',
  'Death screenshots remain disabled by default.',
  'Store timestamp, zone/location if available, and cause only if explicitly exposed by the game API.',
  'Do not infer a death cause.',
]);

H3('F-008: Profession overview (simplified MVP)');
P('Goal: show which professions a character has, their current skill level, and the recipes the character knows. No inventory, item tracking, crafting history, or recipe-source tracking.');
P('**Profession snapshots:**');
UL([
  'Show professions per character.',
  'For each profession, display profession name and current skill level/rank using fields available from the actual Forever client.',
  'Profession snapshots are refreshed on login, on skill change events where available, and via a manual refresh command.',
]);
P('**Recipe snapshots:**');
UL([
  'Recipe data can only be read while the profession window is open. Recipes are therefore captured on `TRADE_SKILL_SHOW` / `TRADE_SKILL_LIST_UPDATE` (debounced, at most once per 5 seconds) and via a manual refresh while the window is open. They are not captured at login.',
  'Enumerate with the unfiltered recipe list (`C_TradeSkillUI.GetAllRecipeIDs`) and keep only recipes whose info reports them as learned. Search text, filters and collapsed categories in the profession window then do not affect the result, and the addon never changes the user’s profession UI state. Phase 0 must confirm that this list is unfiltered in Forever.',
  '**Own professions only:** never record a snapshot while the window shows another player’s linked profession, a guild profession or NPC crafting (`IsTradeSkillLinked`, `IsTradeSkillGuild`, `IsNPCCrafting`). The profession shown must match one of the character’s own professions.',
  'Gathering and secondary professions without recipes have no recipe snapshot.',
  'Completeness: `complete` when the unfiltered list was read without errors; `partial` when some recipe info could not be read (for example data not yet loaded); `unavailable` when the API is missing.',
  'A newer complete snapshot replaces the current view; partial snapshots never remove recipes that a complete snapshot showed.',
  'Show known/learned recipes grouped by profession.',
  'Recipe list supports search by name and filtering by profession.',
  'Show recipe ID and recipe name where available; optional fields may include recipe category and required skill level, but only when reliable and exposed.',
  'Show when each snapshot was last refreshed and its completeness status.',
  'If no reliable method exists, mark the recipe list as unavailable rather than presenting an incomplete list as complete.',
]);
P('**Exclusions:** do not record or infer which items were crafted. Do not record ingredient inventories, auction prices, loot, or item ownership. Recipe and profession data are snapshots, not event history, for MVP.');
AC([
  'Each character has a profession overview.',
  'Each profession shows its current skill level if available.',
  'Known recipes appear grouped under the correct profession.',
  'A recipe list is shown as complete only if the snapshot status is `complete`.',
  'Active search or filters in the profession window do not change the captured recipe list.',
  'Viewing another player’s linked profession does not create a snapshot.',
  'Search and profession filters work in the desktop app.',
  'Missing/unsupported recipe data is clearly labelled.',
  'No item/loot/crafting history is implemented.',
]);

H3('F-009: In-game UI and settings');
UL([
  'Provide a compact settings/status UI and slash commands.',
  'Defaults are visible and editable.',
  'Show API capability diagnostics for screenshots, positions, quests, achievements, professions, and recipes.',
  'Show storage usage per stream and a warning when a stream reaches 80% of its retention cap.',
  'Avoid blocking gameplay or doing expensive operations in combat/event handlers.',
]);
P('**General slash commands:**');
UL([
  '`/fc status`: tracker status, current session, last save time.',
  '`/fc api`: API capability report.',
  '`/fc diag on|off`: diagnostic logging.',
  '`/fc storage`: storage usage and retention caps.',
  '`/fc refresh`: refresh profession snapshot (and recipe snapshot if the profession window is open).',
  '`/fc played`: request server played time.',
  '`/fc save`: explains that data is written on reload/logout and offers a /reload to save now.',
]);

H3('F-010: Desktop timeline and gallery');
UL([
  'Browse events chronologically by character.',
  'Filter by event type and date range.',
  'Open screenshots linked to events where files can be matched reliably (see F-003).',
  'One screenshot may appear for several events; one event may have at most one screenshot.',
  'Selecting a timeline event moves the map time slider to the corresponding timestamp.',
  'Missing screenshot files show a non-fatal placeholder.',
  'Data gaps appear in the timeline as their own entries.',
]);

H3('F-011: Local data export/import and backups');
UL([
  'Provide validated JSONL export/import. This format is used for backups and for moving data between computers; it is not produced by the addon.',
  'The first line is a header record containing `record_type: "header"`, schema version, application version and export timestamp. Each following line is one record with a `record_type` field.',
  'Do not include credentials or secrets.',
  'Create an automatic backup of the SQLite database before every schema migration and before every JSONL import merge. Keep the last 5 backups by default.',
  'Import is idempotent and reports invalid rows rather than failing the entire file.',
]);

H3('F-012: Diagnostics and compatibility');
UL([
  'On startup, probe only safe function presence and known capabilities.',
  'Keep an API compatibility report with client build/version and locale.',
  'Validate actual event delivery and screenshot behavior in-game.',
  'Separate “function exists” from “feature confirmed working”.',
  'Unsupported capabilities must be visible to the user.',
  'Add a diagnostic mode with concise logs.',
  'Never assume that a Mainline function implies the matching Classic+ game system exists.',
  'Record secret or blocked values (Midnight rules) as unknown and count them in diagnostics; they must never cause a Lua error.',
]);

H3('F-013: Storage budget and retention (new)');
UL([
  '**Why:** the addon’s data lives in one SavedVariables file that the client loads completely into memory at every login and rewrites at every logout. If it grows without limit, login and logout become slow. The addon therefore keeps only the most recent records; the desktop app holds the complete history.',
  '**What this means for the user:** import into the desktop app before the addon’s storage fills up. With default caps, the position stream holds about 140 hours of active movement (fewer if more frequent sampling is configured); all other streams last much longer. Importing once a week is sufficient for typical play.',
  'Each stream (events, position samples, screenshot records, sessions, snapshots) is a ring buffer with a configurable cap. Defaults: 10,000 events, 50,000 position samples, 2,000 screenshot records, 1,000 sessions, latest 3 snapshots per profession.',
  'Position samples are stored in a compact form (for example one delimited string per sample) instead of one table per sample.',
  'Target: the SavedVariables file stays below 5 MB with default caps.',
  'When a cap is reached, the oldest records are removed and a counter of removed records per stream is kept. The desktop importer uses this to detect and display data gaps.',
  'The addon warns once per session when a stream reaches 80% of its cap and recommends importing into the desktop app.',
  'The desktop application never writes back to SavedVariables in MVP. A future acknowledgement mechanism (desktop marks records as imported while the client is closed) may be added later.',
]);
AC([
  'With default caps, the SavedVariables file stays below the size target in a long-play test.',
  'Overflowing a stream never causes a Lua error.',
  'An overflow between two imports appears as a data gap in the desktop app.',
]);

H3('F-014: SavedVariables import (new)');
UL([
  'The user selects the WoW Forever installation folder. The application lists the account folders that contain Forever Chronicle data and the user chooses which to import.',
  'The parser accepts only Lua table literals and never executes code.',
  'The file is copied before parsing and only imported if its size and modification time are stable.',
  'The client keeps the previous version as `<AddonName>.lua.bak`. If the main file is malformed or truncated, the importer may import the `.bak` copy instead and reports this.',
  'Account folders are named by the client (for example `131324136#1`); show them as found.',
  'A truncated or malformed file is reported and leaves the database unchanged.',
  'Each import is stored as an `ImportRun` with counts of imported, duplicate and invalid records.',
  'Import can be triggered manually and, optionally, automatically when the file changes.',
]);
AC([
  'Importing the same file twice adds no records.',
  'A file with Lua code instead of table literals is rejected without executing anything.',
  'A truncated file does not modify the database.',
]);

// ---------------------------------------------------------------------
H2('6. Data model');
P('Minimum logical entities. "nullable" fields are stored as unknown when the client does not expose them. New or changed fields compared to v1.0 are marked with (new).');

ENTITY('Character', null, [
  ['character_id', 'UUID, PK', 'Locally generated.'],
  ['player_guid (new)', 'text, nullable', 'Natural key; globally unique in Forever.'],
  ['identity_quality (new)', 'text', '`guid` or `name_based`.'],
  ['name', 'text', 'Current name.'],
  ['name_history (new)', 'JSON', 'Previous names with first/last seen times.'],
  ['realm', 'text, nullable', 'Unknown if not exposed.'],
  ['name_suffix (new)', 'text, nullable', 'Second return value of UnitName("player"); information only.'],
  ['wow_account_folder (new)', 'text, nullable', 'Account folder the data was imported from.'],
  ['faction (new)', 'text, nullable', ''],
  ['class_name', 'text, nullable', ''],
  ['race_name', 'text, nullable', ''],
  ['level', 'integer, nullable', ''],
  ['client_build', 'text', ''],
  ['client_locale (new)', 'text, nullable', ''],
  ['created_at', 'timestamp', ''],
  ['last_seen_at', 'timestamp', ''],
]);
ENTITY('Event', null, [
  ['event_id', 'UUID, PK', 'Generated in the addon.'],
  ['character_id', 'FK', ''],
  ['session_id (new)', 'FK, nullable', ''],
  ['event_type', 'text', 'Unknown types are preserved.'],
  ['occurred_at', 'timestamp (UTC)', 'From `time()`.'],
  ['server_time (new)', 'timestamp, nullable', 'From `GetServerTime()`.'],
  ['zone_id / zone_name', 'nullable', ''],
  ['map_id', 'nullable', ''],
  ['x / y', 'real, nullable', 'Normalized 0..1.'],
  ['locale (new)', 'text, nullable', 'Locale of names in the payload.'],
  ['payload_json', 'JSON', 'Includes raw source values where practical.'],
  ['source', 'text', 'API/event that produced the record.'],
  ['schema_version', 'integer', ''],
]);
ENTITY('PositionSample', null, [
  ['sample_id', 'PK', ''],
  ['character_id', 'FK', ''],
  ['session_id (new)', 'FK, nullable', ''],
  ['occurred_at', 'timestamp', 'First time at this position.'],
  ['last_seen_at (new)', 'timestamp, nullable', 'Extended by stationary de-duplication.'],
  ['map_id / zone_id', 'nullable', ''],
  ['zone_name', 'nullable', ''],
  ['x / y', 'real, nullable', ''],
  ['on_taxi (new)', 'boolean, nullable', ''],
  ['source', 'text', ''],
  ['quality', 'text', '`exact`, `zone_only`, `estimated`.'],
]);
ENTITY('KnownZone (new)', 'Zones entered by a character since tracking began; used to decide whether a zone visit is a first visit.', [
  ['character_id', 'FK', ''],
  ['zone_id / map_id', 'key', ''],
  ['first_seen_at', 'timestamp', ''],
  ['initial_zone', 'boolean', 'True for the zone the character was in when tracking began (no screenshot).'],
]);
ENTITY('MapInfo (new)', 'Map geometry recorded once per map by the addon; used to place routes on zone and continent maps.', [
  ['map_id', 'PK', 'Forever `uiMapID`.'],
  ['name / locale', 'text', ''],
  ['map_type', 'text, nullable', 'Zone, continent, dungeon, etc.'],
  ['parent_map_id', 'nullable', ''],
  ['rect_on_parent', 'JSON, nullable', 'minX, maxX, minY, maxY from `C_Map.GetMapRectOnMap`.'],
  ['client_build', 'text', 'Geometry may change between builds.'],
  ['artwork_file', 'text, nullable', 'Set by the desktop app when matching artwork is found.'],
]);
ENTITY('ScreenshotRecord', null, [
  ['screenshot_id', 'PK', ''],
  ['character_id', 'FK', ''],
  ['requested_at', 'timestamp', ''],
  ['captured_at', 'timestamp, nullable', 'Time of the API call.'],
  ['trigger_type', 'text', 'Highest-priority trigger of the coalesced events.'],
  ['status', 'text', '`requested`, `api_called`, `confirmed`, `failed`, `stale`, `rejected`, `dropped_on_logout`.'],
  ['file_name (new)', 'text, nullable', 'Set by the desktop app after a file match.'],
  ['file_match (new)', 'text, nullable', '`matched`, `ambiguous`, `not_found`.'],
  ['error_message', 'text, nullable', ''],
]);
ENTITY('ScreenshotEventLink (new)', 'Links one screenshot to one or more events (coalescing).', [
  ['screenshot_id', 'FK', ''],
  ['event_id', 'FK', 'Unique: one screenshot per event.'],
]);
ENTITY('Session', null, [
  ['session_id', 'PK', ''],
  ['character_id', 'FK', ''],
  ['started_at', 'timestamp', ''],
  ['ended_at', 'timestamp, nullable', ''],
  ['last_heartbeat_at (new)', 'timestamp, nullable', ''],
  ['duration_seconds', 'integer, nullable', ''],
  ['duration_quality', 'text', '`observed`, `estimated`, `incomplete`.'],
  ['end_reason (new)', 'text, nullable', '`logout`, `crash_incomplete`, `unknown`.'],
  ['reload_count (new)', 'integer', ''],
  ['played_total_seconds (new)', 'integer, nullable', 'Server-reported at session start.'],
  ['played_level_seconds (new)', 'integer, nullable', 'Server-reported at session start.'],
]);
ENTITY('ProfessionSnapshot', null, [
  ['snapshot_id', 'PK', ''],
  ['character_id', 'FK', ''],
  ['profession_id', 'nullable', ''],
  ['profession_name', 'text', ''],
  ['locale (new)', 'text, nullable', ''],
  ['skill_level', 'integer, nullable', ''],
  ['skill_max', 'integer, nullable', ''],
  ['captured_at', 'timestamp', ''],
  ['source', 'text', ''],
  ['completeness_status', 'text', ''],
]);
ENTITY('RecipeSnapshot (new)', 'One capture of the recipe list of one profession.', [
  ['recipe_snapshot_id', 'PK', ''],
  ['character_id', 'FK', ''],
  ['profession_id / profession_name', '', ''],
  ['captured_at', 'timestamp', ''],
  ['source', 'text', 'API used.'],
  ['completeness_status', 'text', '`complete`, `partial`, `unavailable`.'],
  ['recipe_count', 'integer', ''],
  ['locale', 'text, nullable', ''],
]);
ENTITY('KnownRecipe', null, [
  ['known_recipe_id (new)', 'PK', ''],
  ['recipe_snapshot_id (new)', 'FK', ''],
  ['character_id', 'FK', ''],
  ['profession_id', 'nullable', ''],
  ['recipe_id', 'nullable', ''],
  ['recipe_name', 'text', 'Original name as shown by the client.'],
  ['category', 'nullable', ''],
  ['required_skill', 'nullable', ''],
]);
P('Recipe uniqueness within a snapshot: character + recipe ID when available; otherwise normalized recipe name + profession + locale. Keep the original name.');
ENTITY('ImportRun (new)', null, [
  ['import_id', 'PK', ''],
  ['source_path', 'text', ''],
  ['source_type', 'text', '`saved_variables` or `jsonl`.'],
  ['file_mtime / file_size', '', ''],
  ['started_at / finished_at', 'timestamp', ''],
  ['rows_imported / rows_duplicate / rows_invalid', 'integer', ''],
  ['gaps_detected', 'integer', ''],
  ['status', 'text', '`ok`, `partial`, `rejected`.'],
]);
P('Every SavedVariables root table and every JSONL header carries a schema version.');

// ---------------------------------------------------------------------
H2('7. Privacy and security');
UL([
  'MVP data stays local by default.',
  'No account passwords, session tokens, or Blizzard credentials.',
  'No data upload in MVP.',
  'Future sharing must be opt-in per character and per data category.',
  'Screenshots may contain chat or personal information; never upload/share automatically.',
  'The SavedVariables parser never executes code from the file.',
  'Provide delete/export controls and document where screenshots are stored.',
]);
H3('7.1 Known limitations to document for users');
UL([
  'Data since the last /reload or logout is lost if the client crashes.',
  'Addon storage is bounded; data not imported before the retention cap is reached is lost and shown as a gap.',
  'Recipe lists are only updated while the profession window is open.',
]);

// ---------------------------------------------------------------------
H2('8. Error handling and reliability');
UL([
  'All API calls that may fail are guarded.',
  'Event handlers must be short and non-blocking.',
  'Invalid data must not stop other trackers.',
  'Queue overflow, stale screenshot requests, retention overflow and unsupported APIs must be logged clearly.',
  'Persist data safely and back up before schema migrations.',
  'Desktop import uses transactions and reports partial failures.',
  'Keep a small diagnostic log with rotation or size limits.',
]);

// ---------------------------------------------------------------------
H2('9. Testing plan');
H3('Automated (outside the client)');
UL([
  'Static syntax/lint check for Lua (for example luacheck) and Python (for example ruff).',
  'Lua unit tests (for example busted) with mocked WoW API for: queue priority, FIFO order, coalescing, capture delay, cooldown and bypass, maximum age, overflow replacement, ring buffer retention, ID generation, serialization.',
  'Python unit tests (pytest) for: SavedVariables parser (valid, malformed, truncated, code injection, very large files), import idempotency, gap detection, natural-key character matching, screenshot file matching, JSONL round trip.',
]);
H3('In-game (target Forever build)');
UL([
  'Install addon on the target Forever build and confirm it loads without Lua errors.',
  'Trigger/test each registered event where possible.',
  'Confirm screenshot API presence, capture behavior and confirmation events.',
  'Test a level-up together with an achievement (coalescing).',
  'Test zone screenshots on a flight path, through a portal/loading screen, and when leaving before the dwell time.',
  'Test SavedVariables persistence across /reload, logout, and full client restart.',
  'Test a forced client termination and confirm the session is marked incomplete.',
  'Test zone transitions, revisits, and that the zone at first run does not trigger a screenshot.',
  'Test played-time request at login: no chat output for the automatic request, normal output for a manual `/played`.',
  'Test that recipe capture ignores search text and filters, and that viewing another player’s linked profession creates no snapshot.',
  'Test the addon in combat and in a dungeon/boss encounter: no Lua errors from secret values; deferred work runs after combat.',
  'Test map display with provided artwork on zone and continent maps, and a map without artwork (schematic view).',
  'Test position sampling, stationary de-duplication, instances and missing API behavior.',
  'Test profession/recipe completeness against the in-game profession UI, with and without collapsed headers and filters.',
  'Test multiple characters, same-name characters on different realms, and a renamed character.',
  'Long-play test: SavedVariables size stays within the target with default caps.',
  'Verify no item/inventory/crafting-history feature exists in MVP.',
]);

// ---------------------------------------------------------------------
H2('10. Recommended implementation order');
OL([
  '**Phase 0:** API discovery and compatibility report for the current Forever beta build: verify the APIs in section 3, the AddOns folder and Interface version, the played-time display function, and which Classic+ systems (achievements, professions) exist. Re-run the report after every client update during beta.',
  'Minimal addon bootstrap, diagnostics and `/fc` command.',
  'Character identity (GUID) and versioned, bounded event storage with retention.',
  '**Pipeline proof:** desktop SavedVariables locator, safe parser, importer and SQLite schema with a minimal event list. Validate end to end with real files before continuing.',
  'Screenshot manager and queue, including confirmation and desktop file matching.',
  'Session, played time, known zones, map geometry, zone and position tracking.',
  'Desktop timeline and screenshot gallery.',
  'Map and route replay.',
  'Profession and recipe snapshots.',
  'Quest, achievement, and death integration.',
  'JSONL export/import and backups.',
  'QA, recovery, documentation, packaging.',
]);

// ---------------------------------------------------------------------
H2('11. Definition of Done');
P('The MVP is done when:');
UL([
  'The addon loads cleanly in the target Forever build.',
  'Supported events are recorded with timestamps and character identity, and characters are matched by GUID where available.',
  'Screenshot rules match the requested defaults, coalesced events share one screenshot, every request has a logged outcome, and unsupported capture is reported honestly.',
  'The desktop app imports SavedVariables safely and idempotently and displays a synchronized timeline and route playback, including data gaps.',
  'Profession name, current skill level, and known recipes are shown per character where the client exposes reliable data, with completeness status.',
  'No item/inventory/loot/crafting-history feature is present.',
  'The SavedVariables file stays within the size target with default retention caps.',
  'Data survives normal reload/logout/restart tests; the crash limitation is documented and shown, and a working export/backup route exists.',
  'Unsupported API capabilities are clearly surfaced instead of silently fabricated.',
]);

// ---------------------------------------------------------------------
H2('12. Decisions');
TABLE([700, 2700, 1300, 4326], ['ID', 'Question', 'Status', 'Resolution'], [
  ['Q1', 'Which client is Forever based on?', 'Decided', 'Blizzard’s official Classic+ on the Mainline engine and API with Midnight addon rules; client 1.60.x. Verified in Phase 0 (section 3).'],
  ['Q2', 'Source of map artwork?', 'Decided', 'Provided by the product owner, private use. Format in F-005.'],
  ['Q3', 'Cooldown bypass for level-up and achievement screenshots?', 'Decided', 'Bypass enabled by default, configurable with `/fcshot bypass`.'],
  ['Q4', 'Retention caps and size target?', 'Decided', 'Defaults from F-013, configurable. Import roughly once a week.'],
  ['Q5', 'Reconstruct zone visits from before installation?', 'Decided', 'No. History starts with tracking; the timeline and map are sufficient.'],
  ['Q6', 'Can played time be requested without chat output?', 'Decided', 'Yes. Unregistering the chat frames during the request works (F-004).'],
  ['Q7', 'Which Classic+ systems exist (achievements, professions, quest events)?', 'Decided', 'All exist: achievements (29 categories, 112 achievements), Mainline professions and recipes, quest events. `ACHIEVEMENT_EARNED` and `PLAYER_LEVEL_UP` are logged as confirmed when first observed.'],
  ['Q8', 'AddOns folder and Interface version of the Forever client?', 'Decided', '`_classic_beta_\\Interface\\AddOns`, Interface 16001. Re-check after client updates and at release.'],
]);

// =====================================================================
const doc = new Document({
  creator: 'Forever Chronicle',
  title: 'Feature Specification: Forever Chronicle v1.3',
  styles: {
    default: { document: { run: { font: 'Calibri', size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 36, bold: true, color: '1F3864' }, paragraph: { spacing: { before: 120, after: 200 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, color: '2E74B5' }, paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, color: '1F3864' }, paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: numberingConfigs },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: 'Forever Chronicle Spec v1.3 – ', size: 18, color: '808080' }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18, color: '808080' })] })] }) },
    children: body,
  }],
});

Packer.toBuffer(doc).then(buf => { fs.writeFileSync(OUT, buf); console.log('wrote', OUT, buf.length, 'bytes'); });
