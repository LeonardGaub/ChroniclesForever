-- Forever Chronicle - map canvas
-- Draws a map with the client's own map art (the same tiles and explored-area overlays as the world map),
-- route lines, event icons and a position marker. If the client cannot provide the art, a plain
-- parchment-coloured area with the map name is shown instead.
--
-- Zoom: mouse wheel (at the cursor), drag to pan, right-click to reset. The visible area (frame) clips a
-- content frame that is scaled and moved; lines, icons and the marker are counter-scaled so they keep
-- their on-screen size.

local ADDON, FC = ...
local Util = FC.Util
local UI = FC.UI

local Canvas = {}
Canvas.__index = Canvas
UI.MapCanvas = Canvas

local TILE = 256
local MIN_LINE_PIXELS = 3   -- route points closer than this (on screen) are merged into one line
local MAX_LINES = 4000
local LINE_THICKNESS = 2.5
local DOT_SIZE, MARKER_SIZE = 5, 18
local MAX_ZOOM, ZOOM_STEP = 6, 1.25
local ROUTE_COLOR = { 1, 0.82, 0, 0.95 }
local TAXI_COLOR = { 0.41, 0.8, 0.94, 0.9 }

function Canvas.New(parent, width, height)
  local self = setmetatable({ zoom = 1, offX = 0, offY = 0 }, Canvas)
  local f = CreateFrame("Frame", nil, parent)
  f:SetSize(width, height)
  f:SetClipsChildren(true)
  self.frame, self.width, self.height = f, width, height

  local bg = f:CreateTexture(nil, "BACKGROUND", nil, -8)
  bg:SetAllPoints()
  bg:SetColorTexture(0.32, 0.25, 0.16, 1)

  local content = CreateFrame("Frame", nil, f)
  content:SetSize(width, height)
  content:SetPoint("TOPLEFT")
  self.content = content

  -- Map art is laid out in map units (e.g. 1002 x 668) on a scaled child frame.
  self.art = CreateFrame("Frame", nil, content)
  self.art:SetPoint("TOPLEFT")
  self.tiles, self.overlays = {}, {}

  self.name = content:CreateFontString(nil, "ARTWORK", "GameFontDisableHuge")
  self.name:SetPoint("CENTER")

  self.lines, self.dots, self.pins = {}, {}, {}
  self.lineLayer = CreateFrame("Frame", nil, content)
  self.lineLayer:SetAllPoints()
  self.lineLayer:SetFrameLevel(content:GetFrameLevel() + 2)
  self.pinLayer = CreateFrame("Frame", nil, content)
  self.pinLayer:SetAllPoints()
  self.pinLayer:SetFrameLevel(content:GetFrameLevel() + 4)

  self.marker = self.pinLayer:CreateTexture(nil, "OVERLAY", nil, 7)
  self.marker:SetSize(MARKER_SIZE, MARKER_SIZE)
  self.marker:SetTexture("Interface\\Common\\Indicator-Yellow")
  self.marker:Hide()

  -- Mouse: wheel zoom, drag to pan, right-click to reset.
  f:EnableMouse(true)
  f:EnableMouseWheel(true)
  f:SetScript("OnMouseWheel", function(_, delta) self:ZoomAtCursor(delta > 0 and ZOOM_STEP or 1 / ZOOM_STEP) end)
  f:SetScript("OnMouseDown", function(_, button)
    if button == "RightButton" then
      self:ResetZoom()
    elseif button == "LeftButton" and self.zoom > 1 then
      local cx, cy = self:CursorPosition()
      self.drag = { cx = cx, cy = cy, offX = self.offX, offY = self.offY }
    end
  end)
  f:SetScript("OnMouseUp", function() self.drag = nil end)
  f:SetScript("OnHide", function() self.drag = nil end)
  f:SetScript("OnUpdate", function()
    if not self.drag then return end
    local cx, cy = self:CursorPosition()
    self:SetView(self.zoom, self.drag.offX + (cx - self.drag.cx), self.drag.offY + (cy - self.drag.cy))
  end)
  return self
end

-------------------------------------------------------------------------------
-- Zoom and pan
-------------------------------------------------------------------------------

