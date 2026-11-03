# Journey Forever – History

The session notes that used to be the "History" section of `NEXT_STEPS.md`, newest first, kept as they were written
at the time: older entries may describe things that changed or were removed later. The current state is in
`NEXT_STEPS.md`.

### 3D map for the cinematic mode (2026-11-03)
- Planned with the user (14 decisions, docs/3D_Map_Viewer.md) and built on branch `investigate/3d-map-viewer`
  (worktree `WowAddon-3d`): a 3D mode of the cinematic (option "cine_3d", off by default), terrain only for now.
- Data: `tools/build_terrain.py` reads the WDT/ADT files from CASC (Map.db2 for the WDTs): 129 x 129 heights and
  the 512 px minimap per tile, the MH2O liquids (vertex format from the block size; kind from LiquidType's
  SoundBank, field 3), overviews for the far view. Kalimdor 988 tiles, Eastern Kingdoms 736, Zephras Isle 72:
  88 MB. The z of `UnitPosition` is always 0, so every height comes from the terrain.
- Coordinates: map position → world yards through UiMapAssignment (matches the probe's `GetWorldPosFromMapPos`
  to 0.05 yd); both continents in one shared world at the world map's layout (their scales differ by 0.4 %).
- Spike first (`tools/terrain_spike.py`), then the cinematic. Instead of moving the cinematic behind a stage
  interface (the plan's phase 2), the 3D stage mirrors the 2D scene each step: no change to the 2D replay.
- Found on the way: PySide6 needs `VoidPtr(0)` for `glDrawElements` and uniforms by location; blending must keep
  the framebuffer's alpha at 1 (Qt composites it premultiplied); a sea plane at z = 0 floods inland ground below
  sea level (Orgrimmar), so the sea comes from the liquids on the tiles; QPainter inside `paintGL` is left out of
  `QWidget.render` (the export), so the 2D items are painted on a widget above the GL one; the minimap paints the
  open sea black (and the void round Zephras Isle).
- Measured on the user's PC: vsync-bound (about 68 fps), tile streaming at most 2-3 ms a frame, a whole journey
  opens in about 1 s, a 15-minute range exports at 720p in 25 s.
- Same day, at the user's request: buildings (WMO) and a calmer camera over hills. The placement transform was
  fitted to the MODF boxes. The big buildings' LOD 1 skips interior groups, and classic Orgrimmar is all interior,
  so those come in full where they reach above the ground. 73% of the building textures seemed missing in the
  local CASC, so buildings were coloured from the minimap at first. Building floors carry the route (Orgrimmar's floors are 13-93
  yd above its terrain). Details in docs/3D_Map_Viewer.md, "As built".
- Same day: `wow/casc.py` read the first-listed variant of a file (root blocks with content flags), which for most
  building and ground textures was the uninstalled one. Now it reads the installed variant, and every texture
  is there. With that: building textures, ground textures as detail on the minimap colour, a camera director
  (cities from higher up, clear views, cut-away under roofs, shots). Pillow's BLP decoder (pure Python) and the
  alpha maps' unpacking in a thread starved the drawing thread: a numpy decoder, and worker processes (which needed
  `__main__.py` guarded).

### Kino tab replaces the desktop map page (2026-11-02)
- User decision: the desktop map page lacked screenshot pins and the replay's moments, and the cinematic mode is
  always better; the addon's map is the place to browse the route. `ui/pages/map_page.py` is gone, with its
  tests (the route projection and dungeon-entrance tests stay in `tests/test_map.py`).
- New Kino tab (`ui/pages/cinema.py`): a banner with the whole journey on the seamless world map
  (`ui/journey_art.py`, route colours, the current spot glowing), the character's title and "▶ Die ganze Reise" /
  "⤓ Video"; below it every session with route points as a numbered chapter (main zone, day, time, length, levels,
  quests, deaths, first screenshot). Selecting chapters lights their route up on the banner; double-click or Enter
  plays them, several together play as one.
- The route colour choice moved to Einstellungen → Kino-Modus. The Chronik's "▶ Ab hier" (or Enter) plays the chosen
  moment from 30 s before it to the end of its session (it replaced "selecting an event moves the map",
  `AppContext.focus_time` is gone). The home screen's card is "Kino" with the journey picture.
- The cinematic window fades in when opened (option "ui_motion").

