-- Forever Chronicle - Screenshots page
-- Latest screenshot requests: status icon, event icon, event and time. Details in the row tooltip.
-- Icon buttons: test screenshot, open the screenshot settings.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "screenshots", labelKey = "TAB_SCREENSHOTS", icon = "Interface\\Icons\\INV_Misc_Spyglass_02", order = 30 }
local ROW_HEIGHT = 28

local STATUS_ICON = { confirmed = "ok", api_called = "wait" }

-- First event of a screenshot (looked up in the events stream), or nil for test screenshots.
local function firstEvent(eventId)
  if not eventId then return nil end
  local records = FC:ViewStream("events").records
  for i = #records, math.max(1, #records - 500), -1 do
    if records[i].id == eventId then return records[i] end
  end
end

local function createRow(row)
  row.status = row:CreateTexture(nil, "ARTWORK")
  row.status:SetSize(16, 16)
  row.status:SetPoint("LEFT", 6, 0)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(22, 22)
  row.icon:SetPoint("LEFT", row.status, "RIGHT", 8, 0)
  row.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  row.time = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.time:SetPoint("RIGHT", -8, 0)
  row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.text:SetPoint("LEFT", row.icon, "RIGHT", 8, 0)
  row.text:SetPoint("RIGHT", row.time, "LEFT", -8, 0)
  row.text:SetJustifyH("LEFT")
  row.text:SetWordWrap(false)
  row:EnableMouse(true)
  UI:Tooltip(row, function(r) return r.title end, function(r) return r.detail end)
end

local function updateRow(row, rec)
  UI:SetIcon(row.status, UI.STATUS_ICONS[STATUS_ICON[rec.status] or "bad"])
  local event = firstEvent(rec.events and rec.events[1])
  local text, icon
  if event then
    text, icon = FC:DescribeEvent(event)
  else
    text, icon = L.TRIGGER_MANUAL, "Interface\\Icons\\INV_Misc_Spyglass_02"
  end
  if rec.events and #rec.events > 1 then text = text .. string.format(L.SHOT_MORE_EVENTS, #rec.events - 1) end
  UI:SetIcon(row.icon, icon)
  row.text:SetText(text)
  row.time:SetText(Util.FormatTime(rec.capturedAt or rec.requestedAt))
  row.title = text
  row.detail = L["SHOT_STATUS_" .. rec.status:upper()] .. (rec.fileStamp and ("\nWoWScrnShot_" .. rec.fileStamp) or "")
end

function page:Create(c)
  self.list = UI:List(c, ROW_HEIGHT, createRow, updateRow)
  self.list.scroll:SetPoint("TOPLEFT", 6, -8)
  self.list.scroll:SetPoint("BOTTOMRIGHT", -28, 52)

  local settings = UI:IconButton(c, 36, "Interface\\Icons\\INV_Misc_Gear_01", "SHOT_SETTINGS_BUTTON", nil, function()
    for i, p in ipairs(UI.pages) do if p.id == "settings" then UI:SelectPage(i) end end
  end)
  settings:SetPoint("BOTTOMRIGHT", -12, 8)
  local test = UI:IconButton(c, 36, "Interface\\Icons\\INV_Misc_Spyglass_02", "SHOT_TEST_BUTTON", "SHOT_TEST_TIP",
    function() SlashCmdList.FOREVERCHRONICLESHOT("test") end)
  test:SetPoint("RIGHT", settings, "LEFT", -8, 0)

  self.empty = UI:Label(c, "SHOT_NONE", "GameFontDisable")
  self.empty:SetPoint("CENTER")
end

function page:Refresh()
  local items = FC:GetModule("Screenshots"):GetRecent(100, FC:ViewStream("screenshots"))
  self.list:SetItems(items)
  self.empty:SetShown(#items == 0)
end

UI:RegisterPage(page)
