-- Journey Forever - Route
-- Reads the compact "positions" stream into points (cached, updated incrementally) and provides the route
-- rules shared with the desktop app (spec F-005):
--   * coordinates are never interpolated; lines only connect consecutive recorded points
--   * a time gap, a map change, a taxi change or an instance point ends a segment
--   * a time lookup returns the point covering that time, else the nearest recorded point
--
-- Point: { time, endTime, mapID, x, y, taxi, instanceID }

local ADDON, FC = ...

local Route = {}
FC.Route = Route

Route.GAP_SECONDS = 120

-------------------------------------------------------------------------------
-- Parsing and cache
-------------------------------------------------------------------------------

-- "time,mapID,x,y,until,flags,instanceID" -> point, or false if malformed.
function Route.Parse(text)
  if type(text) ~= "string" then return false end
  local t, map, x, y, untilT, flags, inst = text:match("^(%d+),(%d*),([%d%.]*),([%d%.]*),(%d*),(%a*),(%d*)$")
  if not t then return false end
  local p = { time = tonumber(t), mapID = tonumber(map), x = tonumber(x), y = tonumber(y),
    taxi = flags:find("T", 1, true) ~= nil, instanceID = tonumber(inst) }
  p.endTime = tonumber(untilT) or p.time
  if (p.x == nil) ~= (p.y == nil) or (not p.mapID and not p.instanceID) then return false end
  return p
end

local cache = { key = nil, firstSeq = 1, points = {}, version = nil }

