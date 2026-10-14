-- Forever Chronicle - Storage
-- Owns the SavedVariables table, schema versioning, character records and bounded streams.
--
-- ForeverChronicleDB = {
--   schemaVersion, addonVersion, createdAt,
--   settings    = { language, debug, modules = { [moduleName] = {...} } },
--   diagnostics = { log = {...}, capabilities = {...} },
--   characters  = { [characterKey] = {
--       info    = { guid, name, nameSuffix, realm, ... },
--       stats   = { [statKey] = number },
--       state   = { [moduleName] = {...} },        -- free per-module state
--       streams = { [streamName] = { nextSeq, dropped, records = { ... } } },
--   } },
-- }
--
-- Every stream record has a per-stream `seq`. The desktop importer uses it to detect
-- records that were dropped by the retention cap before they could be imported.

local ADDON, FC = ...
local Util = FC.Util

local Storage = {}
FC.Storage = Storage

-- Streams declared by modules: name -> { cap = n }
Storage.streams = {}

-- Ordered migrations: [n] upgrades a database from schema n-1 to n.
local MIGRATIONS = {
  -- [2] = function(db) ... end,
}

-------------------------------------------------------------------------------
-- Setup
-------------------------------------------------------------------------------

local function newDatabase()
  return {
    schemaVersion = FC.SCHEMA_VERSION,
    createdAt = time(),
    settings = { language = FC.DEFAULT_LANGUAGE, debug = false, modules = {} },
    diagnostics = { log = {}, capabilities = {} },
    characters = {},
  }
end

function Storage:Initialize()
  local db = ForeverChronicleDB
  if type(db) ~= "table" or type(db.schemaVersion) ~= "number" then
    db = newDatabase()
  end
  if db.schemaVersion > FC.SCHEMA_VERSION then
    -- Written by a newer addon version: keep it untouched and run without saving changes to it.
    FC.readOnlyReason = "schema " .. db.schemaVersion .. " is newer than " .. FC.SCHEMA_VERSION
    db = newDatabase()
  else
    for v = db.schemaVersion + 1, FC.SCHEMA_VERSION do
      if MIGRATIONS[v] then MIGRATIONS[v](db) end
      db.schemaVersion = v
    end
    ForeverChronicleDB = db
  end
  Util.MergeDefaults(db, newDatabase())
  db.addonVersion = FC.VERSION
  FC.db = db
end

-------------------------------------------------------------------------------
-- Characters
-------------------------------------------------------------------------------

-- Natural key: the player GUID (globally unique in Forever). Falls back to name-realm.
local function characterKey()
  local guid = Util.SafeValue("string", UnitGUID, "player")
  if guid then return guid, "guid" end
  local name = Util.SafeValue("string", UnitName, "player") or "?"
  local realm = Util.SafeValue("string", GetRealmName) or "?"
  return name .. "-" .. realm, "name_based"
end

function Storage:OpenCharacter()
  local key, quality = characterKey()
  local chars = FC.db.characters
  local char = chars[key]
  if not char then
    char = { info = { firstSeenAt = time() }, stats = {}, state = {}, streams = {} }
    chars[key] = char
  end
  Util.MergeDefaults(char, { info = {}, stats = {}, state = {}, streams = {} })
  char.info.key = key
  char.info.identityQuality = quality
  FC.char = char
  FC.charKey = key
  for name in pairs(self.streams) do self:GetStream(name) end
  return char
end

-- Free-form persistent state for a module on the current character.
function Storage:GetState(moduleName)
  local state = FC.char.state
  state[moduleName] = state[moduleName] or {}
  return state[moduleName]
end

-------------------------------------------------------------------------------
-- Streams (bounded, append-only record lists)
-------------------------------------------------------------------------------

-- Declare a stream. cap = number of records kept in SavedVariables; icon is shown in the storage overview.
function Storage:DefineStream(name, cap, icon)
  self.streams[name] = { cap = cap, icon = icon }
end

function Storage:GetStream(name)
  local streams = FC.char.streams
  local s = streams[name]
  if not s then
    s = { nextSeq = 1, dropped = 0, records = {} }
    streams[name] = s
  end
  return s
end

-- Removes the oldest records so that at most `cap` remain. Done in batches to keep appends cheap.
local function trim(stream, cap, name)
  local records = stream.records
  local excess = #records - cap
  if excess <= 0 then return end
  local n = #records
  for i = 1, n - excess do records[i] = records[i + excess] end
  for i = n - excess + 1, n do records[i] = nil end
  stream.dropped = stream.dropped + excess
  FC.Diagnostics:Log("warn", string.format("stream %s: %d old records dropped (cap %d)", name, excess, cap))
end

-- Appends a record (table) and assigns its seq. Returns the record.
function Storage:Append(name, record)
  local def = self.streams[name]
  assert(def, "unknown stream " .. tostring(name))
  local stream = self:GetStream(name)
  record.seq = stream.nextSeq
  stream.nextSeq = stream.nextSeq + 1
  local records = stream.records
  records[#records + 1] = record
  if #records > def.cap * 1.1 then trim(stream, def.cap, name) end
  self:WarnIfNearlyFull(name, #records, def.cap)
  return record
end

-- Warns once per session per stream when 80% of the cap is reached (spec F-013).
local warned = {}
function Storage:WarnIfNearlyFull(name, count, cap)
  if warned[name] or count < cap * 0.8 then return end
  warned[name] = true
  local L = FC.L
  FC:Print(string.format(L.STORAGE_WARNING, L["STREAM_" .. name:upper()], math.floor(math.min(count, cap) / cap * 100)))
end

-- Compact streams store plain values (e.g. strings) instead of tables. Their seq is implicit:
-- the record at index i has seq = nextSeq - #records + i - 1 (records are only appended and trimmed
-- from the front). The desktop importer derives it the same way.
function Storage:AppendRaw(name, value)
  local def = self.streams[name]
  assert(def, "unknown stream " .. tostring(name))
  local stream = self:GetStream(name)
  local records = stream.records
  records[#records + 1] = value
  stream.nextSeq = stream.nextSeq + 1
  if #records > def.cap * 1.1 then trim(stream, def.cap, name) end
  self:WarnIfNearlyFull(name, #records, def.cap)
end

-- Replaces the newest record of a compact stream (e.g. to extend a stationary position sample).
function Storage:ReplaceLast(name, value)
  local records = self:GetStream(name).records
  if #records > 0 then records[#records] = value end
end

-- Usage per stream for the UI and the storage warning: list of { name, count, cap, dropped }.
function Storage:GetUsage()
  local usage = {}
  if not FC.char then return usage end
  for name, def in pairs(self.streams) do
    local s = self:GetStream(name)
    usage[#usage + 1] = { name = name, count = #s.records, cap = def.cap, dropped = s.dropped, icon = def.icon }
  end
  table.sort(usage, function(a, b) return a.name < b.name end)
  return usage
end

-- Final trim on logout so the saved file never exceeds the caps.
function Storage:TrimAll()
  if not FC.char then return end
  for name, def in pairs(self.streams) do
    trim(self:GetStream(name), def.cap, name)
  end
end
