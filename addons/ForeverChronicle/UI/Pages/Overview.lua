-- Forever Chronicle - Overview page
-- Left: full name, level line, XP bar and gold, then the stat groups (heading, short description,
-- tiles with icon, name and value). Right: the character model with the equipped gear around it,
-- like the Classic character window. Stats and groups come from the registry (FC:RegisterStat/StatGroup).

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "overview", labelKey = "TAB_OVERVIEW", icon = "portrait", order = 10 }
local TILE_W, TILE_H, TILE_COLUMNS = 178, 40, 2
local SLOT_SIZE, SLOT_GAP = 37, 4

-- Gear slots as in the Classic character window: left column, right column, weapons at the bottom.
local LEFT_SLOTS = { "HeadSlot", "NeckSlot", "ShoulderSlot", "BackSlot", "ChestSlot", "ShirtSlot", "TabardSlot", "WristSlot" }
local RIGHT_SLOTS = { "HandsSlot", "WaistSlot", "LegsSlot", "FeetSlot", "Finger0Slot", "Finger1Slot", "Trinket0Slot", "Trinket1Slot" }
local WEAPON_SLOTS = { "MainHandSlot", "SecondaryHandSlot", "RangedSlot" }

-------------------------------------------------------------------------------
-- Stat tiles: icon, name (gold, small) and value (white)
-------------------------------------------------------------------------------

local function statTile(parent, def)
  local t = CreateFrame("Frame", nil, parent)
  t:SetSize(TILE_W, TILE_H)
  local bg = t:CreateTexture(nil, "BACKGROUND")
  bg:SetSize(34, 34)
  bg:SetPoint("LEFT")
  bg:SetColorTexture(0, 0, 0, 0.7)
  t.icon = t:CreateTexture(nil, "ARTWORK")
  t.icon:SetPoint("TOPLEFT", bg, 2, -2)
  t.icon:SetPoint("BOTTOMRIGHT", bg, -2, 2)
  t.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  UI:SetIcon(t.icon, def.icon)
  t.name = UI:Label(t, def.labelKey, "GameFontNormalSmall")
  t.name:SetPoint("TOPLEFT", bg, "TOPRIGHT", 8, -2)
  t.name:SetPoint("RIGHT", t, "RIGHT")
  t.name:SetWordWrap(false)
  t.value = t:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  t.value:SetPoint("BOTTOMLEFT", bg, "BOTTOMRIGHT", 8, 2)
  t.value:SetPoint("RIGHT", t, "RIGHT")
  t.value:SetJustifyH("LEFT")
  t.def = def
  return t
end

-------------------------------------------------------------------------------
-- Gear slots
-------------------------------------------------------------------------------

local function gearSlot(parent, slotName)
  local slotID, emptyTexture = Util.SafeValues(GetInventorySlotInfo, slotName)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(SLOT_SIZE, SLOT_SIZE)
  b.border = b:CreateTexture(nil, "BACKGROUND")
  b.border:SetPoint("TOPLEFT", -2, 2)
  b.border:SetPoint("BOTTOMRIGHT", 2, -2)
  b.icon = b:CreateTexture(nil, "ARTWORK")
  b.icon:SetAllPoints()
  b:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
  b.slotID, b.slotName, b.emptyTexture = slotID, slotName, emptyTexture
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

local function showEmpty(b)
  UI:SetIcon(b.icon, b.emptyTexture)
  b.icon:SetTexCoord(0, 1, 0, 1)
  b.border:SetColorTexture(0.15, 0.15, 0.15, 1)
end

-- Gear of a character that is not being played, from its snapshot (Modules/Gear.lua).
local function updateSlotFromSnapshot(b, entry)
  b.link = entry and entry.link
  if not entry then
    showEmpty(b)
    return
  end
  local icon = entry.icon or (C_Item and C_Item.GetItemIconByID and entry.item
    and Util.SafeValue(nil, C_Item.GetItemIconByID, entry.item))
  UI:SetIcon(b.icon, icon)
  b.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  local r, g, bl = UI:QualityColor(entry.quality)
  b.border:SetColorTexture(r or 0.3, g or 0.3, bl or 0.3, 1)
end

local function updateSlot(b)
  b.link = nil
  local texture = b.slotID and Util.SafeValue(nil, GetInventoryItemTexture, "player", b.slotID)
  if texture then
    b.icon:SetTexture(texture)
    b.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
    local r, g, bl = UI:QualityColor(Util.SafeValue("number", GetInventoryItemQuality, "player", b.slotID))
    b.border:SetColorTexture(r or 0.3, g or 0.3, bl or 0.3, 1)
  else
    showEmpty(b)
  end
  return texture
end

-------------------------------------------------------------------------------
-- Page
-------------------------------------------------------------------------------

