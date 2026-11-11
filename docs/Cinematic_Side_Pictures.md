# Cinematic: screenshots at the side

Status: designed 2026-11-09 (user grilled through 16 questions) and built the same day: `SideShots` in
`desktop/forever_chronicle/ui/cinematic_fx.py`, the replay's part in `ui/cinematic.py` (`SIDE_*` constants,
`_advance_side`), `is_big` in `domain/cinematic.py`, tests in `desktop/tests/test_cinematic_side.py`.

## Why

Today every screenshot slows the replay (1.5 s), stops it while the polaroid is shown in the centre (5.5 s) and
ramps back (1 s): about 8 s per picture. A journey with 60 screenshots spends ~8 minutes standing still, and
zone discoveries come in bursts (46 of 147 screenshots in the local database).

## Decisions

| Topic | Decision |
|---|---|
| Version | A setting picks the style; the new side style is the default, the old centre pauses stay available. |
| Setting | Settings tab only, in the cinematic box (next to daylight, credits, ambience). |
| Placement | No columns: one pile floats over the right edge of the full-screen map (first built as two stacks, left and right by turns; changed the same day after the first look). |
| Stack | Up to 5 pictures: the newest on top, each older one peeking out a little lower and further in, so its place · date strip shows; a sixth pushes the oldest off. |
| Size | About 22 % of the window width per picture (~420 px at 1920 px). |
| Arrival | A small flash at the marker, then the polaroid flies out of the marker to its side and lands on top of that stack. |
| Quiet time | Each picture fades out after a while (~20–30 s real time) without newer ones; the map is plain again. |
| Bursts | Pictures queue and land at least ~1.5 s apart, even if the replay has moved on a little. |
| Speed | The replay never stops for a picture. Big moments slow it gently to ~50 % for ~2 s, then back to speed. Others don't slow it at all. |
| Big moments | Level-ups, dungeon completed / boss killed, manual screenshots and /fj moments. |
| Caption | A compact achievement-style banner (heading + title, icon) above the polaroid, plus the handwritten place · date strip under the picture. |
| Level-up | The big centred level title shows as today, and its screenshot flies to its side at the same moment. |
| Alerts | Event toasts move from the top right to the top centre, under the letterbox bar. |
| Interaction | Clicking a side picture pauses the replay and shows it large in the centre (today's polaroid view); click or Space goes on. |
| Export | The video export follows the setting. |
| 3D | Built for the 2D cinematic on main; the 3D branch (investigate/3d-map-viewer) picks it up when merged. |

## Defaults taken without asking (change if wanted)

- The camera keeps the marker away from the right while pictures stand there.
- Map pins (the small polaroid where a screenshot was taken) stay as today.
- Deaths, teleports, the intro and the end credits are unchanged.
- An event whose screenshot is shown still gets no separate toast (the picture's banner names it).
- The timeline's "next moment" key and marks work as today; a jump clears the stacks.
- The pictures underneath peek out lower, further in and a little smaller, in deepening shade; their banners fade as a newer one covers them. The whole pile stands centred in the picture.
- The "fast-forward" standstill note moves from the top centre to the bottom centre (the alerts are there now).
- A big moment slows the replay over the last second before it and speeds back up over the second after.