### Kills and level-up snapshots, data only (2026-11-02)
- The user compared the Road to Sixty addon (installed in `_forever_`, all rights reserved: ideas only) and asked
  for its data, without showing it yet: smoother route lines, a snapshot at each level-up, records, kills with XP
  and name.
- `Modules/Kills.lua`: compact stream `kills` (`time,xp,rested,name`, cap 50,000) from `CHAT_MSG_COMBAT_XP_GAIN`,
  matched with `Util.FormatMatcher` against the client's `COMBATLOG_XPGAIN_FIRSTPERSON` (numbered arguments of other
  languages handled). Stats `kill_xp`, `rested_xp`; Progress adds `quest_xp`, `quest_money`. None is registered,
  so nothing shows them.
- `level_up` data: `stats` (copy), `money`, `gear` (slot -> item string), `professions` (name -> "rank/max"), and
  from Session `playedTotal`, `levelPlayed`. Session's PLAYER_LEVEL_UP handler runs before Progress's (TOC order)
  and keeps the finished level's time for the event.
- Records need no further data except the gear-worn one (an event per gear change).
- Smoother lines (the user said yes afterwards): from zoom 1.5 the in-game map draws each route line as pieces of a
  centripetal Catmull-Rom curve through the drawn points (`Route.CurvePoint`, one piece per 4 screen pixels, at
  most 12), only while every point is drawn and the pieces fit the 5,000-line budget, else straight as before.
  `Route.Glide` names the line it glides on (`curve`), and the canvas moves the marker along the same pieces
  (`Canvas:PlaceMarker`, also after each redraw). Stored points never change; the desktop app stays straight.

### Cinematic tracking: facts instead of guesses (2026-10-30)
- User picked from a brainstorm: record why a teleport happened, how a death ended, riding, the group (with
  friends walking along in the cinematic), a hearthstone toast, notable loot with a clear trash/loot rule, and a
  manual screenshot with the player's own text.
- Addon: route flags `M` (mounted), `H`/`P` (the jump after a long cast: hearthstone/Astral Recall or another
  spell, always with `J`); `player_died` gains releasedAt, revivedAt, revive, reviver (filled in later, also
  across sessions); new modules Mounts (`mount_learned`, first = milestone + trigger "mount"), Group (stream
  `group`: "start,until,name/class/guid;..."), Loot (`item_obtained`, rules in the file header; trigger "loot" for
  epic+; changed the same day at the user's request: epics always, blue gear only from a boss/rare or worn within an
  hour, no greens, no quality setting), Moments (`moment`, `/fj moment`, key binding in Bindings.xml, trigger "moment" without delay or
  cooldown); Travel records `hearth_set`.
- Desktop: schema 13 (positions.mounted/cause, group_stretches); a re-import updates an event's payload (the
  addon fills events in later); deaths and cast teleports come from the data when present, the route heuristics
  stay for older data; new cues and banners, a revival toast, "with Gigel" on boss/dungeon/rare cues, the mount's
  icon on the marker while riding, and friends' markers from their own routes while grouped. Credits lines for
  all of this were built and removed again the same day: the user wants only cool long-term stats in the credits.

### Cloud backup replaces the friends sync (2026-10-27)
- User: plays the same characters on two PCs and found the first answer (a whole two-PC sync with join codes and a
  three-way merge, built the same day and never committed) far too complicated. New rules: back up the screenshots
  and the addon file when the game starts or quits and by a button; a cloud folder chosen by hand; data always both
  local and in the cloud, nothing overwritten; no friend invites; friends back up the same way and the import reads
  everyone's data. Design: `docs/Cloud_Backup.md`.
- User decisions: backup plus manual restore (no merge); the desktop app watches WoW (only while open) and catches
  up at its start; dated copies, newest 30; the app database too; full-size screenshots for everyone; friends only
  in the desktop app, whole addon files (no share settings); the sync lives in the app; the app installs addon
  updates and removes the old companion; the old cloud layout stays until deleted by hand; a banner when my other
  PC has newer data.
