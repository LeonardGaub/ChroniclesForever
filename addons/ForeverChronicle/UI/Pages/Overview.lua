-- Journey Forever - Overview page
-- Left: full name, level line, XP bar and gold, then the stat groups (heading, short description,
-- tiles with icon, name and value). Right: the character model with the equipped gear around it,
-- like the Classic character window. Stats and groups come from the registry (FC:RegisterStat/StatGroup).

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "overview", labelKey = "TAB_OVERVIEW", icon = "portrait", order = 10 }
local TILE_W, TILE_H, TILE_COLUMNS = 178, 40, 2
local SLOT_SIZE, SLOT_GAP, MODEL_W = 37, 4, 260

-------------------------------------------------------------------------------
-- Stat tiles: icon, name (gold, small) and value (white)
-------------------------------------------------------------------------------

local function statTile(parent, def)
  local t = CreateFrame("Frame", nil, parent)
  t:SetSize(TILE_W, TILE_H)
  local bg
  bg, t.icon = UI:IconSquare(t, 34)
  bg:SetPoint("LEFT")
  UI:SetIcon(t.icon, def.icon)
  t.name = UI:Label(t, def.labelKey, "GameFontNormalSmall")
  t.name:SetPoint("TOPLEFT", bg, "TOPRIGHT", 8, -2)
  t.name:SetPoint("RIGHT", t, "RIGHT")
  t.name:SetWordWrap(false)
  t.value = UI:Label(t, nil, "GameFontHighlight")
  t.value:SetPoint("BOTTOMLEFT", bg, "BOTTOMRIGHT", 8, 2)
  t.value:SetPoint("RIGHT", t, "RIGHT")
  t.def = def
  return t
end

-------------------------------------------------------------------------------
-- Gear slots
-------------------------------------------------------------------------------

-- The game's item button (slot frame and quality border, as in the character window) where the client has
-- it; otherwise a plain button with a coloured border.
local function itemButton(parent)
  local ok, b = pcall(CreateFrame, "ItemButton", nil, parent)
  if not ok or not b then ok, b = pcall(CreateFrame, "Button", nil, parent, "ItemButtonTemplate") end
  if not ok or not b then b = CreateFrame("Button", nil, parent) end
  return b
end

