-- Forever Chronicle - friends: texts (German default, English fallback like the main addon).
local FC = ForeverChronicle

FC:RegisterLocale("deDE", {
  VIEW_NO_FRIENDS = "Noch keine Freunde: ihre Charaktere kommen über den gemeinsamen Cloud-Ordner (danach /reload).",
  SECTION_SHARE = "Mit Freunden teilen",
  OPT_SHARE_NAME = "Dein Name für Freunde",
  OPT_SHARE_NAME_TIP = "So sehen dich deine Freunde in ihrer Charakterauswahl. Leer = Name deines Charakters.",
  OPT_SHARE_CHARS = "Geteilte Charaktere",
  OPT_SHARE_STATS = "Statistiken",
  OPT_SHARE_CHRONICLE = "Chronik (letzte 200 Einträge)",
  OPT_SHARE_ROUTES = "Routen (letzte 3 Sitzungen)",
  OPT_SHARE_SESSIONS = "Sitzungen und Spielzeit",
  OPT_SHARE_PROFESSIONS = "Berufe und Rezepte",
  OPT_SHARE_GEAR = "Ausrüstung",
  CAP_SHARE = "Teilen (Freunde-Daten-Addon)",
  CMD_SHARE = "zeigt, was mit Freunden geteilt wird (gespeichert beim Logout und /reload)",
  SHARE_SUMMARY = "Geteilt werden %d Charakter(e) als \"%s\" - %s",
  SHARE_READY = "wird beim nächsten Logout oder /reload gespeichert.",
  SHARE_ADDON_MISSING = "das Addon \"Forever Chronicle - Freunde-Daten\" ist nicht aktiv, daher wird nichts geteilt.",
})

FC:RegisterLocale("enUS", {
  VIEW_NO_FRIENDS = "No friends yet: their characters arrive through the shared cloud folder (then /reload).",
  SECTION_SHARE = "Share with friends",
  OPT_SHARE_NAME = "Your name for friends",
  OPT_SHARE_NAME_TIP = "How your friends see you in their character chooser. Empty = your character's name.",
  OPT_SHARE_CHARS = "Shared characters",
  OPT_SHARE_STATS = "Statistics",
  OPT_SHARE_CHRONICLE = "Chronicle (last 200 entries)",
  OPT_SHARE_ROUTES = "Routes (last 3 sessions)",
  OPT_SHARE_SESSIONS = "Sessions and play time",
  OPT_SHARE_PROFESSIONS = "Professions and recipes",
  OPT_SHARE_GEAR = "Gear",
  CAP_SHARE = "Sharing (friends data addon)",
  CMD_SHARE = "shows what is shared with friends (saved on logout and /reload)",
  SHARE_SUMMARY = "Sharing %d character(s) as \"%s\" - %s",
  SHARE_READY = "saved on the next logout or /reload.",
  SHARE_ADDON_MISSING = "the addon \"Forever Chronicle - Freunde-Daten\" is not enabled, so nothing is shared.",
})
