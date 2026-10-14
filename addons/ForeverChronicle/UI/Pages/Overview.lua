-- Forever Chronicle - Overview page
-- Character header, current session, statistics (from the stat registry) and storage usage as icon tiles.
-- Names and explanations are in the tooltips.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "overview", labelKey = "TAB_OVERVIEW", icon = "portrait", order = 10 }
local TILE_W, TILE_GAP, COLUMNS = 196, 8, 3
local I = "Interface\\Icons\\"

local function divider(c, anchor, y)
  local line = c:CreateTexture(nil, "ARTWORK")
  line:SetColorTexture(1, 0.82, 0, 0.2)
  line:SetHeight(1)
  line:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, y)
  line:SetPoint("RIGHT", c, "RIGHT", -14, 0)
  return line
end

-- Places tiles in a grid below `anchor`; returns the last row's first tile for further anchoring.
local function grid(tiles, anchor, y)
  for i, tile in ipairs(tiles) do
    local col = (i - 1) % COLUMNS
    local row = math.floor((i - 1) / COLUMNS)
    tile:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", col * (TILE_W + TILE_GAP), y - row * 46)
  end
end

function page:Create(c)
  -- Character
  self.name = c:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
  self.name:SetPoint("TOPLEFT", 16, -14)
  self.details = c:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  self.details:SetPoint("TOPLEFT", self.name, "BOTTOMLEFT", 0, -4)

  -- Current session
  local sessionLine = divider(c, self.details, -12)
  self.sessionTiles = {
    UI:Tile(c, I .. "INV_Misc_PocketWatch_03", "FIELD_SESSION_TIME", TILE_W),
    UI:Tile(c, I .. "Spell_Nature_Reincarnation", "FIELD_RELOADS", TILE_W),
    UI:Tile(c, I .. "INV_Misc_Rune_01", "FIELD_PLAYED_LEVEL", TILE_W),
  }
  grid(self.sessionTiles, sessionLine, -10)

  -- Statistics since tracking began
  local statsLine = divider(c, self.sessionTiles[1], -10)
  self.statTiles = {}
  for i, def in ipairs(FC.statDefs) do
    local tile = UI:Tile(c, def.icon, def.labelKey, TILE_W)
    tile.def = def
    self.statTiles[i] = tile
  end
  grid(self.statTiles, statsLine, -10)
  local lastRowFirst = self.statTiles[math.floor((#self.statTiles - 1) / COLUMNS) * COLUMNS + 1]

  -- Storage: icon + bar per stream, two columns
  self.storageLine = divider(c, lastRowFirst, -10)
  self.bars = {}
end

local function storageRow(self, c, i, usage)
  local row = self.bars[i]
  if row then return row end
  row = CreateFrame("Frame", nil, c)
  row:SetSize(296, 24)
  local col, line = (i - 1) % 2, math.floor((i - 1) / 2)
  row:SetPoint("TOPLEFT", self.storageLine, "BOTTOMLEFT", col * 304, -10 - line * 30)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(22, 22)
  row.icon:SetPoint("LEFT")
  row.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  UI:SetIcon(row.icon, usage.icon)
  row.bar = UI:Bar(row, 262)
  row.bar:SetPoint("LEFT", row.icon, "RIGHT", 8, 0)
  row:EnableMouse(true)
  UI:Tooltip(row, function(r) return L["STREAM_" .. r.name:upper()] end,
    function(r) return string.format(L.STORAGE_TIP, r.count, r.cap) end)
  self.bars[i] = row
  return row
end

function page:Refresh()
  local c = self.container
  local info = FC.char.info
  self.name:SetText(UI:ClassColored(info.name or "?", info.classFile))
  self.details:SetText(string.format(L.CHAR_DETAILS, info.level or "?", info.raceName or "", info.className or "")
    .. "  \194\183  " .. (info.realm or ""))

  local session = FC:GetModule("Session"):GetCurrent()
  self.sessionTiles[1]:SetValue(FC.sessionStartedAt and Util.FormatDuration(time() - FC.sessionStartedAt) or "-")
  self.sessionTiles[2]:SetValue(session and tostring(session.reloads or 0) or "-")
  self.sessionTiles[3]:SetValue(session and session.playedLevel and Util.FormatDuration(session.playedLevel) or "-")

  for _, tile in ipairs(self.statTiles) do
    local value = FC:GetStatValue(tile.def)
    tile:SetValue(value ~= nil and FC:FormatStat(tile.def, value) or "-")
  end

  for i, u in ipairs(FC.Storage:GetUsage()) do
    local row = storageRow(self, c, i, u)
    row.name, row.count, row.cap = u.name, u.count, u.cap
    local ratio = u.cap > 0 and u.count / u.cap or 0
    row.bar:SetValue(ratio)
    if ratio >= 0.8 then row.bar:SetStatusBarColor(1, 0.5, 0) else row.bar:SetStatusBarColor(0.2, 0.6, 0.2) end
    row.bar.text:SetText(string.format("%d%%", math.floor(ratio * 100)))
  end
end

UI:RegisterPage(page)
