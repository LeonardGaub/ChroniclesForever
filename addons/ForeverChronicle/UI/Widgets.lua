-- Journey Forever - UI widgets
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

-- Relabel `region` (FontString or Button) with locale string `key` on language change.
function UI:Track(region, key)
  localized[#localized + 1] = { region = region, key = key }
end

function UI:Relocalize()
  for _, entry in ipairs(localized) do entry.region:SetText((entry.prefix or "") .. L[entry.key]) end
end

-- Separator between the parts of a line of text: "  ·  ".
UI.SEP = "  \194\183  "

-- Character name with the last name (title suffix) if it has one, e.g. "Blind Bullseye".
function UI:FullName(info)
  local name = info.name or "?"
  if info.nameSuffix and info.nameSuffix ~= "" then name = name .. " " .. info.nameSuffix end
  return name
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

-- Sets a backdrop (nil clears it) with optional { r, g, b, a } colours. No-op where the client has no backdrops.
function UI:Backdrop(frame, def, bg, border)
  if not frame.SetBackdrop then return end
  frame:SetBackdrop(def)
  if bg then frame:SetBackdropColor(unpack(bg)) end
  if border then frame:SetBackdropBorderColor(unpack(border)) end
end

-- Gold border around a selected button (choices, toggles, tabs). nil where the client has no backdrops.
function UI:SelectionBorder(button)
  local ok, border = pcall(CreateFrame, "Frame", nil, button, "BackdropTemplate")
  if not ok or not border.SetBackdrop then return nil end
  border:SetPoint("TOPLEFT", -4, 4)
  border:SetPoint("BOTTOMRIGHT", 4, -4)
  border:SetBackdrop({ edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 12 })
  border:SetBackdropBorderColor(1, 0.82, 0, 1)
  border:Hide()
  return border
end

-- Shows the gold border (button.selection) and keeps the button's highlight glow on while selected.
function UI:SetSelected(button, selected)
  if button.selection then button.selection:SetShown(selected) end
  if selected then button:LockHighlight() else button:UnlockHighlight() end
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

-- Trims the dark border baked into the edges of most icon files.
function UI:CropIcon(tex)
  tex:SetTexCoord(0.07, 0.93, 0.07, 0.93)
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

-- Icon inset 2 px on a dark square. Without size the square fills the parent. Returns square, icon.
function UI:IconSquare(parent, size)
  local bg = parent:CreateTexture(nil, "BACKGROUND")
  if size then bg:SetSize(size, size) else bg:SetAllPoints() end
  bg:SetColorTexture(0, 0, 0, 0.7)
  local icon = parent:CreateTexture(nil, "ARTWORK")
  icon:SetPoint("TOPLEFT", bg, 2, -2)
  icon:SetPoint("BOTTOMRIGHT", bg, -2, 2)
  self:CropIcon(icon)
  return bg, icon
end

-- Square icon button (action-button style) with tooltip. Use UI:SetSelected for a gold "active" border.
function UI:IconButton(parent, size, icon, title, line, onClick)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(size, size)
  b.bg, b.icon = self:IconSquare(b)
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

-------------------------------------------------------------------------------
-- Scrolling list with recycled rows
--   createRow(rowFrame)            builds the row's regions once
--   updateRow(rowFrame, item, i)   fills them for an item
-- rowHeight: a number (striped rows) or function(item) -> height (rows of different heights, no stripes).
-- Each row keeps its offset from the top in row.y.
-------------------------------------------------------------------------------

function UI:List(parent, rowHeight, createRow, updateRow)
  local scroll = CreateFrame("ScrollFrame", nil, parent, "UIPanelScrollFrameTemplate")
  local content = CreateFrame("Frame", nil, scroll)
  content:SetSize(1, 1)
  scroll:SetScrollChild(content)
  scroll:SetScript("OnSizeChanged", function(_, w) content:SetWidth(w) end)

  local list = { scroll = scroll, content = content, rows = {} }
  local fixed = type(rowHeight) == "number"

  function list:SetItems(items)
    local y = 0
    for i, item in ipairs(items) do
      local row = self.rows[i]
      if not row then
        row = CreateFrame("Frame", nil, content)
        row:SetPoint("RIGHT", content, "RIGHT")
        if fixed and i % 2 == 0 then
          local stripe = row:CreateTexture(nil, "BACKGROUND")
          stripe:SetAllPoints()
          stripe:SetColorTexture(1, 1, 1, 0.03)
        end
        createRow(row)
        self.rows[i] = row
      end
      local h = fixed and rowHeight or rowHeight(item)
      row.y = y
      row:SetHeight(h)
      row:SetPoint("TOPLEFT", 0, -y)
      updateRow(row, item, i)
      row:Show()
      y = y + h
    end
    for i = #items + 1, #self.rows do self.rows[i]:Hide() end
    content:SetHeight(math.max(1, y))
  end

  return list
end

-------------------------------------------------------------------------------
-- Animations
-- UI:Tween(key, duration, delay, step, done) calls step(p) with p eased from 0 to 1 over `duration` seconds,
-- after `delay`. key is any table (usually the animated frame): a new tween on the same key replaces the
-- running one. With the "animations" option off, step(1) runs at once.
-------------------------------------------------------------------------------

local tweens, driver = {}, nil

local function easeOut(p) return 1 - (1 - p) ^ 3 end

function UI:AnimationsOn()
  local s = FC.db and FC.db.settings.modules.UI
  return not (s and s.animations == false)
end

function UI:Tween(key, duration, delay, step, done)
  if not self:AnimationsOn() then
    tweens[key] = nil
    step(1)
    if done then done() end
    return
  end
  tweens[key] = { t = -(delay or 0), d = math.max(duration or 0.2, 0.01), step = step, done = done }
  step(0)
  if not driver then
    driver = CreateFrame("Frame")
    driver:SetScript("OnUpdate", function(f, dt)
      local finished
      for k, tw in pairs(tweens) do
        tw.t = tw.t + dt
        if tw.t >= 0 then
          local p = math.min(1, tw.t / tw.d)
          tw.step(easeOut(p))
          if p >= 1 then
            tweens[k] = nil
            if tw.done then finished = finished or {}; finished[#finished + 1] = tw.done end
          end
        end
      end
      for _, fn in ipairs(finished or {}) do fn() end
      if next(tweens) == nil then f:Hide() end
    end)
  end
  driver:Show()
end

-- Ends the tween on key; with finish, it jumps to its end state first.
function UI:StopTween(key, finish)
  local tw = tweens[key]
  if not tw then return end
  tweens[key] = nil
  if finish then
    tw.step(1)
    if tw.done then tw.done() end
  end
end

-- Fades a frame in from transparent.
function UI:FadeIn(frame, duration, delay)
  self:Tween(frame, duration or 0.15, delay, function(p) frame:SetAlpha(p) end)
end

-------------------------------------------------------------------------------
-- Art with fallbacks: the client may not ship every Classic or Retail texture.
-------------------------------------------------------------------------------

UI.CIRCLE = "Interface\\CharacterFrame\\TempPortraitAlphaMask"
UI.WHITE = "Interface\\Buttons\\WHITE8X8"

function UI:HasAtlas(name)
  return name and C_Texture and C_Texture.GetAtlasInfo and C_Texture.GetAtlasInfo(name) ~= nil or false
end

-- candidates: list of { atlas = name } or { file = path, coords = { l, r, t, b } }. Uses the first one the
-- client has and returns its index, or nil if none loaded.
function UI:SetTextureFirst(tex, candidates)
  for i, c in ipairs(candidates) do
    if c.atlas then
      if self:HasAtlas(c.atlas) and tex.SetAtlas then
        tex:SetAtlas(c.atlas)
        return i
      end
    elseif c.file and tex:SetTexture(c.file) ~= false then
      if c.coords then tex:SetTexCoord(unpack(c.coords)) else tex:SetTexCoord(0, 1, 0, 1) end
      return i
    end
  end
end

-- Vertical or horizontal colour gradient (r, g, b, a from the bottom/left to the top/right).
function UI:Gradient(tex, orientation, r1, g1, b1, a1, r2, g2, b2, a2)
  tex:SetTexture(self.WHITE)
  if CreateColor and tex.SetGradient then
    local ok = pcall(tex.SetGradient, tex, orientation, CreateColor(r1, g1, b1, a1), CreateColor(r2, g2, b2, a2))
    if ok then return end
  end
  if tex.SetGradientAlpha then
    local ok = pcall(tex.SetGradientAlpha, tex, orientation, r1, g1, b1, a1, r2, g2, b2, a2)
    if ok then return end
  end
  tex:SetColorTexture((r1 + r2) / 2, (g1 + g2) / 2, (b1 + b2) / 2, (a1 + a2) / 2)
end

-- Font object by name, if the client has it; otherwise the fallback.
function UI:Font(name, fallback)
  return (name and _G[name]) and name or fallback
end

-- A filled circle texture (dots, pins, rings).
function UI:Circle(parent, layer, sublevel, size)
  local t = parent:CreateTexture(nil, layer or "ARTWORK", nil, sublevel)
  if t:SetTexture(self.CIRCLE) == false then t:SetTexture(self.WHITE) end
  if size then t:SetSize(size, size) end
  return t
end

-- Clips a texture to a circle (no-op where the client has no mask textures).
function UI:MaskCircle(parent, tex)
  if not parent.CreateMaskTexture then return end
  local mask = parent:CreateMaskTexture()
  if not mask then return end
  mask:SetTexture(self.CIRCLE, "CLAMPTOBLACKADDITIVE", "CLAMPTOBLACKADDITIVE")
  mask:SetAllPoints(tex)
  tex:AddMaskTexture(mask)
  return mask
end

-------------------------------------------------------------------------------
-- Pages: registered by UI/Pages/*.lua, shown as icon tabs on the window's right edge, sorted by order.
--   page = { id, labelKey, icon, order, Create = function(page, container), Refresh = function(page),
--            OnViewChanged = function(page) (optional: another character is shown) }
-------------------------------------------------------------------------------

function UI:RegisterPage(page)
  page.order = page.order or 100
  table.insert(self.pages, page)
  table.sort(self.pages, function(a, b) return a.order < b.order end)
end