- Removed: `addons/ForeverChronicle_Share` (Share module, Teilen settings, friends view), `sync/` (ForeverSync.ps1,
  Einrichten.bat, Abgleichen.bat), `desktop/forever_chronicle/cloud_sync.py`, `tests/addon/dump_friends.js`, the
  share and friends fixtures, addon test phase 13 (phase 12 now tests the alt alone), `docs/Sharing_Design.md`,
  `docs/Friends_Map_Design.md` (friends' routes in game have no source any more).
- The live client appeared on 2026-10-27 (`_forever_`, flavor `wowf`, 1.60.1.70634): added to the known flavors.

### Cinematic: wider flights, softer way into the credits (2026-10-26)
- User: the flight Thunder Bluff → Orgrimmar stayed too close, and the credits came too abruptly with the music
  cut off. Zooming out now has its own quicker time constant (`ZOOM_OUT_SECONDS` 1.8 s, in stays 2.6 s); flights
  go out to 0.78 (was 0.86), fast stretches to 0.87 (was 0.9).
- Credits: `MusicPlayer.play` takes optional (out, in) fades; the adventure music fades out over 4 s and the theme
  in over 3.5 s. The camera pulls back over 5 s (was 4), the map dims over 4 s (was 2.5) and the first line comes
  up after 3.5 s (was 1.2), about when the old music has gone.

### Map tab on the seamless world map (2026-10-26)
- User request: the Karte tab shows the same seamless (OpenMap) world map as the cinematic mode. Every zone,
  continent and Azeroth (new entry in the map list) is a place on it: picking a map or following the player only
  moves the view there, the route crosses from zone to zone, detail tiles load as you zoom or drag, and a city's
  own map lies over it while the marker is in the city. You can zoom out to the whole world from any zone.
- Places the world map does not show (Zephras Isle, maps without geometry) and installs without `maps/world/`
  keep the old per-zone art. `soft_edges` moved from the cinematic into `ui/world_art.py` for both.

### Video export as sharp as the cinematic mode (2026-10-26)
- User compared a frame of the cinematic mode with the same moment of an exported video: photos, chat text and
  titles were much softer in the video. Cause: their screen is 4K at 150 % (2560×1440 logical), so the cinematic
  mode draws at 3840×2160, while the export laid the window out at 1280×720 logical (output size / screen pixel
  ratio) and drew 1920×1080. The HUD and titles were also bigger in proportion than full screen.
- Now the export window takes the screen's logical size cut to 16:9 (`layout_size`) and is drawn with
  `QWidget.render` into an image of its own pixel ratio: the video's size, or the layout's own when that is bigger
  (ffmpeg scales it down with lanczos). Independent of the screen's pixel ratio. 1440p and 4K added, CRF 20 → 18.
- Checked with a real 1080p export of Dorgar's replay: the photo's chat text is as sharp as in the live
  screenshot. ~40 ms per frame at 1080p here (was ~25–30). The map art itself stays soft when close (1002×668
  zone art, zoom 2.4); sharper map art would need upscaled tiles (not done).

### Cinematic: adventure music by level instead of zone music (2026-10-26)
- The zone music switched too often when crossing zones. A plan by stays in one place (switch only for stays of
  10 s real time, flights and day/night kept) was built and rejected by the user the same day, not committed.
- Now one adventure music: the day music of Elwynn Forest, Mulgore, Dun Morogh, the Barrens, Stranglethorn Vale,
  Ashenvale, Tanaris and Stormwind (`zone_music.ADVENTURE`), one theme per chapter, starting again after the last.
  A chapter begins at the levels in `CHAPTER_LEVELS` (1, 8, 15, 21, 27, 32, 37, 41, 45, 49, 52, 55, 58): long
  early, short late, where a level takes much longer. The switch is at the level-up itself (the old theme fades
  out under the fanfare). Dungeons and cities play it too. The option keeps its value `cine_music: "zone"`.
- Theme choice and order are a first pick, not yet listened to in the app.
- Mixed by race (user: "undead should have more undead zones sounds"): `RACE_THEMES` per race token (Scourge:
  Tirisfal, Plaguelands, Felwood; Human: Elwynn, Stormwind; Tauren: Mulgore, Thunder Bluff; ...). Even chapters
  play the race's themes, odd ones the common themes without those; unknown races (Forever's own, if any) get the
  common list. Undead: Tirisfal, Elwynn, Plaguelands, Mulgore, Felwood, Dun Morogh, Tirisfal, ... `Character`
  now carries `race_file` (the column was already there).

