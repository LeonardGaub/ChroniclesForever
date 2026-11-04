-- Journey Forever - Group module
-- Who the player played with: one record per stretch with the same group in the compact "group" stream, so the
-- desktop app can name companions in the cinematic, its credits and draw friends' routes next to the player's.
--
-- Record format (one string per stretch):  start,until,member;member;...
--   member: name/classFile/guid (name with "-Realm" for other realms); other players only, no NPC followers
-- The open stretch's until is moved on every minute and when the group changes or the player logs out.

local ADDON, FC = ...
local Util = FC.Util

local Group = FC:NewModule("Group", { order = 37 })

FC.Storage:DefineStream("group", 2000, "Interface\\Icons\\INV_Misc_GroupNeedMore")

local INTERVAL = 60

FC:RegisterCapability("group", "CAP_GROUP", function()
  return type(GetNumGroupMembers) == "function" and FC.eventStatus.GROUP_ROSTER_UPDATE == "registered"
end)

-- The other players in the group as { name, class, guid }, sorted by GUID, and a signature of them.
function Group:Members()
  local count = Util.SafeValue("number", GetNumGroupMembers) or 0
  if count == 0 then return {}, "" end
  local raid = Util.SafeValue("boolean", IsInRaid) == true
  -- A battleground or arena puts everyone on the player's side in one raid: only those who were in the group
  -- before the match count (the friends the player queued with), not strangers.
  local _, instanceType = Util.SafeValues(IsInInstance)
  if instanceType == "pvp" or instanceType == "arena" then
    if not self.home then
      self.home = {}
      for _, m in ipairs(self.open and self.open.members or {}) do self.home[m.guid] = true end
    end
  else
    self.home = nil
  end
  local home = self.home
  local units = {}
  if raid then
    for i = 1, count do units[#units + 1] = "raid" .. i end
  else
    for i = 1, 4 do units[#units + 1] = "party" .. i end
  end
  local members = {}
  for _, unit in ipairs(units) do
    local guid = Util.SafeValue("string", UnitGUID, unit)
    if guid and guid:find("^Player%-") and guid ~= FC.char.info.guid and (not home or home[guid])
        and Util.SafeValue("boolean", UnitIsPlayer, unit) ~= false then
      local name, realm = Util.SafeValues(UnitName, unit)
      if type(name) == "string" and name ~= "" and name ~= UNKNOWNOBJECT then
        if type(realm) == "string" and realm ~= "" then name = name .. "-" .. realm end
        local _, classFile = Util.SafeValues(UnitClass, unit)
        members[#members + 1] = { name = name:gsub("[,;/]", ""), class = type(classFile) == "string" and classFile or "",
          guid = guid }
      end
    end
  end
  table.sort(members, function(a, b) return a.guid < b.guid end)
  local guids = {}
  for i, m in ipairs(members) do guids[i] = m.guid end
  return members, table.concat(guids, ";")
end

function Group.Encode(stretch)
  local parts = {}
  for i, m in ipairs(stretch.members) do parts[i] = m.name .. "/" .. m.class .. "/" .. m.guid end
  return string.format("%d,%d,%s", stretch.time, stretch.untilTime, table.concat(parts, ";"))
end

-- "start,until,members" -> { time, untilTime, members = { { name, class, guid } } }, or nil if malformed.
function Group.Parse(text)
  if type(text) ~= "string" then return nil end
  local t, u, list = text:match("^(%d+),(%d+),(.*)$")
  if not t then return nil end
  local stretch = { time = tonumber(t), untilTime = tonumber(u), members = {} }
  for member in list:gmatch("[^;]+") do
    local name, class, guid = member:match("^([^/]*)/([^/]*)/([^/]*)$")
    if name then stretch.members[#stretch.members + 1] = { name = name, class = class, guid = guid } end
  end
  return stretch
end

function Group:Update()
  if not FC.char then return end
  local members, signature = self:Members()
  local now, open = time(), self.open
  if open then
    open.untilTime = now
    FC.Storage:ReplaceLast("group", Group.Encode(open))
    if open.signature == signature then return end
    self.open = nil
  end
  if signature ~= "" then
    self.open = { time = now, untilTime = now, members = members, signature = signature }
    FC.Storage:AppendRaw("group", Group.Encode(self.open))
    FC:ConfirmCapability("group")
  end
end

function Group:OnEnable()
  self:Update()
  FC:NewTicker(INTERVAL, function() self:Update() end)
end

Group:RegisterEvent("GROUP_ROSTER_UPDATE", function(self) FC:Debounce(self, "pending", 2, function() self:Update() end) end)
Group:RegisterEvent("PLAYER_LOGOUT", function(self) self:Update() end)
