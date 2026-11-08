# Journey Forever – Changelog

Player-facing changes to the main addon (`addons/ForeverChronicle`), collected for the next CurseForge upload.
Add an entry with every addon change. When uploading, paste the section into the CurseForge changelog field,
then turn "Unreleased" into the uploaded version and date.

## Unreleased

- Screenshots with "Keep popups": the screenshot now waits 2 seconds after the popup (level-up banner,
  achievement toast) appears instead of 1, so it no longer fires the instant you level up.
- More history per character: the route keeps 200,000 points before the oldest are thinned into the archive
  (was 100,000, roughly 110 hours of movement instead of 55), the route archive holds four times as much, and
  the kill log keeps 100,000 kills (was 50,000).

## 0.16.0 – 2026-11-04

Shared with friends as `dist/friends/JourneyForever-0.16.0-Komplett.zip` (addon + desktop app), not uploaded to
CurseForge yet.

- PvP in the chronicle (new filter "PvP"):
  - Enemy players you or your group defeat in the open world, with their level, race, class and guild, who
    landed the killing blow and the honor it gave. A PvP kill takes a screenshot (new setting "On PvP kills and
    won battlegrounds", on by default).
  - Deaths by another player's hand say who it was: hover the entry ("Level 31 Human Rogue <Deathwatch>").
  - Duels you win, lose or flee from.
  - Battlegrounds and arenas as one entry per match: victory or defeat, your killing blows, honorable kills,
    deaths and honor. A won match takes a screenshot of the score board. Deaths inside a match take no
    screenshot, and the players of the battleground raid no longer count as your group (only the friends you
    queued with).
- The Professions tab is gone, and with it the recipe list, the "Known recipes" statistic, recipe entries in the
  chronicle and `/fj professions`. Learning a profession and training a new rank still appear in the chronicle
  (and in the desktop app's cinematic). Old recipe entries are removed from the saved file.
- Screenshots with "Keep popups": the pet bar, other action bars, the target's frame and similar parts of the
  interface no longer stay visible when they happen to appear right after the event (a pet summoned, a new
  target); only the event's popup does.
- Map: zoomed in, the route is drawn as smooth curves through the recorded points instead of straight corners,
  and the replay marker follows the curve.
- Groundwork for future statistics, nothing new to see yet: every kill that gives experience is noted with its
  experience and the enemy's name, and each level-up keeps what you had at that moment (statistics, gold, gear
  and the time played on the level).
- Notable loot in the chronicle (new filter "Loot and mounts"). Not every drop, only what is worth telling:
  every epic item the first time you get it, and blue gear that mattered: from a boss or rare enemy, or put on
  within an hour of getting it ("New gear"). Blue gear you sell, green and white items, anything that stacks
  (herbs, cloth, potions), quest items, items taken out of the bank and items you had before are left out. Turn
  off the blue gear under Settings → Loot to keep only epics. Hover an entry to see where it came from (a boss, a rare enemy, a quest,
  fishing, crafting, a vendor, the mail, a trade or the auction house). Your first epic takes a screenshot.
- New mounts appear in the chronicle; the very first one is a highlight and takes a screenshot.
- "Hearthstone set: Razor Hill" when you bind your hearthstone to a new inn.
- Deaths now tell how you came back: "Resurrected by Gigel", by the spirit healer, at your body, or by yourself
  (soulstone, ankh). Hover the entry.
- Capture a moment: `/fj moment Sunset over Thunder Bluff` takes a screenshot at once and keeps your words with
  it in the chronicle. You can also bind a key ("Capture a moment" under the AddOns key bindings): it takes the
  screenshot and then asks for the text.
- The route remembers when you were mounted and which teleports were your hearthstone or a teleport spell, and
  who you played with in a group.
- Ready for the release client: the addon also counts as up to date on game versions 1.60.2, 1.60.3 and 1.61.0.
- Two new statistics on the overview: "Jumps" and "Fish caught". Only jumps from the ground count (not pressing
  jump in mid-air, swimming up or on a flight path), and every catch from fishing counts as one fish.
- The `/fj dungeon` command is gone. It reported test data for dungeon maps, which the addon no longer has;
  that data is removed from the saved file.
- Safer reading of other characters' saved data: a specially crafted entry can no longer freeze the game.
- Negative numbers show correctly ("-123,456" instead of "-,123,456").
- The gold graph keeps working for characters with more than 214,748 gold.

## 0.15.0 – 2026-10-20

### Chronicle
- New "Book" look, with entries on a parchment page. Switch back under Settings → "Chronicle look".
- Entries are grouped under a heading for each day ("Today", "Yesterday", "Wednesday, ...").
  Level-ups, achievements, completed dungeons and new professions stand out with a larger icon and a gold
  accent; deaths get a red accent.
- Entries that are new since you last looked pop in one after the other when you open it.
- A search box finds entries by their text or place (for example a quest, a zone or a boss).
- Filter buttons for each kind of entry (level-ups, quests, exploration, achievements, rare enemies, dungeons,
  professions, deaths, sessions), in a row you unfold with "Filters". Click to show or hide a kind, Shift-click
  to show only that kind. "Filters (2 hidden)" reminds you while kinds are hidden.
- Deaths name their cause, read from the game's death recap: "Killed by Hogger in Elwynn Forest", or "Drowned",
  "Fell to death" and so on. Hover the entry for the killing blow (spell and damage). Deaths without a recap
  stay "Died in ...".
- Screenshots now appear in the chronicle; the Screenshots tab is gone. An entry that got a screenshot shows a
  marker with its status (hover for the file name), test screenshots are entries of their own, and "Only with
  screenshot" (top right) lists just those.

### Map
- The slider is now a timeline. Coloured bands show the zone you were in, and marks above it show level-ups,
  deaths, rare kills, achievements and new zones. Hover for details, click a mark to jump to it. Logouts and
  long breaks are left out, so a slider over many sessions is no longer mostly empty.
- Clearer playback controls in a bar under the map. Play turns into Pause while playing, new buttons jump to the
  previous or next mark on the timeline, and "Live" has a red dot that pulses while it follows you.
- Replay "paints" the route: only the way up to the shown moment is drawn, the marker glides along the route
  line instead of jumping from point to point, and event pins pop up as the route reaches them.
- Event icons are round pins with a coloured ring. Milestones are larger and gold, deaths show a skull on red.
- Route colours: colour the route by character level (with a legend), by session, or in one colour. Flight
  paths stay blue.
- New "Last 15 minutes" button. It shows only the last 15 minutes of the route, with older parts fading out, so
  zones where you spent hours stay readable.
- Zooming in now shows the route in full detail; it used to stay as coarse as the full map view.

### Overview
- Gear slots use the game's item buttons and quality borders. Shift-click an item to link it in chat,
  Ctrl-click to try it on in the dressing room.
- Your race's dressing-room picture behind the character model.
- The experience bar looks like the game's: purple, blue while rested, a lighter rested part with the rested
  marker, 20 segments and the percentage. It glides when you gain experience.
- The graph has a soft fill under the line, grid lines, a crosshair when you hover, and a dot on the newest
  value.
- The "Tracked play time" statistic is gone. It almost always showed the same as "Total played" from the
  server, which stays.

### Screenshots
- The main switch "Automatic screenshots" is gone. Each kind of screenshot (level-up, achievement, ...) has its
  own check box, and every ticked one takes screenshots. If you had the main switch off, untick the kinds you
  don't want.
- "Hide interface" now has three choices. "All" hides everything and now also works in combat. "Keep popups"
  hides everything except the event's popup (for example the level-up banner) and takes the screenshot as soon
  as the popup is fully shown, so it is still on screen. The minimap is hidden as well, so its arrow and quest
  areas no longer float on the picture.
- New trigger "On dungeon completion" (on by default) for the first kill of a dungeon's last boss.
- The test screenshot button moved to Settings → Screenshots.

### Dungeons
- Boss kills appear in the chronicle ("Boss defeated: Bazzalan (Ragefire Chasm)"), and the first time you
  defeat a dungeon's last boss, the dungeon counts as completed. New stats: bosses defeated, dungeons completed.
- New command `/fj dungeon`: shows what the game offers inside the current dungeon (map, bosses).

### Other
- UI polish: the window and its pages fade in, and the tabs on the right edge look like the spellbook's tabs.
  The new "Animations" setting turns all animations off.
- Routes are no longer lost when the route storage is full. The oldest points are thinned out (only points a
  replay would not miss are removed) and kept in a route archive.
- The slash command is now `/fj` (was `/fc`), and `/fjshot` (was `/fcshot`). `/chronicle` still works.

### Fixed
- Saved data no longer stops loading when it grows large. The game refuses a saved file with too many separate
  values (several characters with long histories could reach that), and the addon would then have started
  empty. The addon now stores many records together in the saved file. Older addon versions do not open the
  new format and leave it untouched, so going back to an older version cannot overwrite your data.
- Map: a hearthstone or portal no longer draws a route line across the whole map. The route now breaks at
  every teleport, including on routes recorded with earlier versions.
- Map: the route legend now lists every level (or session) the drawn route passes through. Before, it only
  showed the levels at the start and end of each route line, so levels gained along the way were missing.

## 0.14.1 – 2026-10-14

Last CurseForge build (`dist/curseforge/JourneyForever-0.14.1.zip`).
