-- Journey Forever - Character module (spec F-001)
-- Keeps the character's identity and metadata up to date.

local ADDON, FC = ...
local Util = FC.Util

local Character = FC:NewModule("Character", { order = 10 })

FC:RegisterCapability("identity", "CAP_IDENTITY", function()
  return type(UnitGUID) == "function" and type(GetRealmName) == "function"
end)

function Character:Refresh()
  local info = FC.char.info
  local name, nameSuffix = Util.SafeValues(UnitName, "player")
  if type(name) == "string" and info.name and info.name ~= name then
    -- Renamed: keep the previous name (spec F-001).
    info.nameHistory = info.nameHistory or {}
    table.insert(info.nameHistory, { name = info.name, renamedAt = time() })
  end
  info.guid = Util.SafeValue("string", UnitGUID, "player")
  info.name = type(name) == "string" and name or info.name
  info.nameSuffix = type(nameSuffix) == "string" and nameSuffix or nil
  info.realm = Util.SafeValue("string", GetRealmName) or info.realm
  info.realmNormalized = Util.SafeValue("string", GetNormalizedRealmName) or info.realmNormalized
  local className, classFile = Util.SafeValues(UnitClass, "player")
  info.className, info.classFile = className or info.className, classFile or info.classFile
  local raceName, raceFile = Util.SafeValues(UnitRace, "player")
  info.raceName, info.raceFile = raceName or info.raceName, raceFile or info.raceFile
  info.faction = Util.SafeValue("string", UnitFactionGroup, "player") or info.faction
  info.level = Util.SafeValue("number", UnitLevel, "player") or info.level
  info.locale = Util.SafeValue("string", GetLocale)
  local version, build = Util.SafeValues(GetBuildInfo)
  info.clientVersion, info.clientBuild = version, build
  info.lastSeenAt = time()
  if info.guid then FC:ConfirmCapability("identity") end
end

function Character:OnEnable()
  self:Refresh()
end

Character:RegisterEvent("PLAYER_ENTERING_WORLD", function(self) self:Refresh() end)
Character:RegisterEvent("PLAYER_LEVEL_UP", function(self, _, level)
  -- UnitLevel may still report the old level inside this event.
  local lvl = Util.Plain(level)
  if type(lvl) == "number" then FC.char.info.level = lvl end
end)
