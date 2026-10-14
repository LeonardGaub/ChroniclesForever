-- Forever Chronicle - Rares module
-- Records kills of rare mobs ("rare" and "rare elite") as "rare_killed" events; the screenshot module has a
-- trigger for them. The kill itself (PARTY_KILL) only carries GUIDs, so rares are remembered when they are
-- seen as target, mouseover or nameplate (name and classification by GUID). If the client hides the GUIDs
-- (secret values), a dead rare target at the time of the kill is used instead.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Rares = FC:NewModule("Rares", { order = 31 })

local RARE = { rare = true, rareelite = true }
local MAX_SEEN = 100

FC:RegisterCapability("rares", "CAP_RARES", function()
  return FC.eventStatus.PARTY_KILL == "registered" and type(UnitClassification) == "function"
end)

FC:RegisterEventType("rare_killed", {
  icon = "Interface\\Icons\\INV_Misc_Head_Dragon_01",
  format = function(r) return string.format(L.EVT_RARE_KILLED, r.data.name or "?") end,
})

FC:RegisterStat("rares_killed", { labelKey = "STAT_RARES", order = 20, icon = "Interface\\Icons\\INV_Misc_Head_Dragon_01" })

-------------------------------------------------------------------------------
-- Rares seen recently (GUID -> { name, classification })
-------------------------------------------------------------------------------

Rares.seen, Rares.seenOrder, Rares.killed = {}, {}, {}

-- NPC ID from a creature GUID: "Creature-0-<server>-<instance>-<zone>-<npcID>-<spawn>"
local function npcID(guid)
  local id = guid and guid:match("^%a+%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
  return tonumber(id)
end

function Rares:Remember(unit)
  local guid = Util.SafeValue("string", UnitGUID, unit)
  local classification = Util.SafeValue("string", UnitClassification, unit)
  if not guid or not RARE[classification] or self.seen[guid] then return end
  self.seen[guid] = { name = Util.SafeValue("string", UnitName, unit), classification = classification,
    level = Util.SafeValue("number", UnitLevel, unit) }
  table.insert(self.seenOrder, guid)
  if #self.seenOrder > MAX_SEEN then self.seen[table.remove(self.seenOrder, 1)] = nil end
end

Rares:RegisterEvent("PLAYER_TARGET_CHANGED", function(self) self:Remember("target") end)
Rares:RegisterEvent("UPDATE_MOUSEOVER_UNIT", function(self) self:Remember("mouseover") end)
Rares:RegisterEvent("NAME_PLATE_UNIT_ADDED", function(self, _, unit)
  unit = Util.Plain(unit)
  if type(unit) == "string" then self:Remember(unit) end
end)

-------------------------------------------------------------------------------
-- Kills
-------------------------------------------------------------------------------

function Rares:Record(guid, info)
  if self.killed[guid] then return end -- one event per rare, even if the kill is reported twice
  self.killed[guid] = true
  FC:Record("rare_killed", { guid = guid, npcID = npcID(guid), name = info.name,
    classification = info.classification, level = info.level })
  FC:IncrementStat("rares_killed")
  FC:ConfirmCapability("rares")
end

Rares:RegisterEvent("PARTY_KILL", function(self, _, _, targetGUID)
  local guid = Util.Plain(targetGUID)
  if type(guid) == "string" then
    local info = self.seen[guid]
    if info then self:Record(guid, info) end
    return
  end
  -- GUID hidden by the client: use the target if it is a dead rare.
  local targetIsDead = Util.SafeValue("boolean", UnitIsDead, "target")
  if targetIsDead then
    self:Remember("target")
    local tguid = Util.SafeValue("string", UnitGUID, "target")
    local info = tguid and self.seen[tguid]
    if info then self:Record(tguid, info) end
  end
end)
