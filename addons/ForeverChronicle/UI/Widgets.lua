-- Forever Chronicle - UI widgets
-- Small building blocks on top of Blizzard templates and fonts, so every page looks like the
-- native UI: gold section headers (GameFontNormal), white values (GameFontHighlight),
-- grey hints (GameFontDisableSmall), standard scroll frames, buttons and check boxes.

local ADDON, FC = ...
local L = FC.L

local UI = {}
FC.UI = UI
UI.pages = {}
local localized = {} -- { region, key, fmt } relabelled when the language changes

-------------------------------------------------------------------------------
-- Text
-------------------------------------------------------------------------------

-- FontString whose text is the locale string `key`; updated automatically on language change.
function UI:Label(parent, key, font, layer)
  local fs = parent:CreateFontString(nil, layer or "OVERLAY", font or "GameFontHighlight")
  fs:SetJustifyH("LEFT")
  if key then
    fs:SetText(L[key])
    localized[#localized + 1] = { region = fs, key = key }
  end
  return fs
end

-- Gold section header with a thin divider line below it.
function UI:Header(parent, key)
  local fs = self:Label(parent, key, "GameFontNormal")
  local line = parent:CreateTexture(nil, "ARTWORK")
  line:SetColorTexture(1, 0.82, 0, 0.25)
  line:SetHeight(1)
  line:SetPoint("TOPLEFT", fs, "BOTTOMLEFT", 0, -3)
  line:SetPoint("RIGHT", parent, "RIGHT", -12, 0)
  fs.line = line
  return fs
end

-- Label/value pair laid out in a row: returns the value FontString.
function UI:Field(parent, key, anchor, x, y, labelWidth)
  local label = self:Label(parent, key, "GameFontNormalSmall")
  label:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", x or 0, y or -6)
  label:SetWidth(labelWidth or 150)
  local value = parent:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  value:SetJustifyH("LEFT")
  value:SetPoint("LEFT", label, "RIGHT", 6, 0)
  value.label = label
  return value
end

-- Relabel `region` (FontString or Button) with locale string `key` on language change.
function UI:Track(region, key)
  localized[#localized + 1] = { region = region, key = key }
end

function UI:Relocalize()
  for _, entry in ipairs(localized) do entry.region:SetText(L[entry.key]) end
end

function UI:ClassColored(text, classFile)
  if classFile and C_ClassColor and C_ClassColor.GetClassColor then
    local color = C_ClassColor.GetClassColor(classFile)
    if color then return color:WrapTextInColorCode(text) end
  end
  local c = classFile and RAID_CLASS_COLORS and RAID_CLASS_COLORS[classFile]
  if c and c.colorStr then return "|c" .. c.colorStr .. text .. "|r" end
  return text
end

-------------------------------------------------------------------------------
-- Controls
-------------------------------------------------------------------------------

function UI:Button(parent, key, width, onClick)
  local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  b:SetSize(width or 120, 22)
  b:SetText(L[key])
  localized[#localized + 1] = { region = b, key = key }
  b:SetScript("OnClick", onClick)
  return b
end

function UI:CheckBox(parent, key, tooltipKey, onClick)
  local cb = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
  cb:SetSize(26, 26)
  local label = self:Label(parent, key, "GameFontHighlight")
  label:SetPoint("LEFT", cb, "RIGHT", 4, 1)
  cb.label = label
  cb:SetScript("OnClick", function(self) onClick(self:GetChecked() and true or false) end)
  if tooltipKey then
    cb:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetText(L[key], 1, 0.82, 0)
      GameTooltip:AddLine(L[tooltipKey], 1, 1, 1, true)
      GameTooltip:Show()
    end)
    cb:SetScript("OnLeave", GameTooltip_Hide)
  end
  return cb
end

-- Classic status bar with text, e.g. storage usage.
function UI:Bar(parent, width)
  local bar = CreateFrame("StatusBar", nil, parent)
  bar:SetSize(width or 200, 14)
  bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
  bar:SetMinMaxValues(0, 1)
  local bg = bar:CreateTexture(nil, "BACKGROUND")
  bg:SetAllPoints()
  bg:SetColorTexture(0, 0, 0, 0.5)
  bar.text = bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  bar.text:SetPoint("CENTER")
  return bar
end

-------------------------------------------------------------------------------
-- Scrolling list with recycled rows
--   createRow(rowFrame)            builds the row's regions once
--   updateRow(rowFrame, item, i)   fills them for an item
-------------------------------------------------------------------------------

function UI:List(parent, rowHeight, createRow, updateRow)
  local scroll = CreateFrame("ScrollFrame", nil, parent, "UIPanelScrollFrameTemplate")
  local content = CreateFrame("Frame", nil, scroll)
  content:SetSize(1, 1)
  scroll:SetScrollChild(content)
  scroll:SetScript("OnSizeChanged", function(_, w) content:SetWidth(w) end)

  local list = { scroll = scroll, content = content, rows = {} }

  function list:SetItems(items)
    for i, item in ipairs(items) do
      local row = self.rows[i]
      if not row then
        row = CreateFrame("Frame", nil, content)
        row:SetHeight(rowHeight)
        row:SetPoint("TOPLEFT", 0, -(i - 1) * rowHeight)
        row:SetPoint("RIGHT", content, "RIGHT")
        if i % 2 == 0 then
          local stripe = row:CreateTexture(nil, "BACKGROUND")
          stripe:SetAllPoints()
          stripe:SetColorTexture(1, 1, 1, 0.03)
        end
        createRow(row)
        self.rows[i] = row
      end
      updateRow(row, item, i)
      row:Show()
    end
    for i = #items + 1, #self.rows do self.rows[i]:Hide() end
    content:SetHeight(math.max(1, #items * rowHeight))
  end

  return list
end

-------------------------------------------------------------------------------
-- Pages: registered by UI/Pages/*.lua, shown as bottom tabs in registration order.
--   page = { id, labelKey, order, Create = function(page, container), Refresh = function(page) }
-------------------------------------------------------------------------------

function UI:RegisterPage(page)
  page.order = page.order or 100
  table.insert(self.pages, page)
  table.sort(self.pages, function(a, b) return a.order < b.order end)
end
