-- Forever Chronicle - Diagnostics page (spec F-012)
-- Capability status per feature (status icon + name, details in the tooltip) and the diagnostic log.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local page = { id = "diagnostics", labelKey = "TAB_DIAGNOSTICS", icon = "Interface\\Icons\\INV_Misc_Wrench_01", order = 90 }

local STATUS = {
  confirmed = { "ok", "CAP_STATUS_CONFIRMED" },
  present = { "wait", "CAP_STATUS_PRESENT" },
  missing = { "bad", "CAP_STATUS_MISSING" },
}
local COLUMN_W, ROW_H = 290, 24

function page:Create(c)
  self.version = c:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.version:SetPoint("TOPLEFT", 16, -12)

  self.capRows = {}
  local caps = FC.Diagnostics:GetCapabilities()
  local perColumn = math.ceil(#caps / 2)
  for i = 1, #caps do
    local row = CreateFrame("Frame", nil, c)
    row:SetSize(COLUMN_W, ROW_H)
    local col, line = math.floor((i - 1) / perColumn), (i - 1) % perColumn
    row:SetPoint("TOPLEFT", self.version, "BOTTOMLEFT", col * (COLUMN_W + 20), -12 - line * ROW_H)
    row.status = row:CreateTexture(nil, "ARTWORK")
    row.status:SetSize(18, 18)
    row.status:SetPoint("LEFT")
    row.label = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    row.label:SetPoint("LEFT", row.status, "RIGHT", 8, 0)
    row:EnableMouse(true)
    UI:Tooltip(row, function(r) return r.title end, function(r) return r.detail end)
    self.capRows[i] = row
  end

  local line = c:CreateTexture(nil, "ARTWORK")
  line:SetColorTexture(1, 0.82, 0, 0.2)
  line:SetHeight(1)
  line:SetPoint("TOPLEFT", self.version, "BOTTOMLEFT", 0, -20 - perColumn * ROW_H)
  line:SetPoint("RIGHT", c, "RIGHT", -14, 0)

  self.log = UI:List(c, 14, function(row)
    row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    row.text:SetPoint("LEFT", 2, 0)
    row.text:SetPoint("RIGHT", -2, 0)
    row.text:SetJustifyH("LEFT")
    row.text:SetWordWrap(false)
  end, function(row, text)
    row.text:SetText(text)
  end)
  self.log.scroll:SetPoint("TOPLEFT", line, "BOTTOMLEFT", -4, -8)
  self.log.scroll:SetPoint("BOTTOMRIGHT", -28, 8)
end

function page:Refresh()
  local info = FC.char.info
  self.version:SetText(string.format(L.DIAG_VERSION_LINE, FC.VERSION, FC.db.schemaVersion,
    info.clientVersion or "?", tostring(info.clientBuild or "?")))

  for i, cap in ipairs(FC.Diagnostics:GetCapabilities()) do
    local row = self.capRows[i]
    if row then
      local status = STATUS[cap.status]
      UI:SetIcon(row.status, UI.STATUS_ICONS[status[1]])
      row.label:SetText(cap.label)
      row.title = cap.label
      row.detail = L[status[2]] .. (cap.confirmedAt and ("\n" .. FC.Util.FormatTime(cap.confirmedAt)) or "")
    end
  end

  local log, lines = FC.Diagnostics:GetLog(), {}
  for i = #log, math.max(1, #log - 99), -1 do lines[#lines + 1] = log[i] end
  if #lines == 0 then lines[1] = L.LOG_EMPTY end
  self.log:SetItems(lines)
end

UI:RegisterPage(page)
