-- Journey Forever - Dungeons module
-- Boss kills in dungeons and raids, and the first kill of a dungeon's last boss ("dungeon_completed", with its
-- own screenshot trigger).
--   boss_killed:       every won boss encounter { encounterID, name, instanceID, instance, difficultyID,
--                      first = this character's first kill of this boss, final = the instance's last boss
--                      (nil when the client cannot tell) }
--   dungeon_completed: this character's first kill of an instance's last boss { instanceID, instance,
--                      encounterID, boss }
-- The last boss is the last encounter in the client's encounter journal; without a journal entry, the
-- dungeon finder's boss list (all bosses dead) is used instead.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Dungeons = FC:NewModule("Dungeons", { order = 32 })

local DEDUPE_SECONDS = 15   -- ENCOUNTER_END and BOSS_KILL report the same kill

FC:RegisterCapability("bosses", "CAP_BOSSES", function() return FC.eventStatus.ENCOUNTER_END == "registered" end)

FC:RegisterEventCategory("dungeons", { labelKey = "CAT_DUNGEONS", icon = "Interface\\Icons\\INV_Misc_Key_03", order = 50 })

FC:RegisterEventType("boss_killed", {
  icon = "Interface\\Icons\\INV_Sword_04", category = "dungeons",
  format = function(r)
    local d = r.data
    return d.instance and string.format(L.EVT_BOSS_KILLED_IN, d.name or "?", d.instance)
      or string.format(L.EVT_BOSS_KILLED, d.name or "?")
  end,
})
FC:RegisterEventType("dungeon_completed", {
  icon = "Interface\\Icons\\INV_Misc_Key_03", category = "dungeons", highlight = "milestone",
  format = function(r) return string.format(L.EVT_DUNGEON_COMPLETED, r.data.instance or "?", r.data.boss or "?") end,
})

FC:RegisterStat("bosses_killed", { labelKey = "STAT_BOSSES", order = 21, icon = "Interface\\Icons\\INV_Sword_04" })
FC:RegisterStat("dungeons_completed", { labelKey = "STAT_DUNGEONS", order = 22, icon = "Interface\\Icons\\INV_Misc_Key_03" })

-------------------------------------------------------------------------------
-- Encounter journal
-------------------------------------------------------------------------------

-- instanceID -> { journalID, lastEncounterID, lastBoss } (false if the journal has nothing)
Dungeons.journal = {}

-- The journal entry of an instance, by searching the journal's instance lists (all tiers, dungeons and raids).
local function findJournalID(instanceID)
  if type(EJ_GetInstanceByIndex) ~= "function" or type(EJ_GetInstanceInfo) ~= "function" then return nil end
  local tiers = Util.SafeValue("number", EJ_GetNumTiers) or 1
  local previousTier = Util.SafeValue("number", EJ_GetCurrentTier)
  local found
  for tier = 1, tiers do
    if type(EJ_SelectTier) == "function" then pcall(EJ_SelectTier, tier) end
    for _, isRaid in ipairs({ false, true }) do
      for i = 1, 100 do
        local journalID = Util.SafeValues(EJ_GetInstanceByIndex, i, isRaid)
        if type(journalID) ~= "number" then break end
        if select(10, Util.SafeValues(EJ_GetInstanceInfo, journalID)) == instanceID then found = journalID; break end
      end
      if found then break end
    end
    if found then break end
  end
  if previousTier and type(EJ_SelectTier) == "function" then pcall(EJ_SelectTier, previousTier) end
  return found
end

-- What the journal knows about an instance (cached).
function Dungeons:Journal(instanceID)
  if not instanceID then return nil end
  local known = self.journal[instanceID]
  if known ~= nil then return known or nil end
  local journalID = findJournalID(instanceID)
  if not journalID then
    self.journal[instanceID] = false
    return nil
  end
  local entry = { journalID = journalID }
  if type(EJ_GetEncounterInfoByIndex) == "function" then
    for i = 1, 40 do
      local name, _, _, _, _, _, encounterID = Util.SafeValues(EJ_GetEncounterInfoByIndex, i, journalID)
      if type(name) ~= "string" then break end
      entry.lastBoss, entry.lastEncounterID = name, type(encounterID) == "number" and encounterID or nil
    end
  end
  self.journal[instanceID] = entry
  return entry
end

-- The dungeon finder's boss list: true if all bosses of the current instance are dead, nil if unknown.
local function finderComplete()
  local lfgID = select(10, Util.SafeValues(GetInstanceInfo))
  if type(lfgID) ~= "number" or lfgID <= 0 then return nil end
  local total, done = Util.SafeValues(GetLFGDungeonNumEncounters, lfgID)
  if type(total) ~= "number" or total == 0 or type(done) ~= "number" then return nil end
  return done >= total
end

-- Is this encounter the instance's last boss? nil when the client cannot tell.
function Dungeons:IsFinal(instanceID, encounterID)
  local journal = self:Journal(instanceID)
  if journal and journal.lastEncounterID then return journal.lastEncounterID == encounterID end
  return finderComplete()
end

-------------------------------------------------------------------------------
-- Boss kills
-------------------------------------------------------------------------------

local function state()
  local s = FC.Storage:GetState("Dungeons")
  s.killed = s.killed or {}       -- encounterID -> time of the first kill
  s.completed = s.completed or {} -- instanceID -> time of the first kill of the last boss
  return s
end

function Dungeons:OnBossKilled(encounterID, name, difficultyID)
  if type(encounterID) ~= "number" then return end
  local now = time()
  if self.lastKill and self.lastKill.id == encounterID and now - self.lastKill.time <= DEDUPE_SECONDS then return end
  self.lastKill = { id = encounterID, time = now }

  local instanceName, kind, _, _, _, _, _, instanceID = Util.SafeValues(GetInstanceInfo)
  instanceName = type(instanceName) == "string" and instanceName or nil
  instanceID = type(instanceID) == "number" and instanceID or nil
  local s = state()
  local key = tostring(encounterID)
  local first = s.killed[key] == nil
  if first then s.killed[key] = now end
  local final = instanceID and self:IsFinal(instanceID, encounterID)
  FC:Record("boss_killed", { encounterID = encounterID, name = name, instanceID = instanceID,
    instance = instanceName, difficultyID = difficultyID, kind = kind, first = first, final = final })
  FC:IncrementStat("bosses_killed")
  FC:ConfirmCapability("bosses")

  if final and instanceID and s.completed[tostring(instanceID)] == nil then
    s.completed[tostring(instanceID)] = now
    FC:Record("dungeon_completed", { instanceID = instanceID, instance = instanceName, encounterID = encounterID,
      boss = name })
    FC:IncrementStat("dungeons_completed")
  end
end

-- ENCOUNTER_END(encounterID, encounterName, difficultyID, groupSize, success)
Dungeons:RegisterEvent("ENCOUNTER_END", function(self, _, encounterID, name, difficultyID, _, success)
  encounterID, name, success = Util.Plain(encounterID), Util.Plain(name), Util.Plain(success)
  if success == 1 or success == true then self:OnBossKilled(encounterID, name, Util.Plain(difficultyID)) end
end)
-- BOSS_KILL(encounterID, encounterName): the same kill, in case ENCOUNTER_END is missing or hidden.
Dungeons:RegisterEvent("BOSS_KILL", function(self, _, encounterID, name)
  self:OnBossKilled(Util.Plain(encounterID), Util.Plain(name))
end)
