-- Forever Chronicle - Diagnostics page (spec F-012)
-- Capability status per feature and the tail of the diagnostic log.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local page = { id = "diagnostics", labelKey = "TAB_DIAGNOSTICS", order = 90 }

local STATUS_COLORS = {
  confirmed = { 0.1, 1, 0.1, "CAP_STATUS_CONFIRMED" },
  present = { 1, 0.82, 0, "CAP_STATUS_PRESENT" },
  missing = { 1, 0.25, 0.25, "CAP_STATUS_MISSING" },
}

function page:Create(c)
  self.version = c:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.version:SetPoint("TOPLEFT", 14, -12)
  self.version:SetPoint("RIGHT", c, "RIGHT", -14, 0)
  self.version:SetJustifyH("LEFT")

  local capHeader = UI:Header(c, "SECTION_CAPABILITIES")
  capHeader:SetPoint("TOPLEFT", self.version, "BOTTOMLEFT", 0, -12)
  self.capRows = {}
  local caps = FC.Diagnostics:GetCapabilities()
  local anchor = capHeader
  for i = 1, #caps do
    local label = c:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    label:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, i == 1 and -10 or -5)
    label:SetWidth(200)
    label:SetJustifyH("LEFT")
    local status = c:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    status:SetPoint("LEFT", label, "RIGHT", 8, 0)
    self.capRows[i] = { label = label, status = status }
    anchor = label
  end

  local logHeader = UI:Header(c, "SECTION_LOG")
  logHeader:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, -16)
  self.log = UI:List(c, 14, function(row)
    row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    row.text:SetPoint("LEFT", 2, 0)
    row.text:SetPoint("RIGHT", -2, 0)
    row.text:SetJustifyH("LEFT")
    row.text:SetWordWrap(false)
  end, function(row, line)
    row.text:SetText(line)
  end)
  self.log.scroll:SetPoint("TOPLEFT", logHeader, "BOTTOMLEFT", 0, -8)
  self.log.scroll:SetPoint("BOTTOMRIGHT", -28, 8)
end

function page:Refresh()
  local info = FC.char.info
  self.version:SetText(string.format(L.DIAG_VERSION_LINE, FC.VERSION, FC.db.schemaVersion,
    info.clientVersion or "?", tostring(info.clientBuild or "?")))

  for i, cap in ipairs(FC.Diagnostics:GetCapabilities()) do
    local row = self.capRows[i]
    if row then
      local color = STATUS_COLORS[cap.status]
      row.label:SetText(cap.label)
      row.status:SetText(L[color[4]])
      row.status:SetTextColor(color[1], color[2], color[3])
    end
  end

  local log, lines = FC.Diagnostics:GetLog(), {}
  for i = #log, math.max(1, #log - 99), -1 do lines[#lines + 1] = log[i] end
  if #lines == 0 then lines[1] = L.LOG_EMPTY end
  self.log:SetItems(lines)
end

UI:RegisterPage(page)
