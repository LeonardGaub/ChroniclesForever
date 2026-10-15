-- Journey Forever - Settings page (spec F-009)
-- One block per registered option section (FC:RegisterOptionSection), each generated from the options
-- in that section. Modules add sections and options; this page needs no changes for that.

local ADDON, FC = ...
local UI = FC.UI

local page = { id = "settings", labelKey = "TAB_SETTINGS", icon = "Interface\\Icons\\INV_Misc_Gear_01", order = 80 }

function page:Create(outer)
  -- Scrollable, so modules can keep adding options without running out of room.
  local scroll = CreateFrame("ScrollFrame", nil, outer, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 0, -4)
  scroll:SetPoint("BOTTOMRIGHT", -28, 4)
  local c = CreateFrame("Frame", nil, scroll)
  c:SetSize(770, 600)
  scroll:SetScrollChild(c)
  self.content = c

  self.controls = {}
  local anchor, offset = nil, 0
  for _, section in ipairs(FC.optionSections) do
    local header = UI:Header(c, section.labelKey, section.icon)
    if anchor then
      header:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, offset - 14)
    else
      header:SetPoint("TOPLEFT", 14, -12)
    end
    local controls = UI:BuildOptions(c, section.key, header)
    for _, control in ipairs(controls) do self.controls[#self.controls + 1] = control end
    anchor, offset = header, controls.bottom
  end

  -- Addon storage: one bar per stream (limits of the SavedVariables file).
  self.storageHeader = UI:Header(c, "SECTION_STORAGE", "Interface\\Icons\\INV_Misc_Book_09")
  self.storageHeader:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, offset - 14)
  self.storageDesc = UI:Label(c, "STORAGE_DESC", "GameFontDisableSmall")
  self.storageDesc:SetPoint("TOPLEFT", self.storageHeader, "BOTTOMLEFT", 0, -10)
  self.storageDesc:SetPoint("RIGHT", c, "RIGHT", -14, 0)
  self.bars = {}
end

local function storageRow(self, c, i, usage)
  local row = self.bars[i]
  if row then return row end
  row = CreateFrame("Frame", nil, c)
  row:SetSize(250, 24)
  local col, line = (i - 1) % 3, math.floor((i - 1) / 3)
  row:SetPoint("TOPLEFT", self.storageDesc, "BOTTOMLEFT", col * 262, -8 - line * 30)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(22, 22)
  row.icon:SetPoint("LEFT")
  row.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  UI:SetIcon(row.icon, usage.icon)
  row.label = c:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  row.label:SetPoint("LEFT", row.icon, "RIGHT", 8, 0)
  row.label:SetWidth(84)
  row.label:SetJustifyH("LEFT")
  row.bar = UI:Bar(row, 140)
  row.bar:SetPoint("LEFT", row.label, "RIGHT", 6, 0)
  self.bars[i] = row
  return row
end

function page:Refresh()
  UI:SyncOptions(self.controls)
  local L = FC.L
  local lowest
  for i, u in ipairs(FC.Storage:GetUsage()) do
    local row = storageRow(self, self.content, i, u)
    lowest = row
    local ratio = u.cap > 0 and u.count / u.cap or 0
    row.label:SetText(L["STREAM_" .. u.name:upper()])
    row.bar:SetValue(ratio)
    if ratio >= 0.8 then row.bar:SetStatusBarColor(1, 0.5, 0) else row.bar:SetStatusBarColor(0.2, 0.6, 0.2) end
    row.bar.text:SetText(string.format("%s / %s", FC.Util.FormatNumber(u.count), FC.Util.FormatNumber(u.cap)))
  end
  -- Scroll height = everything down to the last storage bar.
  local top, bottom = self.content:GetTop(), lowest and lowest:GetBottom()
  if top and bottom and top > bottom then self.content:SetHeight(top - bottom + 16) end
end

UI:RegisterPage(page)

-------------------------------------------------------------------------------
-- Core options (language, debug). Module options are registered by the modules themselves.
-------------------------------------------------------------------------------

FC:RegisterOption({
  type = "choice", labelKey = "OPT_LANGUAGE", order = 1,
  choices = { { value = "deDE", labelKey = "LANG_DE" }, { value = "enUS", labelKey = "LANG_EN" } },
  get = function() return FC:GetLanguage() end,
  set = function(value) FC:SetLanguage(value) end,
})

FC:RegisterOption({
  type = "choice", module = "UI", key = "chronicleStyle", labelKey = "OPT_CHRONICLE_STYLE",
  tooltipKey = "OPT_CHRONICLE_STYLE_TIP", order = 5,
  choices = { { value = "book", labelKey = "OPT_STYLE_BOOK" }, { value = "classic", labelKey = "OPT_STYLE_CLASSIC" } },
  onChange = function() UI:RestyleChronicle() end,
})

FC:RegisterOption({
  type = "toggle", column = 2, module = "UI", key = "animations", labelKey = "OPT_ANIMATIONS",
  tooltipKey = "OPT_ANIMATIONS_TIP", order = 40,
})

FC:RegisterOption({
  type = "toggle", column = 2, labelKey = "OPT_DEBUG", tooltipKey = "OPT_DEBUG_TIP", order = 90,
  get = function() return FC.db.settings.debug end,
  set = function(value) FC.db.settings.debug = value end,
})
