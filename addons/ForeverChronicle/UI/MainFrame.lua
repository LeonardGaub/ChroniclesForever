-- Forever Chronicle - Main frame
-- A Blizzard portrait frame (ButtonFrameTemplate) with one bottom tab per registered page,
-- like the character and spellbook windows. Created lazily on first open.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local FRAME_NAME = "ForeverChronicleFrame"
local WIDTH, HEIGHT = 560, 500

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

  -- Pages share the inset area; tabs sit below the frame.
  f.Tabs = {}
  for i, page in ipairs(self.pages) do
    local container = CreateFrame("Frame", nil, f.Inset or f)
    container:SetAllPoints()
    container:Hide()
    page.container = container
    page:Create(container)

    local tab = CreateFrame("Button", FRAME_NAME .. "Tab" .. i, f, "PanelTabButtonTemplate")
    tab:SetID(i)
    tab:SetText(L[page.labelKey])
    if i == 1 then
      tab:SetPoint("TOPLEFT", f, "BOTTOMLEFT", 12, 2)
    else
      tab:SetPoint("TOPLEFT", f.Tabs[i - 1], "TOPRIGHT", 4, 0)
    end
    tab:SetScript("OnClick", function()
      playSound("IG_CHARACTER_INFO_TAB")
      UI:SelectPage(i)
    end)
    if PanelTemplates_TabResize then PanelTemplates_TabResize(tab, 0) end
    f.Tabs[i] = tab
  end
  if PanelTemplates_SetNumTabs then PanelTemplates_SetNumTabs(f, #self.pages) end

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
    playSound("IG_CHARACTER_INFO_OPEN")
    UI:RefreshCurrent()
  end)
  f:SetScript("OnHide", function() playSound("IG_CHARACTER_INFO_CLOSE") end)

  self.frame = f
  self:SelectPage(1)
end

function UI:SelectPage(index)
  self.current = index
  local selected = self.pages[index]
  self.frame:SetSize(selected.width or WIDTH, selected.height or HEIGHT) -- e.g. the map needs more room
  for i, page in ipairs(self.pages) do
    page.container:SetShown(i == index)
  end
  if PanelTemplates_SetTab then PanelTemplates_SetTab(self.frame, index) end
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

-- Language switch: relabel everything that was created with UI:Label / UI:Button and the tabs.
FC:NewModule("UI", { order = 1000 }):RegisterMessage("FC_LANGUAGE_CHANGED", function()
  UI:Relocalize()
  if UI.frame then
    for i, page in ipairs(UI.pages) do
      local tab = UI.frame.Tabs[i]
      tab:SetText(L[page.labelKey])
      if PanelTemplates_TabResize then PanelTemplates_TabResize(tab, 0) end
    end
    UI:RefreshCurrent()
  end
end)

-- Addon compartment button (minimap addon menu), declared in the .toc.
function ForeverChronicle_OnAddonCompartmentClick()
  UI:Toggle()
end
