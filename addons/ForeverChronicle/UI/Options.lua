-- Forever Chronicle - option controls
-- Builds check boxes and choice rows from the option registry, one section at a time.
-- Options choose their section with def.section (default "general") and their column with def.column.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local COLUMN_X = { 0, 270 }
local GOLD = { 1, 0.82, 0 }

local function createToggle(c, def)
  local cb = UI:CheckBox(c, def.labelKey, def.tooltipKey, function(checked) FC:SetOptionValue(def, checked) end)
  cb.Sync = function(self) self:SetChecked(FC:GetOptionValue(def) and true or false) end
  cb.height = 28
  return cb
end

-- Gold border around the selected choice, plus the button's own highlight glow.
function UI:SelectionBorder(button)
  local ok, border = pcall(CreateFrame, "Frame", nil, button, "BackdropTemplate")
  if not ok or not border.SetBackdrop then return nil end
  border:SetPoint("TOPLEFT", -4, 4)
  border:SetPoint("BOTTOMRIGHT", 4, -4)
  border:SetBackdrop({ edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 12 })
  border:SetBackdropBorderColor(GOLD[1], GOLD[2], GOLD[3], 1)
  border:Hide()
  return border
end

function UI:SetSelected(button, selected)
  if button.selection then button.selection:SetShown(selected) end
  if selected then button:LockHighlight() else button:UnlockHighlight() end
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
    b:SetSize(choice.labelKey and 100 or 52, 22)
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
