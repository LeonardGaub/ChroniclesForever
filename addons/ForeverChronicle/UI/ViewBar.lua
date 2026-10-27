-- Journey Forever - character chooser around the window (ARCHITECTURE.md)
-- A wide dropdown bar across the top of the window shows whose character the window shows; it opens a
-- scrollable list of all characters: mine (this account; the played one first) and, grouped by owner, the
-- characters other addons add (FC:RegisterViewSource, e.g. friends). Choosing one makes every tab show that
-- character (FC:SetView) and the portrait in the corner shows it (live portrait for the played character,
-- class emblem otherwise).
-- For any other character the bar says so ("nur lesen") and offers a button back to my own.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local ROW_HEIGHT = 36
local BAR_HEIGHT = 32
local LIST_H = 440
local CLASS_ICONS = "Interface\\TargetingFrame\\UI-Classes-Circles"

-- Class emblem on a texture; false if the class is unknown.
function UI:SetClassIcon(tex, classFile)
  local coords = CLASS_ICON_TCOORDS and classFile and CLASS_ICON_TCOORDS[classFile]
  if not coords then
    tex:SetTexture(UI.ICON_FALLBACK)
    UI:CropIcon(tex)
    return false
  end
  tex:SetTexture(CLASS_ICONS)
  tex:SetTexCoord(coords[1], coords[2], coords[3], coords[4])
  return true
end

-- The portrait in the window corner and on the overview tab: the played character's face, otherwise the
-- class emblem of the character shown (the game only draws faces for units that are present).
function UI:UpdatePortrait()
  local f = self.frame
  if not f then return end
  local played = FC:IsViewingPlayed()
  local classFile = FC:ViewChar().info.classFile
  if played then
    f:SetPortraitToUnit("player")
    f:SetPortraitTexCoord(0, 1, 0, 1)
  elseif CLASS_ICON_TCOORDS and classFile and CLASS_ICON_TCOORDS[classFile] then
    f:SetPortraitToClassIcon(classFile)
  else
    f:SetPortraitToAsset(UI.ICON_FALLBACK)
    f:SetPortraitTexCoord(0, 1, 0, 1)
  end
  for _, tab in ipairs(f.Tabs or {}) do
    if tab.page.icon == "portrait" then
      if played and SetPortraitTexture then
        SetPortraitTexture(tab.icon, "player")
        tab.icon:SetTexCoord(0.1, 0.9, 0.1, 0.9)
      else
        self:SetClassIcon(tab.icon, classFile)
      end
    end
  end
end