### Cinematic: profession toasts, quest pops, zone ambience, flight sounds (2026-10-26)
- User picks from the second brainstorm ("try out the quest pops"): profession progress cfd44de, quest pops
  6123480 (the experimental one, its own commit), ambience and flight sounds together (they share the new
  `LoopPlayer`, the export's mixing and the window's sound methods). The postcards were already there: a
  screenshot flies back to the marker and stays as a small polaroid pin, also through the outro.
- Checked with tests and rendered frames; not yet listened to in the app.
- Professions: `profession_learned` and `profession_rank` are cue types (toast, pin, timeline mark).
- Quests: `Interface\GossipFrame\ActiveQuestIcon` (16 px, `quest_turnin.png`) drawn at 34 px on a dark halo
  and gold glow (burst kind "quest", `PinsItem.quest`: several at once are staggered by `QUEST_STAGGER`).
- Ambience: `AreaTable.AmbienceID` (column 7) -> `SoundAmbience` (DB2 1310628, `AmbienceID[2]` day/night
  SoundKits) -> `SoundKitEntry`; one ~60 s OGG loop per zone and time of day (51 files), in `zone_music.json`
  under "ambience". `AMBIENCE_SETTLE` 2.5 real seconds before a new place's ambience plays; crossfade 2.5 s out,
  3.5 s in. Night from 20:30 to 6:00 (`daylight.night`). Option `cine_ambience`, at the effects' volume.
- Flight sounds, found without the listfile (the sound files have no names in the root): `TaxiNodes`
  `MountCreatureID` = 541 (gryphon), 2224 (wind rider), 3837 (hippogryph), 3574 (bat); `CreatureModelData` rows
  named by their M2 header (Gryphon, Wyvern), `SoundID` column 13 -> `CreatureSoundData` 145 / 85 (column 0 is
  the ID). Aggro calls 551348 / 564754, wing flap 564176, glide 564172. The wind: `SoundAmbience`'s extra kit
  292700 = ten 5 s wind loops, joined into one 44 s seamless loop (`game_sounds.join_loop`).
- Short flights: the wind blows at least `WIND_HOLD` (1.6 s) after take-off, so a flight lasting a moment at speed
  is one call and one gust; landing glide only after `LAND_AFTER` (2 s); no call within `CALL_GAP` (6 s) of a
  landing (connecting flights). Flaps follow the marker's drawn beats (`MarkerItem.take_off`, `pop_beats`).

### Cinematic: opening dive, flights, level-up textures, footprints, smooth own maps (2026-10-26)
- User picks from the brainstorm, "to test them all but may revert them later": one commit each, so each can be
  reverted on its own: opening dive a7d6507, smooth own maps b359622, flights 1f800d4, level-up 60c3de8,
  footprints 67819da. Checked on rendered frames, not yet watched in the app.
- Opening: the whole map (filling the picture) under the character's title, then a straight dive to the first
  point (`INTRO_HOLD`, `INTRO_DIVE`, `_advance_intro`); a jump skips it.
