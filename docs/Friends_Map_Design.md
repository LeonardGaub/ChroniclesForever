# Friends' routes on the map: design note

Status: idea, written down 2026-10-14 at the user's request. Not built yet. It belongs to the friends companion
(`ForeverChronicle_Share`), not to the CurseForge addon.

## Goal
See your own route and your friends' routes on the same map: where everyone went, who reached a zone first, and
where you met.

## What is already there
- The companion shares each friend character's route from its **last 3 sessions**, at most **20,000 points**
  (`Share.ROUTE_SESSIONS`, `Share.MAX_POINTS`), in the same compact format as the positions stream. It also
  shares the map geometry, instances and dungeon entrances the route uses.
- The sync script writes them into `Friends\FriendsData.lua` (one function per friend). The character chooser
  already shows a friend's character read-only, with the same map page.
- The map page draws one character at a time (`FC:ViewStream`). Route logic in `Core/Route.lua` works on any
  list of points.

## Features (in order of value)
1. **Ghost routes.** On the map page, an "Add friends" button lists friend characters that have points on the
   shown map. Each chosen one is drawn as a thinner line in its own colour (class colour, or a fixed palette when
   two share a class), under your own route. The legend shows name and colour. Painting and the 15-minute trail
   work the same way, so a replay shows everyone moving at once.
2. **Replay together.** One time slider for everyone; each friend gets their own marker with a name tag. Only
   time when at least one shown character has points counts on the timeline.
3. **Level race.** Instead of the date, line up the characters by **level** (time since reaching level N) or by
   **play time since level 1**, and replay them side by side: who was where at level 20, who reached
   Stranglethorn first. Needs `level_up` events of the friend's character (already shared, last 200 events) and
   for the play-time version the sessions (shared).
4. **"Met here" markers.** Places where you and a friend were on the same map within a short distance at the
   same time (for example under 0.01 map units for at least 30 s). Shown as a small double icon with the time;
   clicking jumps there.

## Open questions
- **How much route to share.** Three sessions is too little for a level race. Options: share more sessions, or
  share the thinned route archive (`routeArchive`, many points per record) for older sessions. The archive
  keeps the file small.
- **Size of `FriendsData.lua`.** It is loaded at every game start like saved variables, so the same limits
  apply: file size and load time, and possibly the Lua limit of about 262,000 distinct constants per function.
  One function per friend helps. The in-game load test (October 2026) shows whether that limit is real.
- **Performance.** Drawing several routes at full detail costs line regions in game (the canvas caps at 5,000
  lines). Friends' routes could use the coarser line merging, and only for the shown map and time range.
- **Desktop.** The desktop app could show the same overlay in its cinematic mode with screenshots, but friends'
  screenshots are never shared, so only routes and events.
- **Privacy.** The current sharing settings (per character and per category) also cover this; no new setting is
  needed unless friends want to hide routes from the race.
