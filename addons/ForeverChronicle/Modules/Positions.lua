-- Journey Forever - Positions module (spec F-005)
-- Samples the player's position at a fixed interval into the compact "positions" stream and records the
-- geometry of every map once (account-wide), so the desktop app can draw routes on zone and continent maps.
--
-- Sample format (one string per sample, comma separated):
--   time,mapID,x,y,until,flags,instanceID
--   time/until: epoch seconds; until is set when a stationary sample was extended (empty otherwise)
--   x,y:        normalized 0..1 on mapID, 4 decimals; empty when no position is available
--   flags:      "T" = on a taxi, "J" = first sample after a loading screen (a teleport: not connected to the
--               previous sample by a route line)
--   instanceID: set inside instances, where the client gives no map position (zone-only sample)
-- Coordinates are never interpolated. Standing still extends the previous sample instead of adding new ones.
--
-- Dungeon entrances (FC.db.entrances, account-wide): instanceID -> { mapID, x, y, source, name }.
--   source "journal": from the encounter journal's entrance list of a zone (when the client has it)
--   source "walked":  the last outdoor sample right before the player walked into the instance

local ADDON, FC = ...
local Util = FC.Util

local Positions = FC:NewModule("Positions", { order = 26, defaults = { enabled = true, interval = 2 } })

-- ~55 hours of movement at 2 s; standing still adds no points. Older points are not lost: they are thinned
-- out (FC.Route.Thin) and kept in the route archive, many points per record.
FC.Storage:DefineStream("positions", 100000, "Interface\\Icons\\INV_Boots_05", {
  quiet = true, onTrim = function(records) Positions:Archive(records) end })
FC.Storage:DefineStream("routeArchive", 500, "Interface\\Icons\\INV_Misc_Map02")

local MOVE_THRESHOLD = 0.002 -- 0.2 % of the map size

FC:RegisterCapability("positions", "CAP_POSITIONS", function()
  return C_Map ~= nil and type(C_Map.GetPlayerMapPosition) == "function"
end)

-------------------------------------------------------------------------------
-- Map geometry (account-wide: FC.db.maps, FC.db.instances)
-------------------------------------------------------------------------------

function Positions:RecordMap(mapID)
  local key = tostring(mapID)
  local known = FC.db.maps[key]
  if known and known.build == Util.ClientBuild() and known.entrancesChecked then return end
  local continentType = Util.MapType.Continent

  local info = Util.SafeValue("table", C_Map.GetMapInfo, mapID)
  if not info then return end
  local entry = { name = Util.Plain(info.name), mapType = Util.Plain(info.mapType),
    parent = Util.Plain(info.parentMapID), build = Util.ClientBuild() }

  -- Walk up to the continent and store this map's rectangle on it.
  local id = entry.parent
  for _ = 1, 6 do
    if type(id) ~= "number" or id == 0 then break end
    local parent = Util.SafeValue("table", C_Map.GetMapInfo, id)
    if not parent then break end
    if Util.Plain(parent.mapType) == continentType then
      entry.continent = id
      break
    end
    id = Util.Plain(parent.parentMapID)
  end
  if entry.continent and C_Map.GetMapRectOnMap then
    local minX, maxX, minY, maxY = Util.SafeValues(C_Map.GetMapRectOnMap, mapID, entry.continent)
    if type(minX) == "number" and type(maxY) == "number" then
      entry.minX, entry.maxX = Util.Round(minX, 5), Util.Round(maxX, 5)
      entry.minY, entry.maxY = Util.Round(minY, 5), Util.Round(maxY, 5)
    end
    self:RecordMap(entry.continent)
  end
  FC.db.maps[key] = entry
  if entry.mapType ~= continentType then self:RecordEntrances(mapID, entry) end
  entry.entrancesChecked = true
end

-------------------------------------------------------------------------------
-- Dungeon entrances
-------------------------------------------------------------------------------

-- Entrances the encounter journal lists for a zone (Mainline API; skipped if the client lacks it).
-- When a dungeon is listed on several maps (city and zone), the smaller map wins.
function Positions:RecordEntrances(mapID, entry)
  local get = C_EncounterJournal and C_EncounterJournal.GetDungeonEntrancesForMap
  if type(get) ~= "function" or type(EJ_GetInstanceInfo) ~= "function" then return end
  local ok, list = pcall(get, mapID)
  if not ok or type(list) ~= "table" then return end
  local area = entry.minX and (entry.maxX - entry.minX) * (entry.maxY - entry.minY) or nil
  for _, e in ipairs(list) do
    local x, y
    local pos = type(e) == "table" and e.position
    if type(pos) == "table" then
      if pos.GetXY then x, y = Util.SafeValues(pos.GetXY, pos) else x, y = Util.Plain(pos.x), Util.Plain(pos.y) end
    end
    local journalID = type(e) == "table" and Util.Plain(e.journalInstanceID)
    local instanceID = type(journalID) == "number" and select(10, Util.SafeValues(EJ_GetInstanceInfo, journalID))
    if type(instanceID) == "number" and type(x) == "number" and type(y) == "number" then
      local key = tostring(instanceID)
      local known = FC.db.entrances[key]
      if not known or known.source ~= "journal" or (area and known.area and area < known.area) then
        FC.db.entrances[key] = { mapID = mapID, x = Util.Round(x, 4), y = Util.Round(y, 4), source = "journal",
          name = Util.Plain(e.name), area = area }
        FC.Diagnostics:Log("info", "dungeon entrance from the journal: " .. key .. " on map " .. mapID)
      end
    end
  end
