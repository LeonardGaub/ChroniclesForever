-- Forever Chronicle - Progress module (spec F-003 triggers, F-006, F-007)
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

FC:RegisterEventType("level_up", {
  icon = "Interface\\Icons\\Spell_Holy_InnerFire",
  format = function(r) return string.format(L.EVT_LEVEL_UP, r.data.level or "?") end,
})
FC:RegisterEventType("quest_completed", {
  icon = "Interface\\Icons\\INV_Misc_Note_01",
  format = function(r) return string.format(L.EVT_QUEST_COMPLETED, r.data.title or ("#" .. tostring(r.data.questID))) end,
})
FC:RegisterEventType("player_died", {
  icon = "Interface\\Icons\\INV_Misc_Bone_HumanSkull_01",
  format = function(r)
    local where = r.location and (r.location.subzone or r.location.zone)
    return where and string.format(L.EVT_DIED_IN, where) or L.EVT_DIED
  end,
})
FC:RegisterEventType("achievement_earned", {
  icon = "Interface\\Icons\\INV_Misc_Book_09",
  getIcon = function(r) return r.data.icon end,
  format = function(r) return string.format(L.EVT_ACHIEVEMENT, r.data.name or ("#" .. tostring(r.data.achievementID))) end,
})

FC:RegisterStat("levels_gained", { labelKey = "STAT_LEVELS", order = 20 })
FC:RegisterStat("quests_completed", { labelKey = "STAT_QUESTS", order = 21 })
FC:RegisterStat("deaths", { labelKey = "STAT_DEATHS", order = 22 })
FC:RegisterStat("achievements", { labelKey = "STAT_ACHIEVEMENTS", order = 23 })

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
