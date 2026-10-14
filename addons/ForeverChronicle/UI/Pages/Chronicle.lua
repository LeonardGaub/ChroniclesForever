-- Journey Forever - Chronicle page
-- The most recent recorded events, newest first. Text and icon come from the event type registry.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local page = { id = "chronicle", labelKey = "TAB_CHRONICLE", icon = "Interface\\Icons\\INV_Misc_Book_09", order = 20 }
local ROW_HEIGHT = 30
local MAX_ROWS = 200

local function createRow(row)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(24, 24)
  row.icon:SetPoint("LEFT", 4, 0)
  row.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.text:SetPoint("TOPLEFT", row.icon, "TOPRIGHT", 8, -1)
  row.text:SetPoint("RIGHT", row, "RIGHT", -8, 0)
  row.text:SetJustifyH("LEFT")
  row.text:SetWordWrap(false)
  row.sub = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.sub:SetPoint("BOTTOMLEFT", row.icon, "BOTTOMRIGHT", 8, 1)
  row.sub:SetPoint("RIGHT", row, "RIGHT", -8, 0)
  row.sub:SetJustifyH("LEFT")
  row.sub:SetWordWrap(false)

  -- Click: show this moment on the map.
  local hl = row:CreateTexture(nil, "HIGHLIGHT")
  hl:SetAllPoints()
  hl:SetColorTexture(1, 0.82, 0, 0.08)
  row:EnableMouse(true)
  row:SetScript("OnMouseUp", function(r)
    if r.record and UI.FocusMap then UI:FocusMap(r.record.time) end
  end)
  row:SetScript("OnEnter", function(r)
    GameTooltip:SetOwner(r, "ANCHOR_CURSOR")
    GameTooltip:SetText(L.CHRONICLE_CLICK_HINT, 1, 1, 1)
    GameTooltip:Show()
  end)
  row:SetScript("OnLeave", GameTooltip_Hide)
end

local function updateRow(row, record)
  row.record = record
  local text, icon = FC:DescribeEvent(record)
  row.icon:SetTexture(icon)
  row.text:SetText(text)
  local where = record.location and (record.location.subzone or record.location.zone)
  local when = FC.Util.FormatTime(record.time)
  row.sub:SetText(where and (when .. "  \194\183  " .. where) or when)
end

function page:Create(c)
  self.list = UI:List(c, ROW_HEIGHT, createRow, updateRow)
  self.list.scroll:SetPoint("TOPLEFT", 6, -8)
  self.list.scroll:SetPoint("BOTTOMRIGHT", -28, 8)
  self.empty = UI:Label(c, "CHRONICLE_EMPTY", "GameFontDisable")
  self.empty:SetPoint("CENTER")
end

function page:Refresh()
  local stream = FC:ViewStream("events")
  local seq = tostring(FC:ViewKey()) .. ":" .. tostring(stream.nextSeq)
  if self.lastSeq == seq and self.lastLang == FC:GetLanguage() then return end -- nothing new
  self.lastSeq, self.lastLang = seq, FC:GetLanguage()
  local items = FC:GetRecentEvents(MAX_ROWS, stream)
  self.list:SetItems(items)
  self.empty:SetShown(#items == 0)
end

UI:RegisterPage(page)