end

-- The player just entered an instance: the previous outdoor sample is its entrance, unless the player was
-- teleported in by the dungeon finder or the sample is older than Route.ENTRY_SECONDS (the same rule the
-- route uses to derive entrances). Journal entrances are kept.
function Positions:LearnEntrance(instanceID, prev, now)
  if not (prev and prev.mapID and prev.x) or prev.taxi or prev.instanceID then return end
  if now - (prev.untilTime or prev.time) > FC.Route.ENTRY_SECONDS then return end
  if IsPartyLFG and Util.SafeValues(IsPartyLFG) == true then return end
  local key = tostring(instanceID)
  local known = FC.db.entrances[key]
  if known and known.source == "journal" then return end
  FC.db.entrances[key] = { mapID = prev.mapID, x = prev.x, y = prev.y, source = "walked" }
end

-------------------------------------------------------------------------------
-- Archive
-------------------------------------------------------------------------------

-- Called with the oldest position records right before the cap removes them.
function Positions:Archive(records)
  local Route = FC.Route
  local kept = Route.Thin(records)
  for i = 1, #kept, Route.ARCHIVE_CHUNK do
    FC.Storage:AppendRaw("routeArchive", table.concat(kept, ";", i, math.min(#kept, i + Route.ARCHIVE_CHUNK - 1)))
  end
  FC.Diagnostics:Log("info", string.format("route archive: %d of %d old points kept", #kept, #records))
end

-------------------------------------------------------------------------------
-- Sampling
-------------------------------------------------------------------------------

local function encode(s)
  return string.format("%d,%s,%s,%s,%s,%s,%s", s.time, s.mapID or "",
    s.x and string.format("%.4f", s.x) or "", s.y and string.format("%.4f", s.y) or "",
    (s.untilTime and s.untilTime ~= s.time) and s.untilTime or "", (s.taxi and "T" or "") .. (s.jump and "J" or ""),
    s.instanceID or "")
end

local function samePlace(a, b)
  if a.mapID ~= b.mapID or a.instanceID ~= b.instanceID or a.taxi ~= b.taxi then return false end
  if b.instanceID then return true end
  if not (a.x and b.x) then return a.x == b.x end
  return math.abs(a.x - b.x) < MOVE_THRESHOLD and math.abs(a.y - b.y) < MOVE_THRESHOLD
end

function Positions:Sample()
  if not FC.char or not self:GetSettings().enabled or FC.loadingScreen then return end
  local now = time()
  local s = { time = now }
  s.mapID = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
  local x, y = FC:PlayerMapPosition(s.mapID)
  if x and (x > 0 or y > 0) then s.x, s.y = Util.Round(x, 4), Util.Round(y, 4) end
  if not s.x and Util.SafeValues(IsInInstance) == true then
    s.mapID = nil
    s.instanceID = FC:CurrentInstanceID()
    if s.instanceID then
      FC.db.instances[tostring(s.instanceID)] = Util.SafeValue("string", GetRealZoneText)
    end
  end
  if not s.x and not s.instanceID then return end -- nothing reliable to record

  local travel = FC:GetModule("Travel")
  s.taxi = travel and travel:IsOnTaxi() or nil

  -- The first sample after a loading screen starts a new route line, unless the player did not move.
  local afterLoading = self.afterLoading
  self.afterLoading = nil

  local last = self.last
  if last and samePlace(last, s) then
    last.untilTime = now
    FC.Storage:ReplaceLast("positions", encode(last))
    return
  end
  s.jump = afterLoading and last ~= nil or nil
  FC.Storage:AppendRaw("positions", encode(s))
  if s.instanceID then self:LearnEntrance(s.instanceID, last, now) end
  self.last = s
  if s.mapID then self:RecordMap(s.mapID) end
  FC:ConfirmCapability("positions")
end

function Positions:Restart()
  if self.ticker then self.ticker:Cancel() end
  self.ticker = nil
  local s = self:GetSettings()
  if s.enabled then
    self.ticker = FC:NewTicker(s.interval, function() self:Sample() end)
  end
end

function Positions:OnEnable()
  self:Restart()
end

-- An extra sample shortly after zone changes and loading screens makes route segments start cleanly.
local function sampleSoon(self) FC:After(1, function() self:Sample() end) end
Positions:RegisterEvent("ZONE_CHANGED_NEW_AREA", sampleSoon)
Positions:RegisterEvent("PLAYER_ENTERING_WORLD", function(self)
  self.afterLoading = true
  sampleSoon(self)
end)
Positions:RegisterEvent("LOADING_SCREEN_ENABLED", function(self) self.afterLoading = true end)

-------------------------------------------------------------------------------
-- Options
-------------------------------------------------------------------------------

FC:RegisterOptionSection("travel", "SECTION_TRAVEL", 15, "Interface\\Icons\\INV_Boots_05")
FC:RegisterOption({ section = "travel", module = "Positions", key = "enabled", type = "toggle",
  labelKey = "OPT_POSITIONS", tooltipKey = "OPT_POSITIONS_TIP", order = 1,
  onChange = function() Positions:Restart() end })
FC:RegisterOption({ section = "travel", module = "Positions", key = "interval", type = "choice", column = 2,
  labelKey = "OPT_POSITION_INTERVAL", order = 2,
  choices = { { value = 1, text = "1 s" }, { value = 2, text = "2 s" }, { value = 5, text = "5 s" },
    { value = 10, text = "10 s" } },
  onChange = function() Positions:Restart() end })
