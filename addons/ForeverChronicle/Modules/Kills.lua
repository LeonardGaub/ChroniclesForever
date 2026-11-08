-- Journey Forever - Kills module
-- Every kill that gave experience, with its XP and the enemy's name, in the compact "kills" stream. Data only for
-- now (most killed enemy, XP from kills versus quests, kills per level, the best session); nothing shows it yet.
-- Where a kill happened is where the route was at its time (positions stream), so no position is stored.
--
-- Record format (one string per kill):  time,xp,rested,name
--   xp: the experience the message names (the rested bonus included); rested: the rested bonus in it, empty when
--   there was none; name: the enemy's name as the message gives it (last, so it may contain commas).
--
-- The source is the client's own experience message (CHAT_MSG_COMBAT_XP_GAIN, "Hogger dies, you gain 120
-- experience."), matched against its format string so it works in every client language. Forever blocks the
-- combat log for addons, and the message is the one place that names the enemy, inside instances too. Kills without
-- experience (grey enemies, a group member's kill out of range) send no message and are not recorded; the
-- "kills" statistic (PARTY_KILL, Modules/Progress.lua) still counts the player's and the group's killing blows.

local ADDON, FC = ...
local Util = FC.Util

local Kills = FC:NewModule("Kills", { order = 31 })

FC.Storage:DefineStream("kills", 100000, "Interface\\Icons\\Ability_DualWield")

FC:RegisterCapability("kill_xp", "CAP_KILL_XP", function()
  return FC.eventStatus.CHAT_MSG_COMBAT_XP_GAIN == "registered" and type(COMBATLOG_XPGAIN_FIRSTPERSON) == "string"
end)

-- Built once the client's strings are there (they are when the addon loads; the fallback is the English text).
local matchKill, matchRested

function Kills:OnInitialize()
  matchKill = Util.FormatMatcher(COMBATLOG_XPGAIN_FIRSTPERSON or "%s dies, you gain %d experience.")
  -- "... (+60 exp Rested bonus)": the same start with the bonus after it. A group bonus may follow the rested
  -- one; the third argument is still the rested amount.
  matchRested = Util.FormatMatcher(COMBATLOG_XPGAIN_EXHAUSTION1)
end

-- { time, xp, rested, name } -> "time,xp,rested,name"
function Kills.Encode(kill)
  return string.format("%d,%d,%s,%s", kill.time, kill.xp, kill.rested and tostring(kill.rested) or "", kill.name)
end

-- "time,xp,rested,name" -> { time, xp, rested, name }, or nil if malformed.
function Kills.Parse(text)
  if type(text) ~= "string" then return nil end
  local t, xp, rested, name = text:match("^(%d+),(%d+),(%d*),(.*)$")
  if not t then return nil end
  return { time = tonumber(t), xp = tonumber(xp), rested = tonumber(rested), name = name }
end

-- The kill a message tells of as { time, xp, rested, name }, or nil when it is not a kill's experience message.
function Kills.FromMessage(msg, now)
  local name, xp = matchKill(msg)
  if type(name) ~= "string" or type(xp) ~= "number" then return nil end
  name = name:gsub("[\r\n]", " ")
  if name == "" then return nil end
  local rested
  local _, _, bonus = matchRested(msg)
  if bonus then rested = tonumber(tostring(bonus):match("%d+")) end
  return { time = now, xp = xp, rested = rested, name = name }
end

Kills:RegisterEvent("CHAT_MSG_COMBAT_XP_GAIN", function(_, _, msg)
  local kill = Kills.FromMessage(Util.Plain(msg), time())
  if not kill then return end
  FC.Storage:AppendRaw("kills", Kills.Encode(kill))
  -- Running totals, not shown: the level-up snapshot (Modules/Progress.lua) copies the statistics.
  FC:IncrementStat("kill_xp", kill.xp)
  if kill.rested then FC:IncrementStat("rested_xp", kill.rested) end
  FC:ConfirmCapability("kill_xp")
end)