- Sharper maps: the client has nothing sharper (every zone 1002x668 from 256 px DXT1 tiles, used at full size;
  OpenMap's tiles at 16 px per world unit). Own maps (Zephras Isle) were drawn nearest-neighbour (a pixmap item
  ignores the view's render hint): now smooth. Upscaling (Lanczos, Real-ESRGAN) was judged not worth it: little
  gain, 2.5x the disk, or invented detail.
- Flights (built and reverted the same day at the user's request; do not bring them back without asking): the map
  leaned back 30 degrees, drawn flat into a larger picture and shown tilted (a perspective view transform drops
  lines with a point behind the eye: the route, the sky's tint), and on a flight path the frame showed at least
  90x60 world units within a second. Without it, leaving a city by flight path the camera stays city-close for
  a few seconds (5-15x the coarse art's pixels).
- Level-up: `Interface\LevelUp\LevelUpTex` gives the gold line and the golden glow (`tools/build_ui_skin.py`,
  `levelup_line.png`, `levelup_glow.png`); its dark backdrop overlaps other pieces there, so the title keeps its
  soft band. Title tone "level": lines grow from the middle, the glow flares behind; a pillar of the glow rises
  from the player (burst "level").
- Footprints (the last three game minutes walked, alternating, at fixed distances along the route) were built and
  reverted the same day at the user's request. Do not bring them back without asking. Mounts cannot be told
  from the route anyway (Zitter, a Windshaper rogue without a mount, reads at mount speed 11 % of the time).

### Cinematic: alerts in videos, city landings, standstill symbols, cloud trips (2026-10-26)
- Found by rendering Zitter's replay frame by frame (the export's loop, a copy of the data) and looking at the
  frames. Desktop only; the brainstorm's other ideas are not built.
- Standstill symbols: ⏩ and ⏭ are emoji by default, so Qt drew them as blue Segoe UI Emoji tiles (Friz Quadrata
  has neither). Now "▶▶" (faster) and "▶▶|" (skip), plain text symbols in the label's colour like the ▶ button.
  The offscreen platform has no font fallback and shows boxes for all such symbols; judge glyphs on Windows.
- Alerts in videos: a fourth alert pushes the oldest out with `deleteLater()`, which never runs during the video
  export (it runs inside a button's slot, and `processEvents` does not delete). The pushed-out alert stood in the
  video until the end (Oggleflint from Ragefire still shown in Tirisfal hours later). Alerts are hidden first now
  (`CinematicWindow._drop_toast`).
- Arriving in a city by teleport: the city's own map faded in only after landing (0.8 s), so the dive ended close
  up on the coarse world tiles (a huge blurred "ORGRIMMAR" banner). The destination city now fades in during the
  dive (`_update_world`), and a camera cut shows or hides city maps at once (`world_cut`).
- Standstill note: naming only standstills of 5 minutes or more was tried and reverted at the user's request (a
  skipped mob hunt then went by without a word, which felt weird). Every skipped standstill is named again. Most
  last 1-3 minutes (Zitter: 45, median 108 s).
- Standstills are AFK only now (user: early on Zitter's replay 8 minutes of questing were skipped; "it should only
  skip afk periods, where the player has not moved a single yard"). That span (14.10 15:17-15:26, Zephras Isle,
  quest "Al'Aketh Assassins") was a mob hunt: 46 points every 2-10 s, always within the old ~25-yard reach of one
  spot. A walking limit per minute was tried first and replaced. Now a standstill is the same spot (map, x, y)
  for `STILL_SECONDS`: the addon keeps not moving as one sample whose end time it extends (`samePlace` in
  Positions.lua), and any step starts a new one. Zitter: 17 standstills (was 45), Dorgar 15 (was 33); the end
  credits' standing time counts only these. The hearthstone check keeps its own ~25 yards (`CAST_REACH`).
- Cloud trips (user: the clouds must come and go only with the new map under them): the map changed on the first
  frame after the clouds closed and they began to part in the same frame, steepest at the start; live, loading
  the new map makes the next step long (up to 0.1 s), so the new map could show through at once. Now the trip's
  clock restarts after the change (loading time does not count), the clouds stay closed `SKY_HOLD` (0.25 s) and
  part gently (1 - x^1.6). About 0.7 s of closed clouds in all. Old and new code rendered the trips identically
  before this, so the cleanup commits and the city fix had not changed them.
- Clouds redrawn (user: in from the sides to the middle, covering everything; out from the middle first): a front
  of puffs on an ellipse the shape of the picture (`CloudCover`), solid mist behind it, closing to the middle and
  opening outward; its pace is (1 - amount)^0.6, slow at the edges and quick across the middle. The front is
  puffy, puffs further back grow and fade into the mist (an even field of puffs looked like bubble wrap). The
  sky trip's parting curve became 1 - x^1.3. Fully covered: ~0.55 s per trip (measured on the rendered frames:
  no coloured map pixels left), before ~0.66 s.

### Stat tiles, jumps and fish, Zephras Isle through the clouds (2026-10-26)
- Desktop overview: the stats are tiles as in the addon (game icon in a dark square, gold name, white value, two
  per row, each group with its description). Every stat has an icon (`domain/stats.py`); `tools/extract_icons.py`
  bundles the stat icons with the event types' (test: `test_every_stat_has_an_icon_kept_in_git`). Icons only in
  the app: longest session Spell_Holy_BorrowedTime, tracked since INV_Misc_Book_07, quests per hour
  Ability_Rogue_Sprint.
- Addon module `Modules/Pastimes.lua`: `jumps` (post-hook on `JumpOrAscendStart`, the jump key's function; not
  counted while falling, swimming, flying or on a taxi) and `fish_caught` (`LOOT_OPENED` with `IsFishingLoot()`,
  one per catch). Statistics only, shown in the addon and the app. The client's own API docs (CASC,
  `Blizzard_APIDocumentationGenerated`) and LootFrame confirm `LOOT_OPENED`, `IsFishingLoot`, `IsFalling`,
  `IsSwimming`, `IsFlying`; the jump binding's file was not found, so the hook is unverified in Forever. User
  check: `/run hooksecurefunc("JumpOrAscendStart", function() print("jump!") end)`, or jump and watch the tile.
- Zephras Isle (UiMap 2521) is a world of its own (MapID 2991, UiMapAssignment); the world map 947 has no part for
  it, so the game places it nowhere. Recorded trips: a portal up from Orgrimmar (Cleft of Shadow), Thunder Bluff or
  Hillsbrad to one spot (0.62, 0.73), and down from the south edge onto north Mulgore or Hillsbrad after an
  11-17 s loading screen. User decision: no invented place for the island; the cinematic shows these trips
  through the clouds (`maps.SKY_ISLANDS`, `_SkyTrip` in ui/cinematic.py, `CloudCover` in ui/cinematic_fx.py).
- Seamless world map, cities: OpenMap's baked tiles leave the cities to its own city maps (Orgrimmar is a
  transparent hole, the banners of Undercity, Thunder Bluff, Darnassus are blurred out), and the app shows a
  city's map only while the player is inside, so from outside they looked blurry. `tools/build_world_map.py` now
  bakes each city as the Classic zone map paints it into the tiles: its zone's map inside the frame (OpenMap's
  MapEdge), the neighbouring zone maps where that ends, Durotar mirrored into the rest of Orgrimmar's hole, and
  the zone's name banner (OpenMap's MapBanner) on top, placed by UiMapAssignment (`map_rects`). Rebuilt: 27
  tiles round the six cities and base.jpg changed. Stormwind's north-west corner (outside Elwynn's map) stays a
  little soft.

