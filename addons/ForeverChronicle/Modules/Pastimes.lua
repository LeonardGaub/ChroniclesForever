-- Journey Forever - Pastimes module
-- Counts the small things: jumps and fish caught. Statistics only, no chronicle events.
-- Jumps: the client has no jump event. The jump key calls JumpOrAscendStart, which is hooked; presses in the
-- air, while swimming (ascend), flying or on a flight path are not jumps. Fish: LOOT_OPENED with fishing loot,
-- one per catch.

local ADDON, FC = ...
local Util = FC.Util

local Pastimes = FC:NewModule("Pastimes", { order = 32 })

FC:RegisterCapability("jumps", "CAP_JUMPS", function() return Pastimes.jumpHooked == true end)
FC:RegisterCapability("fishing", "CAP_FISHING", function()
  return FC.eventStatus.LOOT_OPENED == "registered" and type(IsFishingLoot) == "function"
end)

FC:RegisterStat("fish_caught", { labelKey = "STAT_FISH", order = 29, icon = "Interface\\Icons\\INV_Misc_Fish_02",
  format = function(v) return Util.FormatNumber(v) end })
FC:RegisterStat("jumps", { labelKey = "STAT_JUMPS", order = 30, icon = "Interface\\Icons\\INV_Gizmo_RocketBoot_01",
  format = function(v) return Util.FormatNumber(v) end })

-------------------------------------------------------------------------------
-- Jumps
-------------------------------------------------------------------------------

local function inAir()
  return Util.SafeValue("boolean", IsFalling) or Util.SafeValue("boolean", IsSwimming)
    or Util.SafeValue("boolean", IsFlying) or Util.SafeValue("boolean", UnitOnTaxi, "player")
end

function Pastimes:OnJump()
  if not FC.char or inAir() then return end
  FC:IncrementStat("jumps")
  FC:ConfirmCapability("jumps")
end

if type(hooksecurefunc) == "function" and type(JumpOrAscendStart) == "function" then
  Pastimes.jumpHooked = pcall(hooksecurefunc, "JumpOrAscendStart", function() FC:SafeCall(Pastimes.OnJump, Pastimes) end)
end

-------------------------------------------------------------------------------
-- Fishing
-------------------------------------------------------------------------------

Pastimes:RegisterEvent("LOOT_OPENED", function()
  if not Util.SafeValue("boolean", IsFishingLoot) then return end
  FC:IncrementStat("fish_caught")
  FC:ConfirmCapability("fishing")
end)
