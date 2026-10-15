-- Journey Forever - Main frame
-- A Blizzard portrait frame (ButtonFrameTemplate) with one tab per registered page on its right edge,
-- like the spellbook's skill line tabs. Created lazily on first open; fades in when shown.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local FRAME_NAME = "ForeverChronicleFrame"
local WIDTH, HEIGHT = 820, 670 -- one size for all pages (fits the map)
local TAB_SIZE, TAB_STEP = 32, 48
local TAB_ART = "Interface\\SpellBook\\SpellBook-SkillLineTab"
local TAB_GLOW = "Interface\\Buttons\\CheckButtonHilight"

local function playSound(kit)
  if SOUNDKIT and SOUNDKIT[kit] and PlaySound then PlaySound(SOUNDKIT[kit]) end
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
  if f.SetTitle then f:SetTitle("Journey Forever") elseif f.TitleText then f.TitleText:SetText("Journey Forever") end
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

    local tab = self:IconButton(f, TAB_SIZE, page.icon, page.labelKey, nil, function()
      playSound("IG_CHARACTER_INFO_TAB")
      UI:SelectPage(i)
    end)
    tab:SetPoint("TOPLEFT", f, "TOPRIGHT", 0, -58 - (i - 1) * TAB_STEP)
    tab.page = page
    self:TabArt(tab)
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
    -- The corner portrait and tabs with icon = "portrait" show the character the window shows (UI/ViewBar.lua).
    UI:UpdatePortrait()
    playSound("IG_CHARACTER_INFO_OPEN")
    UI:FadeIn(f, 0.18)
    UI:RefreshCurrent()
  end)
  f:SetScript("OnHide", function() playSound("IG_CHARACTER_INFO_CLOSE") end)

  self.frame = f
  self:SelectPage(1)
end

-- Spellbook tab look: the tab art behind the icon (tucked under the window edge) and a glow when selected.
-- Without the art the icon keeps its dark square.
function UI:TabArt(tab)
  tab.icon:SetPoint("TOPLEFT")
  tab.icon:SetPoint("BOTTOMRIGHT")
  local art = tab:CreateTexture(nil, "BACKGROUND", nil, -1)
  if art:SetTexture(TAB_ART) ~= false then
    art:SetSize(64, 64)
    art:SetPoint("TOPLEFT", -3, 11)
    tab.bg:Hide()
  else
    art:Hide()
  end
  tab.glow = tab:CreateTexture(nil, "OVERLAY")
  tab.glow:SetAllPoints()
  if tab.glow:SetTexture(TAB_GLOW) == false then tab.glow:SetColorTexture(1, 0.82, 0, 0.25) end
  tab.glow:SetBlendMode("ADD")
  tab.glow:Hide()
end

function UI:SelectPage(index)
  local changed = self.current ~= index
  self.current = index
  for i, page in ipairs(self.pages) do
    page.container:SetShown(i == index)
    local tab = self.frame.Tabs[i]
    self:SetSelected(tab, i == index)
    if tab.glow then tab.glow:SetShown(i == index) end
  end
  if changed then self:FadeIn(self.pages[index].container, 0.14) end
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
FC:NewModule("UI", { order = 1000, defaults = {
  animations = true,
  chronicleStyle = "book",   -- "book" (parchment page) or "classic"
  chronicleHidden = {},      -- event categories hidden in the Chronicle
  chronicleFiltersOpen = false, -- the Chronicle's filter row is unfolded
  chronicleSeen = {},        -- per shown character: time of the newest entry already seen (newer ones pop in)
} }):RegisterMessage("FC_LANGUAGE_CHANGED", function()
  UI:Relocalize()
  if UI.frame then UI:RefreshCurrent() end
end)

-- Addon compartment button (minimap addon menu), declared in the .toc.
function ForeverChronicle_OnAddonCompartmentClick()
  UI:Toggle()
end
