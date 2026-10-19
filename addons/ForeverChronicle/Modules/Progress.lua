-- Journey Forever - Progress module (spec F-003 triggers, F-006, F-007)
-- Level-ups, quest completions, deaths and achievements.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Progress = FC:NewModule("Progress", { order = 30 })

-------------------------------------------------------------------------------
-- Registrations
-------------------------------------------------------------------------------

FC:RegisterCapability("level_up", "CAP_LEVEL_UP", function() return FC.eventStatus.PLAYER_LEVEL_UP == "registered" end)
FC:RegisterCapability("quests", "CAP_QUESTS", function() return FC.eventStatus.QUEST_TURNED_IN == "registered" end)
FC:RegisterCapability("deaths", "CAP_DEATHS", function() return FC.eventStatus.PLAYER_DEAD == "registered" end)
FC:RegisterCapability("achievements", "CAP_ACHIEVEMENTS", function()
  return FC.eventStatus.ACHIEVEMENT_EARNED == "registered" and type(GetAchievementInfo) == "function"
end)

FC:RegisterEventCategory("levels", { labelKey = "CAT_LEVELS", icon = "Interface\\Icons\\Spell_Holy_InnerFire", order = 10 })
FC:RegisterEventCategory("quests", { labelKey = "CAT_QUESTS", icon = "Interface\\Icons\\INV_Misc_Note_01", order = 20 })
FC:RegisterEventCategory("achievements", { labelKey = "CAT_ACHIEVEMENTS", icon = "Interface\\Icons\\Achievement_General", order = 40 })
FC:RegisterEventCategory("deaths", { labelKey = "CAT_DEATHS", icon = "Interface\\Icons\\INV_Misc_Bone_HumanSkull_01", order = 70 })

FC:RegisterEventType("level_up", {
  icon = "Interface\\Icons\\Spell_Holy_InnerFire", category = "levels", highlight = "milestone",
  format = function(r) return string.format(L.EVT_LEVEL_UP, r.data.level or "?") end,
})
FC:RegisterEventType("quest_completed", {
  icon = "Interface\\Icons\\INV_Misc_Note_01", category = "quests",
  format = function(r) return string.format(L.EVT_QUEST_COMPLETED, r.data.title or ("#" .. tostring(r.data.questID))) end,
})
FC:RegisterEventType("player_died", {
  icon = "Interface\\Icons\\INV_Misc_Bone_HumanSkull_01", category = "deaths", highlight = "danger",
  pinIcon = "Interface\\TargetingFrame\\UI-TargetingFrame-Skull",
  format = function(r)
    local where = r.location and (r.location.subzone or r.location.zone)
    local d = r.data
    local env = d.environment and L["DEATH_ENV_" .. d.environment:upper()]
    local what = env or ((d.killer or d.spell) and string.format(L.EVT_KILLED_BY, d.killer or d.spell))
    if what then return where and string.format(L.EVT_CAUSE_IN, what, where) or what end
    return where and string.format(L.EVT_DIED_IN, where) or L.EVT_DIED
  end,
  -- Tooltip: the killing blow ("Heroic Strike: 245 damage (37 overkill)").
  details = function(r)
    local d = r.data
    if not d.damage then return nil end
    local how = d.spell or (not d.environment and L.DEATH_MELEE) or (d.environment and L["DEATH_ENV_" .. d.environment:upper()])
    local dmg = Util.FormatNumber(d.damage)
    local line = d.overkill and d.overkill > 0
      and string.format(L.DEATH_BLOW_OVERKILL, how or "?", dmg, Util.FormatNumber(d.overkill))
      or string.format(L.DEATH_BLOW, how or "?", dmg)
    return { line }
  end,
})
FC:RegisterEventType("achievement_earned", {
  icon = "Interface\\Icons\\INV_Misc_Book_09", category = "achievements", highlight = "milestone",
  getIcon = function(r) return r.data.icon end,
  format = function(r) return string.format(L.EVT_ACHIEVEMENT, r.data.name or ("#" .. tostring(r.data.achievementID))) end,
})

FC:RegisterCapability("kills", "CAP_KILLS", function() return FC.eventStatus.PARTY_KILL == "registered" end)
FC:RegisterCapability("xp", "CAP_XP", function()
  return FC.eventStatus.PLAYER_XP_UPDATE == "registered" and type(UnitXP) == "function"
end)

FC:RegisterStat("kills", { labelKey = "STAT_KILLS", order = 18, icon = "Interface\\Icons\\Ability_Hunter_SniperShot" })
FC:RegisterStat("xp_earned", { labelKey = "STAT_XP", order = 19, icon = "Interface\\Icons\\Spell_Holy_InnerFire",
  format = function(v) return Util.FormatNumber(v) end })
FC:RegisterStat("quests_completed", { labelKey = "STAT_QUESTS", order = 21, icon = "Interface\\Icons\\INV_Misc_Note_01" })
FC:RegisterStat("deaths", { labelKey = "STAT_DEATHS", order = 22, icon = "Interface\\Icons\\INV_Misc_Bone_HumanSkull_01" })
FC:RegisterStat("achievements", { labelKey = "STAT_ACHIEVEMENTS", order = 23, icon = "Interface\\Icons\\INV_Misc_Ribbon_01" })

-------------------------------------------------------------------------------
-- Handlers
-------------------------------------------------------------------------------

Progress:RegisterEvent("PLAYER_LEVEL_UP", function(_, _, level)
  level = Util.Plain(level)
  FC:Record("level_up", { level = type(level) == "number" and level or nil })
  FC:IncrementStat("levels_gained") -- no longer shown, still counted for existing saved data
  FC:ConfirmCapability("level_up")
end)

