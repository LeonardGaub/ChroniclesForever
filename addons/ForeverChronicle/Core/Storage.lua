-- Journey Forever - Storage
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
--       snapshots = { [name] = {...} },            -- current state (professions, ...), exported as is
--       streams = { [streamName] = { nextSeq, dropped, records = { ... } } },
--   } },
--   maps, instances, entrances = { ... },        -- account-wide, written by Modules/Positions.lua
-- }
--
-- Every stream record has a per-stream `seq`. The desktop importer uses it to detect
-- records that were dropped by the retention cap before they could be imported.
--
-- In the saved file (schema 2) streams are packed: records = {} and packed = { format, kind, chunks }, many
-- records per string (see "Packing" below). In memory they are always unpacked.

local ADDON, FC = ...
local Util = FC.Util

local Storage = {}
FC.Storage = Storage

-- Streams declared by modules: name -> { cap = n }
Storage.streams = {}

-- Ordered migrations: [n] upgrades a database from schema n-1 to n.
local MIGRATIONS = {
  -- [2]: streams are packed in the saved file. Nothing to convert: unpacking accepts unpacked streams, and
  -- the next save packs them. The schema number keeps older addon versions from overwriting packed data.
  [2] = function() end,
}

-------------------------------------------------------------------------------
-- Packing
-- The client loads a saved file as one Lua chunk, and Lua allows only about 262,000 distinct constants
-- (strings and numbers) per chunk. A file with more does not load at all ("constant table overflow",
-- confirmed in game on 2026-10-14) and would be overwritten with empty data on the next logout. Every record
-- adds one constant or more, so on logout each stream is packed into a few long strings and unpacked on load:
--   kind "lines":  compact string records, joined with newlines, PACK_LINES per chunk
--   kind "tables": table records as Lua table text "{...},{...}", PACK_TABLES per chunk
-------------------------------------------------------------------------------

Storage.PACK_FORMAT = 1
Storage.PACK_LINES = 400
Storage.PACK_TABLES = 100

local KEYWORDS = {}
for word in ([[and break do else elseif end false for function goto if in local nil not or repeat return then
  true until while]]):gmatch("%a+") do KEYWORDS[word] = true end

local ESCAPES = { ["\\"] = "\\\\", ['"'] = '\\"', ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }
local function quote(s)
  return '"' .. s:gsub('[%c"\\]', function(c) return ESCAPES[c] or string.format("\\%03d", c:byte()) end) .. '"'
end

