-- Forever Chronicle - screenshot countdown
-- A small tooltip-style box at the top of the screen: "Screenshot in 4 s". The screenshot module hides
-- it before every capture, so it never appears in a screenshot. Drag it with Shift + left mouse to move it;
-- the position is saved.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local Countdown = {}
UI.Countdown = Countdown

local function create()
  local ok, f = pcall(CreateFrame, "Frame", "ForeverChronicleCountdown", UIParent, "TooltipBackdropTemplate")
  if not ok then f = CreateFrame("Frame", "ForeverChronicleCountdown", UIParent) end
  f:SetSize(210, 34)
  f:SetFrameStrata("HIGH")
  f:SetClampedToScreen(true)
  f:SetMovable(true)
  f:EnableMouse(true)
  f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", function(self) if IsShiftKeyDown() then self:StartMoving() end end)
  f:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    local point, _, relPoint, x, y = self:GetPoint()
    FC.db.settings.countdownPosition = { point, relPoint, x, y }
  end)

  local pos = FC.db.settings.countdownPosition
  if type(pos) == "table" and pos[1] then
    f:SetPoint(pos[1], UIParent, pos[2], pos[3], pos[4])
  else
    f:SetPoint("TOP", UIParent, "TOP", 0, -140)
  end

  f.icon = f:CreateTexture(nil, "ARTWORK")
  f.icon:SetSize(22, 22)
  f.icon:SetPoint("LEFT", 8, 0)
  f.icon:SetTexture("Interface\\Icons\\INV_Misc_Spyglass_02")
  f.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  f.text = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  f.text:SetPoint("LEFT", f.icon, "RIGHT", 8, 0)
  f.text:SetPoint("RIGHT", -8, 0)
  f.text:SetJustifyH("LEFT")
  f:Hide()
  return f
end

-- seconds: remaining time; math.huge means "waiting" (e.g. until the flight has landed).
function Countdown:ShowRemaining(seconds)
  self.frame = self.frame or create()
  if seconds == math.huge then
    self.frame.text:SetText(L.COUNTDOWN_WAITING)
  else
    self.frame.text:SetText(string.format(L.COUNTDOWN_TEXT, math.max(1, math.ceil(seconds))))
  end
  self.frame:Show()
end

function Countdown:Hide()
  if self.frame then self.frame:Hide() end
end
