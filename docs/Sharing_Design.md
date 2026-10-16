# Friends' characters: design

## Version 2: cloud sync, in-game first (decided 2026-10-14, replaces share files)
The user wants to move mostly into the addon: the desktop app is hard to keep updated on friends' PCs. Share
files and the desktop share dialog are no longer needed.

- **Split (2026-10-14, for CurseForge):** everything about friends lives in the companion addon
  `ForeverChronicle_Share` (Share module, settings, friends view source, `Friends/FriendsData.lua`); the main addon
  is standalone and is what goes to CurseForge. The companion is only distributed through the git repository
  (2026-10-15: the friends have access; the cloud folder holds player data only).
- **Data:** a second addon `ForeverChronicle_Share` declares `## SavedVariables: ForeverChronicleShareDB`,
  so the game itself writes a separate, small file with only the data meant for friends. The main addon fills it on
  every logout and `/reload`: one entry per character of the account, in the record shape the character chooser
  already reads (info, stats, gear, professions, last 200 events, routes of the last 3 sessions, sessions, the maps,
  instances and entrances used), plus the sender's name and addon version.
- **Sharing settings in game:** "Teilen" settings section with the name for friends (free text), per character
  on/off, and per category on/off. Default: everything on. Screenshots are not shared (the game cannot show images).
- **Sync script** (`ForeverSync.ps1`, PowerShell, built into Windows, no extra app). It is set up once by
  `sync\Einrichten.bat` in the repository clone: remember the clone, find the shared cloud folder ("Journey Forever
  Cloud" in OneDrive, else asked; any synced folder works), find the game folder (Battle.net records, then the
  usual folders), and register a hidden start at logon, repeating every 10 minutes. Each run:
  1. updates itself from `<repo>/sync/`;
  2. addon update: if `<repo>/addons/` holds a newer version (after a `git pull`), mirrors it into the game's
     AddOns folder (keeps
     `Friends\FriendsData.lua`); only while WoW is not running, otherwise next run;
  3. upload: copies each account's `ForeverChronicle_Share.lua` to `<cloud>/players/<name>-<id>-<account>.lua`
     when it changed (one file per person and account; nobody writes another's file). `<name>` is the name
     friends see (letters and digits), `<id>` the first 8 characters of the shareId; when the name changes the
     old file is removed. Since 2026-10-16; before that `<shareId>-<account>.lua`, still accepted from friends;
  4. download: reads all other players' files, accepts them only if they are pure data (strict literal-only
     check, size limit), and writes `Friends\FriendsData.lua` (one function per friend); visible after `/reload`;
  5. backup: once a day copies the addon's SavedVariables to a local backup folder (newest 10 kept);
  6. log file `%LOCALAPPDATA%\ForeverChronicle\sync.log`.
- **Releases:** a new addon version is published by pushing it to the repository; after a `git pull` everyone's
  script installs it, also on the developer's own PC. The cloud folder holds only `players/` (2026-10-15; until
  then it also had `addon/` and `tools/`).
- **Desktop app:** optional (long history beyond the SavedVariables caps, screenshot gallery). It stops writing
  `FriendsData.lua` (the script owns it); share files and the share dialog are removed.
- **Postponed:** addon messages between online friends (cloud sync already brings all data, also offline; maybe
  later for live info such as who is online where).
- **Limits:** new data arrives after the sender's logout or `/reload` plus the sync interval and is shown after
  the receiver's `/reload`. History in game is limited by the SavedVariables caps; daily backups keep older states.

---

## Version 1 (share files; superseded by version 2)

Goal: a few friends who all use Journey Forever see each other's characters, in the desktop app and in game.
This is the "future sharing" of the spec (§1, §2 out of MVP, privacy rules: opt-in per character and data category,
screenshots never automatic).

## Decisions (2026-10-14)
- **Transport:** a share file first (`.fcshare`, sent by hand, e.g. Discord). It is designed so a shared cloud
  folder (OneDrive, Dropbox, Google Drive) can exchange the same files automatically later. No server.
- **Audience:** a few trusted friends who run the addon and the desktop app.
- **Shareable, each opt-in per character:** stats and chronicle, routes, sessions and play times, and
  screenshots the user picks one by one.
- **Where:** desktop app and in game.
- **Sender name:** free text, chosen by the user (saved in the app settings).
- **No re-sharing:** friends' characters are never exported again (not in share files, not in the JSONL backup
  export; they come back by importing the friend's share file).
