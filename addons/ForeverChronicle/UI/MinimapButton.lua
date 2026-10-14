-- Journey Forever - minimap button
-- Classic-style round button on the minimap edge: left-click opens the window, right-click the settings,
-- drag moves it around the minimap (the angle is saved). Can be hidden in the settings.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local Button = FC:NewModule("MinimapButton", { order = 1001, defaults = { show = true, angle = 225 } })

local atan2 = math.atan2 or function(y, x) return math.atan(y, x) end

local function place(b, angle)
  local radius = (Minimap:GetWidth() or 140) / 2 + 5
  local rad = math.rad(angle)
  b:ClearAllPoints()
  b:SetPoint("CENTER", Minimap, "CENTER", math.cos(rad) * radius, math.sin(rad) * radius)
end

function Button:Create()
  local b = CreateFrame("Button", "ForeverChronicleMinimapButton", Minimap)
  b:SetSize(31, 31)
  b:SetFrameStrata("MEDIUM")
  b:SetFrameLevel(8)
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:RegisterForDrag("LeftButton")
  b:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

  local bg = b:CreateTexture(nil, "BACKGROUND")
  bg:SetSize(20, 20)
  bg:SetPoint("TOPLEFT", 7, -5)
  bg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  local icon = b:CreateTexture(nil, "ARTWORK")
  icon:SetSize(17, 17)
  icon:SetPoint("TOPLEFT", 7, -6)
  icon:SetTexture("Interface\\Icons\\INV_Misc_Book_09")
  icon:SetTexCoord(0.05, 0.95, 0.05, 0.95)
  b.icon = icon
  local border = b:CreateTexture(nil, "OVERLAY")
  border:SetSize(53, 53)
  border:SetPoint("TOPLEFT")
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")

  b:SetScript("OnClick", function(_, mouse)
    if mouse == "RightButton" then
      for i, p in ipairs(UI.pages) do
        if p.id == "settings" then
          if not (UI.frame and UI.frame:IsShown()) then UI:Toggle() end
          UI:SelectPage(i)
        end
      end
    else
      UI:Toggle()
    end
  end)
  b:SetScript("OnDragStart", function(self) self.dragging = true end)
  b:SetScript("OnDragStop", function(self) self.dragging = nil end)
  b:SetScript("OnUpdate", function(self)
    if not self.dragging then return end
    local mx, my = Minimap:GetCenter()
    local cx, cy = GetCursorPosition()
    local scale = Minimap:GetEffectiveScale()
    local angle = math.deg(atan2(cy / scale - my, cx / scale - mx)) % 360
    Button:GetSettings().angle = angle
    place(self, angle)
  end)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("Journey Forever", 1, 0.82, 0)
    GameTooltip:AddLine(L.MINIMAP_TIP, 1, 1, 1, true)
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", GameTooltip_Hide)
  self.button = b
end

function Button:Update()
  local s = self:GetSettings()
  if not s.show then
    if self.button then self.button:Hide() end
    return
  end
  if not self.button then self:Create() end
  place(self.button, s.angle)
  self.button:Show()
end

function Button:OnEnable()
  if Minimap then self:Update() end
end

FC:RegisterOption({ module = "MinimapButton", key = "show", type = "toggle", column = 2, labelKey = "OPT_MINIMAP",
  tooltipKey = "OPT_MINIMAP_TIP", order = 30, onChange = function() Button:Update() end })