-- List items: headers and characters, in FC:ViewEntries order.
local function items()
  local out, group = {}, false
  local others = false
  for _, e in ipairs(FC:ViewEntries()) do
    local g = e.owner or ""
    if g ~= group then
      group = g
      out[#out + 1] = { header = e.owner and e.owner or L.VIEW_MINE }
    end
    if e.owner then others = true end
    out[#out + 1] = { entry = e }
  end
  -- A view source (e.g. friends) may explain how its characters get here while it has none.
  for _, source in ipairs(FC.viewSources) do
    if source.emptyNoteKey and not others then out[#out + 1] = { note = L[source.emptyNoteKey] } end
  end
  return out
end

local function createRow(row)
  row.header = row:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  row.header:SetPoint("BOTTOMLEFT", 6, 5)
  row.note = UI:Label(row, nil, "GameFontDisableSmall")
  row.note:SetPoint("LEFT", 8, 0)
  row.note:SetPoint("RIGHT", -8, 0)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(28, 28)
  row.icon:SetPoint("LEFT", 12, 0)
  row.name = UI:Label(row, nil, "GameFontHighlight")
  row.name:SetPoint("TOPLEFT", row.icon, "TOPRIGHT", 8, -1)
  row.name:SetPoint("RIGHT", -8, 0)
  row.name:SetWordWrap(false)
  row.sub = UI:Label(row, nil, "GameFontDisableSmall")
  row.sub:SetPoint("BOTTOMLEFT", row.icon, "BOTTOMRIGHT", 8, 1)
  row.sub:SetPoint("RIGHT", -8, 0)
  row.sub:SetWordWrap(false)
  row.hl = row:CreateTexture(nil, "HIGHLIGHT")
  row.hl:SetAllPoints()
  row.hl:SetColorTexture(1, 0.82, 0, 0.10)
  row.selected = row:CreateTexture(nil, "BACKGROUND", nil, 1)
  row.selected:SetAllPoints()
  row.selected:SetColorTexture(1, 0.82, 0, 0.18)
  row:EnableMouse(true)
  row:SetScript("OnMouseUp", function(r)
    if r.key then
      UI.viewList:Hide()
      FC:SetView(r.key)
    end
  end)
end

local function updateRow(row, item)
  local e = item.entry
  row.key = e and e.key
  row.header:SetShown(item.header ~= nil)
  row.note:SetShown(item.note ~= nil)
  for _, region in ipairs({ row.icon, row.name, row.sub, row.hl }) do region:SetShown(e ~= nil) end
  row.selected:SetShown(e ~= nil and e.key == FC:ViewKey())
  if item.header then row.header:SetText(item.header) end
  if item.note then row.note:SetText(item.note) end
  if e then
    local info = e.char.info
    UI:SetClassIcon(row.icon, info.classFile)
    row.name:SetText(UI:ClassColored(UI:FullName(info), info.classFile) .. (e.played and ("  |cff999999(" .. L.VIEW_PLAYED .. ")|r") or ""))
    local sub = string.format(L.VIEW_ROW, tostring(info.level or "?"), info.realm or "")
    if info.lastSeenAt and not e.played then sub = sub .. UI.SEP .. Util.FormatTime(info.lastSeenAt) end
    row.sub:SetText(sub)
  end
end

function UI:CreateViewBar(f)
  -- The bar: from the portrait to the right edge of the window, under the title.
  local bar = CreateFrame("Button", nil, f, "BackdropTemplate")
  bar:SetHeight(BAR_HEIGHT)
  bar:SetPoint("TOPLEFT", f, "TOPLEFT", 58, -25)
  bar:SetPoint("TOPRIGHT", f, "TOPRIGHT", -8, -25)
  UI:Backdrop(bar, { bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } },
    { 0.08, 0.06, 0.04, 0.95 }, { 1, 0.82, 0, 0.7 })
  bar:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  bar.name = UI:Label(bar, nil, "GameFontNormalLarge")
  bar.name:SetPoint("LEFT", 12, 0)
  bar.name:SetWordWrap(false)
  bar.sub = UI:Label(bar, nil, "GameFontHighlightSmall")
  bar.sub:SetPoint("LEFT", bar.name, "RIGHT", 12, -1)
  bar.sub:SetWordWrap(false)
  bar.arrow = bar:CreateTexture(nil, "OVERLAY")
  bar.arrow:SetSize(24, 24)
  bar.arrow:SetPoint("RIGHT", -6, 0)
  bar.arrow:SetTexture("Interface\\Buttons\\UI-ScrollBar-ScrollDownButton-Up")
  UI:Tooltip(bar, "VIEW_CHOOSE", "VIEW_CHOOSE_TIP")
  self.viewBar = bar

  -- Back to the played character (inside the bar, right).
  self.viewBack = CreateFrame("Button", nil, bar, "UIPanelButtonTemplate")
  self.viewBack:SetSize(130, 22)
  self.viewBack:SetPoint("RIGHT", bar.arrow, "LEFT", -8, 0)
  self.viewBack:SetScript("OnClick", function() FC:SetView(nil) end)
  bar.sub:SetPoint("RIGHT", self.viewBack, "LEFT", -8, 0)

  -- The list: as wide as the bar, below it.
  local list = CreateFrame("Frame", nil, f, "BackdropTemplate")
  list:SetHeight(LIST_H)
  list:SetPoint("TOPLEFT", bar, "BOTTOMLEFT", 0, -2)
  list:SetPoint("TOPRIGHT", bar, "BOTTOMRIGHT", 0, -2)
  list:SetFrameStrata("DIALOG")
  UI:Backdrop(list, { bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 14, insets = { left = 4, right = 4, top = 4, bottom = 4 } },
    { 0.05, 0.04, 0.03, 0.97 }, { 1, 0.82, 0, 0.8 })
  list:EnableMouse(true)
  list:Hide()
  self.viewList = list
  self.viewRows = UI:List(list, ROW_HEIGHT, createRow, updateRow)
  self.viewRows.scroll:SetPoint("TOPLEFT", 8, -8)
  self.viewRows.scroll:SetPoint("BOTTOMRIGHT", -28, 8)

  bar:SetScript("OnClick", function()
    if list:IsShown() then
      list:Hide()
    else
      self.viewRows:SetItems(items())
      list:Show()
    end
  end)
  f:HookScript("OnHide", function() list:Hide() end)
  self:UpdateViewBar()
end

function UI:UpdateViewBar()
  local bar = self.viewBar
  if not bar then return end
  local char = FC:ViewChar()
  local info = char.info
  local played = FC:IsViewingPlayed()
  local owner = FC:ViewOwner()
  bar.name:SetText(UI:ClassColored(UI:FullName(info), info.classFile))
  local sub = string.format(L.VIEW_ROW, tostring(info.level or "?"), info.realm or "")
  if owner then
    sub = sub .. UI.SEP .. string.format(L.VIEW_FRIEND_OF, owner) .. "  |cff999999(" .. L.VIEW_READONLY .. ")|r"
  elseif not played then
    sub = sub .. UI.SEP .. L.VIEW_OTHER_OWN .. "  |cff999999(" .. L.VIEW_READONLY .. ")|r"
  end
  bar.sub:SetText(sub)
  self.viewBack:SetText(L.VIEW_BACK)
  self.viewBack:SetShown(not played)
  self:UpdatePortrait()
  if self.viewList:IsShown() then self.viewRows:SetItems(items()) end
end

-- Another character is shown: pages start over (OnViewChanged), the bar updates, the visible page refreshes.
FC:NewModule("ViewBar", { order = 1002 }):RegisterMessage("FC_VIEW_CHANGED", function()
  for _, page in ipairs(UI.pages) do
    if page.OnViewChanged then FC:SafeCall(page.OnViewChanged, page) end
  end
  UI:UpdateViewBar()
  UI:RefreshCurrent()
end)
