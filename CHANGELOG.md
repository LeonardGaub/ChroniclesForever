# Journey Forever – Changelog

Player-facing changes to the main addon (`addons/ForeverChronicle`), collected for the next CurseForge upload.
Add an entry with every addon change. When uploading, paste the section into the CurseForge changelog field,
then turn "Unreleased" into the uploaded version and date.

## Unreleased (0.15.0)

### New
- The character's current experience (the bar as it stands) is saved, for the desktop app's experience bar.
- Deaths name their cause, read from the game's death recap: "Killed by Hogger in Elwynn Forest", or "Drowned",
  "Fell to death" and so on. Hover the entry for the killing blow (spell and damage). Deaths without a recap
  stay "Died in ...".
- UI polish: the window and its pages fade in, and the tabs on the right edge look like the spellbook's tabs.
  The new "Animations" setting turns all animations off.
- Chronicle: a search box finds entries by their text or place (for example a quest, a zone or a boss).
- Chronicle: filter buttons for each kind of entry (level-ups, quests, exploration, achievements, rare enemies,
  dungeons, professions, deaths, sessions), in a row you unfold with "Filters". Click to show or hide a kind,
  Shift-click to show only that kind. "Filters (2 hidden)" reminds you while kinds are hidden. The "Only with
  screenshot" filter sits at the top right.
- The test screenshot button moved to Settings → Screenshots.
- Chronicle: entries are grouped under a heading for each day ("Today", "Yesterday", "Wednesday, ...").
  Level-ups, achievements, completed dungeons and new professions stand out with a larger icon and a gold
  accent; deaths get a red accent.
- Chronicle: entries that are new since you last looked pop in one after the other when you open it.
- Chronicle: new "Book" look, with entries on a parchment page. Switch back under Settings → "Chronicle look".
- Overview: gear slots use the game's item buttons and quality borders. Shift-click an item to link it in chat,
  Ctrl-click to try it on in the dressing room.
- Overview: your race's dressing-room picture behind the character model.
- Overview: the experience bar looks like the game's: purple, blue while rested, a lighter rested part with the
  rested marker, 20 segments and the percentage. It glides when you gain experience.
- Overview: the graph has a soft fill under the line, grid lines, a crosshair when you hover, and a dot on the
  newest value.
- Map: clearer playback controls in a bar under the map. Play turns into Pause while playing, new buttons jump
  to the previous or next mark on the timeline, and "Live" has a red dot that pulses while it follows you.
- Map: event icons are round pins with a coloured ring. Milestones are larger and gold, deaths show a skull on
  red. During a replay, pins pop up as the route reaches them.
- Dungeons: boss kills appear in the chronicle ("Boss defeated: Bazzalan (Ragefire Chasm)"), and the first time
  you defeat a dungeon's last boss, the dungeon counts as completed. New stats: bosses defeated, dungeons
  completed.
- Screenshots: the main switch "Automatic screenshots" is gone. Each kind of screenshot (level-up, achievement, ...)
  has its own check box, and every ticked one takes screenshots. If you had the main switch off, untick the kinds
  you don't want.
- Screenshots: "Hide interface" now has three choices. "All" hides everything and now also works in combat.
  "Keep popups" hides everything except the event's popup (for example the level-up banner) and takes the
  screenshot as soon as the popup is fully shown, so it is still on screen. The minimap is hidden as well, so
  its arrow and quest areas no longer float on the picture.
- Screenshots: new trigger "On dungeon completion" (on by default) for the first kill of a dungeon's last boss.
- The Screenshots tab is gone; screenshots now appear in the chronicle. An entry that got a screenshot shows a
  marker with its status (hover for the file name), test screenshots are entries of their own, and "Only with
  screenshot" lists just those.
- New command `/fj dungeon`: shows what the game offers inside the current dungeon (map, bosses). It prepares a
  dungeon map for a later version.
- Map: replay now "paints" the route. Only the way up to the shown moment is drawn, and event icons appear as
  the replay reaches them.
- Map: new "Last 15 minutes" button. It shows only the last 15 minutes of the route, with older parts fading
  out, so zones where you spent hours stay readable.
- Map: route colours. Colour the route by character level (with a legend), by session, or in one colour.
  Flight paths stay blue.
- Map: the slider is now a timeline. Coloured bands show the zone you were in, and marks above it show
  level-ups, deaths, rare kills, achievements and new zones. Hover for details, click a mark to jump to it.
  Logouts and long breaks are left out, so a slider over many sessions is no longer mostly empty.
- Map: during replay the marker glides along the route line instead of jumping from point to point.
- Map: zooming in now shows the route in full detail; it used to stay as coarse as the full map view.
- Routes are no longer lost when the route storage is full. The oldest points are thinned out (only points a
  replay would not miss are removed) and kept in a new route archive.
- The slash command is now `/fj` (was `/fc`), and `/fjshot` (was `/fcshot`). `/chronicle` still works.
- Overview: the "Tracked play time" statistic is gone. It almost always showed the same as "Total played"
  from the server, which stays.

### Fixed
- Saved data no longer stops loading when it grows large. The game refuses a saved file with too many separate
  values (several characters with long histories could reach that), and the addon would then have started
  empty. The addon now stores many records together in the saved file. Older addon versions do not open the
  new format and leave it untouched, so going back to an older version cannot overwrite your data.
- Map: a hearthstone or portal no longer draws a route line across the whole map. The route now breaks at
  every teleport, including on routes recorded with earlier versions and on friends' routes.
- Map: the route legend now lists every level (or session) the drawn route passes through. Before, it only
  showed the levels at the start and end of each route line, so levels gained along the way were missing.

## 0.14.1 – 2026-10-14

Last CurseForge build (`dist/curseforge/JourneyForever-0.14.1.zip`).
