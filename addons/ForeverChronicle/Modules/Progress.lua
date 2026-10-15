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
    return where and string.format(L.EVT_DIED_IN, where) or L.EVT_DIED
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
  format = function(v) return FC.Util.FormatNumber(v) end })
FC:RegisterStat("quests_completed", { labelKey = "STAT_QUESTS", order = 21, icon = "Interface\\Icons\\INV_Misc_Note_01" })
FC:RegisterStat("deaths", { labelKey = "STAT_DEATHS", order = 22, icon = "Interface\\Icons\\INV_Misc_Bone_HumanSkull_01" })
FC:RegisterStat("achievements", { labelKey = "STAT_ACHIEVEMENTS", order = 23, icon = "Interface\\Icons\\INV_Misc_Ribbon_01" })

-------------------------------------------------------------------------------
-- Handlers
-------------------------------------------------------------------------------

Progress:RegisterEvent("PLAYER_LEVEL_UP", function(_, _, level)
  level = Util.Plain(level)
  FC:Record("level_up", { level = type(level) == "number" and level or nil })
  FC:IncrementStat("levels_gained")
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
  return FC.Util.SafeValue("number", UnitXP, "player"), FC.Util.SafeValue("number", UnitXPMax, "player")
end

function Progress:OnEnable()
  self.lastXP, self.lastMax = self:ReadXP()
end

Progress:RegisterEvent("PLAYER_XP_UPDATE", function(self, _, unit)
  if unit and Util.Plain(unit) ~= "player" then return end
  local xp, max = self:ReadXP()
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

Progress:RegisterEvent("PLAYER_DEAD", function()
  -- The cause of death is not exposed by the API and is never inferred (spec F-007).
  FC:Record("player_died", {})
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
