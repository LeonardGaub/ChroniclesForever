-- Journey Forever - Recorder
-- Builds normalized event records (spec F-002) and appends them to the "events" stream.
--
-- Record layout (unchanged since schema 1):
--   { id, seq, type, time, serverTime, session, location = {...} | nil, data = {...} }

local ADDON, FC = ...
local Util = FC.Util

FC.Storage:DefineStream("events", 10000, "Interface\\Icons\\INV_Misc_Book_09")

-- The player's normalized position (0..1) on a map as plain numbers, or nil if the client gives none.
function FC:PlayerMapPosition(mapID)
  if not (mapID and C_Map) then return nil end
  local pos = Util.SafeValue("table", C_Map.GetPlayerMapPosition, mapID, "player")
  if not (pos and pos.GetXY) then return nil end
  local x, y = Util.SafeValues(pos.GetXY, pos)
  if type(x) == "number" and type(y) == "number" then return x, y end
  return nil
end

-- The instance ID while inside an instance (where the client gives no map position, Phase 0), else nil.
function FC:CurrentInstanceID()
  if Util.SafeValues(IsInInstance) ~= true then return nil end
  local instanceID = select(4, Util.SafeValues(UnitPosition, "player"))
  return type(instanceID) == "number" and instanceID or nil
end

-- Current location. Inside instances only the zone and instance ID are available (Phase 0).
function FC:GetLocation()
  local loc = {}
  loc.zone = Util.SafeValue("string", GetRealZoneText)
  local sub = Util.SafeValue("string", GetSubZoneText)
  if sub and sub ~= "" then loc.subzone = sub end

  local mapID = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
  if mapID then
    loc.mapID = mapID
    local x, y = self:PlayerMapPosition(mapID)
    if x then loc.x, loc.y = Util.Round(x, 4), Util.Round(y, 4) end
  end

  loc.instanceID = self:CurrentInstanceID()
  loc.quality = (loc.x and "exact") or "zone_only"
  return loc
end

-- Records an event of the given type. opts.time overrides the timestamp; opts.noLocation skips location.
function FC:Record(eventType, data, opts)
  if not self.char then return nil end
  opts = opts or {}
  local record = {
    id = Util.NewId(),
    type = eventType,
    time = opts.time or time(),
    serverTime = Util.SafeValue("number", GetServerTime),
    session = self.sessionId,
    data = data or {},
  }
  if not opts.noLocation then record.location = self:GetLocation() end
  self.Storage:Append("events", record)
  self:SendMessage("FC_EVENT_RECORDED", record)
  return record
end
