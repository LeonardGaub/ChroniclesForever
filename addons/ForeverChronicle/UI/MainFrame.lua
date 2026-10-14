-- Forever Chronicle - Main frame
-- A Blizzard portrait frame (ButtonFrameTemplate) with one bottom tab per registered page,
-- like the character and spellbook windows. Created lazily on first open.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local FRAME_NAME = "ForeverChronicleFrame"
local WIDTH, HEIGHT = 820, 670 -- one size for all pages (fits the map)

local function playSound(kit)
  if SOUNDKIT and SOUNDKIT[kit] and PlaySound then PlaySound(SOUNDKIT[kit]) end
end

local function setPortrait(frame)
  if frame.SetPortraitToUnit then
    frame:SetPortraitToUnit("player")
  elseif frame.portrait and SetPortraitTexture then
    SetPortraitTexture(frame.portrait, "player")
  end
end

function UI:Create()
  local f = CreateFrame("Frame", FRAME_NAME, UIParent, "ButtonFrameTemplate")
  f:SetSize(WIDTH, HEIGHT)
  f:SetPoint("CENTER")
  f:SetFrameStrata("HIGH")
  f:SetToplevel(true)
  f:SetMovable(true)
  f:SetClampedToScreen(true)
  f:EnableMouse(true)
  f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", f.StartMoving)
  f:SetScript("OnDragStop", f.StopMovingOrSizing)
  if ButtonFrameTemplate_HideButtonBar then ButtonFrameTemplate_HideButtonBar(f) end
  if f.SetTitle then f:SetTitle("Forever Chronicle") elseif f.TitleText then f.TitleText:SetText("Forever Chronicle") end
  tinsert(UISpecialFrames, FRAME_NAME) -- close with Escape
  f:Hide()

  -- Character chooser (which character the tabs show) under the title.
  self:CreateViewBar(f)

  -- Pages share the inset area. Tabs are icon buttons on the right edge (like the spellbook tabs);
  -- the page name is shown in the tooltip.
  f.Tabs = {}
  for i, page in ipairs(self.pages) do
    local container = CreateFrame("Frame", nil, f.Inset or f)
    container:SetAllPoints()
    container:Hide()
    page.container = container
    page:Create(container)

    local tab = self:IconButton(f, 38, page.icon, page.labelKey, nil, function()
      playSound("IG_CHARACTER_INFO_TAB")
      UI:SelectPage(i)
    end)
    tab:SetPoint("TOPLEFT", f, "TOPRIGHT", 1, -56 - (i - 1) * 46)
    tab.page = page
    f.Tabs[i] = tab
  end

  -- Refresh the visible page once per second while open (session timer, new events).
  local elapsed = 0
  f:SetScript("OnUpdate", function(_, dt)
    elapsed = elapsed + dt
    if elapsed >= 1 then
      elapsed = 0
      UI:RefreshCurrent()
    end
  end)
  f:SetScript("OnShow", function()
    setPortrait(f)
    -- Pages with icon = "portrait" show the character's portrait on their tab.
    for _, tab in ipairs(f.Tabs) do
      if tab.page.icon == "portrait" and SetPortraitTexture then
        SetPortraitTexture(tab.icon, "player")
        tab.icon:SetTexCoord(0.1, 0.9, 0.1, 0.9)
      end
    end
    playSound("IG_CHARACTER_INFO_OPEN")
    UI:RefreshCurrent()
  end)
  f:SetScript("OnHide", function() playSound("IG_CHARACTER_INFO_CLOSE") end)

  self.frame = f
  self:SelectPage(1)
end

function UI:SelectPage(index)
  self.current = index
  for i, page in ipairs(self.pages) do
    page.container:SetShown(i == index)
    self:SetSelected(self.frame.Tabs[i], i == index)
  end
  self:RefreshCurrent()
end

function UI:RefreshCurrent()
  local page = self.pages[self.current or 1]
  if page and page.Refresh and self.frame and self.frame:IsShown() then
    FC:SafeCall(page.Refresh, page)
  end
end

function UI:Toggle()
  if not FC.ready then return end
  if not self.frame then
    local ok = FC:SafeCall(self.Create, self)
    if not ok then FC:Print(L.UI_ERROR) return end
  end
  self.frame:SetShown(not self.frame:IsShown())
end

-- Language switch: relabel everything created with UI:Label / UI:Button. Tooltips read the locale when shown.
FC:NewModule("UI", { order = 1000 }):RegisterMessage("FC_LANGUAGE_CHANGED", function()
  UI:Relocalize()
  if UI.frame then UI:RefreshCurrent() end
end)

-- Addon compartment button (minimap addon menu), declared in the .toc.
function ForeverChronicle_OnAddonCompartmentClick()
  UI:Toggle()
end
