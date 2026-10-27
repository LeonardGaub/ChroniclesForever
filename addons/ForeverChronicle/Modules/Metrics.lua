-- Journey Forever - Metrics module
-- A small time series for graphs: every minute (and on logout) the current totals are stored in the compact
-- "metrics" stream when something changed:  time,xpEarned,kills,money,level
-- Graphs show a window over the last hours of played time (Metrics:PlayedWindow, Metrics:WindowPoints).

local ADDON, FC = ...
local Util = FC.Util

local Metrics = FC:NewModule("Metrics", { order = 40 })
FC.Metrics = Metrics

FC.Storage:DefineStream("metrics", 20000, "Interface\\Icons\\INV_Misc_Note_02")

local INTERVAL = 60
local FIELDS = { "time", "xp", "kills", "money", "level" }

local function current()
  local stats = FC.char.stats
  return {
    time = time(),
    xp = math.floor(stats.xp_earned or 0),
    kills = stats.kills or 0,
    money = Util.SafeValue("number", GetMoney) or 0,
    level = FC.char.info.level or 0,
  }
end

local function encode(s)
  -- %.0f for the totals that can pass 2^31 (money in copper): %d is 32-bit on some clients
  return string.format("%d,%.0f,%d,%.0f,%d", s.time, s.xp, s.kills, s.money, s.level)
end

function Metrics.Parse(text)
  if type(text) ~= "string" then return nil end
  local values, i = {}, 0
  for part in text:gmatch("[^,]+") do
    i = i + 1
    values[FIELDS[i]] = tonumber(part)
  end
  if i ~= #FIELDS or not values.time then return nil end
  return values
end

function Metrics:Sample()
  if not FC.char then return end
  local s = current()
  local last = self.last
  if last and last.xp == s.xp and last.kills == s.kills and last.money == s.money and last.level == s.level then
    return -- nothing changed: idle minutes add no data
  end
  FC.Storage:AppendRaw("metrics", encode(s))
  self.last = s
end

function Metrics:OnEnable()
  local records = FC.Storage:GetStream("metrics").records
  self.last = Metrics.Parse(records[#records])
  self:Sample()
  FC:NewTicker(INTERVAL, function() self:Sample() end)
end

Metrics:RegisterEvent("PLAYER_LOGOUT", function(self) self:Sample() end)

-------------------------------------------------------------------------------
-- Queries for graphs: a window over the last hours of *played* time (time between sessions is skipped)
-------------------------------------------------------------------------------

-- The last `seconds` of played time as spans { from, to, x } (x = where the span starts in the window,
-- in seconds), oldest first, and the window length (shorter if less has been played).
function Metrics:PlayedWindow(seconds)
  local sessions = FC.Storage:GetStream("sessions").records
  local spans, remaining = {}, seconds
  for i = #sessions, 1, -1 do
    local s = sessions[i]
    local stop = s.endedAt or time()
    local start = math.max(s.startedAt, stop - remaining)
    if stop > start then
      table.insert(spans, 1, { from = start, to = stop })
      remaining = remaining - (stop - start)
    end
    if remaining <= 0 then break end
  end
  local x = 0
  for _, span in ipairs(spans) do
    span.x = x
    x = x + (span.to - span.from)
  end
  return spans, x
end

-- Wall-clock time at window position x.
function Metrics.TimeAt(spans, x)
  for _, span in ipairs(spans) do
    if x <= span.x + (span.to - span.from) then return span.from + (x - span.x) end
  end
  local last = spans[#spans]
  return last and last.to
end

-- Samples of a metrics field since `since` (plus the one before it): { { time, value } } ascending.
function Metrics:FieldSeries(field, since)
  local records = FC.Storage:GetStream("metrics").records
  local out = {}
  for i = #records, 1, -1 do
    local s = Metrics.Parse(records[i])
    if s and s[field] then
      table.insert(out, 1, { time = s.time, value = s[field] })
      if s.time <= since then break end
    end
  end
  return out
end

-- Running count of events of a type: { { time, value } } ascending (value = events up to that time).
function Metrics:EventSeries(eventType, since)
  local records, times = FC.Storage:GetStream("events").records, {}
  for i = #records, 1, -1 do
    local r = records[i]
    if r.time and r.time < since then break end
    if r.type == eventType and r.time then table.insert(times, 1, r.time) end
  end
  local out = { { time = since, value = 0 } }
  for i, t in ipairs(times) do out[#out + 1] = { time = t, value = i } end
  return out
end

-- Points of a series inside the window: { { x, value, time } }. The value at a time is the last sample at or
-- before it. def.step draws changes as steps (exact event times); def.relative shows the change since the
-- start of the window instead of the value itself.
function Metrics:WindowPoints(series, spans, def)
  local function valueAt(t)
    local v
    for _, p in ipairs(series) do
      if p.time <= t then v = p.value else break end
    end
    return v
  end
  local points = {}
  local function add(x, t, v)
    if v ~= nil then points[#points + 1] = { x = x, time = t, value = v } end
  end
  for _, span in ipairs(spans) do
    add(span.x, span.from, valueAt(span.from))
    for _, p in ipairs(series) do
      if p.time > span.from and p.time <= span.to then
        local x = span.x + (p.time - span.from)
        if def.step then add(x, p.time, valueAt(p.time - 1)) end
        add(x, p.time, p.value)
      end
    end
    add(span.x + (span.to - span.from), span.to, valueAt(span.to))
  end
  if def.relative and points[1] then
    local base = points[1].value
    for _, p in ipairs(points) do p.value = p.value - base end
  end
  return points
end

-------------------------------------------------------------------------------
-- Graphs (FC:RegisterGraph): series(since) -> { { time, value } }
-------------------------------------------------------------------------------

local function coins(v)
  local sign = v < 0 and "-" or ""
  return sign .. (GetCoinTextureString and GetCoinTextureString(math.abs(v)) or tostring(math.abs(v)))
end

FC:RegisterGraph("xp", { labelKey = "GRAPH_XP", order = 10, color = { 0.58, 0.2, 0.85 }, relative = true,
  series = function(since) return Metrics:FieldSeries("xp", since) end })
FC:RegisterGraph("kills", { labelKey = "GRAPH_KILLS", order = 20, color = { 0.85, 0.2, 0.2 }, relative = true,
  series = function(since) return Metrics:FieldSeries("kills", since) end })
FC:RegisterGraph("quests", { labelKey = "GRAPH_QUESTS", order = 30, color = { 1, 0.82, 0 }, relative = true,
  step = true, series = function(since) return Metrics:EventSeries("quest_completed", since) end })
FC:RegisterGraph("gold", { labelKey = "GRAPH_GOLD", order = 40, color = { 0.95, 0.8, 0.3 },
  series = function(since) return Metrics:FieldSeries("money", since) end, format = coins })
