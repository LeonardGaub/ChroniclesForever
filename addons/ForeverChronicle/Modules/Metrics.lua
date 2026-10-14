-- Forever Chronicle - Metrics module
-- A small time series for graphs: every minute (and on logout) the current totals are stored in the compact
-- "metrics" stream when something changed:  time,xpEarned,kills,money,level
-- Graphs use FC.Metrics:HourlyDeltas(field) and FC.Metrics:PlayedHours(n) (hours overlapped by sessions).

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
  return string.format("%d,%d,%d,%d,%d", s.time, s.xp, s.kills, s.money, s.level)
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
-- Queries for graphs
-------------------------------------------------------------------------------

local function hourOf(t) return t - (t % 3600) end

-- Start times of the last n clock hours in which the character played (ascending).
function Metrics:PlayedHours(n)
  local set = {}
  for _, s in ipairs(FC.Storage:GetStream("sessions").records) do
    local stop = s.endedAt or time()
    for h = hourOf(s.startedAt), hourOf(stop), 3600 do set[h] = true end
  end
  local hours = {}
  for h in pairs(set) do hours[#hours + 1] = h end
  table.sort(hours)
  local out = {}
  for i = math.max(1, #hours - n + 1), #hours do out[#out + 1] = hours[i] end
  return out
end

-- Change of a metric per clock hour: { [hourStart] = delta }. Each change counts in the hour it was sampled.
function Metrics:HourlyDeltas(field)
  local out, prev = {}, nil
  for _, text in ipairs(FC.Storage:GetStream("metrics").records) do
    local s = Metrics.Parse(text)
    if s then
      if prev and s[field] and prev[field] then
        local h = hourOf(s.time)
        out[h] = (out[h] or 0) + (s[field] - prev[field])
      end
      prev = s
    end
  end
  return out
end

-- Number of events of a type per clock hour.
function Metrics:HourlyEventCounts(eventType)
  local out = {}
  for _, r in ipairs(FC.Storage:GetStream("events").records) do
    if r.type == eventType and r.time then
      local h = hourOf(r.time)
      out[h] = (out[h] or 0) + 1
    end
  end
  return out
end

-------------------------------------------------------------------------------
-- Graphs (FC:RegisterGraph): values for the given hours
-------------------------------------------------------------------------------

-- Builds a values function from a function that returns { [hourStart] = value } (computed once per call).
local function fromMap(map) return function(hours)
  local byHour, values = map(), {}
  for i, h in ipairs(hours) do values[i] = byHour[h] or 0 end
  return values
end end

FC:RegisterGraph("xp", { labelKey = "GRAPH_XP", order = 10, color = { 0.58, 0.2, 0.85 },
  values = fromMap(function() return Metrics:HourlyDeltas("xp") end),
  format = function(v) return FC.Util.FormatNumber(v) end })
FC:RegisterGraph("kills", { labelKey = "GRAPH_KILLS", order = 20, color = { 0.85, 0.2, 0.2 },
  values = fromMap(function() return Metrics:HourlyDeltas("kills") end) })
FC:RegisterGraph("quests", { labelKey = "GRAPH_QUESTS", order = 30, color = { 1, 0.82, 0 },
  values = fromMap(function() return Metrics:HourlyEventCounts("quest_completed") end) })
FC:RegisterGraph("gold", { labelKey = "GRAPH_GOLD", order = 40, color = { 0.95, 0.8, 0.3 },
  values = fromMap(function() return Metrics:HourlyDeltas("money") end),
  format = function(v)
    local sign = v < 0 and "-" or ""
    return sign .. (GetCoinTextureString and GetCoinTextureString(math.abs(v)) or tostring(math.abs(v)))
  end })
