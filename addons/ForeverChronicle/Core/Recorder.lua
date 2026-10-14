-- Forever Chronicle - Recorder
-- Builds normalized event records (spec F-002) and appends them to the "events" stream.
--
-- Record layout (schema 1):
--   { id, seq, type, time, serverTime, session, location = {...} | nil, data = {...} }

local ADDON, FC = ...
local Util = FC.Util

FC.Storage:DefineStream("events", 10000, "Interface\\Icons\\INV_Misc_Book_09")

-- Current location. Inside instances only the zone and instance ID are available (Phase 0).
function FC:GetLocation()
  local loc = {}
  loc.zone = Util.SafeValue("string", GetRealZoneText)
  local sub = Util.SafeValue("string", GetSubZoneText)
  if sub and sub ~= "" then loc.subzone = sub end

  local mapID = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
  if mapID then
    loc.mapID = mapID
    local pos = Util.SafeValue("table", C_Map.GetPlayerMapPosition, mapID, "player")
    if pos and pos.GetXY then
      local x, y = Util.SafeValues(pos.GetXY, pos)
      if type(x) == "number" and type(y) == "number" then
        loc.x, loc.y = Util.Round(x, 4), Util.Round(y, 4)
      end
    end
  end

  local inInstance = Util.SafeValues(IsInInstance)
  if inInstance == true then
    loc.instanceID = select(4, Util.SafeValues(UnitPosition, "player"))
  end
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

-- Newest first, at most `limit` records of the events stream.
function FC:GetRecentEvents(limit)
  local records = self.Storage:GetStream("events").records
  local out = {}
  for i = #records, math.max(1, #records - (limit or 100) + 1), -1 do
    out[#out + 1] = records[i]
  end
  return out
end
