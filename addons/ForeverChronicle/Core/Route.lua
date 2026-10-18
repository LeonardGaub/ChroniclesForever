-- Journey Forever - Route
-- Reads the compact "positions" stream into points (cached, updated incrementally) and provides the route
-- rules shared with the desktop app (spec F-005):
--   * coordinates are never interpolated; lines only connect consecutive recorded points
--   * a time gap, a map change, a taxi change, a teleport or an instance point ends a segment
--   * a time lookup returns the point covering that time, else the nearest recorded point
--   * old points are thinned out, never moved: when the positions stream reaches its cap, the oldest
--     points lose the samples that lie on a nearly straight line and go to the "routeArchive" stream
--
-- Point: { time, endTime, mapID, x, y, taxi, jump, instanceID }

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
    taxi = flags:find("T", 1, true) ~= nil, jump = flags:find("J", 1, true) ~= nil, instanceID = tonumber(inst) }
  p.endTime = tonumber(untilT) or p.time
  if (p.x == nil) ~= (p.y == nil) or (not p.mapID and not p.instanceID) then return false end
  return p
end

-- Archive records hold many points each: "point;point;..." (one string per chunk keeps the saved file small).
Route.ARCHIVE_CHUNK = 400

local function archivePoints(stream, out)
  for _, chunk in ipairs(stream.records) do
    if type(chunk) == "string" then
      for text in chunk:gmatch("[^;]+") do
        local p = Route.Parse(text)
        if p then out[#out + 1] = p end
      end
    end
  end
end

local cache = { key = nil, version = nil }

-- All points of the viewed character (FC:ViewChar) in time order: the archive, then the positions stream.
-- Only new records are parsed and appended; the newest record is always re-read because a stationary point
-- may have been extended. The returned list is reused (and grows) while the character stays the same.
function Route.Points()
  local stream = FC:ViewStream("positions")
  local archive = FC:ViewStream("routeArchive")
  local key = FC:ViewKey()
  local records = stream.records
  local n = #records
  local first = (stream.nextSeq or n + 1) - n
  local archiveVersion = tostring(archive.nextSeq) .. "/" .. #archive.records
  local version = tostring(key) .. ":" .. archiveVersion .. ":" .. tostring(stream.nextSeq) .. ":" .. tostring(records[n])
  if cache.key == key and cache.version == version and cache.out then
    return cache.out, version -- unchanged: no parsing, no new tables
  end

  if cache.key ~= key or first ~= cache.firstSeq or cache.archiveVersion ~= archiveVersion or not cache.out
      or n < cache.parsed then
    -- New character, or records moved to the archive: start over.
    cache.key, cache.firstSeq, cache.archiveVersion = key, first, archiveVersion
    cache.out, cache.parsed = {}, 0
    archivePoints(archive, cache.out)
    cache.base = #cache.out
  end

  -- cache.base: number of points before the newest parsed record (which may have changed since).
  local out = cache.out
  for i = #out, cache.base + 1, -1 do out[i] = nil end
  for i = math.max(1, cache.parsed), n do
    if i == n then cache.base = #out end
    local p = Route.Parse(records[i])
    if p then out[#out + 1] = p end
  end
  cache.parsed = n
  cache.version = version
  return out, version
end

-------------------------------------------------------------------------------
-- Geometry
-------------------------------------------------------------------------------

-- Normalized position of a point on the view map, or nil if it is not on that map.
-- Zone points can be shown on their continent, and continent points on a zone that contains them.
function Route.Project(p, view)
  if not p.mapID or not p.x then return nil end
  if p.mapID == view then return p.x, p.y end
  local info = FC:MapInfo(p.mapID)
  if info and info.continent == view and info.minX then
    return info.minX + p.x * (info.maxX - info.minX), info.minY + p.y * (info.maxY - info.minY)
  end
  local zone = FC:MapInfo(view)
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
    local info = FC:MapInfo(z)
    local c = info and info.minX and info.continent
    if c and not seen[c] then
      seen[c] = true
      continents[#continents + 1] = c
    end
  end
  for _, c in ipairs(continents) do zones[#zones + 1] = c end
  return zones
end

-- Teleports (hearthstone, portals) must not draw a line across the map. The addon flags the first point
-- after a loading screen ("J"). Teleports without one, and routes recorded before the flag, are recognised
-- by a step faster than any mount or flight path. Speeds are measured on the continent so cities and zones
-- compare alike: recorded ground travel and flight paths peak around 0.0015 continent widths per second.
Route.TELEPORT_SPEED = 0.004       -- continent widths per second
Route.TELEPORT_DISTANCE = 0.01     -- shorter steps never count as a teleport
Route.UNKNOWN_ZONE_SCALE = 0.1     -- assumed size of a zone without continent geometry (new Forever zones)

-- Size of one map unit in continent widths: 1 on a continent, the zone's width on it, else the assumption.
local function continentScale(mapID)
  local info = FC:MapInfo(mapID)
  if info and info.mapType == FC.Util.MapType.Continent then return 1 end
  if info and info.minX and info.maxX > info.minX then return info.maxX - info.minX end
  return Route.UNKNOWN_ZONE_SCALE
end

-- True when the step from prev to p (both on the same map) is a teleport.
function Route.IsJump(prev, p)
  if p.jump then return true end
  if prev.taxi or p.taxi or not (prev.x and p.x) then return false end
  local scale = continentScale(p.mapID)
  local d = math.sqrt((p.x - prev.x) ^ 2 + (p.y - prev.y) ^ 2) * scale
  return d >= Route.TELEPORT_DISTANCE and d / math.max(1, p.time - prev.endTime) > Route.TELEPORT_SPEED
end

-- True when a route line connects prev to p (same map, no time gap, same travel mode, no teleport).
function Route.Connected(prev, p)
  return p.time - prev.endTime <= Route.GAP_SECONDS and prev.mapID == p.mapID and prev.taxi == p.taxi
    and not Route.IsJump(prev, p)
end

-------------------------------------------------------------------------------
-- Thinning old points (archive)
-------------------------------------------------------------------------------

Route.THIN_TOLERANCE = 0.0005   -- map units a dropped sample may lie off the remaining line
Route.THIN_MAX_SECONDS = 90     -- kept points stay closer than this, so lines never break at GAP_SECONDS
Route.THIN_DWELL = 10           -- a sample where the player stood this long is always kept

-- Where a replay shows the player at time t between the connected points a and b (see Route.Glide).
local function glideAt(a, b, t)
  if t <= a.endTime or b.time <= a.endTime then return a.x, a.y end
  local f = math.min(1, (t - a.endTime) / (b.time - a.endTime))
  return a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f
end

-- How far a replay over a -> b would be from the sample p, at the start and the end of p's time.
local function offLine(a, b, p)
  local worst = 0
  for _, t in ipairs({ p.time, p.endTime }) do
    local x, y = glideAt(a, b, t)
    worst = math.max(worst, math.sqrt((x - p.x) ^ 2 + (y - p.y) ^ 2))
  end
  return worst
end

-- Removes samples that a replay would show at nearly the same place anyway: on a straight line between their
-- neighbours, passed at an even pace. Kept records are returned unchanged (same strings, never moved);
-- line ends, dwell points, teleports and instance points are kept.
-- "anchor" is the last kept sample; "skipped" are the dropped samples since then, all close to the line from
-- the anchor to the current sample.
function Route.Thin(records)
  local kept, pts = {}, {}
  for _, text in ipairs(records) do
    local p = Route.Parse(text)
    if p then pts[#pts + 1] = { p = p, text = text } end
  end
  local anchor, skipped = nil, {}
  local function keep(item)
    kept[#kept + 1] = item.text
    anchor, skipped = item, {}
  end
  for i, item in ipairs(pts) do
    local p, prev = item.p, pts[i - 1]
    if not anchor or not p.x or not prev.p.x or not Route.Connected(prev.p, p)
        or p.endTime - p.time >= Route.THIN_DWELL then
      if prev and prev ~= anchor then keep(prev) end
      keep(item)
    elseif prev ~= anchor then
      -- Can prev be dropped? The line from the last kept sample to p must pass close to all in between.
      local a = anchor.p
      local ok = p.time - a.endTime <= Route.THIN_MAX_SECONDS
      if ok then
        skipped[#skipped + 1] = prev
        for _, s in ipairs(skipped) do
          if offLine(a, p, s.p) > Route.THIN_TOLERANCE then ok = false; break end
        end
      end
      if not ok then keep(prev) end
    end
  end
  local last = pts[#pts]
  if last and last ~= anchor then kept[#kept + 1] = last.text end
  return kept
end

-------------------------------------------------------------------------------
-- Segments
-------------------------------------------------------------------------------

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
        if not current or not prev or not Route.Connected(prev, p) then
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

-- Where a replay shows the player at time t: like PointAt, but between two points joined by a route line the
-- marker moves along that line instead of jumping from sample to sample. The line itself only connects
-- recorded points, so the marker never leaves the drawn route (and thinned stretches replay as before).
function Route.Glide(points, t)
  local i = lastAtOrBefore(points, t)
  local a, b = points[i], points[i + 1]
  if a and b and a.x and b.x and t > a.endTime and t < b.time and Route.Connected(a, b) then
    local x, y = glideAt(a, b, t)
    return { time = t, endTime = t, mapID = a.mapID, x = x, y = y, taxi = a.taxi }
  end
  return Route.PointAt(points, t)
end

-------------------------------------------------------------------------------
-- Timeline: the slider shows only time with route points. Logouts and longer breaks are collapsed, so a
-- slider over many sessions is not mostly empty. Value = seconds of active time since the start.
-------------------------------------------------------------------------------

Route.TIMELINE_GAP = 300 -- a break longer than this (no points) is collapsed

-- { intervals = { { from, to, offset }, ... }, total } for the points within [startTime, endTime].
function Route.Timeline(points, startTime, endTime)
  local intervals, total, current = {}, 0, nil
  for i = math.max(1, lastAtOrBefore(points, startTime)), #points do
    local p = points[i]
    if p and p.endTime >= startTime then
      if p.time > endTime then break end
      local from, to = math.max(p.time, startTime), math.min(p.endTime, endTime)
      if current and from - current.to <= Route.TIMELINE_GAP then
        current.to = math.max(current.to, to)
      else
        if current then total = total + (current.to - current.from) end
        current = { from = from, to = to, offset = total }
        intervals[#intervals + 1] = current
      end
    end
  end
  if current then total = total + (current.to - current.from) end
  if #intervals == 0 then
    intervals[1] = { from = startTime, to = endTime, offset = 0 }
    total = endTime - startTime
  end
  return { intervals = intervals, total = math.max(1, total) }
end

-- Index of the last interval starting at or before key (field "from" or "offset").
local function intervalAt(list, field, key)
  local lo, hi, found = 1, #list, 1
  while lo <= hi do
    local mid = math.floor((lo + hi) / 2)
    if list[mid][field] <= key then found, lo = mid, mid + 1 else hi = mid - 1 end
  end
  return list[found]
end

function Route.TimeToValue(timeline, t)
  local iv = intervalAt(timeline.intervals, "from", t)
  return iv.offset + math.max(0, math.min(iv.to, t) - iv.from)
end

function Route.ValueToTime(timeline, v)
  local iv = intervalAt(timeline.intervals, "offset", v)
  return math.min(iv.to, iv.from + math.max(0, v - iv.offset))
end

-- Stretches of time in one zone (or dungeon) within [startTime, endTime], for the slider's colour bands:
-- list of { from, to, mapID, instanceID }. A stretch lasts until the next one starts.
function Route.ZoneRuns(points, startTime, endTime)
  local runs, current = {}, nil
  for i = math.max(1, lastAtOrBefore(points, startTime)), #points do
    local p = points[i]
    if p.time > endTime then break end
    if p.endTime >= startTime then
      local mapID = not p.instanceID and p.mapID or nil
      if current and current.mapID == mapID and current.instanceID == p.instanceID then
        current.to = math.min(p.endTime, endTime)
      else
        local from = math.max(p.time, startTime)
        if current then current.to = math.max(current.to, from) end
        current = { from = from, to = math.min(p.endTime, endTime), mapID = mapID, instanceID = p.instanceID }
        runs[#runs + 1] = current
      end
    end
  end
  return runs
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
