-- Forever Chronicle - Route
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

-- All points of the current character in time order. Only new records are parsed; the newest record is
-- always re-read because a stationary point may have been extended.
function Route.Points()
  local stream = FC.Storage:GetStream("positions")
  local records = stream.records
  local n = #records
  local first = stream.nextSeq - n
  local version = stream.nextSeq .. ":" .. tostring(records[n])
  if cache.key == FC.charKey and cache.version == version and cache.out then
    return cache.out, version -- unchanged: no parsing, no new tables
  end

  if cache.key ~= FC.charKey or first < cache.firstSeq then
    cache.key, cache.firstSeq, cache.points = FC.charKey, first, {}
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
  return FC.db.maps and FC.db.maps[tostring(mapID)]
end

-- Normalized position of a point on the view map, or nil if it is not on that map.
function Route.Project(p, view)
  if not p.mapID or not p.x then return nil end
  if p.mapID == view then return p.x, p.y end
  local info = mapInfo(p.mapID)
  if info and info.continent == view and info.minX then
    return info.minX + p.x * (info.maxX - info.minX), info.minY + p.y * (info.maxY - info.minY)
  end
  return nil
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

-- Sessions of the current character, newest first: list of { startedAt, endedAt }.
function Route.Sessions()
  local out = {}
  local records = FC.Storage:GetStream("sessions").records
  for i = #records, 1, -1 do
    local s = records[i]
    out[#out + 1] = { startedAt = s.startedAt, endedAt = s.endedAt or time() }
  end
  return out
end
