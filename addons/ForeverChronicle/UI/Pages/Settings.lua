-- Forever Chronicle - Settings page (spec F-009)
-- One block per registered option section (FC:RegisterOptionSection), each generated from the options
-- in that section. Modules add sections and options; this page needs no changes for that.

local ADDON, FC = ...
local UI = FC.UI

local page = { id = "settings", labelKey = "TAB_SETTINGS", order = 80 }

function page:Create(c)
  self.controls = {}
  local anchor, offset = nil, 0
  for _, section in ipairs(FC.optionSections) do
    local header = UI:Header(c, section.labelKey)
    if anchor then
      header:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, offset - 14)
    else
      header:SetPoint("TOPLEFT", 14, -12)
    end
    local controls = UI:BuildOptions(c, section.key, header)
    for _, control in ipairs(controls) do self.controls[#self.controls + 1] = control end
    anchor, offset = header, controls.bottom
  end
  local hint = UI:Label(c, "HINT_COMMANDS", "GameFontDisableSmall")
  hint:SetPoint("BOTTOMLEFT", 14, 10)
  hint:SetPoint("RIGHT", c, "RIGHT", -14, 0)
end

function page:Refresh()
  UI:SyncOptions(self.controls)
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
  type = "toggle", column = 2, labelKey = "OPT_DEBUG", tooltipKey = "OPT_DEBUG_TIP", order = 90,
  get = function() return FC.db.settings.debug end,
  set = function(value) FC.db.settings.debug = value end,
})
