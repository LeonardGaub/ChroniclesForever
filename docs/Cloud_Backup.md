# Cloud backup and friends (decided 2026-10-27)

Replaces the friends sync (companion addon `ForeverChronicle_Share`, share files, `sync/ForeverSync.ps1`,
`FriendsData.lua`, friends in game), which the user found far too complicated. The user's rules:

- When the game starts or quits, back up all screenshots and the addon file to the cloud. A button in the desktop
  app does the same by hand.
- No friend invites. The player sets the cloud folder by hand; their data is backed up there.
- The data always exists locally and in the cloud: nothing is overwritten, nothing gets lost.
- Friends upload the same way into the same folder; the desktop import reads everyone's data. Friends are shown
  only in the desktop app, not in game.

## Layout
One cloud folder, chosen in the desktop app (Import page, "Cloud-Sicherung"); any folder a cloud client syncs
works, e.g. a shared OneDrive folder. Each player types a name; it is their folder:

```
<cloud>\<name>\addon\<account hash>\ForeverChronicle_<YYYY-MM-DD_HHMMSS>_<PC>.lua   the newest 30 are kept
<cloud>\<name>\database\chronicle_<YYYY-MM-DD_HHMMSS>_<PC>.db                       the newest 30 are kept
<cloud>\<name>\screenshots\WoWScrnShot_*.jpg                                         full size, never deleted
```

The account hash hides the WoW account number. My second PC uses the same name and lands in the same folder; each
copy's name says which PC made it. Every other folder with an `addon\` folder is a friend's; the old layout
(`players\`, `screenshots\`, `roaming\`) is ignored and can be deleted by hand once every friend has backed up once.

## Backing up (`desktop/forever_chronicle/cloud_backup.py`, `ui/backup_runner.py`)
- When: WoW starts, WoW was closed (15 s without a WoW process from the client folder, so the saved file is
  written and a restart is no end; closing imports first), at app start if anything changed since this PC's last
  backup, and by hand ("In die Cloud sichern", F5). Only while the app is open: the addon cannot write files or
  start programs.
- What: per WoW account the addon file, a new copy only when it changed since this PC's last backup (hash in
  `%APPDATA%\ForeverChronicle\cloud_backup.json`); the app database (SQLite backup API, made in the main thread, a
  new copy when its bytes changed); every screenshot the cloud does not have yet. Copies go through a temporary
  file and a rename. Local files are never changed by a backup. The file copies run in a worker thread.
- Settings: `extra.cloud_folder` and `extra.cloud_name` in the app's config. At the first start after the change the
  app takes the old sync's cloud folder and the old share name as a start (`adopt_old_settings`).

## Restoring (`ui/restore_dialog.py`)
"Aus der Cloud wiederherstellen …": an addon copy (newest preselected; any PC; WoW must be closed), the screenshots
missing here, a database copy. What is replaced is saved first: the addon file in
`%APPDATA%\ForeverChronicle\backups\before-restore\`, the database through `Database.restore` (its own backup).
There is no merge: playing on two PCs means restoring before switching.
- The hint: at app start, if my folder holds a copy from another PC that is newer than this PC's file and differs
  from it, a banner above the page offers the restore (preselected). It compares with the local file's time, so this
  PC backing up its older file does not hide it. Nothing happens by itself.

## Friends (`importing/friend_importer.py`, `importing/friend_screenshots.py`)
- Every friend folder: the newest addon copy per account, imported read-only under one owner per folder
  (`share_id` `player:<folder>`); a newer copy adds to what the app has (entries by ID, points by time), a character
  no longer in their files goes, a folder that is gone takes the friend with it. A cloud folder that is not there
  (OneDrive offline) changes nothing. Friends see everything (no per-category settings any more).
- Their pictures: only those their screenshot records point to are copied to
  `%APPDATA%\ForeverChronicle\friend_screenshots\<friend>\` and linked.

## Addon install
The app installs a newer addon from the repository at start (WoW closed; `setup_addon.update_addon`), and every
install removes the old companion folder `ForeverChronicle_Share`. Friends: `git pull`, start the app, set the
cloud folder and their name once.

## Limits
- No backup while the app is closed (the catch-up at the next start covers it).
- Two PCs are not merged: playing on PC B without restoring first and restoring later replaces PC B's newer sessions
  (they stay as copies in the cloud and in `before-restore`).
- Full-size screenshots of every player count against the shared folder owner's OneDrive space.
- OneDrive's own version history is an extra safety net.
