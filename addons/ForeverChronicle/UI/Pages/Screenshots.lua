-- Forever Chronicle - Screenshots page
-- The latest screenshot requests with their outcome, and a test button. Settings are on the Settings page.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "screenshots", labelKey = "TAB_SCREENSHOTS", order = 30 }

local STATUS_COLORS = {
  confirmed = { 0.1, 1, 0.1 }, api_called = { 1, 0.82, 0 }, failed = { 1, 0.25, 0.25 },
}
local GREY = { 0.6, 0.6, 0.6 }

-- Description of the first event a screenshot belongs to (looked up in the events stream).
local function eventText(eventId)
  if not eventId then return L.TRIGGER_MANUAL end
  local records = FC.Storage:GetStream("events").records
  for i = #records, math.max(1, #records - 500), -1 do
    if records[i].id == eventId then return (FC:DescribeEvent(records[i])) end
  end
  return "?"
end

local function createRow(row)
  row.status = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  row.status:SetPoint("LEFT", 4, 0)
  row.status:SetWidth(120)
  row.status:SetJustifyH("LEFT")
  row.time = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.time:SetPoint("LEFT", row.status, "RIGHT", 4, 0)
  row.time:SetWidth(110)
  row.time:SetJustifyH("LEFT")
  row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  row.text:SetPoint("LEFT", row.time, "RIGHT", 4, 0)
  row.text:SetPoint("RIGHT", -4, 0)
  row.text:SetJustifyH("LEFT")
  row.text:SetWordWrap(false)
end

local function updateRow(row, rec)
  local color = STATUS_COLORS[rec.status] or GREY
  row.status:SetText(L["SHOT_STATUS_" .. rec.status:upper()])
  row.status:SetTextColor(color[1], color[2], color[3])
  row.time:SetText(Util.FormatTime(rec.capturedAt or rec.requestedAt))
  local text = eventText(rec.events and rec.events[1])
  if rec.events and #rec.events > 1 then text = text .. string.format(L.SHOT_MORE_EVENTS, #rec.events - 1) end
  row.text:SetText(text)
end

function page:Create(c)
  local header = UI:Header(c, "SECTION_RECENT_SHOTS")
  header:SetPoint("TOPLEFT", 14, -12)
  self.list = UI:List(c, 20, createRow, updateRow)
  self.list.scroll:SetPoint("TOPLEFT", header, "BOTTOMLEFT", -4, -10)
  self.list.scroll:SetPoint("BOTTOMRIGHT", -28, 40)

  local test = UI:Button(c, "SHOT_TEST_BUTTON", 160, function() SlashCmdList.FOREVERCHRONICLESHOT("test") end)
  test:SetPoint("BOTTOMLEFT", 12, 10)
  self.hint = UI:Label(c, "SHOT_SETTINGS_HINT", "GameFontDisableSmall")
  self.hint:SetPoint("LEFT", test, "RIGHT", 12, 0)
  self.hint:SetPoint("RIGHT", c, "RIGHT", -14, 0)
  self.empty = UI:Label(c, "SHOT_NONE", "GameFontDisable")
  self.empty:SetPoint("TOP", self.list.scroll, "TOP", 0, -20)
end

function page:Refresh()
  local items = FC:GetModule("Screenshots"):GetRecent(100)
  self.list:SetItems(items)
  self.empty:SetShown(#items == 0)
end

UI:RegisterPage(page)
