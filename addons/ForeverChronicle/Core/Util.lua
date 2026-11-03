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

-- NPC ID from a creature GUID ("Creature-0-<server>-<instance>-<zone>-<npcID>-<spawn>"), or nil.
function Util.NpcID(guid)
  local id = type(guid) == "string" and guid:match("^%a+%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
  return tonumber(id)
end

-------------------------------------------------------------------------------
-- Client
-------------------------------------------------------------------------------

-- Enum.UIMapType values, with the Mainline numbers where the enum is missing.
local mapTypes = (Enum and Enum.UIMapType) or {}
Util.MapType = {
  Continent = mapTypes.Continent or 2,
  Zone = mapTypes.Zone or 3,           -- micro maps (caves, building floors) have higher numbers
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
  local v = math.floor(n)
  local s = tostring(math.abs(v)) -- the sign is added afterwards, so no separator lands next to it
  local sep = FC.L.THOUSANDS_SEP
  local out = s:reverse():gsub("(%d%d%d)", "%1" .. sep):reverse()
  if out:sub(1, #sep) == sep then out = out:sub(#sep + 1) end
  return (v < 0 and "-" or "") .. out
end

function Util.FormatTime(t)
  if type(t) ~= "number" then return FC.L.UNKNOWN end
  return date(FC.L.DATETIME_FORMAT, t)
end

-- Lower case for searching, including the German umlauts (string.lower leaves non-ASCII letters alone).
local UMLAUTS = { ["\195\132"] = "\195\164", ["\195\150"] = "\195\182", ["\195\156"] = "\195\188" }
function Util.Fold(s)
  return (string.lower(s):gsub("\195[\132\150\156]", UMLAUTS))
end

-- A matcher for messages built from one of the client's format strings (COMBATLOG_XPGAIN_FIRSTPERSON, ...), so it
-- works in every client language: matcher(msg) returns the arguments in argument order (%d as a number, anything
-- else as text), or nil when msg does not start like the format. Numbered arguments ("%1$s stirbt, Ihr bekommt
-- %2$d Erfahrung.") may come in any order. A format that is not a string never matches.
function Util.FormatMatcher(format)
  if type(format) ~= "string" then return function() return nil end end
  local pattern, slots, i = { "^" }, {}, 1
  while i <= #format do
    local c = format:sub(i, i)
    if c == "%" and format:sub(i + 1, i + 1) == "%" then
      pattern[#pattern + 1] = "%%"
      i = i + 2
    elseif c == "%" then
      local pos, conv, stop = format:match("^(%d*%$?)[-+ #0-9.]*([a-zA-Z])()", i + 1)
      if not conv then
        pattern[#pattern + 1] = "%%"
        i = i + 1
      else
        local numeric = conv == "d" or conv == "i" or conv == "u"
        pattern[#pattern + 1] = numeric and "(%d+)" or "(.-)"
        slots[#slots + 1] = { index = pos:find("%$") and tonumber(pos:match("%d+")) or #slots + 1, numeric = numeric }
        i = stop
      end
    else
      pattern[#pattern + 1] = c:find("[%^%$%(%)%.%[%]%*%+%-%?]") and "%" .. c or c
      i = i + 1
    end
  end
  -- A text argument at the very end would match nothing with "(.-)": let it take the rest.
  if pattern[#pattern] == "(.-)" then pattern[#pattern] = "(.+)" end
  pattern = table.concat(pattern)
  return function(msg)
    if type(msg) ~= "string" then return nil end
    local captures = { msg:match(pattern) }
    if captures[1] == nil then return nil end
    local args, n = {}, 0
    for k, slot in ipairs(slots) do
      local v = captures[k]
      args[slot.index] = slot.numeric and tonumber(v) or v
      n = math.max(n, slot.index)
    end
    return unpack(args, 1, n)
  end
end

-- Binary search in a list sorted ascending: the index of the last element that is <= value (0 if none).
-- field: compare element[field] instead of the element itself.
function Util.BinarySearch(list, value, field)
  local lo, hi, found = 1, #list, 0
  while lo <= hi do
    local mid = math.floor((lo + hi) / 2)
    local v = list[mid]
    if field ~= nil then v = v[field] end
    if v <= value then found, lo = mid, mid + 1 else hi = mid - 1 end
  end
  return found
end
