-- Forever Chronicle - View
-- Which character the window shows (docs/Sharing_Design.md, phase 2). Recording always writes to the played
-- character (FC.char); the pages read through the view instead:
--   FC:ViewChar(), FC:ViewStream(name), FC:ViewSnapshot(name), FC:IsViewingPlayed(), FC:ViewOwner()
-- Available characters: every character of this account (FC.db.characters, all in the same SavedVariables)
-- and every friend character from Friends\FriendsData.lua (ForeverChronicleFriends, written by the desktop
-- app). Friends' characters have the same record shape and are read-only. After login the view is the played
-- character.

local ADDON, FC = ...

local View = { key = nil, entry = nil } -- key nil = the played character
FC.View = View

-- Friends' data written by the desktop app, or nil.
function FC:FriendsData()
  local data = rawget(_G, "ForeverChronicleFriends")
  return type(data) == "table" and data or nil
end

local function lastSeen(char) return type(char.info.lastSeenAt) == "number" and char.info.lastSeenAt or 0 end

-- Everything that can be shown, in display order: the played character, the account's other characters
-- (newest first), then friends' characters (grouped by friend).
--   { key, char, played = bool, owner = friend name or nil }
function FC:ViewEntries()
  local own = {}
  for key, char in pairs(self.db.characters) do
    if type(char) == "table" and type(char.info) == "table" and char.info.name then
      own[#own + 1] = { key = key, char = key == self.charKey and self.char or char, played = key == self.charKey }
    end
  end
  table.sort(own, function(a, b)
    if a.played ~= b.played then return a.played end
    return lastSeen(a.char) > lastSeen(b.char)
  end)
  local data = self:FriendsData()
  if data and type(data.friends) == "table" then
    for i, friend in ipairs(data.friends) do
      if type(friend) == "table" and type(friend.characters) == "table" then
        for _, char in ipairs(friend.characters) do
          if type(char) == "table" and type(char.info) == "table" and char.info.name then
            own[#own + 1] = { key = "friend:" .. i .. ":" .. tostring(char.info.key), char = char,
              owner = tostring(friend.name or "?") }
          end
        end
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
  if type(s) == "table" and type(s.records) == "table" then return s end
  return { nextSeq = 1, dropped = 0, records = {} }
end

function FC:ViewSnapshot(name)
  local char = self:ViewChar()
  if char == self.char then return self.Storage:GetSnapshot(name) end
  local s = type(char.snapshots) == "table" and char.snapshots[name]
  return type(s) == "table" and s or {}
end

-------------------------------------------------------------------------------
-- Account-wide lookups that also know the friends' data
-------------------------------------------------------------------------------

local function friendsTable(name)
  local data = FC:FriendsData()
  local t = data and data[name]
  return type(t) == "table" and t or nil
end

function FC:MapInfo(mapID)
  local key = tostring(mapID)
  local own = self.db.maps and self.db.maps[key]
  if own then return own end
  local friends = friendsTable("maps")
  return friends and friends[key]
end

-- All known maps (own first): calls fn(mapID, info) once per map.
function FC:EachMap(fn)
  local seen = {}
  for _, source in ipairs({ self.db.maps or {}, friendsTable("maps") or {} }) do
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
  local name = self.db.instances and self.db.instances[key]
  if not name then
    local friends = friendsTable("instances")
    name = friends and friends[key]
  end
  return type(name) == "string" and name or ("#" .. key)
end

function FC:StoredEntrance(instanceID)
  local key = tostring(instanceID)
  local e = self.db.entrances and self.db.entrances[key]
  if not e then
    local friends = friendsTable("entrances")
    e = friends and friends[key]
  end
  return type(e) == "table" and e.mapID and e.x and e or nil
end
