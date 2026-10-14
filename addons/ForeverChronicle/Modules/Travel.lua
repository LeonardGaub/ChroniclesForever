-- Forever Chronicle - Travel module (spec F-005, first part)
-- Known zones per character and "zone discovered" events (first visit since tracking began).
-- A zone counts as discovered after the player has stayed in it for the dwell time, not on a taxi
-- and not during a loading screen. The zone the character is in at the very first run is known
-- without an event. Position sampling and the route stream follow in a later step.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Travel = FC:NewModule("Travel", { order = 25, defaults = { dwellSeconds = 5 } })

FC:RegisterCapability("zones", "CAP_ZONES", function()
  return FC.eventStatus.ZONE_CHANGED_NEW_AREA == "registered" and type(GetRealZoneText) == "function"
end)

FC:RegisterEventType("zone_discovered", {
  icon = "Interface\\Icons\\INV_Misc_Map_01",
  format = function(r) return string.format(L.EVT_ZONE_DISCOVERED, r.data.zone or "?") end,
})

FC:RegisterStat("zones_discovered", { labelKey = "STAT_ZONES", order = 25 })

-------------------------------------------------------------------------------
-- Zone identity
-------------------------------------------------------------------------------

local ZONE_TYPE = 3 -- Enum.UIMapType.Zone; micro maps (caves, building floors) roll up to it

-- Returns key, info for the current zone. Keys: "map:<id>", "instance:<id>" or "zone:<name>".
function Travel:CurrentZone()
  local zoneType = (Enum and Enum.UIMapType and Enum.UIMapType.Zone) or ZONE_TYPE
  local zone = Util.SafeValue("string", GetRealZoneText)
  local mapID = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
  if mapID and C_Map.GetMapInfo then
    for _ = 1, 5 do
      local info = Util.SafeValue("table", C_Map.GetMapInfo, mapID)
      local mapType = info and Util.Plain(info.mapType)
      local parent = info and Util.Plain(info.parentMapID)
      if type(mapType) ~= "number" or mapType <= zoneType or type(parent) ~= "number" or parent == 0 then break end
      mapID = parent
    end
  end
  if mapID then
    return "map:" .. mapID, { mapID = mapID, zone = zone }
  end
  local inInstance = Util.SafeValues(IsInInstance)
  if inInstance == true then
    local instanceID = select(4, Util.SafeValues(UnitPosition, "player"))
    if type(instanceID) == "number" then
      return "instance:" .. instanceID, { instanceID = instanceID, zone = zone }
    end
  end
  if zone and zone ~= "" then return "zone:" .. zone, { zone = zone } end
  return nil
end

function Travel:IsOnTaxi()
  return Util.SafeValue("boolean", UnitOnTaxi, "player") == true
end

-------------------------------------------------------------------------------
-- Discovery
-------------------------------------------------------------------------------

function Travel:Known()
  local state = FC.Storage:GetState("Travel")
  state.known = state.known or {}
  return state.known
end

-- First run for this character: the current zone becomes known without a "discovered" event.
function Travel:MarkInitialZone()
  local known = self:Known()
  if next(known) ~= nil then return false end
  local key = self:CurrentZone()
  if key then known[key] = { firstSeenAt = time(), initial = true } end
  return key ~= nil
end

-- Called on every zone change; checks again after the dwell time.
function Travel:ScheduleCheck()
  self.checkToken = (self.checkToken or 0) + 1
  local token = self.checkToken
  local key = self:CurrentZone()
  if not key then return end
  FC:After(self:GetSettings().dwellSeconds, function()
    if token ~= self.checkToken or FC.loadingScreen or self:IsOnTaxi() then return end
    local nowKey, info = self:CurrentZone()
    if nowKey == key then self:Discover(key, info) end
  end)
end

function Travel:Discover(key, info)
  local known = self:Known()
  if known[key] then return end
  known[key] = { firstSeenAt = time() }
  FC:Record("zone_discovered", { zoneKey = key, mapID = info.mapID, instanceID = info.instanceID, zone = info.zone })
  FC:IncrementStat("zones_discovered")
  FC:ConfirmCapability("zones")
end

Travel:RegisterEvent("ZONE_CHANGED_NEW_AREA", function(self) self:ScheduleCheck() end)
Travel:RegisterEvent("PLAYER_ENTERING_WORLD", function(self)
  if not self:MarkInitialZone() then self:ScheduleCheck() end
end)
Travel:RegisterEvent("PLAYER_CONTROL_GAINED", function(self) self:ScheduleCheck() end) -- e.g. landing after a flight

-- Loading screen state is shared with other modules (screenshots wait for it).
Travel:RegisterEvent("LOADING_SCREEN_ENABLED", function() FC.loadingScreen = true end)
Travel:RegisterEvent("LOADING_SCREEN_DISABLED", function() FC.loadingScreen = false end)