-- Cursor position in the visible area, in pixels from its top-left corner.
function Canvas:CursorPosition()
  local x, y = GetCursorPosition()
  local scale = self.frame:GetEffectiveScale()
  return x / scale - (self.frame:GetLeft() or 0), (self.frame:GetTop() or 0) - y / scale
end

-- zoom >= 1; offX/offY: position of the content's top-left corner in the visible area (<= 0).
function Canvas:SetView(zoom, offX, offY)
  zoom = math.max(1, math.min(MAX_ZOOM, zoom))
  self.zoom = zoom
  self.offX = math.max(self.width - self.width * zoom, math.min(0, offX))
  self.offY = math.max(self.height - self.height * zoom, math.min(0, offY))
  self.content:SetScale(zoom)
  self.content:ClearAllPoints()
  self.content:SetPoint("TOPLEFT", self.frame, "TOPLEFT", self.offX / zoom, -self.offY / zoom)
  -- Keep lines, dots, icons and the marker at their on-screen size.
  for _, line in ipairs(self.lines) do line:SetThickness(LINE_THICKNESS / zoom) end
  for _, dot in ipairs(self.dots) do dot:SetSize(DOT_SIZE / zoom, DOT_SIZE / zoom) end
  self.marker:SetSize(MARKER_SIZE / zoom, MARKER_SIZE / zoom)
  for _, pin in ipairs(self.pins) do self:PlacePin(pin) end
end

function Canvas:ZoomAtCursor(factor)
  local cx, cy = self:CursorPosition()
  local newZoom = math.max(1, math.min(MAX_ZOOM, self.zoom * factor))
  -- Keep the map point under the cursor in place.
  local px, py = (cx - self.offX) / self.zoom, (cy - self.offY) / self.zoom
  self:SetView(newZoom, cx - px * newZoom, cy - py * newZoom)
end

function Canvas:ResetZoom()
  self.drag = nil
  self:SetView(1, 0, 0)
end

-------------------------------------------------------------------------------
-- Map art
-------------------------------------------------------------------------------

local function hideAll(list) for _, r in ipairs(list) do r:Hide() end end

-- Returns true if the client provided art for this map.
function Canvas:SetMap(mapID, fallbackName)
  if mapID ~= self.mapID then self:ResetZoom() end
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
    self.lines[i] = line
  end
  line:SetThickness(LINE_THICKNESS / self.zoom)
  return line
end

local function dotRegion(self, i)
  local dot = self.dots[i]
  if not dot then
    dot = self.lineLayer:CreateTexture(nil, "ARTWORK", nil, 1)
    dot:SetTexture("Interface\\Common\\Indicator-Gray")
    self.dots[i] = dot
  end
  dot:SetSize(DOT_SIZE / self.zoom, DOT_SIZE / self.zoom)
  return dot
end

-- segments: from FC.Route.Segments. Ends of every segment get a small grey dot (recorded data starts or stops).
-- Points closer than MIN_LINE_PIXELS at zoom 1 are merged, so long routes stay cheap to draw.
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
          line:SetStartPoint("TOPLEFT", self.content, lastX, -lastY)
          line:SetEndPoint("TOPLEFT", self.content, px, -py)
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
      dot:SetPoint("CENTER", self.content, "TOPLEFT", px, -py)
      dot:Show()
    end
  end
  for i = lineCount + 1, #self.lines do self.lines[i]:Hide() end
  for i = dotCount + 1, #self.dots do self.dots[i]:Hide() end
end

-------------------------------------------------------------------------------
-- Event icons and marker
-------------------------------------------------------------------------------

-- Icons are counter-scaled: a frame's anchor offsets are in its own (scaled) units, so they are
-- multiplied by the zoom to stay on their map position.
function Canvas:PlacePin(pin)
  if not pin.px then return end
  pin:SetScale(1 / self.zoom)
  pin:ClearAllPoints()
  pin:SetPoint("CENTER", self.content, "TOPLEFT", pin.px * self.zoom, -pin.py * self.zoom)
end

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
      UI:Tooltip(pin, function(p) return p.title end, function(p) return p.text end)
      self.pins[i] = pin
    end
    pin.px, pin.py = self:ToPixels(data.x, data.y)
    self:PlacePin(pin)
    UI:SetIcon(pin.icon, data.icon)
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
  self.marker:SetPoint("CENTER", self.content, "TOPLEFT", px, -py)
  self.marker:Show()
end
