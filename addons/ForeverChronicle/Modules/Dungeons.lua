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
--
-- Inside dungeons the client gives no map position (Phase 0: GetBestMapForUnit and UnitPosition return nil in
-- Ragefire Chasm), so routes stop at the entrance. To find out what a dungeon map could show instead, the
-- module probes once per instance and session what the client offers there and stores it account-wide in
-- FC.db.dungeonProbe[instanceID] (see docs/Dungeon_Maps.md), including the sub-area names passed inside.
-- "/fj dungeon" prints the result.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Dungeons = FC:NewModule("Dungeons", { order = 32 })

local DUNGEON_MAP_TYPE = 4  -- Enum.UIMapType.Dungeon
local AZEROTH = 947
local DEDUPE_SECONDS = 15   -- ENCOUNTER_END and BOSS_KILL report the same kill
local PROBE_DELAY = 3
local PROBE_LATER = { 30, 120 } -- seconds after entering: is there a position after moving around?

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

-- instanceID -> { journalID, mapID, lastEncounterID, lastBoss, encounters } (false if the journal has nothing)
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
  local entry = { journalID = journalID, encounters = 0 }
  entry.mapID = select(7, Util.SafeValues(EJ_GetInstanceInfo, journalID))
  if type(entry.mapID) ~= "number" or entry.mapID == 0 then entry.mapID = nil end
  if type(EJ_GetEncounterInfoByIndex) == "function" then
    for i = 1, 40 do
      local name, _, _, _, _, _, encounterID = Util.SafeValues(EJ_GetEncounterInfoByIndex, i, journalID)
      if type(name) ~= "string" then break end
      entry.encounters = i
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
  self:NoteEncounter("kill", encounterID, name, final)

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
Dungeons:RegisterEvent("ENCOUNTER_START", function(self, _, encounterID, name)
  self:NoteEncounter("start", Util.Plain(encounterID), Util.Plain(name))
end)

-------------------------------------------------------------------------------
-- Probe: what does the client offer inside this instance?
-------------------------------------------------------------------------------

Dungeons.probed = {}

-- The dungeon's map: from the journal, else a dungeon map of the same name anywhere in Azeroth.
local function findDungeonMap(instanceID, instanceName)
  local journal = Dungeons:Journal(instanceID)
  if journal and journal.mapID then return journal.mapID, "journal" end
  if not (C_Map and C_Map.GetMapChildrenInfo and instanceName) then return nil end
  local children = Util.SafeValue("table", C_Map.GetMapChildrenInfo, AZEROTH, DUNGEON_MAP_TYPE, true)
  for _, info in ipairs(children or {}) do
    if Util.Plain(info.name) == instanceName then return Util.Plain(info.mapID), "name" end
  end
  return nil
end

local function playerPositionOn(mapID)
  if not mapID then return nil end
  local pos = Util.SafeValue("table", C_Map.GetPlayerMapPosition, mapID, "player")
  local x, y
  if pos and pos.GetXY then x, y = Util.SafeValues(pos.GetXY, pos) end
  if type(x) == "number" and type(y) == "number" and (x > 0 or y > 0) then
    return string.format("%.4f,%.4f", x, y)
  end
  return nil
end

function Dungeons:CurrentProbe()
  local _, _, _, _, _, _, _, instanceID = Util.SafeValues(GetInstanceInfo)
  return instanceID and FC.db.dungeonProbe and FC.db.dungeonProbe[tostring(instanceID)]
end

