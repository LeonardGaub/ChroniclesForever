-- Forever Chronicle - map canvas
-- Draws a map with the client's own map art (the same tiles and explored-area overlays as the world map),
-- route lines, event icons and a position marker. If the client cannot provide the art, a plain
-- parchment-coloured area with the map name is shown instead.

local ADDON, FC = ...
local Util = FC.Util
local UI = FC.UI

local Canvas = {}
Canvas.__index = Canvas
UI.MapCanvas = Canvas

local TILE = 256
local MIN_LINE_PIXELS = 3   -- route points closer than this (on screen) are merged into one line
local MAX_LINES = 4000
local ROUTE_COLOR = { 1, 0.82, 0, 0.95 }
local TAXI_COLOR = { 0.41, 0.8, 0.94, 0.9 }

function Canvas.New(parent, width, height)
  local self = setmetatable({}, Canvas)
  local f = CreateFrame("Frame", nil, parent)
  f:SetSize(width, height)
  f:SetClipsChildren(true)
  self.frame, self.width, self.height = f, width, height

  local bg = f:CreateTexture(nil, "BACKGROUND", nil, -8)
  bg:SetAllPoints()
  bg:SetColorTexture(0.32, 0.25, 0.16, 1)
  self.background = bg

  -- Map art is laid out in map units (e.g. 1002 x 668) on a scaled child frame.
  self.art = CreateFrame("Frame", nil, f)
  self.art:SetPoint("TOPLEFT")
  self.tiles, self.overlays = {}, {}

  self.name = f:CreateFontString(nil, "ARTWORK", "GameFontDisableHuge")
  self.name:SetPoint("CENTER")

  self.lines, self.dots, self.pins = {}, {}, {}
  self.lineLayer = CreateFrame("Frame", nil, f)
  self.lineLayer:SetAllPoints()
  self.lineLayer:SetFrameLevel(f:GetFrameLevel() + 2)
  self.pinLayer = CreateFrame("Frame", nil, f)
  self.pinLayer:SetAllPoints()
  self.pinLayer:SetFrameLevel(f:GetFrameLevel() + 4)

  self.marker = self.pinLayer:CreateTexture(nil, "OVERLAY", nil, 7)
  self.marker:SetSize(18, 18)
  self.marker:SetTexture("Interface\\Common\\Indicator-Yellow")
  self.marker:Hide()
  return self
end

-------------------------------------------------------------------------------
-- Map art
-------------------------------------------------------------------------------

local function hideAll(list) for _, r in ipairs(list) do r:Hide() end end

