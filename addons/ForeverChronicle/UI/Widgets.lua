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

-- Gold section header with a thin divider line below it; optionally with a small inline icon in front.
function UI:Header(parent, key, icon)
  local fs = self:Label(parent, key, "GameFontNormal")
  if icon then
    local entry = localized[#localized]
    entry.prefix = "|T" .. icon .. ":16:16:0:0:64:64:5:59:5:59|t  "
    fs:SetText(entry.prefix .. L[key])
  end
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
  for _, entry in ipairs(localized) do entry.region:SetText((entry.prefix or "") .. L[entry.key]) end
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
-- Icons
-------------------------------------------------------------------------------

UI.ICON_FALLBACK = "Interface\\Icons\\INV_Misc_QuestionMark"
UI.STATUS_ICONS = {
  ok = "Interface\\RaidFrame\\ReadyCheck-Ready",
  wait = "Interface\\RaidFrame\\ReadyCheck-Waiting",
  bad = "Interface\\RaidFrame\\ReadyCheck-NotReady",
}

-- Colour of an item quality (0 poor ... 7 heirloom) as r, g, b, or nil if unknown.
function UI:QualityColor(quality)
  if type(quality) ~= "number" then return nil end
  local Util = FC.Util
  if C_Item and C_Item.GetItemQualityColor then
    local r, g, b = Util.SafeValues(C_Item.GetItemQualityColor, quality)
    if type(r) == "number" then return r, g, b end
  end
  if GetItemQualityColor then
    local r, g, b = Util.SafeValues(GetItemQualityColor, quality)
    if type(r) == "number" then return r, g, b end
  end
end

-- Sets a texture; falls back to the question mark icon if the client does not have the file.
function UI:SetIcon(tex, path)
  local ok = tex:SetTexture(path or self.ICON_FALLBACK)
  if ok == false then tex:SetTexture(self.ICON_FALLBACK) end
  return ok ~= false
end

-- Tooltip with a gold title (locale key or function) and an optional white line (key, text or function).
function UI:Tooltip(frame, title, line)
  frame:SetScript("OnEnter", function(owner)
    local t = type(title) == "function" and title(owner) or L[title]
    if not t then return end
    GameTooltip:SetOwner(owner, "ANCHOR_RIGHT")
    GameTooltip:SetText(t, 1, 0.82, 0)
    local l = type(line) == "function" and line(owner) or (line and L[line])
    if l and l ~= "" then GameTooltip:AddLine(l, 1, 1, 1, true) end
    GameTooltip:Show()
  end)
  frame:SetScript("OnLeave", GameTooltip_Hide)
end

-- Square icon button (action-button style) with tooltip. Use UI:SetSelected for a gold "active" border.
function UI:IconButton(parent, size, icon, title, line, onClick)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(size, size)
  local bg = b:CreateTexture(nil, "BACKGROUND")
  bg:SetAllPoints()
  bg:SetColorTexture(0, 0, 0, 0.7)
  b.icon = b:CreateTexture(nil, "ARTWORK")
  b.icon:SetPoint("TOPLEFT", 2, -2)
  b.icon:SetPoint("BOTTOMRIGHT", -2, 2)
  b.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  self:SetIcon(b.icon, icon)
  b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
  b.selection = self:SelectionBorder(b)
  self:Tooltip(b, title, line)
  if onClick then b:SetScript("OnClick", onClick) end
  return b
end

-- On/off icon button: desaturated when off, gold border when on.
function UI:SetToggle(button, on)
  button.on = on
  button.icon:SetDesaturated(not on)
  button.icon:SetAlpha(on and 1 or 0.6)
  self:SetSelected(button, on)
end

-- Classic page arrow (spellbook style). dir: "Prev" or "Next".
function UI:ArrowButton(parent, dir, onClick)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(26, 26)
  b:SetNormalTexture("Interface\\Buttons\\UI-SpellbookIcon-" .. dir .. "Page-Up")
  b:SetPushedTexture("Interface\\Buttons\\UI-SpellbookIcon-" .. dir .. "Page-Down")
  b:SetDisabledTexture("Interface\\Buttons\\UI-SpellbookIcon-" .. dir .. "Page-Disabled")
  b:SetHighlightTexture("Interface\\Buttons\\UI-Common-MouseHilight", "ADD")
  b:SetScript("OnClick", onClick)
  return b
end

-- Stat tile: icon and value; the name is shown in the tooltip. title: locale key; line: optional extra text.
function UI:Tile(parent, icon, title, width)
  local t = CreateFrame("Frame", nil, parent)
  t:SetSize(width or 160, 40)
  local bg = t:CreateTexture(nil, "BACKGROUND")
  bg:SetSize(36, 36)
  bg:SetPoint("LEFT")
  bg:SetColorTexture(0, 0, 0, 0.7)
  t.icon = t:CreateTexture(nil, "ARTWORK")
  t.icon:SetPoint("TOPLEFT", bg, 2, -2)
  t.icon:SetPoint("BOTTOMRIGHT", bg, -2, 2)
  t.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  self:SetIcon(t.icon, icon)
  t.value = t:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
  t.value:SetPoint("LEFT", bg, "RIGHT", 8, 0)
  t.value:SetPoint("RIGHT", t, "RIGHT", -2, 0)
  t.value:SetJustifyH("LEFT")
  t.value:SetWordWrap(false)
  t:EnableMouse(true)
  self:Tooltip(t, title, function(owner) return owner.extra end)
  function t:SetValue(text, extra)
    self.value:SetText(text)
    self.extra = extra
  end
  return t
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
