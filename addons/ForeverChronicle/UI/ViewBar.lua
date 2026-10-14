-- Forever Chronicle - character chooser around the window (docs/Sharing_Design.md, phase 2)
-- A button under the title shows whose character the window shows; it opens a scrollable list of all
-- characters: mine (this account; the played one first) and, grouped by friend, my friends' characters from
-- the desktop app. Choosing one makes every tab show that character (FC:SetView). When it is not the played
-- character, a banner says so ("nur lesen") with a button back to my own.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local ROW_HEIGHT = 34
local LIST_W, LIST_H = 360, 430

local function fullName(info)
  local name = info.name or "?"
  if info.nameSuffix and info.nameSuffix ~= "" then name = name .. " " .. info.nameSuffix end
  return name
end

-- List items: headers and characters, in FC:ViewEntries order.
local function items()
  local out, group = {}, false
  local hasFriends = false
  for _, e in ipairs(FC:ViewEntries()) do
    local g = e.owner or ""
    if g ~= group then
      group = g
      out[#out + 1] = { header = e.owner and e.owner or L.VIEW_MINE }
    end
    if e.owner then hasFriends = true end
    out[#out + 1] = { entry = e }
  end
  if not hasFriends then out[#out + 1] = { note = L.VIEW_NO_FRIENDS } end
  return out
end

local function createRow(row)
  row.header = row:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  row.header:SetPoint("BOTTOMLEFT", 6, 4)
  row.note = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.note:SetPoint("LEFT", 8, 0)
  row.note:SetPoint("RIGHT", -8, 0)
  row.note:SetJustifyH("LEFT")
  row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.name:SetPoint("TOPLEFT", 14, -3)
  row.name:SetPoint("RIGHT", -8, 0)
  row.name:SetJustifyH("LEFT")
  row.name:SetWordWrap(false)
  row.sub = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.sub:SetPoint("BOTTOMLEFT", 14, 4)
  row.sub:SetPoint("RIGHT", -8, 0)
  row.sub:SetJustifyH("LEFT")
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
  row.name:SetShown(e ~= nil)
  row.sub:SetShown(e ~= nil)
  row.hl:SetShown(e ~= nil)
  row.selected:SetShown(e ~= nil and e.key == FC:ViewKey())
  if item.header then row.header:SetText(item.header) end
  if item.note then row.note:SetText(item.note) end
  if e then
    local info = e.char.info
    row.name:SetText(UI:ClassColored(fullName(info), info.classFile) .. (e.played and ("  |cff999999(" .. L.VIEW_PLAYED .. ")|r") or ""))
    local sub = string.format(L.VIEW_ROW, tostring(info.level or "?"), info.realm or "")
    if info.lastSeenAt and not e.played then sub = sub .. "  \194\183  " .. Util.FormatTime(info.lastSeenAt) end
    row.sub:SetText(sub)
  end
end

function UI:CreateViewBar(f)
  local button = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  button:SetSize(280, 22)
  button:SetPoint("TOPLEFT", f, "TOPLEFT", 66, -30)
  local text = button:GetFontString()
  if text then
    text:ClearAllPoints()
    text:SetPoint("LEFT", 10, 0)
    text:SetPoint("RIGHT", -24, 0)
    text:SetJustifyH("LEFT")
  end
  local arrow = button:CreateTexture(nil, "OVERLAY")
  arrow:SetSize(16, 16)
  arrow:SetPoint("RIGHT", -6, 0)
  arrow:SetTexture("Interface\\ChatFrame\\ChatFrameExpandArrow")
  arrow:SetRotation(-math.pi / 2)
  UI:Tooltip(button, "VIEW_CHOOSE", "VIEW_CHOOSE_TIP")
  self.viewButton = button

  self.viewBanner = f:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  self.viewBanner:SetPoint("LEFT", button, "RIGHT", 12, 0)
  self.viewBack = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  self.viewBack:SetSize(130, 22)
  self.viewBack:SetPoint("LEFT", self.viewBanner, "RIGHT", 10, 0)
  self.viewBack:SetScript("OnClick", function() FC:SetView(nil) end)

  local list = CreateFrame("Frame", nil, f, "BackdropTemplate")
  list:SetSize(LIST_W, LIST_H)
  list:SetPoint("TOPLEFT", button, "BOTTOMLEFT", -4, -2)
  list:SetFrameStrata("DIALOG")
  if list.SetBackdrop then
    list:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 14, insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    list:SetBackdropColor(0.05, 0.04, 0.03, 0.97)
    list:SetBackdropBorderColor(1, 0.82, 0, 0.8)
  end
  list:EnableMouse(true)
  list:Hide()
  self.viewList = list
  self.viewRows = UI:List(list, ROW_HEIGHT, createRow, updateRow)
  self.viewRows.scroll:SetPoint("TOPLEFT", 8, -8)
  self.viewRows.scroll:SetPoint("BOTTOMRIGHT", -28, 8)

  button:SetScript("OnClick", function()
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
  if not self.viewButton then return end
  local char = FC:ViewChar()
  self.viewButton:SetText(UI:ClassColored(fullName(char.info), char.info.classFile))
  local played = FC:IsViewingPlayed()
  local owner = FC:ViewOwner()
  if played then
    self.viewBanner:SetText("")
  elseif owner then
    self.viewBanner:SetText(string.format(L.VIEW_FRIEND_OF, owner) .. "  |cff999999(" .. L.VIEW_READONLY .. ")|r")
  else
    self.viewBanner:SetText(L.VIEW_OTHER_OWN .. "  |cff999999(" .. L.VIEW_READONLY .. ")|r")
  end
  self.viewBack:SetText(L.VIEW_BACK)
  self.viewBack:SetShown(not played)
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