- **Scale:** about 10 friends with several characters each. In game all of them are listed in a scrollable list,
  with no limit on the number of characters; the data per character is trimmed instead (see In game).

## Share file (`.fcshare`)
A ZIP containing:
- `share.jsonl`: the existing JSONL format (header + records, characters referenced by GUID), limited to the
  shared characters and categories. The header adds `share_id` (random, stable per sender), `sender` (display name
  the user chooses), `created_at`, and `categories` per character.
- `screenshots/<screenshot_id>.jpg`: only the pictures the user picked, scaled down (e.g. 1600 px wide).

Categories map to record types:

| Category | Record types |
|---|---|
| stats and chronicle | character, character_stat, event, profession, recipe, recipe_category |
| routes | position, map_info, instance, instance_entrance |
| sessions and play times | session |
| screenshots (picked) | screenshot, screenshot_event + image files |

Never shared: import bookkeeping, gaps, stream state, file paths, WoW account folder name, app settings.

## Desktop
- **Character choice:** the sidebar is the character layer: my characters first ("Meine Charaktere"), then one
  group per friend. At start my own character is shown (the last one, if it is mine).
- **Owners:** a new table `owners` (owner_id, share_id, display_name, last_import_at), and `characters.owner_id`
  (NULL = me). The sidebar shows "Meine Charaktere" and one group per friend.
- **Read-only:** friends' characters can't be changed and are never included in my own share files or merged
  into my data.
- **Import rule:** the friend's newest file is the truth for their characters. Records of a shared category
  are replaced as a whole; a category no longer shared is removed. Files are matched by `share_id`, and an older
  file than the last imported one is ignored.
- **Sharing UI:** "Teilen …" dialog: pick characters, tick categories, pick screenshots (thumbnails, none
  pre-selected), choose sender name, then save `.fcshare` (later: write it to the shared folder).
- **Shared folder (later):** a folder setting; the app writes `<share_id>.fcshare` on change and imports
  every other `.fcshare` in it at start and on change.
- Friends' pages reuse the existing pages (overview, chronicle, map, professions, screenshots) with editing
  hidden; the map can additionally overlay a friend's route on mine (compare).

## In game
The addon cannot download anything. The desktop app must hand friends' data to it:
- **How:** the desktop app writes a Lua data file into the addon folder, e.g.
  `Interface\AddOns\ForeverChronicle\Friends\FriendsData.lua`, listed in the TOC (an empty placeholder ships with the
  addon). Unlike SavedVariables, the client never writes this file back, so it can be updated while the game runs;
  the new data appears after `/reload` or the next login.
- **Safety:** this file is executed by the game and the data comes from other people. It must be generated with a
  strict literal-only serializer (numbers, escaped strings, tables), never by pasting text, and tested against
  injection attempts (quotes, `]]`, newlines, `` in names).
- **Size:** the client loads the file into memory at every login. Sized for ~10 friends × several characters
  (~50 characters): per character the overview and stats, the last 200 chronicle events and the routes of the
  last 3 sessions (compact strings; target well under 5 MB for the whole file).
- **UI: a character layer around the whole window** (user decision 2026-10-14, replaces the separate
  "Freunde" tab). The window gets a character chooser at the top (the portrait / name area opens it):
  a scrollable list of all available characters, grouped as "Meine Charaktere" (every character of the
  account; the addon's SavedVariables already hold them all) and one group per friend (name, level, class,
  last seen). By default the window shows the character being played. Choosing another character makes every
  tab (overview, chronicle with its screenshots, map, professions) show that character, read-only for anyone but the
  one being played; a small banner names whose character is shown, with a button back to my own.
  Implementation: pages read their data through one accessor (e.g. `FC:ViewedCharacter()`) instead of
  `FC.char` directly; recording always keeps writing to the played character.
  Optional later: show a friend's route next to mine on the map tab.
- **Install note:** the addon install/mirror step must not delete `Friends\FriendsData.lua`.

## Phases
1. Desktop: owners model, share file export (categories, picked screenshots), import as read-only friend
   characters, sidebar grouping. Tests incl. hostile files (bad JSON, huge files, path tricks in the ZIP).
   **Done (desktop v0.3.0).**
2. In game: FriendsData.lua writer (safe serializer) + the character layer around the addon window (own
   characters of the account and friends' characters; default: the played character). Battle.net detection of
   the game folder. **Done (addon v0.11.0, desktop v0.4.0).**
3. Shared cloud folder: automatic write/import.
4. Optional: compare view (two routes on one map, levelling speed side by side).