function Dungeons:Probe()
  local name, kind, difficultyID, _, _, _, _, instanceID, _, lfgID = Util.SafeValues(GetInstanceInfo)
  if (kind ~= "party" and kind ~= "raid") or type(instanceID) ~= "number" or self.probed[instanceID] then return end
  self.probed[instanceID] = true
  FC.db.dungeonProbe = FC.db.dungeonProbe or {}
  local p = { time = time(), name = name, kind = kind, difficultyID = difficultyID, lfgID = lfgID,
    build = tostring(select(2, GetBuildInfo())), encounters = {} }

  p.bestMap = Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
  local ux, uy = Util.SafeValues(UnitPosition, "player")
  p.unitPosition = type(ux) == "number" and type(uy) == "number"
  p.facing = Util.SafeValue("number", GetPlayerFacing) ~= nil
  p.speed = Util.SafeValue("number", GetUnitSpeed, "player") ~= nil

  local mapID, mapSource = p.bestMap, p.bestMap and "best" or nil
  if not mapID then mapID, mapSource = findDungeonMap(instanceID, name) end
  p.map, p.mapSource = mapID, mapSource
  if mapID then
    p.position = playerPositionOn(mapID)
    local textures = Util.SafeValue("table", C_Map.GetMapArtLayerTextures, mapID, 1)
    p.artTiles = textures and #textures or 0
    local group = Util.SafeValue("number", C_Map.GetMapGroupID, mapID)
    if group then
      local members = Util.SafeValue("table", C_Map.GetMapGroupMembersInfo, group)
      p.floors = members and #members or nil
    end
    local onMap = C_EncounterJournal and Util.SafeValue("table", C_EncounterJournal.GetEncountersOnMap, mapID)
    if onMap then
      p.bossPins = {}
      for _, e in ipairs(onMap) do
        p.bossPins[#p.bossPins + 1] = string.format("%s,%.3f,%.3f", tostring(Util.Plain(e.encounterID)),
          Util.Plain(e.mapX) or -1, Util.Plain(e.mapY) or -1)
      end
    end
  end
  local journal = self:Journal(instanceID)
  if journal then
    p.journalID, p.journalBosses, p.lastBoss, p.lastEncounterID =
      journal.journalID, journal.encounters, journal.lastBoss, journal.lastEncounterID
  end
  if type(lfgID) == "number" and lfgID > 0 then
    local total, done = Util.SafeValues(GetLFGDungeonNumEncounters, lfgID)
    p.finderBosses = type(total) == "number" and string.format("%d/%s", done or 0, total) or nil
  end
  FC.db.dungeonProbe[tostring(instanceID)] = p
  FC.Diagnostics:Log("info", "dungeon probe: " .. self:Describe(p))
  self.lastArea = nil
  self:NoteArea()

  -- A position may only exist after moving away from the entrance.
  for _, delay in ipairs(PROBE_LATER) do
    FC:After(delay, function()
      local now = select(8, Util.SafeValues(GetInstanceInfo))
      if now == instanceID and p.map then
        p["positionAfter" .. delay] = playerPositionOn(p.map) or "none"
      end
    end)
  end
end

-- Boss encounters seen inside the probed instance (start/kill, ID, name, whether it was the last boss).
function Dungeons:NoteEncounter(what, encounterID, name, final)
  local p = self:CurrentProbe()
  if not p or #p.encounters >= 20 then return end
  p.encounters[#p.encounters + 1] = string.format("%s,%s,%s,%s", what, tostring(encounterID), tostring(name),
    tostring(final))
end

function Dungeons:Describe(p)
  return string.format("%s (%s) map=%s via %s pos=%s art=%s floors=%s bosspins=%s journal=%s bosses=%s last=%s(%s) " ..
    "finder=%s unitpos=%s facing=%s areas=%s", tostring(p.name), tostring(p.kind), tostring(p.map), tostring(p.mapSource),
    tostring(p.position or "none"), tostring(p.artTiles), tostring(p.floors), tostring(p.bossPins and #p.bossPins),
    tostring(p.journalID), tostring(p.journalBosses), tostring(p.lastBoss), tostring(p.lastEncounterID),
    tostring(p.finderBosses), tostring(p.unitPosition), tostring(p.facing), tostring(p.areas and #p.areas or 0))
end

-- Sub-area names inside the instance ("time,name"), the coarsest "where in the dungeon" there is without a
-- position. Recorded in the probe until it holds MAX_AREAS entries.
local MAX_AREAS = 60
function Dungeons:NoteArea()
  local p = self:CurrentProbe()
  if not p then return end
  p.areas = p.areas or {}
  local area = Util.SafeValue("string", GetSubZoneText)
  if not area or area == "" then area = Util.SafeValue("string", GetMinimapZoneText) end
  if not area or area == "" or area == self.lastArea or #p.areas >= MAX_AREAS then return end
  self.lastArea = area
  p.areas[#p.areas + 1] = time() .. "," .. area
end
Dungeons:RegisterEvent("ZONE_CHANGED", "NoteArea")
Dungeons:RegisterEvent("ZONE_CHANGED_INDOORS", "NoteArea")

local function probeSoon(self)
  if Util.SafeValues(IsInInstance) == true then FC:After(PROBE_DELAY, function() self:Probe() end) end
end
Dungeons:RegisterEvent("PLAYER_ENTERING_WORLD", probeSoon)
Dungeons:RegisterEvent("ZONE_CHANGED_NEW_AREA", probeSoon)

-- /fj dungeon: what the client offers in the current (or last probed) dungeon.
FC:RegisterCommand("dungeon", "CMD_DUNGEON", function()
  local p = Dungeons:CurrentProbe()
  if not p then
    local newest
    for _, entry in pairs(FC.db.dungeonProbe or {}) do
      if not newest or (entry.time or 0) > (newest.time or 0) then newest = entry end
    end
    p = newest
  end
  FC:Print(p and Dungeons:Describe(p) or L.DUNGEON_NO_PROBE)
end, 35)
