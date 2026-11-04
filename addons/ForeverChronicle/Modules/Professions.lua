-- Journey Forever - Professions module
-- Records when the character learns a profession ("profession_learned") or reaches a new rank in one
-- ("profession_rank"); the cinematic plays both. Nothing else about professions is kept: no recipes, no skill.
--
-- Professions are read with the Mainline API at login and on skill changes. The list below exists only to tell
-- what is new since the last scan:
--
-- snapshots.professions = {
--   baseline,  -- true after the first scan: professions appearing later become "profession_learned" events
--   list = { { skillLine, name, icon, maxRank, active } },
-- }

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Professions = FC:NewModule("Professions", { order = 35 })

local LOGIN_DELAY = 5        -- profession data can arrive late after login

-------------------------------------------------------------------------------
-- Registrations
-------------------------------------------------------------------------------

local ICON = "Interface\\Icons\\Trade_BlackSmithing"

FC:RegisterCapability("professions", "CAP_PROFESSIONS", function()
  return type(GetProfessions) == "function" and type(GetProfessionInfo) == "function"
end)

FC:RegisterEventCategory("professions", { labelKey = "CAT_PROFESSIONS", icon = ICON, order = 60 })

FC:RegisterEventType("profession_learned", {
  icon = ICON, category = "professions", highlight = "milestone",
  getIcon = function(r) return r.data.icon end,
  format = function(r) return string.format(L.EVT_PROFESSION_LEARNED, r.data.name or "?") end,
})
FC:RegisterEventType("profession_rank", {
  icon = ICON, category = "professions",
  getIcon = function(r) return r.data.icon end,
  format = function(r)
    return string.format(L.EVT_PROFESSION_RANK, r.data.name or "?", Professions.RankName(r.data.maxRank))
  end,
})

-------------------------------------------------------------------------------
-- Helpers
-------------------------------------------------------------------------------

-- Classic rank names by maximum skill (Apprentice 75 ... Artisan 300). Unknown maximums show the number.
local RANKS = { [75] = "RANK_APPRENTICE", [150] = "RANK_JOURNEYMAN", [225] = "RANK_EXPERT", [300] = "RANK_ARTISAN" }

function Professions.RankName(maxRank)
  local key = RANKS[maxRank]
  return key and L[key] or tostring(maxRank or "?")
end

function Professions:GetSnapshot()
  local snap = FC.Storage:GetSnapshot("professions")
  snap.list = snap.list or {}
  return snap
end

function Professions:Find(skillLine)
  for _, prof in ipairs(self:GetSnapshot().list) do
    if prof.skillLine == skillLine then return prof end
  end
end

-- Until 0.15 the addon also kept the skill, the known recipes and "recipe_learned" events. Removes what is left
-- of them from every character in the saved file.
local OLD_FIELDS = { "recipes", "rank", "modifier", "kind", "firstSeenAt", "updatedAt", "unlearnedAt" }

function Professions.RemoveOldData(db)
  local caps = type(db.diagnostics) == "table" and db.diagnostics.capabilities
  if type(caps) == "table" then caps.recipes = nil end
  for _, char in pairs(db.characters or {}) do
    local snap = type(char.snapshots) == "table" and char.snapshots.professions
    if type(snap) == "table" then
      snap.scannedAt = nil
      for _, prof in ipairs(type(snap.list) == "table" and snap.list or {}) do
        for _, field in ipairs(OLD_FIELDS) do prof[field] = nil end
      end
    end
    local events = type(char.streams) == "table" and char.streams.events
    local records = type(events) == "table" and events.records
    if type(records) == "table" then
      local n = 0
      for i = 1, #records do
        local r = records[i]
        if not (type(r) == "table" and r.type == "recipe_learned") then
          n = n + 1
          records[n] = r
        end
      end
      for i = #records, n + 1, -1 do records[i] = nil end
    end
  end
end

-------------------------------------------------------------------------------
-- Scan
-------------------------------------------------------------------------------

-- Reads all professions. Returns the number found, or nil if the API is missing.
-- The first scan that finds something (or the one shortly after login) sets the baseline: professions the
-- character already had are not reported as newly learned.
function Professions:Scan(setBaseline)
  if type(GetProfessions) ~= "function" then return nil end
  local snap = self:GetSnapshot()
  local slots = Util.Pack(Util.SafeValues(GetProfessions))
  local seen, found = {}, 0
  for slot = 1, math.max(slots.n or 0, 7) do
    local index = slots[slot]
    if type(index) == "number" then
      local name, icon, _, maxRank, _, _, skillLine = Util.SafeValues(GetProfessionInfo, index)
      if type(skillLine) == "number" and type(name) == "string" then
        found = found + 1
        seen[skillLine] = true
        self:Update(snap, skillLine, { name = name, icon = icon, maxRank = maxRank })
      end
    end
  end
  -- A profession no longer listed was unlearned. Only trusted when the scan found something at all,
  -- so an empty answer while the client is still loading does not remove anything.
  if found > 0 then
    for _, prof in ipairs(snap.list) do
      if prof.active and not seen[prof.skillLine] then prof.active = false end
    end
    FC:ConfirmCapability("professions")
  end
  snap.baseline = snap.baseline or found > 0 or setBaseline == true
  return found
end

function Professions:Update(snap, skillLine, info)
  local prof = self:Find(skillLine)
  if not prof then
    prof = { skillLine = skillLine }
    table.insert(snap.list, prof)
    if snap.baseline then
      FC:Record("profession_learned", { skillLine = skillLine, name = info.name, icon = info.icon })
    end
  elseif not prof.active and snap.baseline then
    FC:Record("profession_learned", { skillLine = skillLine, name = info.name, icon = info.icon })
  elseif snap.baseline and type(info.maxRank) == "number" and type(prof.maxRank) == "number"
      and info.maxRank > prof.maxRank then
    FC:Record("profession_rank", { skillLine = skillLine, name = info.name, icon = info.icon, maxRank = info.maxRank })
  end
  prof.active = true
  prof.name, prof.icon, prof.maxRank = info.name, info.icon, info.maxRank
  return prof
end

function Professions:ScheduleScan(delay, setBaseline)
  FC:Debounce(self, "scanPending", delay or 1, function() self:Scan(setBaseline) end)
end

-------------------------------------------------------------------------------
-- Events
-------------------------------------------------------------------------------

function Professions:OnEnable()
  self.RemoveOldData(FC.db)
  self:Scan()
  self:ScheduleScan(LOGIN_DELAY, true)
end

Professions:RegisterEvent("SKILL_LINES_CHANGED", function(self) self:ScheduleScan() end)
Professions:RegisterEvent("CHAT_MSG_SKILL", function(self) self:ScheduleScan() end)
