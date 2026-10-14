# Journey Forever – Changelog

Player-facing changes to the main addon (`addons/ForeverChronicle`), collected for the next CurseForge upload.
Add an entry with every addon change. When uploading, paste the section into the CurseForge changelog field,
then turn "Unreleased" into the uploaded version and date.

## Unreleased (0.15.0)

### New
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

### Fixed
- Saved data no longer stops loading when it grows large. The game refuses a saved file with too many separate
  values (several characters with long histories could reach that), and the addon would then have started
  empty. The addon now stores many records together in the saved file. Older addon versions do not open the
  new format and leave it untouched, so going back to an older version cannot overwrite your data.
- Map: a hearthstone or portal no longer draws a route line across the whole map. The route now breaks at
  every teleport, including on routes recorded with earlier versions and on friends' routes.

## 0.14.1 – 2026-10-14

Last CurseForge build (`dist/curseforge/JourneyForever-0.14.1.zip`).
