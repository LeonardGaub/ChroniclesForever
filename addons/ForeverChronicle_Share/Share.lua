-- Journey Forever - friends: Share module (docs/Sharing_Design.md, version 2: cloud sync)
-- Part of ForeverChronicle_Share, the companion addon for a private friend group (not part of the main addon).
-- On every logout and /reload, writes the data meant for friends into ForeverChronicleShareDB, this addon's
-- saved variable. The game saves it as its own file (SavedVariables\ForeverChronicle_Share.lua), which the
-- sync script copies to the shared cloud folder.
--
-- ForeverChronicleShareDB = { format = 1, addonVersion, name, generatedAt,
--   characters = { <character record in the addon's own shape, trimmed> },
--   maps = { [mapID] = geometry }, instances = { [id] = name }, entrances = { [id] = { mapID, x, y } },
--   screenshotFiles = { [fileStamp] = "<name>-<realm>" } }
--
-- Settings ("Teilen" section): the name friends see, per character on/off, per category on/off.
-- Default: everything shared. The screenshots category shares the screenshot records; the pictures themselves
-- (the game cannot show them) are uploaded by the sync script, which finds each picture and its character through
-- screenshotFiles, and friends see them in the desktop app.

local FC = ForeverChronicle -- the main addon (dependency, loaded first)
local L = FC.L

local Share = FC:NewModule("Share", { order = 60, defaults = {
  name = "",
  chars = {},          -- [characterKey] = false to exclude a character
  cats = { stats = true, chronicle = true, routes = true, sessions = true, professions = true, gear = true,
    screenshots = true },
} })

Share.FORMAT = 2               -- 2: streams packed (FC.Storage.Pack)
Share.SHARE_ADDON = "ForeverChronicle_Share"
Share.EVENTS = 200               -- newest chronicle entries per character
Share.MAX_POINTS = 20000         -- newest route points per character (all sessions; about 1 MB at most)
Share.CATEGORIES = { "stats", "chronicle", "routes", "sessions", "professions", "gear", "screenshots" }
local SHOT_FIELDS = { "id", "seq", "trigger", "events", "requestedAt", "capturedAt", "fileStamp", "status" }

local INFO_FIELDS = { "key", "guid", "name", "nameSuffix", "realm", "className", "classFile", "raceName", "raceFile",
  "faction", "level", "xp", "xpMax", "xpAt", "firstSeenAt", "lastSeenAt" }

local function newest(list, n)
  local out = {}
  for i = math.max(1, #list - n + 1), #list do out[#out + 1] = list[i] end
  return out
end

-- The route of all sessions (compact strings "time,..."), the newest MAX_POINTS points. Until 2026-10-16 only the
-- newest 3 sessions were shared, so friends missed the start of a journey.
local function routes(char)
  local positions = char.streams and char.streams.positions and char.streams.positions.records or {}
  local out = {}
  for _, text in ipairs(positions) do
    if type(text) == "string" and text:match("^%d+,") then out[#out + 1] = text end
  end
  return newest(out, Share.MAX_POINTS)
end

-- Screenshots that were taken (a file exists): their records without the error text.
local function shots(char)
  local out = {}
  for _, r in ipairs(char.streams and char.streams.screenshots and char.streams.screenshots.records or {}) do
    if type(r) == "table" and r.fileStamp and (r.status == "confirmed" or r.status == "api_called") then
      local copy = {}
      for _, field in ipairs(SHOT_FIELDS) do copy[field] = r[field] end
      out[#out + 1] = copy
    end
  end
  return out
end

-- One character's record for friends, limited to the shared categories.
function Share:BuildCharacter(key, char)
  FC.Storage.UnpackCharacter(char) -- packed when built after the save preparation (e.g. a second logout handler)
  local cats = self:GetSettings().cats
  local info = {}
  for _, field in ipairs(INFO_FIELDS) do info[field] = char.info[field] end
  info.key = info.key or key
  local record = { info = info, streams = {}, snapshots = {} }
  if cats.stats then record.stats = char.stats end
  local streams = char.streams or {}
  if cats.chronicle and streams.events then
    record.streams.events = { records = newest(streams.events.records or {}, self.EVENTS) }
  end
  if cats.sessions and streams.sessions then record.streams.sessions = { records = streams.sessions.records } end
  if cats.routes then
    local points = routes(char)
    record.streams.positions = { nextSeq = #points + 1, records = points }
    if not cats.sessions and streams.sessions then -- the map's session filter needs the session times
      local times = {}
      for _, s in ipairs(streams.sessions.records or {}) do
        times[#times + 1] = { startedAt = s.startedAt, endedAt = s.endedAt }
      end
      record.streams.sessions = { records = times }
    end
  end
  local snapshots = char.snapshots or {}
  if cats.professions then record.snapshots.professions = snapshots.professions end
  if cats.gear then record.snapshots.gear = snapshots.gear end
  if cats.screenshots then
    local list = shots(char)
    if #list > 0 then record.streams.screenshots = { records = list } end
  end
  return record
end

-- Maps, instances and entrances that the shared events and routes refer to.
local function places(characters)
  local mapIDs, instanceIDs = {}, {}
  for _, char in ipairs(characters) do
    for _, text in ipairs(char.streams.positions and char.streams.positions.records or {}) do
      local map, inst = text:match("^%d+,(%d*),[^,]*,[^,]*,[^,]*,[^,]*,(%d*)$")
      if map and map ~= "" then mapIDs[map] = true end
      if inst and inst ~= "" then instanceIDs[inst] = true end
    end
    for _, e in ipairs(char.streams.events and char.streams.events.records or {}) do
      local loc = e.location
      if loc and loc.mapID then mapIDs[tostring(loc.mapID)] = true end
      if loc and loc.instanceID then instanceIDs[tostring(loc.instanceID)] = true end
    end
  end
  local maps = {}
  for id in pairs(mapIDs) do
    local info = FC.db.maps and FC.db.maps[id]
    if info then
      maps[id] = info
      if info.continent and FC.db.maps[tostring(info.continent)] then
        maps[tostring(info.continent)] = FC.db.maps[tostring(info.continent)]
      end
    end
  end
  local instances, entrances = {}, {}
  for id in pairs(instanceIDs) do
    instances[id] = FC.db.instances and FC.db.instances[id]
    entrances[id] = FC.db.entrances and FC.db.entrances[id]
  end
  return maps, instances, entrances
end

-- Builds the whole share data (all shared characters of this account).
function Share:Build()
  local s = self:GetSettings()
  local characters = {}
  for key, char in pairs(FC.db.characters) do
    if type(char) == "table" and type(char.info) == "table" and char.info.name and s.chars[key] ~= false then
      characters[#characters + 1] = self:BuildCharacter(key, char)
    end
  end
  table.sort(characters, function(a, b) return (a.info.lastSeenAt or 0) > (b.info.lastSeenAt or 0) end)
  local maps, instances, entrances = places(characters)
  -- Which character took which picture, for the sync script (the character records are packed in the file).
  local files = {}
  for _, char in ipairs(characters) do
    local folder = char.info.realm and (char.info.name .. "-" .. char.info.realm) or char.info.name
    for _, r in ipairs(char.streams.screenshots and char.streams.screenshots.records or {}) do
      files[r.fileStamp] = folder
    end
  end
  local name = s.name ~= "" and s.name or (FC.char and FC.char.info.name) or "?"
  return { format = self.FORMAT, addonVersion = FC.VERSION, name = name, generatedAt = time(),
    characters = characters, maps = maps, instances = instances, entrances = entrances, screenshotFiles = files }
end

function Share:IsShareAddonLoaded()
  local isLoaded = C_AddOns and C_AddOns.IsAddOnLoaded or IsAddOnLoaded
  return type(isLoaded) == "function" and isLoaded(self.SHARE_ADDON) and true or false
end

-- Writes the share data; the game saves it right after (logout or /reload).
function Share:Write()
  if not self:IsShareAddonLoaded() then return false end
  local db = self:Build()
  -- Packed like the main file (many records per string), so the file and FriendsData.lua stay loadable.
  for _, char in ipairs(db.characters) do FC.Storage.PackCharacter(char) end
  ForeverChronicleShareDB = db
  return true
end

Share:RegisterEvent("PLAYER_LOGOUT", function(self) self:Write() end)

FC:RegisterCapability("share", "CAP_SHARE", function() return Share:IsShareAddonLoaded() end)

-------------------------------------------------------------------------------
-- Settings: "Teilen"
-------------------------------------------------------------------------------

FC:RegisterOptionSection("share", "SECTION_SHARE", 60, "Interface\\Icons\\INV_Letter_15")
FC:RegisterOption({ section = "share", module = "Share", key = "name", type = "text", labelKey = "OPT_SHARE_NAME",
  tooltipKey = "OPT_SHARE_NAME_TIP", order = 1, maxLetters = 32 })

for i, cat in ipairs(Share.CATEGORIES) do
  FC:RegisterOption({ section = "share", type = "toggle", column = 2, order = 10 + i,
    labelKey = "OPT_SHARE_" .. cat:upper(),
    get = function() return Share:GetSettings().cats[cat] ~= false end,
    set = function(value) Share:GetSettings().cats[cat] = value end })
end

-- Per character on/off: one check box per character of this account.
FC:RegisterOption({ section = "share", type = "custom", order = 2, create = function(c)
  local UI = FC.UI -- the UI files load after the modules
  local row = CreateFrame("Frame", nil, c)
  local label = UI:Label(row, "OPT_SHARE_CHARS", "GameFontHighlight")
  label:SetPoint("TOPLEFT", 4, 0)
  local keys = {}
  for key, char in pairs(FC.db.characters) do
    if type(char) == "table" and type(char.info) == "table" and char.info.name then keys[#keys + 1] = key end
  end
  table.sort(keys, function(a, b) return FC.db.characters[a].info.name < FC.db.characters[b].info.name end)
  row.boxes = {}
  for i, key in ipairs(keys) do
    local info = FC.db.characters[key].info
    local cb = UI:CheckBox(row, nil, nil, function(checked)
      if checked then Share:GetSettings().chars[key] = nil else Share:GetSettings().chars[key] = false end
    end)
    cb:SetPoint("TOPLEFT", label, "BOTTOMLEFT", -4, -2 - (i - 1) * 24)
    cb.label:SetText(UI:ClassColored(info.name, info.classFile))
    cb.key = key
    row.boxes[i] = cb
  end
  row:SetSize(250, 22 + #keys * 24)
  row.height = 28 + #keys * 24
  row.Sync = function(self)
    for _, cb in ipairs(self.boxes) do cb:SetChecked(Share:GetSettings().chars[cb.key] ~= false) end
  end
  return row
end })

FC:RegisterCommand("share", "CMD_SHARE", function()
  local data = Share:Build()
  FC:Print(string.format(L.SHARE_SUMMARY, #data.characters, data.name,
    Share:IsShareAddonLoaded() and L.SHARE_READY or L.SHARE_ADDON_MISSING))
end, 60)
