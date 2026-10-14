-- Forever Chronicle - Overview page
-- Character header, current session, statistics (from the stat registry) and storage usage.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "overview", labelKey = "TAB_OVERVIEW", order = 10 }

function page:Create(c)
  -- Character header
  self.name = c:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  self.name:SetPoint("TOPLEFT", 14, -12)
  self.details = c:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  self.details:SetPoint("TOPLEFT", self.name, "BOTTOMLEFT", 0, -4)
  self.realm = c:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.realm:SetPoint("TOPLEFT", self.details, "BOTTOMLEFT", 0, -3)

  -- Session
  local sessionHeader = UI:Header(c, "SECTION_SESSION")
  sessionHeader:SetPoint("TOPLEFT", self.realm, "BOTTOMLEFT", 0, -16)
  self.sessionTime = UI:Field(c, "FIELD_SESSION_TIME", sessionHeader, 0, -10)
  self.reloads = UI:Field(c, "FIELD_RELOADS", self.sessionTime.label)
  self.played = UI:Field(c, "FIELD_PLAYED", self.reloads.label)
  self.playedLevel = UI:Field(c, "FIELD_PLAYED_LEVEL", self.played.label)

  -- Statistics: one field per registered stat, in two columns.
  local statsHeader = UI:Header(c, "SECTION_STATS")
  statsHeader:SetPoint("TOPLEFT", self.playedLevel.label, "BOTTOMLEFT", 0, -16)
  self.statFields = {}
  local half = math.ceil(#FC.statDefs / 2)
  for i, def in ipairs(FC.statDefs) do
    local field
    if i == 1 then
      field = UI:Field(c, def.labelKey, statsHeader, 0, -10, 130)
    elseif i == half + 1 then
      field = UI:Field(c, def.labelKey, statsHeader, 260, -10, 130)
    else
      field = UI:Field(c, def.labelKey, self.statFields[i - 1].field.label, 0, -6, 130)
    end
    self.statFields[i] = { def = def, field = field }
  end
  local lastLeft = self.statFields[half] and self.statFields[half].field.label or statsHeader

  -- Storage usage per stream
  local storageHeader = UI:Header(c, "SECTION_STORAGE")
  storageHeader:SetPoint("TOPLEFT", lastLeft, "BOTTOMLEFT", 0, -16)
  self.storageHeader = storageHeader
  self.bars = {}

  self.hint = UI:Label(c, "HINT_SAVED", "GameFontDisableSmall")
  self.hint:SetPoint("BOTTOMLEFT", 14, 10)
  self.hint:SetPoint("RIGHT", c, "RIGHT", -14, 0)
end

local function storageBar(self, c, i)
  local row = self.bars[i]
  if row then return row end
  local label = c:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  label:SetWidth(150)
  label:SetJustifyH("LEFT")
  local anchor = i == 1 and self.storageHeader or self.bars[i - 1].label
  label:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, i == 1 and -10 or -8)
  local bar = UI:Bar(c, 260)
  bar:SetPoint("LEFT", label, "RIGHT", 6, 0)
  row = { label = label, bar = bar }
  self.bars[i] = row
  return row
end

function page:Refresh()
  local c = self.container
  local info = FC.char.info

  self.name:SetText(UI:ClassColored(info.name or "?", info.classFile))
  self.details:SetText(string.format(L.CHAR_DETAILS, info.level or "?", info.raceName or "", info.className or ""))
  self.realm:SetText(info.realm or "")

  local session = FC:GetModule("Session"):GetCurrent()
  self.sessionTime:SetText(FC.sessionStartedAt and Util.FormatDuration(time() - FC.sessionStartedAt) or L.UNKNOWN)
  self.reloads:SetText(session and tostring(session.reloads or 0) or L.UNKNOWN)
  local total = session and session.playedTotal or FC.char.stats.played_total
  self.played:SetText(total and Util.FormatDuration(total + (session and session.playedAt and (time() - session.playedAt) or 0))
    or L.PLAYED_UNKNOWN)
  self.playedLevel:SetText(session and session.playedLevel and Util.FormatDuration(session.playedLevel) or L.UNKNOWN)

  for _, entry in ipairs(self.statFields) do
    entry.field:SetText(FC:FormatStat(entry.def, FC:GetStatValue(entry.def)))
  end

  for i, u in ipairs(FC.Storage:GetUsage()) do
    local row = storageBar(self, c, i)
    local ratio = u.cap > 0 and u.count / u.cap or 0
    row.label:SetText(L["STREAM_" .. u.name:upper()])
    row.bar:SetValue(ratio)
    if ratio >= 0.8 then
      row.bar:SetStatusBarColor(1, 0.5, 0)
    else
      row.bar:SetStatusBarColor(0.2, 0.6, 0.2)
    end
    row.bar.text:SetText(string.format("%d / %d", u.count, u.cap))
  end
end

UI:RegisterPage(page)