-- All points of the viewed character (FC:ViewChar) in time order. Only new records are parsed; the newest
-- record is always re-read because a stationary point may have been extended.
function Route.Points()
  local stream = FC:ViewStream("positions")
  local key = FC:ViewKey()
  local records = stream.records
  local n = #records
  local first = (stream.nextSeq or n + 1) - n
  local version = tostring(key) .. ":" .. tostring(stream.nextSeq) .. ":" .. tostring(records[n])
  if cache.key == key and cache.version == version and cache.out then
    return cache.out, version -- unchanged: no parsing, no new tables
  end

  if cache.key ~= key or first < cache.firstSeq then
    cache.key, cache.firstSeq, cache.points = key, first, {}
  elseif first > cache.firstSeq then
    -- Old records were trimmed by the retention cap: drop them from the cache in one pass.
    local drop, kept = first - cache.firstSeq, {}
    for i = drop + 1, #cache.points do kept[#kept + 1] = cache.points[i] end
    cache.points, cache.firstSeq = kept, first
  end

  for i = #cache.points + 1, n do cache.points[i] = Route.Parse(records[i]) end
  if n > 0 then cache.points[n] = Route.Parse(records[n]) end

  local out = {}
  for i = 1, n do
    if cache.points[i] then out[#out + 1] = cache.points[i] end
  end
  cache.version, cache.out = version, out
  return out, version
end

-------------------------------------------------------------------------------
-- Geometry
-------------------------------------------------------------------------------

local function mapInfo(mapID)
  return FC:MapInfo(mapID)
end

-- Normalized position of a point on the view map, or nil if it is not on that map.
-- Zone points can be shown on their continent, and continent points on a zone that contains them.
function Route.Project(p, view)
  if not p.mapID or not p.x then return nil end
  if p.mapID == view then return p.x, p.y end
  local info = mapInfo(p.mapID)
  if info and info.continent == view and info.minX then
    return info.minX + p.x * (info.maxX - info.minX), info.minY + p.y * (info.maxY - info.minY)
  end
  local zone = mapInfo(view)
  if zone and zone.continent == p.mapID and zone.minX and zone.maxX > zone.minX and zone.maxY > zone.minY then
    local x, y = (p.x - zone.minX) / (zone.maxX - zone.minX), (p.y - zone.minY) / (zone.maxY - zone.minY)
    if x >= 0 and x <= 1 and y >= 0 and y <= 1 then return x, y end
  end
  return nil
end

-------------------------------------------------------------------------------
-- Dungeon entrances: the client gives no position inside instances, so instance moments are shown at the
-- entrance. Recorded entrances (FC.db.entrances: encounter journal or where the player walked in, see
-- Modules/Positions.lua) come first; otherwise the entrance is derived from the route.
-------------------------------------------------------------------------------

Route.ENTRY_SECONDS = 60

-- instanceID -> { mapID, x, y }: the last outdoor point shortly before each entry into an instance.
local derived = { version = nil, list = {} }
function Route.DerivedEntrances(points, version)
  if version and derived.version == version then return derived.list end
  local list, prev = {}, nil
  for _, p in ipairs(points) do
    if p.instanceID and prev and not prev.instanceID and prev.mapID and prev.x and not prev.taxi
        and p.time - prev.endTime <= Route.ENTRY_SECONDS then
      list[p.instanceID] = { mapID = prev.mapID, x = prev.x, y = prev.y }
    end
    prev = p
  end
  derived.version, derived.list = version, list
  return list
end

function Route.Entrance(instanceID)
  if not instanceID then return nil end
  local stored = FC:StoredEntrance(instanceID)
  if stored then return stored end
  local points, version = Route.Points()
  return Route.DerivedEntrances(points, version)[instanceID]
end

-- Where something is shown on the map: its own position, or for instance points the dungeon entrance
-- (entrance = true). nil when neither is known.
function Route.Locate(p)
  if not p then return nil end
  if p.mapID and p.x then return p end
  if p.instanceID then
    local e = Route.Entrance(p.instanceID)
    if e then return { mapID = e.mapID, x = e.x, y = e.y, entrance = true, instanceID = p.instanceID } end
  end
  return nil
end

-- The map to show for a point: its zone. The client sometimes reports only the continent (between zones,
-- on boats and zeppelins); then the smallest known zone containing the point is used, else the continent.
-- Instance points use the zone of their dungeon entrance.
function Route.ZoneFor(p)
  if p and not p.mapID and p.instanceID then p = Route.Locate(p) end
  if not p or not p.mapID then return nil end
  if not p.x then return p.mapID end
  local best, bestArea
  FC:EachMap(function(id, info)
    if id ~= p.mapID and info.continent == p.mapID and info.minX then
      local area = (info.maxX - info.minX) * (info.maxY - info.minY)
      if p.x >= info.minX and p.x <= info.maxX and p.y >= info.minY and p.y <= info.maxY
          and (not bestArea or area < bestArea) then
        best, bestArea = id, area
      end
    end
  end)
  return best or p.mapID
end

-- Zone maps that have points, followed by the continents that contain them.
function Route.Views(points)
  local zones, continents, seen = {}, {}, {}
  for _, p in ipairs(points) do
    if p.mapID and not seen[p.mapID] then
      seen[p.mapID] = true
      zones[#zones + 1] = p.mapID
    end
  end
  for _, z in ipairs(zones) do
    local info = mapInfo(z)
    local c = info and info.minX and info.continent
    if c and not seen[c] then
      seen[c] = true
      continents[#continents + 1] = c
    end
  end
  for _, c in ipairs(continents) do zones[#zones + 1] = c end
  return zones
end

-- Segments on the view map within [startTime, endTime]: list of { taxi, points = { {x, y, time}, ... } }.
function Route.Segments(points, view, startTime, endTime)
  local segments, current, prev = {}, nil, nil
  for _, p in ipairs(points) do
    if (startTime and p.endTime < startTime) or (endTime and p.time > endTime) then
      current, prev = nil, nil
    else
      local x, y = Route.Project(p, view)
      if not x then
        current, prev = nil, p
      else
        if not current or not prev or p.time - prev.endTime > Route.GAP_SECONDS
          or prev.mapID ~= p.mapID or prev.taxi ~= p.taxi then
          current = { taxi = p.taxi, points = {} }
          segments[#segments + 1] = current
        end
        current.points[#current.points + 1] = { x, y, p.time }
        prev = p
      end
    end
  end
  return segments
end

-------------------------------------------------------------------------------
-- Time lookup
-------------------------------------------------------------------------------

-- Index of the last point with time <= t (0 if none).
local function lastAtOrBefore(points, t)
  local lo, hi = 1, #points
  local found = 0
  while lo <= hi do
    local mid = math.floor((lo + hi) / 2)
    if points[mid].time <= t then found, lo = mid, mid + 1 else hi = mid - 1 end
  end
  return found
end

function Route.PointAt(points, t)
  if #points == 0 then return nil end
  local i = lastAtOrBefore(points, t)
  if i > 0 and points[i].time <= t and t <= points[i].endTime then return points[i] end
  local best, bestDist
  for _, j in ipairs({ i, i + 1 }) do
    local p = points[j]
    if p then
      local d = math.min(math.abs(t - p.time), math.abs(t - p.endTime))
      if not bestDist or d < bestDist then best, bestDist = p, d end
    end
  end
  return best
end

function Route.NextTimeAfter(points, t)
  local p = points[lastAtOrBefore(points, t) + 1]
  return p and p.time or nil
end

-- Sessions of the viewed character, newest first: list of { startedAt, endedAt }.
function Route.Sessions()
  local out = {}
  local records = FC:ViewStream("sessions").records
  for i = #records, 1, -1 do
    local s = records[i]
    out[#out + 1] = { startedAt = s.startedAt, endedAt = s.endedAt or time() }
  end
  return out
end
