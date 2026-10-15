-- Journey Forever - Util
-- Small helpers without game state: secret-value guards, safe calls, IDs, client constants, table helpers.

local ADDON, FC = ...
FC.Util = {}
local Util = FC.Util

-------------------------------------------------------------------------------
-- Secret values (Midnight addon rules)
-------------------------------------------------------------------------------

-- True if v is a secret value. Check this before comparing or testing values from game APIs.
function Util.IsSecret(v)
  if issecretvalue then
    local ok, res = pcall(issecretvalue, v)
    if ok then return res == true end
  end
  return false
end

-- Returns v, or nil if v is secret.
function Util.Plain(v)
  if Util.IsSecret(v) then return nil end
  return v
end

-- Calls fn and returns its first result as a plain value of the expected Lua type, or nil.
function Util.SafeValue(expectedType, fn, ...)
  if type(fn) ~= "function" then return nil end
  local ok, v = pcall(fn, ...)
  if not ok then return nil end
  v = Util.Plain(v)
  if expectedType and type(v) ~= expectedType then return nil end
  return v
end

function Util.Pack(...)
  return { n = select("#", ...), ... }
end

-- Like SafeValue, but returns all results, each made plain.
function Util.SafeValues(fn, ...)
  if type(fn) ~= "function" then return end
  -- Count with select("#"): results may contain nils (e.g. UnitPosition in instances).
  local res = Util.Pack(pcall(fn, ...))
  if not res[1] then return end
  for i = 2, res.n do res[i] = Util.Plain(res[i]) end
  return unpack(res, 2, res.n)
end

-------------------------------------------------------------------------------
-- IDs
-------------------------------------------------------------------------------

local idCounter = 0

-- Unique record ID: wall-clock time, a per-load counter and two random parts.
function Util.NewId()
  idCounter = idCounter + 1
  return string.format("%08x%04x%07x%07x", time(), idCounter % 0x10000,
    math.random(0, 0xFFFFFFF), math.random(0, 0xFFFFFFF))
end

-------------------------------------------------------------------------------
-- Client
-------------------------------------------------------------------------------

-- Enum.UIMapType values, with the Mainline numbers where the enum is missing.
local mapTypes = (Enum and Enum.UIMapType) or {}
Util.MapType = {
  Continent = mapTypes.Continent or 2,
  Zone = mapTypes.Zone or 3,           -- micro maps (caves, building floors) have higher numbers
  Dungeon = mapTypes.Dungeon or 4,
}

-- The client's build number as a string (e.g. "70338"). Data recorded per build compares against it.
function Util.ClientBuild()
  local _, build = GetBuildInfo()
  return tostring(build)
end

-------------------------------------------------------------------------------
-- Tables and formatting
-------------------------------------------------------------------------------

-- Fills missing keys of target from defaults (recursively). Existing values are kept.
function Util.MergeDefaults(target, defaults)
  for k, v in pairs(defaults) do
    if type(v) == "table" then
      if type(target[k]) ~= "table" then target[k] = {} end
      Util.MergeDefaults(target[k], v)
    elseif target[k] == nil then
      target[k] = v
    end
  end
  return target
end

function Util.Round(v, decimals)
  local m = 10 ^ (decimals or 0)
  return math.floor(v * m + 0.5) / m
end

-- "3 Std. 12 Min." style duration using locale strings.
function Util.FormatDuration(seconds)
  local L = FC.L
  if type(seconds) ~= "number" or seconds < 0 then return L.UNKNOWN end
  local d = math.floor(seconds / 86400)
  local h = math.floor((seconds % 86400) / 3600)
  local m = math.floor((seconds % 3600) / 60)
  if d > 0 then return string.format(L.DURATION_DHM, d, h, m) end
  if h > 0 then return string.format(L.DURATION_HM, h, m) end
  return string.format(L.DURATION_M, m)
end

-- 1234567 -> "1.234.567" (German) / "1,234,567" (English)
function Util.FormatNumber(n)
  if type(n) ~= "number" then return FC.L.UNKNOWN end
  local s = tostring(math.floor(n))
  local sep = FC.L.THOUSANDS_SEP
  local out = s:reverse():gsub("(%d%d%d)", "%1" .. sep):reverse()
  if out:sub(1, #sep) == sep then out = out:sub(#sep + 1) end
  return out
end

function Util.FormatTime(t)
  if type(t) ~= "number" then return FC.L.UNKNOWN end
  return date(FC.L.DATETIME_FORMAT, t)
end
