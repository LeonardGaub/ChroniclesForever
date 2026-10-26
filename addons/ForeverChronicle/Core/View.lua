-- Journey Forever - View
-- Which character the window shows (docs/Sharing_Design.md, phase 2). Recording always writes to the played
-- character (FC.char); the pages read through the view instead:
--   FC:ViewChar(), FC:ViewStream(name), FC:IsViewingPlayed(), FC:ViewOwner()
-- Available characters: every character of this account (FC.db.characters, all in the same SavedVariables)
-- plus whatever other addons add with FC:RegisterViewSource (characters in the same record shape, read-only).
-- After login the view is the played character.

local ADDON, FC = ...

local View = { key = nil, entry = nil } -- key nil = the played character

-- Other addons can add characters to the chooser:
--   source = { entries = function() -> { { key, char, owner } }   -- owner: group name shown in the list
--              data = function(kind) -> { [key] = value }           -- kind: "maps" | "instances" | "entrances"
--              emptyNoteKey = locale key shown when the source has no characters (optional) }
FC.viewSources = {}

function FC:RegisterViewSource(source)
  table.insert(self.viewSources, source)
end

local function sourceEntries(source)
  local ok, list = pcall(source.entries)
  return ok and type(list) == "table" and list or {}
end

local function sourceData(kind)
  local out = {}
  for _, source in ipairs(FC.viewSources) do
    if source.data then
      local ok, t = pcall(source.data, kind)
      if ok and type(t) == "table" then out[#out + 1] = t end
    end
  end
  return out
end

-- True for a usable character record (own, alt or friend): a table with info and a name.
function FC.IsCharacter(char)
  return type(char) == "table" and type(char.info) == "table" and char.info.name ~= nil
end

local function lastSeen(char) return type(char.info.lastSeenAt) == "number" and char.info.lastSeenAt or 0 end

-- Everything that can be shown, in display order: the played character, the account's other characters
-- (newest first), then the characters of view sources (grouped by owner).
--   { key, char, played = bool, owner = group name or nil }
function FC:ViewEntries()
  local own = {}
  for key, char in pairs(self.db.characters) do
    if FC.IsCharacter(char) then
      own[#own + 1] = { key = key, char = key == self.charKey and self.char or char, played = key == self.charKey }
    end
  end
  table.sort(own, function(a, b)
    if a.played ~= b.played then return a.played end
    return lastSeen(a.char) > lastSeen(b.char)
  end)
  for _, source in ipairs(self.viewSources) do
    for _, e in ipairs(sourceEntries(source)) do
      if type(e) == "table" and e.key and type(e.char) == "table" and type(e.char.info) == "table" then
        own[#own + 1] = { key = e.key, char = e.char, owner = e.owner and tostring(e.owner) or "?" }
      end
    end
  end
  return own
end

-- Shows a character in the window. nil (or the played character's key) = back to the played character.
function FC:SetView(key)
  if key == self.charKey then key = nil end
  local entry
  if key ~= nil then
    for _, e in ipairs(self:ViewEntries()) do
      if e.key == key then entry = e end
    end
    if not entry then key = nil end
  end
  View.key, View.entry = key, entry
  self:SendMessage("FC_VIEW_CHANGED", key)
end

function FC:ViewKey() return View.key or self.charKey end
function FC:IsViewingPlayed() return View.key == nil end
function FC:ViewOwner() return View.entry and View.entry.owner end

function FC:ViewChar()
  return View.entry and View.entry.char or self.char
end

-- A stream of the viewed character (read-only for anyone but the played character).
function FC:ViewStream(name)
  local char = self:ViewChar()
  if char == self.char then return self.Storage:GetStream(name) end
  local s = type(char.streams) == "table" and char.streams[name]
  if type(s) == "table" then FC.Storage.Unpack(s) end
  if type(s) == "table" and type(s.records) == "table" then return s end
  return { nextSeq = 1, dropped = 0, records = {} }
end

-------------------------------------------------------------------------------
-- Account-wide lookups that also know the view sources' data
-------------------------------------------------------------------------------

local function lookup(own, kind, key)
  if own and own[key] ~= nil then return own[key] end
  for _, t in ipairs(sourceData(kind)) do
    if t[key] ~= nil then return t[key] end
  end
end

function FC:MapInfo(mapID)
  return lookup(self.db.maps, "maps", tostring(mapID))
end

-- All known maps (own first): calls fn(mapID, info) once per map.
function FC:EachMap(fn)
  local seen = {}
  local tables = { self.db.maps }
  for _, t in ipairs(sourceData("maps")) do tables[#tables + 1] = t end
  for _, source in ipairs(tables) do
    for key, info in pairs(source) do
      local id = tonumber(key)
      if id and not seen[id] and type(info) == "table" then
        seen[id] = true
        fn(id, info)
      end
    end
  end
end

function FC:InstanceName(instanceID)
  local key = tostring(instanceID)
  local name = lookup(self.db.instances, "instances", key)
  return type(name) == "string" and name or ("#" .. key)
end

function FC:StoredEntrance(instanceID)
  local e = lookup(self.db.entrances, "entrances", tostring(instanceID))
  return type(e) == "table" and e.mapID and e.x and e or nil
end
