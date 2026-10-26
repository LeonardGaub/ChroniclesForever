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
  already reads (info, stats, gear, professions, last 200 events, the route of all sessions (newest 20,000 points), sessions, the maps,
  instances and entrances used), plus the sender's name and addon version.
- **Sharing settings in game:** "Teilen" settings section with the name for friends (free text), per character
  on/off, and per category on/off. Default: everything on. Screenshots (since 2026-10-16): the addon
  shares the records and `screenshotFiles` ({ [stamp] = "<character>-<realm>" }); the sync script uploads the
  pictures, scaled to 1920 px wide, to `<cloud>\screenshots\<player file name>\<character>-<realm>\` and removes
  the ones no longer shared. Friends' desktop apps copy them to `%APPDATA%\ForeverChronicle\friend_screenshots\`
  (same folders) and link them to the records, so the cinematic, Chronik and gallery show them (the game cannot).
- **Sync script** (`ForeverSync.ps1`, PowerShell, built into Windows, no extra app). It runs from the repository
  clone and only when asked (user decision 2026-10-16, version 3): the desktop app's "Jetzt abgleichen" (Import
  page, also File menu / F5) or `sync\Abgleichen.bat` (versions 1 and 2 ran by themselves from a Startup entry;
  every PC has moved past them). The setup (the app's "Einrichten und abgleichen" or `sync\Einrichten.bat`)
  remembers the clone, finds the shared cloud folder ("Journey Forever Cloud" in OneDrive, else asked; any synced
  folder works) and the game folder (Battle.net records, then the usual folders), then syncs once. Each run:
  1. addon update: if `<repo>/addons/` holds a newer version (after a `git pull`), mirrors it into the game's
     AddOns folder (keeps `Friends\FriendsData.lua`); only while WoW is not running, otherwise next run;
  2. upload: copies each account's `ForeverChronicle_Share.lua` to `<cloud>/players/<name>-<id>-<account>.lua`
     when it changed (one file per person and account; nobody writes another's file). `<name>` is the name
     friends see (letters and digits), `<id>` the first 8 characters of the shareId; when the name changes the
     old file is removed;
  3. download: reads all other players' files, accepts them only if they are pure data (strict literal-only
     check, size limit), and writes `Friends\FriendsData.lua` (one function per friend); visible after `/reload`;
  4. backup: once a day copies the addon's SavedVariables to a local backup folder (newest 10 kept);
  5. log file `%LOCALAPPDATA%\ForeverChronicle\sync\sync.log`. The desktop app shows from it and from the cloud
     folder what is where: my uploads, friends' files and how many of them the game's friends file holds.
- **Releases:** a new addon version is published by pushing it to the repository; after a `git pull` everyone's
  next sync installs it, also on the developer's own PC. The cloud folder holds only `players/` (2026-10-15; until
  then it also had `addon/` and `tools/`).
- **Desktop app:** optional (long history beyond the SavedVariables caps, screenshot gallery). It stops writing
  `FriendsData.lua` (the script owns it); share files and the share dialog are removed. Since 2026-10-16 every
  import (at start, "Jetzt importieren", after "Jetzt abgleichen") also reads the friends' files from the cloud
  folder (`importing/friend_importer.py`): read-only characters under each friend (one owner per file,
  `<id>-<account>`); a newer file adds to what the app has (so it keeps history beyond the share file's limits),
  a character no longer shared goes, a friend whose file is gone is removed.
- **Postponed:** addon messages between online friends (cloud sync already brings all data, also offline; maybe
  later for live info such as who is online where).
- **Limits:** new data arrives after the sender's logout or `/reload` and their sync, then the receiver's sync, and
  is shown after the receiver's `/reload` (OneDrive must be running on both PCs). History in game is limited by the SavedVariables caps; daily backups keep older states.

---

## Version 1 (share files; superseded by version 2, removed)
Version 1 (2026-10-14) exchanged `.fcshare` files (a ZIP of the JSONL export plus picked screenshots) by hand and
grouped friends' characters under owners in the desktop app. Version 2 replaced it; the desktop share files, the
share dialog and the legacy share IDs are gone. The character layer round the addon window came from it and stays
(ARCHITECTURE.md), and so does **no re-sharing:** friends' characters are never exported again (not in uploads, not
in the JSONL backup export).

## In game
The addon cannot download anything, so friends' data reaches it as a Lua data file that the sync script writes:
`Interface\AddOns\ForeverChronicle_Share\Friends\FriendsData.lua`, listed in the companion's TOC (an empty
placeholder ships with it). Unlike SavedVariables, the client never writes this file back, so it can be updated
while the game runs; the new data appears after `/reload` or the next login.
- **Safety:** the game executes this file and the data comes from other people. The sync accepts a friend's file
  only if it is pure data (a strict literal-only check: numbers, strings, tables; no names, calls or long strings)
  and loads each friend alone in an empty sandbox; tested against injection attempts (quotes, `]]`, newlines).
- **Size:** the client loads the file into memory at every login. Sized for ~10 friends × several characters
  (~50 characters): per character the overview and stats, the last 200 chronicle events and the newest
  20,000 route points of all sessions (compact strings, about 1 MB per character at most; the sync skips friend
  files over 8 MB and stops at 60 MB in all).
- **Install note:** the addon install/mirror step must not delete `Friends\FriendsData.lua`.