### Desktop: the game's UI textures, motion, first-start wizard (2026-10-19)
- User picks from the brainstorm. Skin: `tools/build_ui_skin.py` reads Classic UI textures from the install and
  composes them (Pillow) into nine-slice pictures in `ui/assets/skin/` (in git, 21 files, ~340 KB): dialog frame on
  marble (panels), tooltip border in silver/gold (cards, group boxes, tooltips, menus), UI-Panel-Button
  up/hover/down/disabled plus a gold-bordered "selected" one (checkable buttons that are on), the character
  frame's hanging tabs for the bottom tabs, Common-Input-Border (its top 20 px) for fields, UI-CheckBox, the slider
  gem and UI-Background-Rock for the window. `theme.SKIN_STYLESHEET` is appended when the pictures exist and makes
  plain widgets transparent, so panels show through. The cinematic controls opt out (`border-image: none`).
  Form pages (Import, Einstellungen, Diagnose; `Page.scrollable`) now sit in a scroll area, since the frames are
  thicker; pages hear `Page.leave()` when the window shows another one.
- Motion (`ui/motion.py`, option `extra.ui_motion` under Einstellungen → Oberfläche): page changes crossfade
  (snapshot over the new page, 200 ms); buttons, tabs and clickable cards get a gold drop-shadow glow easing in and
  out (180 ms, only while shown); after an import with new events (`AppContext.imported`, import_ids;
  `Repository.events_of_imports`) a toast per character slides in at the top right (highest level, else an
  achievement/dungeon/rare/zone, else the number of entries).
- First-start wizard (`ui/setup_wizard.py`): welcome + language, game folder (auto or chosen), addon installed and
  its version against `setup_addon.bundled_addon()` (repo or friends' package; installs/updates with
  `install_addon`), saved files per account + import now + automatic import, summary. Opens by itself while no
  character exists and `extra.setup_done` is unset (`AppContext.needs_setup`), before the sound offer; also under
  Datei → Einrichtung and from the home screen's new "Erste Schritte" card (shown while there are no characters).

### Cinematic: the game's experience bar (2026-10-19)
- User request. A player frame (portrait, level, health/mana) top left was built and removed again the same day at
  the user's request, with what only it needed (the addon's `info.sex`, the race portraits and unit frame
  textures). The top bar shows name and level as before. Do not bring the portrait back without asking.