Progress:RegisterEvent("QUEST_TURNED_IN", function(_, _, questID, xpReward, moneyReward)
  questID = Util.Plain(questID)
  if type(questID) ~= "number" then return end
  local title = C_QuestLog and Util.SafeValue("string", C_QuestLog.GetTitleForQuestID, questID)
  FC:Record("quest_completed", {
    questID = questID, title = title, xp = Util.Plain(xpReward), money = Util.Plain(moneyReward),
  })
  FC:IncrementStat("quests_completed")
  FC:ConfirmCapability("quests")
end)

-- Kills: PARTY_KILL fires for killing blows by you or your group. Counted as a statistic only
-- (no event per kill, that would fill the chronicle).
Progress:RegisterEvent("PARTY_KILL", function()
  FC:IncrementStat("kills")
  FC:ConfirmCapability("kills")
end)

-- Experience: the difference between XP readings. A level-up wraps the bar, so the rest of the old
-- level (old max - old XP) is added to the new XP.
function Progress:ReadXP()
  return Util.SafeValue("number", UnitXP, "player"), Util.SafeValue("number", UnitXPMax, "player")
end

-- The bar as it is now (info.xp of info.xpMax at info.xpAt): the desktop's experience bar starts the level there.
function Progress:RememberXP(xp, max)
  local info = FC.char and FC.char.info
  if info and xp and max and max > 0 then
    info.xp, info.xpMax, info.xpAt = xp, max, time()
  end
end

function Progress:OnEnable()
  self.lastXP, self.lastMax = self:ReadXP()
  self:RememberXP(self.lastXP, self.lastMax)
end

Progress:RegisterEvent("PLAYER_XP_UPDATE", function(self, _, unit)
  if unit and Util.Plain(unit) ~= "player" then return end
  local xp, max = self:ReadXP()
  self:RememberXP(xp, max)
  if not xp or not self.lastXP then
    self.lastXP, self.lastMax = xp, max
    return
  end
  local gained = xp >= self.lastXP and (xp - self.lastXP) or ((self.lastMax or 0) - self.lastXP + xp)
  if gained > 0 then
    FC:IncrementStat("xp_earned", gained)
    FC:ConfirmCapability("xp")
  end
  self.lastXP, self.lastMax = xp, max
end)

-- Cause of death: the killing blow from the game's death recap (C_DeathRecap, called without an ID for the
-- newest recap). Only what the recap says is stored, never inferred (spec F-007). The recap can lag behind
-- PLAYER_DEAD, so it is read again a few times and the event's data is filled in when it arrives. A recap
-- whose killing blow is the one already used belongs to an earlier death and is ignored.
local RECAP_RETRIES = { 0.5, 1.5, 3 }

function Progress:ReadDeathCause()
  local api = C_DeathRecap
  if not (api and type(api.GetRecapEvents) == "function") then return nil end
  local ok, events = pcall(api.GetRecapEvents)
  if not ok or type(Util.Plain(events)) ~= "table" then return nil end
  -- The killing blow is the newest entry (the recap lists it first; the timestamps decide if present).
  local blow, newest
  for i, e in ipairs(events) do
    if type(Util.Plain(e)) == "table" then
      local ts = Util.Plain(e.timestamp)
      ts = type(ts) == "number" and ts or nil
      if not blow or (ts and (not newest or ts > newest)) then blow, newest = e, ts end
    end
  end
  if not blow then return nil end
  -- Combat log timestamps are epoch seconds: a killing blow from minutes ago is an earlier death's.
  if newest and newest > 1e9 and math.abs(time() - newest) > 60 then return nil end
  local function get(key, expected)
    local v = Util.Plain(blow[key])
    return type(v) == expected and v or nil
  end
  local env = get("environmentalType", "string")
  local cause = {
    killer = not env and get("sourceName", "string") or nil,
    npcID = Util.NpcID(get("sourceGUID", "string")),
    spell = get("spellName", "string"),
    spellID = get("spellId", "number"),
    environment = env and env:lower() or nil,
    damage = get("amount", "number"),
    overkill = get("overkill", "number"),
  }
  if cause.overkill and cause.overkill <= 0 then cause.overkill = nil end -- -1 or 0: no overkill
  if not (cause.killer or cause.spell or cause.environment) then return nil end
  local key = table.concat({ tostring(newest), tostring(cause.killer), tostring(cause.spellID),
    tostring(cause.environment), tostring(cause.damage) }, "|")
  if key == self.lastRecapKey then return nil end
  return cause, key
end

function Progress:FillDeathCause(record, attempt)
  local cause, key = self:ReadDeathCause()
  if cause then
    self.lastRecapKey = key
    for k, v in pairs(cause) do record.data[k] = v end
    return
  end
  local delay = RECAP_RETRIES[attempt]
  if delay and C_Timer then
    C_Timer.After(delay, function() self:FillDeathCause(record, attempt + 1) end)
  end
end

Progress:RegisterEvent("PLAYER_DEAD", function(self)
  local record = FC:Record("player_died", {})
  if record then self:FillDeathCause(record, 1) end
  FC:IncrementStat("deaths")
  FC:ConfirmCapability("deaths")
end)

Progress:RegisterEvent("ACHIEVEMENT_EARNED", function(_, _, achievementID, alreadyEarned)
  achievementID = Util.Plain(achievementID)
  if type(achievementID) ~= "number" then return end
  local _, name, points, _, _, _, _, _, _, icon = Util.SafeValues(GetAchievementInfo, achievementID)
  FC:Record("achievement_earned", {
    achievementID = achievementID, name = name, points = points, icon = icon,
    alreadyEarned = Util.Plain(alreadyEarned) == true or nil,
  })
  FC:IncrementStat("achievements")
  FC:ConfirmCapability("achievements")
end)