function page:Create(c)
  -- Character header
  self.name = c:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
  self.name:SetPoint("TOPLEFT", 16, -14)
  self.details = c:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  self.details:SetPoint("TOPLEFT", self.name, "BOTTOMLEFT", 0, -4)

  self.xp = UI:Bar(c, 360)
  self.xp:SetPoint("TOPLEFT", self.details, "BOTTOMLEFT", 0, -10)
  self.xp:SetStatusBarColor(0.58, 0, 0.55)
  self.rested = self.xp:CreateTexture(nil, "BORDER")
  self.rested:SetColorTexture(0.0, 0.39, 0.88, 0.6)
  self.rested:SetPoint("TOPLEFT", self.xp, "TOPLEFT")
  self.rested:SetPoint("BOTTOMLEFT", self.xp, "BOTTOMLEFT")
  self.xp:EnableMouse(true)
  UI:Tooltip(self.xp, "XP_BAR", function() return self.xpTip end)
  self.money = c:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  self.money:SetPoint("TOPLEFT", self.xp, "BOTTOMLEFT", 0, -8)

  -- Stat groups
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

  -- Character model with gear (right side)
  local panel = CreateFrame("Frame", nil, c)
  self.gearPanel = panel
  panel:SetPoint("TOPRIGHT", -16, -16)
  panel:SetSize(2 * SLOT_SIZE + 260 + 2 * 10, 8 * (SLOT_SIZE + SLOT_GAP) + SLOT_SIZE + 16)
  self.slots = {}
  for i, name in ipairs(LEFT_SLOTS) do
    local b = gearSlot(panel, name)
    b:SetPoint("TOPLEFT", 0, -(i - 1) * (SLOT_SIZE + SLOT_GAP))
    self.slots[#self.slots + 1] = b
  end
  for i, name in ipairs(RIGHT_SLOTS) do
    local b = gearSlot(panel, name)
    b:SetPoint("TOPRIGHT", 0, -(i - 1) * (SLOT_SIZE + SLOT_GAP))
    self.slots[#self.slots + 1] = b
  end
  for i, name in ipairs(WEAPON_SLOTS) do
    local b = gearSlot(panel, name)
    b:SetPoint("BOTTOM", panel, "BOTTOM", (i - 2) * (SLOT_SIZE + 10), 0)
    self.slots[#self.slots + 1] = b
  end

  local modelBg = panel:CreateTexture(nil, "BACKGROUND")
  self.modelBg = modelBg
  modelBg:SetPoint("TOPLEFT", SLOT_SIZE + 10, 0)
  modelBg:SetPoint("BOTTOMRIGHT", -(SLOT_SIZE + 10), SLOT_SIZE + 16)
  modelBg:SetColorTexture(0, 0, 0, 0.35)
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

  -- Graph under the character, switchable with the arrows (graphs come from FC:RegisterGraph).
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

  -- Other characters (alts, friends): their saved gear, but no live model, XP, gold or graph.
  self.otherNote = UI:Label(c, "VIEW_LIVE_ONLY", "GameFontDisable")
  self.otherNote:SetPoint("LEFT", self.modelBg, "LEFT", 12, 0)
  self.otherNote:SetPoint("RIGHT", self.modelBg, "RIGHT", -12, 0)
  self.otherNote:SetJustifyH("CENTER")
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
  local format = def.format or function(v) return Util.FormatNumber(v) end

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
    subtitle = subtitle .. "  \194\183  " .. (change > 0 and "+" or "") .. format(change)
  end
  self.graphSubtitle:SetText(subtitle)
  self.graph:SetData(points, length, { color = def.color, format = format, emptyText = L.GRAPH_EMPTY,
    ticks = ticks, breaks = breaks, tooltip = function(p)
      return date(L.GRAPH_POINT_TIME, p.time), format(p.value)
    end })
end

function page:Refresh()
  local played = FC:IsViewingPlayed()
  local info = FC:ViewChar().info
  local fullName = info.name or "?"
  if info.nameSuffix and info.nameSuffix ~= "" then fullName = fullName .. " " .. info.nameSuffix end
  self.name:SetText(UI:ClassColored(fullName, info.classFile))
  self.details:SetText(string.format(L.CHAR_DETAILS, info.level or "?", info.raceName or "", info.className or "")
    .. "  \194\183  " .. (info.realm or ""))

  for _, part in ipairs(self.liveParts) do part:SetShown(played) end
  self.otherNote:SetShown(not played)
  if not played then
    local owner = FC:ViewOwner()
    if owner then self.details:SetText(self.details:GetText() .. "  \194\183  " .. string.format(L.VIEW_FRIEND_OF, owner)) end
    self.xp:Hide()
    self.money:SetText(info.lastSeenAt and string.format(L.VIEW_LAST_SEEN, Util.FormatTime(info.lastSeenAt)) or "")
    local gear = FC:GetModule("Gear"):BySlot(FC:ViewChar())
    for _, slot in ipairs(self.slots) do updateSlotFromSnapshot(slot, slot.slotID and gear[slot.slotID]) end
    self.gearSignature = nil -- the played character's model is refreshed when shown again
    for _, tile in ipairs(self.tiles) do
      local value = FC:GetStatValue(tile.def)
      tile.value:SetText(value ~= nil and FC:FormatStat(tile.def, value) or "-")
    end
    return
  end

  -- XP bar with rested XP
  local xp, max = Util.SafeValue("number", UnitXP, "player"), Util.SafeValue("number", UnitXPMax, "player")
  if xp and max and max > 0 then
    local rested = Util.SafeValue("number", GetXPExhaustion) or 0
    self.xp:SetValue(xp / max)
    self.xp.text:SetText(string.format("%s / %s", Util.FormatNumber(xp), Util.FormatNumber(max)))
    local restedEnd = math.min(1, (xp + rested) / max)
    self.rested:SetWidth(math.max(1, self.xp:GetWidth() * restedEnd))
    self.rested:SetShown(rested > 0)
    self.xpTip = string.format(L.XP_TIP, Util.FormatNumber(max - xp), Util.FormatNumber(rested))
    self.xp:Show()
  else
    self.xp:Hide()
  end
  local money = Util.SafeValue("number", GetMoney)
  self.money:SetText(money and GetCoinTextureString and GetCoinTextureString(money) or "")

  for _, tile in ipairs(self.tiles) do
    local value = FC:GetStatValue(tile.def)
    tile.value:SetText(value ~= nil and FC:FormatStat(tile.def, value) or "-")
  end

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
