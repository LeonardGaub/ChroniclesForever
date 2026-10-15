-- Journey Forever - option controls
-- Builds the settings controls from the option registry (FC:RegisterOption), one section at a time:
--   toggle: check box; choice: one button per choice; text: text field; button: runs def.onClick;
--   custom: a module's own control (def.create).
-- Options choose their section with def.section (default "general") and their column with def.column.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local COLUMN_X = { 0, 270 }

local function createToggle(c, def)
  local cb = UI:CheckBox(c, def.labelKey, def.tooltipKey, function(checked) FC:SetOptionValue(def, checked) end)
  cb.Sync = function(self) self:SetChecked(FC:GetOptionValue(def) and true or false) end
  cb.height = 28
  return cb
end

-- A label above one button per choice.
local function createChoice(c, def)
  local row = CreateFrame("Frame", nil, c)
  row:SetSize(250, 46)
  local label = UI:Label(row, def.labelKey, "GameFontHighlight")
  label:SetPoint("TOPLEFT", 4, 0)
  row.buttons = {}
  local prev
  for i, choice in ipairs(def.choices) do
    local b = CreateFrame("Button", nil, row, "UIPanelButtonTemplate")
    b:SetSize(def.buttonWidth or (choice.labelKey and 100 or 52), 22)
    if choice.labelKey then
      b:SetText(L[choice.labelKey])
      UI:Track(b, choice.labelKey)
    else
      b:SetText(choice.text)
    end
    b:SetScript("OnClick", function()
      FC:SetOptionValue(def, choice.value)
      row:Sync()
    end)
    if prev then b:SetPoint("LEFT", prev, "RIGHT", 6, 0) else b:SetPoint("TOPLEFT", label, "BOTTOMLEFT", 2, -6) end
    b.value = choice.value
    b.selection = UI:SelectionBorder(b)
    if def.tooltipKey then UI:Tooltip(b, def.labelKey, def.tooltipKey) end
    row.buttons[i] = b
    prev = b
  end
  row.Sync = function(self)
    local current = FC:GetOptionValue(def)
    for _, b in ipairs(self.buttons) do UI:SetSelected(b, b.value == current) end
  end
  row.height = 52
  return row
end

-- A label above a text field. def.maxLetters limits the length; the value is saved on Enter or when leaving.
local function createText(c, def)
  local row = CreateFrame("Frame", nil, c)
  row:SetSize(250, 46)
  local label = UI:Label(row, def.labelKey, "GameFontHighlight")
  label:SetPoint("TOPLEFT", 4, 0)
  local box = CreateFrame("EditBox", nil, row, "InputBoxTemplate")
  box:SetSize(220, 20)
  box:SetPoint("TOPLEFT", label, "BOTTOMLEFT", 6, -6)
  box:SetAutoFocus(false)
  box:SetMaxLetters(def.maxLetters or 32)
  local function save(b)
    local text = b:GetText()
    text = type(text) == "string" and strtrim(text) or ""
    if text ~= (FC:GetOptionValue(def) or "") then FC:SetOptionValue(def, text) end
  end
  box:SetScript("OnEnterPressed", function(b) save(b); b:ClearFocus() end)
  box:SetScript("OnEditFocusLost", save)
  box:SetScript("OnEscapePressed", function(b) b:ClearFocus(); row:Sync() end)
  if def.tooltipKey then UI:Tooltip(box, def.labelKey, def.tooltipKey) end
  row.box = box
  row.Sync = function(self)
    if not (self.box.HasFocus and self.box:HasFocus() == true) then self.box:SetText(FC:GetOptionValue(def) or "") end
  end
  row.height = 52
  return row
end

-- A button that runs def.onClick (an action, no stored value).
local function createButton(c, def)
  local row = CreateFrame("Frame", nil, c)
  row:SetSize(250, 30)
  local b = UI:Button(row, def.labelKey, def.buttonWidth or 160, function() def.onClick() end)
  b:SetPoint("TOPLEFT", 4, -2)
  if def.tooltipKey then UI:Tooltip(b, def.labelKey, def.tooltipKey) end
  row.button = b
  row.Sync = function() end
  row.height = 34
  return row
end

-- Creates controls for all options of a section below `top`. Returns the controls; controls.bottom is
-- the lowest y offset used (relative to top), for placing what follows.
function UI:BuildOptions(c, section, top, topOffset)
  local controls = {}
  local y = { topOffset or -10, topOffset or -10 }
  for _, def in ipairs(FC.optionDefs) do
    if (def.section or "general") == section then
      local control
      if def.type == "toggle" then
        control = createToggle(c, def)
      elseif def.type == "choice" then
        control = createChoice(c, def)
      elseif def.type == "text" then
        control = createText(c, def)
      elseif def.type == "button" then
        control = createButton(c, def)
      elseif def.type == "custom" then
        control = def.create(c, def)   -- a module's own control: needs :Sync() and .height
      end
      if control then
        local col = def.column or 1
        control:SetPoint("TOPLEFT", top, "BOTTOMLEFT", COLUMN_X[col] - (def.type == "toggle" and 4 or 0), y[col])
        y[col] = y[col] - control.height
        controls[#controls + 1] = control
      end
    end
  end
  controls.bottom = math.min(y[1], y[2])
  return controls
end

function UI:SyncOptions(controls)
  for _, control in ipairs(controls) do control:Sync() end
end