local function gearSlot(parent, slotName)
  local slotID, emptyTexture = Util.SafeValues(GetInventorySlotInfo, slotName)
  local b = itemButton(parent)
  b:SetSize(SLOT_SIZE, SLOT_SIZE)
  b.native = type(b.IconBorder) == "table" and type(SetItemButtonQuality) == "function"
  b.border = b:CreateTexture(nil, "BACKGROUND")
  b.border:SetPoint("TOPLEFT", -2, 2)
  b.border:SetPoint("BOTTOMRIGHT", 2, -2)
  b.border:SetShown(not b.native)
  if type(b.icon) ~= "table" then b.icon = b:CreateTexture(nil, "ARTWORK") end
  b.icon:ClearAllPoints()
  b.icon:SetAllPoints()
  b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
  b.slotID, b.slotName, b.emptyTexture = slotID, slotName, emptyTexture
  -- Shift-click links the item in chat, Ctrl-click opens the dressing room (the game's modified clicks).
  if b.RegisterForClicks then b:RegisterForClicks("LeftButtonUp") end
  b:SetScript("OnClick", function(self)
    if self.itemLink and HandleModifiedItemClick then HandleModifiedItemClick(self.itemLink) end
  end)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    local shown
    if self.link then  -- another character's gear: the tooltip comes from the saved item link
      shown = pcall(GameTooltip.SetHyperlink, GameTooltip, self.link)
    elseif self.slotID then
      shown = GameTooltip:SetInventoryItem("player", self.slotID)
    end
    if not shown then GameTooltip:SetText(_G[slotName:upper()] or slotName, 1, 1, 1) end
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", GameTooltip_Hide)
  return b
end

-- Quality border: the game's own (item button) or the coloured square behind the icon.
local function setQuality(b, quality, link)
  if b.native then
    pcall(SetItemButtonQuality, b, quality, link)
    return
  end
  if quality == nil then
    b.border:SetColorTexture(0.15, 0.15, 0.15, 1)
    return
  end
  local r, g, bl = UI:QualityColor(quality)
  b.border:SetColorTexture(r or 0.3, g or 0.3, bl or 0.3, 1)
end

local function showEmpty(b)
  b.itemLink = nil
  UI:SetIcon(b.icon, b.emptyTexture)
  b.icon:SetTexCoord(0, 1, 0, 1)
  setQuality(b, nil)
end

-- Gear of a character that is not being played, from its snapshot (Modules/Gear.lua).
local function updateSlotFromSnapshot(b, entry)
  b.link = entry and entry.link
  if not entry then
    showEmpty(b)
    return
  end
  b.itemLink = entry.link
  local icon = entry.icon or (C_Item and C_Item.GetItemIconByID and entry.item
    and Util.SafeValue(nil, C_Item.GetItemIconByID, entry.item))
  UI:SetIcon(b.icon, icon)
  b.icon:SetTexCoord(0, 1, 0, 1)
  setQuality(b, entry.quality or 1, entry.link)
end

local function updateSlot(b)
  b.link = nil
  local texture = b.slotID and Util.SafeValue(nil, GetInventoryItemTexture, "player", b.slotID)
  if texture then
    b.itemLink = Util.SafeValue("string", GetInventoryItemLink, "player", b.slotID)
    b.icon:SetTexture(texture)
    b.icon:SetTexCoord(0, 1, 0, 1)
    setQuality(b, Util.SafeValue("number", GetInventoryItemQuality, "player", b.slotID) or 1, b.itemLink)
  else
    showEmpty(b)
  end
  return texture
end

-------------------------------------------------------------------------------
-- Race background behind the model (the dressing room art)
-------------------------------------------------------------------------------

-- Retail: one atlas per race. Classic: four pieces of a 320 x 384 picture.
local PIECES = { { 0, 0, 256, 256 }, { 256, 0, 64, 256 }, { 0, 256, 256, 128 }, { 256, 256, 64, 128 } }

local function setRaceBackground(self, raceFile)
  if raceFile == self.bgRace then return end
  self.bgRace = raceFile
  local box, w, h = self.modelBg, self.modelBgW, self.modelBgH
  for _, piece in ipairs(self.racePieces) do piece:Hide() end
  if not raceFile then return end
  local atlas = (DressUpTexturePath and Util.SafeValue("string", DressUpTexturePath, raceFile))
    or ("dressingroom-background-" .. raceFile)
  if UI:HasAtlas(atlas) then
    local t = self.racePieces[1]
    t:ClearAllPoints()
    t:SetAllPoints(box)
    t:SetAtlas(atlas)
    t:Show()
    return
  end
  for i, p in ipairs(PIECES) do
    local t = self.racePieces[i]
    if t:SetTexture("Interface\\DressUpFrame\\DressUpBackground-" .. raceFile .. i) == false then
      for _, piece in ipairs(self.racePieces) do piece:Hide() end
      return
    end
    t:SetTexCoord(0, 1, 0, 1)
    t:ClearAllPoints()
    t:SetPoint("TOPLEFT", box, "TOPLEFT", p[1] / 320 * w, -p[2] / 384 * h)
    t:SetSize(p[3] / 320 * w, p[4] / 384 * h)
    t:Show()
  end
end

-------------------------------------------------------------------------------
-- XP bar in the style of the game's experience bar: purple, blue while rested, the rested part lighter
-- with the rested marker at its end, 20 segments and a spark at the fill.
-------------------------------------------------------------------------------

local XP_NORMAL, XP_RESTED = { 0.58, 0, 0.55 }, { 0, 0.39, 0.88 }

local function xpBar(parent, width)
  local f = CreateFrame("Frame", nil, parent, "BackdropTemplate")
  f:SetSize(width, 18)
  UI:Backdrop(f, { bgFile = UI.WHITE, edgeFile = UI.WHITE, edgeSize = 1 }, { 0, 0, 0, 0.65 }, { 0.55, 0.45, 0.25, 0.9 })
  local bar = CreateFrame("StatusBar", nil, f)
  bar:SetPoint("TOPLEFT", 2, -2)
  bar:SetPoint("BOTTOMRIGHT", -2, 2)
  bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
  bar:SetMinMaxValues(0, 1)
  f.bar = bar
  f.rested = bar:CreateTexture(nil, "BORDER")
  f.rested:SetTexture("Interface\\TargetingFrame\\UI-StatusBar")
  f.rested:SetPoint("TOPLEFT")
  f.rested:SetPoint("BOTTOMLEFT")
  local inner = width - 4
  for i = 1, 19 do
    local tick = bar:CreateTexture(nil, "OVERLAY", nil, 1)
    tick:SetColorTexture(0, 0, 0, 0.45)
    tick:SetSize(1, 14)
    tick:SetPoint("LEFT", bar, "LEFT", math.floor(inner * i / 20), 0)
  end
  f.spark = bar:CreateTexture(nil, "OVERLAY", nil, 2)
  f.spark:SetTexture("Interface\\CastingBar\\UI-CastingBar-Spark")
  f.spark:SetBlendMode("ADD")
  f.spark:SetSize(16, 30)
  f.marker = f:CreateTexture(nil, "OVERLAY")
  if f.marker:SetTexture("Interface\\MainMenuBar\\UI-ExhaustionTickNormal") == false then f.marker:SetTexture(nil) end
  f.marker:SetSize(24, 24)
  f.text = bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  f.text:SetPoint("CENTER", 0, 1)
  f.inner, f.fill = inner, false

  local function place(self, fill)
    self.bar:SetValue(fill)
    self.spark:ClearAllPoints()
    self.spark:SetPoint("CENTER", self.bar, "LEFT", self.inner * fill, 0)
    self.spark:SetShown(fill > 0.005 and fill < 0.995)
  end

  -- fill and restedEnd are shares of the level (0..1); the fill glides to a new value.
  function f:SetXP(fill, restedEnd)
    local color = restedEnd > fill and XP_RESTED or XP_NORMAL
    self.bar:SetStatusBarColor(color[1], color[2], color[3])
    self.rested:SetVertexColor(color[1], color[2], color[3], 0.4)
    self.rested:SetWidth(math.max(1, self.inner * restedEnd))
    self.rested:SetShown(restedEnd > fill)
    self.marker:ClearAllPoints()
    self.marker:SetPoint("CENTER", self.bar, "LEFT", self.inner * restedEnd, 6)
    self.marker:SetShown(restedEnd > fill)
    local from = self.fill
    self.fill = fill
    if from and from < fill and fill - from < 0.5 then
      UI:Tween(self, 0.6, 0, function(p) place(self, from + (fill - from) * p) end)
    else
      UI:StopTween(self)
      place(self, fill)
    end
  end
  return f
end

-------------------------------------------------------------------------------
-- Page
-------------------------------------------------------------------------------

function page:Create(c)
  self:CreateHeader(c)
  self:CreateStatGroups(c)
  self:CreateGearPanel(c)
  self:CreateGraph(c)

  -- Other characters (alts, friends): their saved gear, but no live model, XP, gold or graph.
  self.otherNote = UI:Label(c, "VIEW_LIVE_ONLY", "GameFontDisable")
  self.otherNote:SetPoint("LEFT", self.modelBg, "LEFT", 12, 0)
  self.otherNote:SetPoint("RIGHT", self.modelBg, "RIGHT", -12, 0)
  self.otherNote:SetJustifyH("CENTER")
end

-- Name, level line, XP bar and gold (top left).
function page:CreateHeader(c)
  self.name = c:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
  self.name:SetPoint("TOPLEFT", 16, -14)
  self.details = c:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  self.details:SetPoint("TOPLEFT", self.name, "BOTTOMLEFT", 0, -4)

  self.xp = xpBar(c, 360)
  self.xp:SetPoint("TOPLEFT", self.details, "BOTTOMLEFT", 0, -10)
  self.xp:EnableMouse(true)
  UI:Tooltip(self.xp, "XP_BAR", function() return self.xpTip end)
  self.money = c:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  self.money:SetPoint("TOPLEFT", self.xp, "BOTTOMLEFT", 0, -8)
end

-- The stat groups under the header: heading, description and a grid of tiles each.
function page:CreateStatGroups(c)
  local anchor, y = self.money, -16
  self.tiles = {}
  for _, group in ipairs(FC.statGroups) do
    local defs = FC:GetStatsInGroup(group.key)
    if #defs > 0 then
      local header = UI:Label(c, group.labelKey, "GameFontNormal")
      header:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, y)
      local desc = UI:Label(c, group.descKey, "GameFontDisableSmall")
      desc:SetPoint("TOPLEFT", header, "BOTTOMLEFT", 0, -2)
      local rows = math.ceil(#defs / TILE_COLUMNS)
      for i, def in ipairs(defs) do
        local tile = statTile(c, def)
        local col, row = (i - 1) % TILE_COLUMNS, math.floor((i - 1) / TILE_COLUMNS)
        tile:SetPoint("TOPLEFT", desc, "BOTTOMLEFT", col * (TILE_W + 8), -6 - row * (TILE_H + 4))
        self.tiles[#self.tiles + 1] = tile
      end
      anchor, y = desc, -6 - rows * (TILE_H + 4) - 10
    end
  end
end

-- Character model with the gear slots around it and the race background (right side).
function page:CreateGearPanel(c)
  local panel = CreateFrame("Frame", nil, c)
  self.gearPanel = panel
  panel:SetPoint("TOPRIGHT", -16, -16)
  panel:SetSize(2 * SLOT_SIZE + MODEL_W + 2 * 10, 8 * (SLOT_SIZE + SLOT_GAP) + SLOT_SIZE + 16)
  -- As in the Classic character window: 8 slots on the left, 8 on the right, the weapons at the bottom.
  self.slots = {}
  for i, name in ipairs(FC:GetModule("Gear").SLOTS) do
    local b = gearSlot(panel, name)
    if i <= 8 then
      b:SetPoint("TOPLEFT", 0, -(i - 1) * (SLOT_SIZE + SLOT_GAP))
    elseif i <= 16 then
      b:SetPoint("TOPRIGHT", 0, -(i - 9) * (SLOT_SIZE + SLOT_GAP))
    else
      b:SetPoint("BOTTOM", panel, "BOTTOM", (i - 18) * (SLOT_SIZE + 10), 0)
    end
    self.slots[i] = b
  end

  local modelBg = panel:CreateTexture(nil, "BACKGROUND")
  self.modelBg = modelBg
  modelBg:SetPoint("TOPLEFT", SLOT_SIZE + 10, 0)
  modelBg:SetPoint("BOTTOMRIGHT", -(SLOT_SIZE + 10), SLOT_SIZE + 16)
  modelBg:SetColorTexture(0, 0, 0, 0.35)
  self.modelBgW, self.modelBgH = MODEL_W, 8 * (SLOT_SIZE + SLOT_GAP)
  local frameLine = panel:CreateTexture(nil, "BACKGROUND", nil, -1)
  frameLine:SetPoint("TOPLEFT", modelBg, -1, 1)
  frameLine:SetPoint("BOTTOMRIGHT", modelBg, 1, -1)
  frameLine:SetColorTexture(0.6, 0.5, 0.3, 0.8)
  self.racePieces = {}
  for i = 1, #PIECES do self.racePieces[i] = panel:CreateTexture(nil, "BACKGROUND", nil, 1) end
  -- Soft dark edges, so the model stands out from the picture.
  local shade = panel:CreateTexture(nil, "BACKGROUND", nil, 2)
  shade:SetPoint("BOTTOMLEFT", modelBg)
  shade:SetPoint("BOTTOMRIGHT", modelBg)
  shade:SetHeight(70)
  UI:Gradient(shade, "VERTICAL", 0, 0, 0, 0.55, 0, 0, 0, 0)
  local ok, model = pcall(CreateFrame, "PlayerModel", nil, panel)
  if ok and model then
    model:SetPoint("TOPLEFT", modelBg)
    model:SetPoint("BOTTOMRIGHT", modelBg)
    model:EnableMouse(true)
    -- Drag to rotate.
    model:SetScript("OnMouseDown", function(m) m.dragX, m.dragFacing = GetCursorPosition(), m:GetFacing() or 0 end)
    model:SetScript("OnMouseUp", function(m) m.dragX = nil end)
    model:SetScript("OnUpdate", function(m)
      if m.dragX then m:SetFacing(m.dragFacing + (GetCursorPosition() - m.dragX) * 0.015) end
    end)
    model:SetScript("OnShow", function(m) m:SetUnit("player") end)
    UI:Tooltip(model, "MODEL_TITLE", "MODEL_TIP")
    self.model = model
  end
end

-- Graph under the character, switchable with the arrows (graphs come from FC:RegisterGraph).
function page:CreateGraph(c)
  local panel = self.gearPanel
  local prev = UI:ArrowButton(c, "Prev", function() self:StepGraph(-1) end)
  prev:SetPoint("TOPLEFT", panel, "BOTTOMLEFT", 0, -12)
  local nextB = UI:ArrowButton(c, "Next", function() self:StepGraph(1) end)
  nextB:SetPoint("TOPRIGHT", panel, "BOTTOMRIGHT", 0, -12)
  self.graphTitle = c:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  self.graphTitle:SetPoint("LEFT", prev, "RIGHT", 4, 6)
  self.graphTitle:SetPoint("RIGHT", nextB, "LEFT", -4, 6)
  self.graphSubtitle = c:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.graphSubtitle:SetPoint("TOP", self.graphTitle, "BOTTOM", 0, -2)
  self.graph = UI:LineGraph(c, panel:GetWidth(), 140)
  self.graph.frame:SetPoint("TOPLEFT", prev, "BOTTOMLEFT", 0, -8)
  self.liveParts = { prev, nextB, self.graphTitle, self.graphSubtitle, self.graph.frame }
  if self.model then self.liveParts[#self.liveParts + 1] = self.model end
end

local GRAPH_SECONDS = 2 * 3600   -- the graph shows the last 2 hours of played time
local TICK_SECONDS = 30 * 60

function page:StepGraph(step)
  local defs = FC.graphDefs
  if #defs == 0 then return end
  local index = 1
  for i, def in ipairs(defs) do if def.key == FC.db.settings.overviewGraph then index = i end end
  index = (index - 1 + step) % #defs + 1
  FC.db.settings.overviewGraph = defs[index].key
  self.graphVersion = nil
  self:RefreshGraph()
end

-- Recomputed only when new data arrived, the graph or the language changed.
function page:RefreshGraph()
  local defs = FC.graphDefs
  if #defs == 0 then return end
  local def = defs[1]
  for _, d in ipairs(defs) do if d.key == FC.db.settings.overviewGraph then def = d end end
  -- The window moves with the clock while playing: recompute at most once per minute.
  local version = table.concat({ def.key, FC:GetLanguage(), FC.Storage:GetStream("metrics").nextSeq, FC:ViewKey(),
    FC.Storage:GetStream("events").nextSeq, FC.Storage:GetStream("sessions").nextSeq, date("%H%M") }, ":")
  if version == self.graphVersion then return end
  self.graphVersion = version

  local Metrics = FC.Metrics
  local spans, length = Metrics:PlayedWindow(GRAPH_SECONDS)
  local points = spans[1] and Metrics:WindowPoints(def.series(spans[1].from), spans, def) or {}
  local format = def.format or Util.FormatNumber

  -- Time labels: start, every 30 minutes of play, end. Faint lines where sessions were joined.
  local ticks, breaks = {}, {}
  if length > 0 then
    ticks[1] = { x = 0, label = date("%H:%M", spans[1].from) }
    for x = TICK_SECONDS, length - TICK_SECONDS / 3, TICK_SECONDS do
      ticks[#ticks + 1] = { x = x, label = date("%H:%M", Metrics.TimeAt(spans, x)) }
    end
    ticks[#ticks + 1] = { x = length, label = date("%H:%M", spans[#spans].to) }
    for i = 2, #spans do breaks[#breaks + 1] = spans[i].x end
  end

  self.graphTitle:SetText(L[def.labelKey])
  local subtitle = string.format(L.GRAPH_SUBTITLE, Util.FormatDuration(length))
  if #points >= 2 then
    local change = points[#points].value - points[1].value
    subtitle = subtitle .. UI.SEP .. (change > 0 and "+" or "") .. format(change)
  end
  self.graphSubtitle:SetText(subtitle)
  self.graph:SetData(points, length, { key = def.key .. ":" .. tostring(FC:ViewKey()),
    color = def.color, format = format, emptyText = L.GRAPH_EMPTY,
    ticks = ticks, breaks = breaks, tooltip = function(p)
      return date(L.GRAPH_POINT_TIME, p.time), format(p.value)
    end })
end

function page:RefreshTiles()
  for _, tile in ipairs(self.tiles) do
    local value = FC:GetStatValue(tile.def)
    tile.value:SetText(value ~= nil and FC:FormatStat(tile.def, value) or "-")
  end
end

function page:Refresh()
  local played = FC:IsViewingPlayed()
  local info = FC:ViewChar().info
  self.name:SetText(UI:ClassColored(UI:FullName(info), info.classFile))
  self.details:SetText(string.format(L.CHAR_DETAILS, info.level or "?", info.raceName or "", info.className or "")
    .. UI.SEP .. (info.realm or ""))

  setRaceBackground(self, info.raceFile)
  for _, part in ipairs(self.liveParts) do part:SetShown(played) end
  self.otherNote:SetShown(not played)
  if not played then
    local owner = FC:ViewOwner()
    if owner then self.details:SetText(self.details:GetText() .. UI.SEP .. string.format(L.VIEW_FRIEND_OF, owner)) end
    self.xp:Hide()
    self.money:SetText(info.lastSeenAt and string.format(L.VIEW_LAST_SEEN, Util.FormatTime(info.lastSeenAt)) or "")
    local gear = FC:GetModule("Gear"):BySlot(FC:ViewChar())
    for _, slot in ipairs(self.slots) do updateSlotFromSnapshot(slot, slot.slotID and gear[slot.slotID]) end
    self.gearSignature = nil -- the played character's model is refreshed when shown again
    self:RefreshTiles()
    return
  end

  -- XP bar with rested XP
  local xp, max = Util.SafeValue("number", UnitXP, "player"), Util.SafeValue("number", UnitXPMax, "player")
  if xp and max and max > 0 then
    local rested = Util.SafeValue("number", GetXPExhaustion) or 0
    self.xp:SetXP(xp / max, math.min(1, (xp + rested) / max))
    self.xp.text:SetText(string.format("%s / %s  (%d %%)", Util.FormatNumber(xp), Util.FormatNumber(max),
      math.floor(xp / max * 100)))
    self.xpTip = string.format(L.XP_TIP, Util.FormatNumber(max - xp), Util.FormatNumber(rested))
    self.xp:Show()
  else
    self.xp:Hide()
  end
  local money = Util.SafeValue("number", GetMoney)
  self.money:SetText(money and GetCoinTextureString and GetCoinTextureString(money) or "")
  self:RefreshTiles()

  -- Gear; the model is refreshed when the equipment changed.
  local signature = {}
  for _, slot in ipairs(self.slots) do signature[#signature + 1] = tostring(updateSlot(slot)) end
  signature = table.concat(signature, ",")
  if self.model and signature ~= self.gearSignature then
    self.gearSignature = signature
    self.model:SetUnit("player")
  end

  self:RefreshGraph()
end

UI:RegisterPage(page)