- XP bar (`ui/cinematic_hud.py`) in the bottom letterbox bar, as the game draws it: its frame with twenty bubbles
  (`skin/xp_frame.png`, 1024×15, from UI-MainMenuBar-Dwarf's four pieces) over UI-StatusBar in the game's purple
  (`skin/xp_fill.png`, 0.58/0/0.55), with "EP: 11510 / 27300" on it (the points count along as the fill glides; a
  level-up fills up, flashes and wraps). Width 1024 × bar/72 (clamped). `domain/experience.py` `values(t)`: exact
  from the addon's minute samples (the "metrics" stream, imported since now: table `metrics`, migration 11): a
  level's size is the experience between its level-ups; the bar as last seen (`info.xp`/`xpMax`/`xpAt`, new in the
  addon, columns `xp`, `xp_max`, `xp_at`) starts and sizes the current level; other levels use the Classic XP table.
  Without samples (friends): the share by playing time between level-ups ("EP: 42 %"), nothing in the level still
  going. Rested experience is not recorded (blue part not shown).
- Addon (0.15.0, not uploaded): `Progress.lua` saves `info.xp`, `xpMax`, `xpAt` on every XP change and at login;
  companion 0.14.4 shares them. Copied to the game folder and hash-checked. Until the next login with this version
  the current level's bar is only known from level-ups inside the samples.

### Cinematic: fly-to teleports, time of day, end credits, the game's sounds (2026-10-19)
- User picks from a brainstorm. All desktop only; options in Einstellungen → "Kino-Modus" (`extra.cine_daylight`,
  `cine_credits`) and "Klänge aus dem Spiel" (`extra.game_sounds`), all on by default.
- Teleports fly (seamless world map): `domain/cinematic.teleports` finds steps much faster than any mount, longer than
  ~450 yards, with at most 120 s (a loading screen) between. A jump to the other continent counts only after
  standing ≥ 5 s before it (hearthstone cast); otherwise it is a boat/zeppelin and keeps the sea crossing. The flight
  reuses `_Voyage` (kind "teleport"/"spirit"): arcane swirl, camera out until both ends fit, a comet on a dotted arc,
  a flash on arrival, the game's teleport sound. The ghost's release to the graveyard flies as a pale wisp. On the
  user's data: 4 hearthstones, 3 of them to the same inn (Crossroads), one from Tirisfal across the sea.
- Fog of war was built the same day and removed again at the user's request (a dark cloud picture over the world
  map that the route uncovered). Do not bring it back without asking.
- Time of day (`domain/daylight.py`): keyframes by the recorded local hour (night 21.5–5, dawn 6, dusk 19.5),
  multiplied onto the map art (`SkyItem`, z 1; route z 2, pins and marker above keep their colours).
- End credits (`domain/credits.py`, `ui/cinematic_credits.py`): at the end the camera pulls back over the whole route
  (never past the world map), the map dims, the music switches to the chosen theme, credits roll (playtime, level,
  km on foot and in flight, teleports, standing time, longest zone, zones, discovered, dungeons, quests,
  achievements, rares, bosses, screenshots, deaths, most frequent cause) with the screenshots drifting by, and end on
  a "Journey Forever" card. Distances use continent widths of 36,800 (Kalimdor) and 40,741 (Eastern Kingdoms) yards
  (community map data, an estimate). Dungeons are instances with a boss kill only: "Ruins of Lordaeron" (Undercity)
  is an instance too and neither its music nor its entrance tells it apart. The export keeps recording until the
  credits' last card has stood (`credits_seconds`); a whole replay's video gets ~45 s longer.
- The game's sounds (`wow/game_sounds.py`): levelup.ogg 567431, iquestcomplete.ogg 567439 (event chime),
  achievmentsound1.ogg 569143, ignewtaxinodediscovered.ogg 567497 (discovery), iuiinterfacebuttona.ogg 567481
  (click), resurrection.ogg 568667 (revive), teleport.ogg 569735. Names via the wago.tools listfile API
  (`https://wago.tools/api/files?search=...`); the root file in this client has no names for sounds. Death and
  screenshot keep the built-in bell and shutter (the game has none). Not heard yet by the user.

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