-- Returns true if the client provided art for this map.
function Canvas:SetMap(mapID, fallbackName)
  self.mapID = mapID
  hideAll(self.tiles)
  hideAll(self.overlays)
  local layers = C_Map and C_Map.GetMapArtLayers and Util.SafeValue("table", C_Map.GetMapArtLayers, mapID)
  local layer = layers and layers[1]
  local textures = layer and C_Map.GetMapArtLayerTextures
    and Util.SafeValue("table", C_Map.GetMapArtLayerTextures, mapID, 1)
  local info = Util.SafeValue("table", C_Map.GetMapInfo, mapID)
  self.name:SetText(info and Util.Plain(info.name) or fallbackName or "")

  if not (layer and textures and #textures > 0) then
    self.name:Show()
    return false
  end
  self.name:Hide()
  local w, h = layer.layerWidth, layer.layerHeight
  self.art:SetSize(w, h)
  self.art:SetScale(self.width / w)
  local cols = math.ceil(w / layer.tileWidth)
  local rows = math.ceil(h / layer.tileHeight)
  for row = 1, rows do
    for col = 1, cols do
      local index = (row - 1) * cols + col
      local tex = self.tiles[index] or self.art:CreateTexture(nil, "BACKGROUND", nil, -7)
      self.tiles[index] = tex
      tex:SetSize(layer.tileWidth, layer.tileHeight)
      tex:ClearAllPoints()
      tex:SetPoint("TOPLEFT", (col - 1) * layer.tileWidth, -(row - 1) * layer.tileHeight)
      tex:SetTexture(textures[index], nil, nil, "TRILINEAR")
      tex:Show()
    end
  end
  self:DrawExplored(mapID)
  return true
end

-- Explored-area overlays, laid out like the world map does it.
function Canvas:DrawExplored(mapID)
  if not (C_MapExplorationInfo and C_MapExplorationInfo.GetExploredMapTextures) then return end
  local explored = Util.SafeValue("table", C_MapExplorationInfo.GetExploredMapTextures, mapID)
  if not explored then return end
  local n = 0
  for _, info in ipairs(explored) do
    if not info.isShownByMouseOver then
      local wide = math.ceil(info.textureWidth / TILE)
      local tall = math.ceil(info.textureHeight / TILE)
      for j = 1, tall do
        local pixelH, fileH = TILE, TILE
        if j == tall then
          pixelH = info.textureHeight % TILE
          if pixelH == 0 then pixelH = TILE end
          fileH = 16
          while fileH < pixelH do fileH = fileH * 2 end
        end
        for k = 1, wide do
          local pixelW, fileW = TILE, TILE
          if k == wide then
            pixelW = info.textureWidth % TILE
            if pixelW == 0 then pixelW = TILE end
            fileW = 16
            while fileW < pixelW do fileW = fileW * 2 end
          end
          n = n + 1
          local tex = self.overlays[n] or self.art:CreateTexture(nil, "BACKGROUND", nil, -6)
          self.overlays[n] = tex
          tex:SetSize(pixelW, pixelH)
          tex:SetTexCoord(0, pixelW / fileW, 0, pixelH / fileH)
          tex:ClearAllPoints()
          tex:SetPoint("TOPLEFT", info.offsetX + TILE * (k - 1), -(info.offsetY + TILE * (j - 1)))
          tex:SetTexture(info.fileDataIDs[(j - 1) * wide + k], nil, nil, "TRILINEAR")
          tex:Show()
        end
      end
    end
  end
end

-------------------------------------------------------------------------------
-- Route
-------------------------------------------------------------------------------

function Canvas:ToPixels(x, y)
  return x * self.width, y * self.height
end

local function lineRegion(self, i)
  local line = self.lines[i]
  if not line then
    line = self.lineLayer:CreateLine(nil, "ARTWORK")
    line:SetThickness(2.5)
    self.lines[i] = line
  end
  return line
end

local function dotRegion(self, i)
  local dot = self.dots[i]
  if not dot then
    dot = self.lineLayer:CreateTexture(nil, "ARTWORK", nil, 1)
    dot:SetSize(5, 5)
    dot:SetTexture("Interface\\Common\\Indicator-Gray")
    self.dots[i] = dot
  end
  return dot
end

-- segments: from FC.Route.Segments. Ends of every segment get a small grey dot (recorded data starts or stops).
function Canvas:DrawRoute(segments)
  local lineCount, dotCount = 0, 0
  local canLine = self.lineLayer.CreateLine ~= nil
  for _, seg in ipairs(segments) do
    local color = seg.taxi and TAXI_COLOR or ROUTE_COLOR
    local lastX, lastY
    for i, pt in ipairs(seg.points) do
      local px, py = self:ToPixels(pt[1], pt[2])
      local isLast = i == #seg.points
      if not lastX then
        lastX, lastY = px, py
      elseif isLast or (math.abs(px - lastX) + math.abs(py - lastY)) >= MIN_LINE_PIXELS then
        if canLine and lineCount < MAX_LINES then
          lineCount = lineCount + 1
          local line = lineRegion(self, lineCount)
          line:SetColorTexture(color[1], color[2], color[3], color[4])
          line:SetStartPoint("TOPLEFT", self.frame, lastX, -lastY)
          line:SetEndPoint("TOPLEFT", self.frame, px, -py)
          line:Show()
        end
        lastX, lastY = px, py
      end
    end
    for _, pt in ipairs({ seg.points[1], seg.points[#seg.points] }) do
      dotCount = dotCount + 1
      local dot = dotRegion(self, dotCount)
      local px, py = self:ToPixels(pt[1], pt[2])
      dot:ClearAllPoints()
      dot:SetPoint("CENTER", self.frame, "TOPLEFT", px, -py)
      dot:Show()
    end
  end
  for i = lineCount + 1, #self.lines do self.lines[i]:Hide() end
  for i = dotCount + 1, #self.dots do self.dots[i]:Hide() end
end

-------------------------------------------------------------------------------
-- Event icons and marker
-------------------------------------------------------------------------------

-- pins: list of { x, y, icon, title, text }
function Canvas:SetPins(pins)
  for i, data in ipairs(pins) do
    local pin = self.pins[i]
    if not pin then
      pin = CreateFrame("Frame", nil, self.pinLayer)
      pin:SetSize(16, 16)
      pin.icon = pin:CreateTexture(nil, "ARTWORK")
      pin.icon:SetAllPoints()
      pin.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
      pin:EnableMouse(true)
      pin:SetScript("OnEnter", function(p)
        GameTooltip:SetOwner(p, "ANCHOR_RIGHT")
        GameTooltip:SetText(p.title, 1, 0.82, 0)
        if p.text then GameTooltip:AddLine(p.text, 1, 1, 1) end
        GameTooltip:Show()
      end)
      pin:SetScript("OnLeave", GameTooltip_Hide)
      self.pins[i] = pin
    end
    local px, py = self:ToPixels(data.x, data.y)
    pin:ClearAllPoints()
    pin:SetPoint("CENTER", self.frame, "TOPLEFT", px, -py)
    pin.icon:SetTexture(data.icon)
    pin.title, pin.text = data.title, data.text
    pin:Show()
  end
  for i = #pins + 1, #self.pins do self.pins[i]:Hide() end
end

function Canvas:SetMarker(x, y)
  if not x then
    self.marker:Hide()
    return
  end
  local px, py = self:ToPixels(x, y)
  self.marker:ClearAllPoints()
  self.marker:SetPoint("CENTER", self.frame, "TOPLEFT", px, -py)
  self.marker:Show()
end