local function serialize(v, out)
  local t = type(v)
  if t == "string" then
    out[#out + 1] = quote(v)
  elseif t == "number" then
    if v ~= v or v == math.huge or v == -math.huge then
      out[#out + 1] = "0"
    elseif v == math.floor(v) and math.abs(v) < 2 ^ 53 then
      out[#out + 1] = string.format("%.0f", v) -- %d is 32-bit on some clients
    else
      out[#out + 1] = string.format("%.17g", v)
    end
  elseif t == "boolean" then
    out[#out + 1] = v and "true" or "false"
  elseif t == "table" then
    out[#out + 1] = "{"
    local n = #v
    for i = 1, n do
      serialize(v[i], out)
      out[#out + 1] = ","
    end
    for k, val in pairs(v) do
      local inArray = type(k) == "number" and k >= 1 and k <= n and k == math.floor(k)
      if not inArray and (type(k) == "string" or type(k) == "number") then
        if type(k) == "string" and k:match("^[%a_][%w_]*$") and not KEYWORDS[k] then
          out[#out + 1] = k .. "="
        else
          out[#out + 1] = "["
          serialize(k, out)
          out[#out + 1] = "]="
        end
        serialize(val, out)
        out[#out + 1] = ","
      end
    end
    out[#out + 1] = "}"
  else
    out[#out + 1] = "nil"
  end
end

-- True if text holds only literal data: strings, numbers, true/false/nil, braces, brackets, keys, "=" and ",".
-- No names, calls, operators or loops, so compiling it cannot run anything (friends' data arrives packed too).
local function plainData(text)
  -- Strings are cut out by walking them like Lua does (escapes included), so nothing outside a string can pass
  -- for one. Long brackets ([[ ]], [=[ ]=]) and comments are never written by the packer: rejected.
  local outside, i, n = {}, 1, #text
  while i <= n do
    local q = text:find('"', i, true)
    outside[#outside + 1] = text:sub(i, (q or n + 1) - 1)
    if not q then break end
    local j = q + 1
    while true do
      local c = text:find('[\\"\n]', j)
      if not c or text:byte(c) == 10 then return false end -- unterminated string
      if text:byte(c) == 34 then j = c + 1; break end
      j = c + 2                                            -- an escape: skip the escaped character
    end
    outside[#outside + 1] = " "
    i = j
  end
  local s = table.concat(outside)
  if s:find("[[", 1, true) or s:find("[=", 1, true) or s:find("--", 1, true) then return false end
  s = s:gsub("[%a_][%w_]*%s*=", "=")                   -- keys
  s = s:gsub("%f[%w_]true%f[^%w_]", ""):gsub("%f[%w_]false%f[^%w_]", ""):gsub("%f[%w_]nil%f[^%w_]", "")
  s = s:gsub("%-?%d+%.?%d*[eE]?[%+%-]?%d*", "")        -- numbers
  return not s:find("[^%s{}%[%]=,]")
end
Storage.IsPlainData = plainData

-- Compiles a chunk of packed table records into a function returning them as a list. Only plain data is
-- compiled, and without access to anything (empty environment).
local function compile(chunk)
  if not plainData(chunk) then return nil end
  local text = "return {" .. chunk .. "}"
  if loadstring and setfenv then
    local fn = loadstring(text, "=packed")
    if fn then setfenv(fn, {}) end
    return fn
  end
  return load(text, "=packed", "t", {})
end

-- Unpacks a stream in place (no-op if it is not packed). Chunks that cannot be read are kept in
-- stream.unreadable, so they are saved again instead of being lost.
function Storage.Unpack(stream)
  local packed = type(stream) == "table" and stream.packed
  if type(packed) ~= "table" then return stream end
  local records = {}
  for _, chunk in ipairs(type(packed.chunks) == "table" and packed.chunks or {}) do
    if type(chunk) == "string" then
      if packed.kind == "lines" then
        for line in chunk:gmatch("[^\n]+") do records[#records + 1] = line end
      else
        local fn = compile(chunk)
        local ok, list = false, nil
        if fn then ok, list = pcall(fn) end
        if ok and type(list) == "table" then
          for _, r in ipairs(list) do records[#records + 1] = r end
        else
          stream.unreadable = stream.unreadable or {}
          table.insert(stream.unreadable, chunk)
          if FC.Diagnostics then FC.Diagnostics:Log("error", "a packed stream chunk could not be read") end
        end
      end
    end
  end
  for _, r in ipairs(type(stream.records) == "table" and stream.records or {}) do records[#records + 1] = r end
  stream.records, stream.packed = records, nil
  return stream
end

-- Packs a stream in place for saving. Records stay in the same order (implicit seq of compact streams).
function Storage.Pack(stream)
  if type(stream) ~= "table" then return stream end
  Storage.Unpack(stream)
  local records = stream.records
  if type(records) ~= "table" or #records == 0 then return stream end
  local lines = true
  for _, r in ipairs(records) do
    if type(r) ~= "string" or r == "" or r:find("\n", 1, true) then lines = false; break end
  end
  local size = lines and Storage.PACK_LINES or Storage.PACK_TABLES
  local chunks = {}
  for i = 1, #records, size do
    local last = math.min(#records, i + size - 1)
    if lines then
      chunks[#chunks + 1] = table.concat(records, "\n", i, last)
    else
      local out = {}
      for j = i, last do
        serialize(records[j], out)
        out[#out + 1] = ","
      end
      chunks[#chunks + 1] = table.concat(out)
    end
  end
  stream.packed = { format = Storage.PACK_FORMAT, kind = lines and "lines" or "tables", chunks = chunks }
  stream.records = {} -- a new table: other references (e.g. the friends share) keep the old one
  return stream
end

function Storage.UnpackCharacter(char)
  if type(char) == "table" and type(char.streams) == "table" then
    for _, s in pairs(char.streams) do Storage.Unpack(s) end
  end
end

function Storage.PackCharacter(char)
  if type(char) == "table" and type(char.streams) == "table" then
    for _, s in pairs(char.streams) do Storage.Pack(s) end
  end
end

-- Right before the game writes the saved file (after every logout handler): trim to the caps, then pack.
function Storage:PrepareSave()
  if FC.readOnlyReason or not FC.db then return end
  self:TrimAll()
  for _, char in pairs(FC.db.characters or {}) do Storage.PackCharacter(char) end
end

-------------------------------------------------------------------------------
-- Setup
-------------------------------------------------------------------------------

local function newDatabase()
  return {
    schemaVersion = FC.SCHEMA_VERSION,
    createdAt = time(),
    settings = { language = FC.DEFAULT_LANGUAGE, debug = false, modules = {},
      map = { trail = false, colors = "level" } },  -- map page: 15-minute trail, route colours
    diagnostics = { log = {}, capabilities = {} },
    characters = {},
    maps = {}, instances = {}, entrances = {}, -- account-wide map geometry, instance names, dungeon entrances
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
  db.dungeonProbe = nil -- research data of the removed dungeon probe (until 0.15.0)
  db.addonVersion = FC.VERSION
  FC.db = db
  for _, char in pairs(db.characters) do Storage.UnpackCharacter(char) end
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
    char = { info = { firstSeenAt = time() }, stats = {}, state = {}, streams = {}, snapshots = {} }
    chars[key] = char
  end
  Util.MergeDefaults(char, { info = {}, stats = {}, state = {}, streams = {}, snapshots = {} })
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

-- Snapshot of something the character has right now (professions, ...). Unlike streams it is replaced
-- over time; the desktop app mirrors the latest version.
function Storage:GetSnapshot(name)
  local snapshots = FC.char.snapshots
  snapshots[name] = snapshots[name] or {}
  return snapshots[name]
end

-------------------------------------------------------------------------------
-- Streams (bounded, append-only record lists)
-------------------------------------------------------------------------------

-- Declare a stream. cap = number of records kept in SavedVariables; icon is shown in the storage overview.
-- opts.onTrim(records): receives the oldest records right before the cap removes them (e.g. to archive them).
-- opts.quiet: no "nearly full" warning (for streams whose old records are archived, not lost).
function Storage:DefineStream(name, cap, icon, opts)
  opts = opts or {}
  self.streams[name] = { cap = cap, icon = icon, onTrim = opts.onTrim, quiet = opts.quiet }
end

function Storage:GetStream(name)
  local streams = FC.char.streams
  local s = streams[name]
  if not s then
    s = { nextSeq = 1, dropped = 0, records = {} }
    streams[name] = s
  end
  return Storage.Unpack(s)
end

-- Removes the oldest records so that at most `cap` remain. Done in batches to keep appends cheap.
local function trim(stream, cap, name, def)
  local records = stream.records
  local excess = #records - cap
  if excess <= 0 then return end
  local n = #records
  if def and def.onTrim then
    local old = {}
    for i = 1, excess do old[i] = records[i] end
    FC:SafeCall(def.onTrim, old)
  end
  for i = 1, n - excess do records[i] = records[i + excess] end
  for i = n - excess + 1, n do records[i] = nil end
  stream.dropped = stream.dropped + excess
  FC.Diagnostics:Log("warn", string.format("stream %s: %d old records dropped (cap %d)", name, excess, cap))
end

-- Adds a value at the end of a stream and advances nextSeq; withSeq also stores the seq in the record.
-- Trims in batches (once the stream is 10 % over its cap) and warns when it is nearly full.
local function append(self, name, value, withSeq)
  local def = self.streams[name]
  assert(def, "unknown stream " .. tostring(name))
  local stream = self:GetStream(name)
  if withSeq then value.seq = stream.nextSeq end
  local records = stream.records
  records[#records + 1] = value
  stream.nextSeq = stream.nextSeq + 1
  if #records > def.cap * 1.1 then trim(stream, def.cap, name, def) end
  self:WarnIfNearlyFull(name, #records, def.cap)
end

-- Appends a record (table) and assigns its seq. Returns the record.
function Storage:Append(name, record)
  append(self, name, record, true)
  return record
end

-- Warns once per session per stream when 80% of the cap is reached (spec F-013).
local warned = {}
function Storage:WarnIfNearlyFull(name, count, cap)
  if warned[name] or count < cap * 0.8 or self.streams[name].quiet then return end
  warned[name] = true
  local L = FC.L
  FC:Print(string.format(L.STORAGE_WARNING, L["STREAM_" .. name:upper()], math.floor(math.min(count, cap) / cap * 100)))
end

-- Compact streams store plain values (e.g. strings) instead of tables. Their seq is implicit:
-- the record at index i has seq = nextSeq - #records + i - 1 (records are only appended and trimmed
-- from the front). The desktop importer derives it the same way.
function Storage:AppendRaw(name, value)
  append(self, name, value)
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
    trim(self:GetStream(name), def.cap, name, def)
  end
end
