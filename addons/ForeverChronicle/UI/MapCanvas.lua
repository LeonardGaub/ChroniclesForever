-- Journey Forever - map canvas
-- Draws a map with the client's own map art (the same tiles and explored-area overlays as the world map),
-- route lines, event icons and a position marker. If the client cannot provide the art, a plain
-- parchment-coloured area with the map name is shown instead.
--
-- Zoom: mouse wheel (at the cursor), drag to pan, right-click to reset. The visible area (frame) clips a
-- content frame that is scaled and moved; lines, icons and the marker are counter-scaled so they keep
-- their on-screen size.
--
-- Route lines are drawn for the visible area (plus a margin) at the detail of the current zoom, and drawn
-- again shortly after the view changes. Every line has a time, so a replay can "paint" the route up to the
-- current moment, optionally only its last minutes with older parts fading out (Canvas:SetPaint).

local ADDON, FC = ...
local Util = FC.Util
local UI = FC.UI

local Canvas = {}
Canvas.__index = Canvas
UI.MapCanvas = Canvas

local TILE = 256
local MIN_LINE_PIXELS = 3   -- route points closer than this (on screen) are merged into one line
local MAX_LINES = 5000      -- above this, points are merged more coarsely
local RENDER_MARGIN = 0.5   -- lines are drawn for the visible area plus this share of it on every side
local RENDER_DELAY = 0.12   -- seconds after a zoom or pan before the route is drawn again
local FADE_MIN = 0.12       -- alpha share of the oldest part of a fading trail
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
    if self.drag then
      local cx, cy = self:CursorPosition()
      self:SetView(self.zoom, self.drag.offX + (cx - self.drag.cx), self.drag.offY + (cy - self.drag.cy))
    end
    if self.renderAt and GetTime() >= self.renderAt then self:RenderRoute() end
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
  -- Draw the route again (soon) when the detail no longer fits or the view left the drawn area.
  local r = self.rendered
  if r and not self.renderAt then
    local x0, y0, x1, y1 = self:VisibleRect()
    local ratio = zoom / r.zoom
    if ratio > 1.2 or ratio < 1 / 1.2 or x0 < r.x0 or y0 < r.y0 or x1 > r.x1 or y1 > r.y1 then
      self.renderAt = GetTime() + RENDER_DELAY
    end
  end
end

-- The visible part of the content, in content pixels: left, top, right, bottom.
function Canvas:VisibleRect()
  local z = self.zoom
  return -self.offX / z, -self.offY / z, (self.width - self.offX) / z, (self.height - self.offY) / z
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
function Canvas:SetMap(mapID)
  if mapID ~= self.mapID then self:ResetZoom() end
  self.mapID = mapID
  hideAll(self.tiles)
  hideAll(self.overlays)
  local layers = C_Map and C_Map.GetMapArtLayers and Util.SafeValue("table", C_Map.GetMapArtLayers, mapID)
  local layer = layers and layers[1]
  local textures = layer and C_Map.GetMapArtLayerTextures
    and Util.SafeValue("table", C_Map.GetMapArtLayerTextures, mapID, 1)
  local info = Util.SafeValue("table", C_Map.GetMapInfo, mapID)
  self.name:SetText(info and Util.Plain(info.name) or "")

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

-- Size of tile `index` of `count` along one side of an overlay that is `total` pixels long: the pixels it
-- covers and the size of its file (files are powers of two, at least 16; only the last tile is partial).
local function overlayTileSize(index, count, total)
  if index < count then return TILE, TILE end
  local pixels = total % TILE
  if pixels == 0 then pixels = TILE end
  local file = 16
  while file < pixels do file = file * 2 end
  return pixels, file
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
        local pixelH, fileH = overlayTileSize(j, tall, info.textureHeight)
        for k = 1, wide do
          local pixelW, fileW = overlayTileSize(k, wide, info.textureWidth)
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

-- Calls emit(n, seg, x1, y1, x2, y2, time) for every line that touches rect (content pixels) and returns the
-- count. Points closer than minDist to the previous line end are merged; the last point of a segment is
-- always drawn. time is the time of the line's end point.
local function walk(self, segments, rect, minDist, emit)
  local n = 0
  for _, seg in ipairs(segments) do
    local lastX, lastY
    local count = #seg.points
    for i, pt in ipairs(seg.points) do
      local px, py = pt[1] * self.width, pt[2] * self.height
      if not lastX then
        lastX, lastY = px, py
      elseif i == count or (math.abs(px - lastX) + math.abs(py - lastY)) >= minDist then
        if math.max(px, lastX) >= rect.x0 and math.min(px, lastX) <= rect.x1
            and math.max(py, lastY) >= rect.y0 and math.min(py, lastY) <= rect.y1 then
          n = n + 1
          if emit then emit(n, seg, lastX, lastY, px, py, pt[3]) end
        end
        lastX, lastY = px, py
      end
    end
  end
  return n
end

-- segments: from FC.Route.Segments. color(seg, time) -> r, g, b, a gives each line its colour (default: gold
-- on foot, blue on a flight path). Ends of every segment get a small grey dot (recorded data starts or stops).
function Canvas:DrawRoute(segments, color)
  self.segments, self.colorFn = segments, color
  self:RenderRoute()
end

function Canvas:RenderRoute()
  self.renderAt = nil
  local segments = self.segments or {}
  local x0, y0, x1, y1 = self:VisibleRect()
  local mx, my = (x1 - x0) * RENDER_MARGIN, (y1 - y0) * RENDER_MARGIN
  local rect = { x0 = x0 - mx, y0 = y0 - my, x1 = x1 + mx, y1 = y1 + my, zoom = self.zoom }
  self.rendered = rect

  -- Detail of the current zoom; coarser if that would need too many lines.
  local minDist = MIN_LINE_PIXELS / self.zoom
  for _ = 1, 4 do
    local n = walk(self, segments, rect, minDist)
    if n <= MAX_LINES then break end
    minDist = minDist * math.max(1.5, n / MAX_LINES)
  end

  local canLine = self.lineLayer.CreateLine ~= nil
  local times, colors = {}, {}
  local colorFn = self.colorFn
  local lineCount = 0
  if canLine then
    lineCount = walk(self, segments, rect, minDist, function(n, seg, ax, ay, bx, by, t)
      if n > MAX_LINES then return end
      local line = lineRegion(self, n)
      local c
      if colorFn then c = { colorFn(seg, t) } end
      if not c or not c[1] then c = seg.taxi and TAXI_COLOR or ROUTE_COLOR end
      line:SetStartPoint("TOPLEFT", self.content, ax, -ay)
      line:SetEndPoint("TOPLEFT", self.content, bx, -by)
      line:Hide()
      times[n], colors[n] = t, c
    end)
    lineCount = math.min(lineCount, MAX_LINES)
  end
  for i = lineCount + 1, #self.lines do self.lines[i]:Hide() end

  local dotTimes, dotCount = {}, 0
  for _, seg in ipairs(segments) do
    for _, pt in ipairs({ seg.points[1], seg.points[#seg.points] }) do
      local px, py = self:ToPixels(pt[1], pt[2])
      if px >= rect.x0 and px <= rect.x1 and py >= rect.y0 and py <= rect.y1 then
        dotCount = dotCount + 1
        local dot = dotRegion(self, dotCount)
        dot:ClearAllPoints()
        dot:SetPoint("CENTER", self.content, "TOPLEFT", px, -py)
        dot:Hide()
        dotTimes[dotCount] = pt[3]
      end
    end
  end
  for i = dotCount + 1, #self.dots do self.dots[i]:Hide() end

  self.lineTimes, self.lineColors, self.dotTimes = times, colors, dotTimes
  self.lineWindow, self.dotWindow = { 1, 0 }, { 1, 0 }
  self:ApplyPaint(true)
end

-------------------------------------------------------------------------------
-- Painting: which lines are shown for the current moment
-------------------------------------------------------------------------------

-- First index whose time is > t (times ascending); #times + 1 if none.
local function firstAfter(times, t)
  local lo, hi = 1, #times
  while lo <= hi do
    local mid = math.floor((lo + hi) / 2)
    if times[mid] > t then hi = mid - 1 else lo = mid + 1 end
  end
  return lo
end

-- Shows the lines with a time in (from, to]; nil = no limit. fade: the lines get fainter towards from.
function Canvas:SetPaint(from, to, fade)
  self.paintFrom, self.paintTo, self.paintFade = from, to, fade and from and to and to > from or nil
  self:ApplyPaint()
  self:PaintPins()
end

function Canvas:LineAlpha(i)
  local c = self.lineColors[i]
  if not self.paintFade then return c[4] or 1 end
  local share = (self.lineTimes[i] - self.paintFrom) / (self.paintTo - self.paintFrom)
  return (c[4] or 1) * (FADE_MIN + (1 - FADE_MIN) * math.max(0, math.min(1, share)))
end

local function colorLine(self, i)
  local c = self.lineColors[i]
  self.lines[i]:SetColorTexture(c[1], c[2], c[3], self:LineAlpha(i))
end

-- Moves a shown window [lo, hi] of regions, showing and hiding only what changed. Returns the new window.
local function moveWindow(regions, old, lo, hi, onShow)
  local plo, phi = old[1], old[2]
  for i = plo, math.min(phi, lo - 1) do regions[i]:Hide() end
  for i = math.max(plo, hi + 1), phi do regions[i]:Hide() end
  for i = lo, math.min(hi, plo - 1) do regions[i]:Show(); if onShow then onShow(i) end end
  for i = math.max(lo, phi + 1), hi do regions[i]:Show(); if onShow then onShow(i) end end
  return { lo, hi }
end

function Canvas:ApplyPaint(recolor)
  local times = self.lineTimes
  if not times then return end
  local from, to = self.paintFrom, self.paintTo
  local lo = from and firstAfter(times, from) or 1
  local hi = to and firstAfter(times, to) - 1 or #times
  self.lineWindow = moveWindow(self.lines, self.lineWindow, lo, hi, function(i) colorLine(self, i) end)
  -- A fading trail changes its colours as time goes on: refresh them now and then, not every frame.
  local refresh = recolor or self.fadedState ~= (self.paintFade or false)
  if self.paintFade and not refresh then
    refresh = math.abs(to - (self.fadedAt or 0)) >= (to - from) / 40
  end
  if refresh then
    for i = lo, hi do colorLine(self, i) end
    self.fadedState, self.fadedAt = self.paintFade or false, to
  end
  local dots = self.dotTimes
  local dlo = from and firstAfter(dots, from) or 1
  local dhi = to and firstAfter(dots, to) - 1 or #dots
  self.dotWindow = moveWindow(self.dots, self.dotWindow, dlo, dhi)
end

-------------------------------------------------------------------------------
-- Legend (e.g. route colours by level)
-------------------------------------------------------------------------------

-- items: list of { r, g, b, text }; nil or empty hides the legend.
function Canvas:SetLegend(items)
  local legend = self.legend
  if not legend then
    legend = CreateFrame("Frame", nil, self.frame)
    legend:SetPoint("BOTTOMLEFT", 8, 8)
    legend:SetFrameLevel(self.frame:GetFrameLevel() + 6)
    local bg = legend:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0, 0, 0, 0.65)
    legend.rows = {}
    self.legend = legend
  end
  items = items or {}
  local width = 0
  for i, item in ipairs(items) do
    local row = legend.rows[i]
    if not row then
      row = { swatch = legend:CreateTexture(nil, "ARTWORK"), text = legend:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall") }
      row.swatch:SetSize(14, 4)
      row.swatch:SetPoint("TOPLEFT", 8, -10 - (i - 1) * 14)
      row.text:SetPoint("LEFT", row.swatch, "RIGHT", 6, 0)
      legend.rows[i] = row
    end
    row.swatch:SetColorTexture(item[1], item[2], item[3], 1)
    row.text:SetText(item[4])
    row.swatch:Show()
    row.text:Show()
    width = math.max(width, row.text:GetStringWidth())
  end
  for i = #items + 1, #legend.rows do
    legend.rows[i].swatch:Hide()
    legend.rows[i].text:Hide()
  end
  legend:SetSize(width + 36, #items * 14 + 12)
  legend:SetShown(#items > 0)
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

-- Pin looks: round icon on a dark disc with a coloured ring. icon/ring: diameters in pixels.
local PIN_LOOKS = {
  normal = { icon = 14, ring = 19, color = { 0.85, 0.7, 0.42 }, back = { 0.08, 0.06, 0.04 } },
  milestone = { icon = 20, ring = 26, color = { 1, 0.82, 0 }, back = { 0.12, 0.08, 0.02 } },
  danger = { icon = 15, ring = 21, color = { 0.95, 0.22, 0.15 }, back = { 0.3, 0.03, 0.02 } },
}
local PIN_LEVEL = { normal = 1, danger = 2, milestone = 3 }

local function pinSize(pin, k)
  local look = pin.look
  pin.ring:SetSize(look.ring * k, look.ring * k)
  pin.back:SetSize((look.ring - 3) * k, (look.ring - 3) * k)
  pin.icon:SetSize(look.icon * k, look.icon * k)
end

local function createPin(layer)
  local pin = CreateFrame("Frame", nil, layer)
  pin:SetSize(22, 22)
  pin.ring = UI:Circle(pin, "BORDER", 0)
  pin.back = UI:Circle(pin, "BORDER", 1)
  pin.icon = pin:CreateTexture(nil, "ARTWORK")
  for _, t in ipairs({ pin.ring, pin.back, pin.icon }) do t:SetPoint("CENTER") end
  UI:MaskCircle(pin, pin.icon)
  pin:EnableMouse(true)
  UI:Tooltip(pin, function(p) return p.title end, function(p) return p.text end)
  -- Hover: the pin grows a little.
  pin:HookScript("OnEnter", function(p) UI:Tween(p, 0.12, 0, function(k) pinSize(p, 1 + 0.3 * k) end) end)
  pin:HookScript("OnLeave", function(p) UI:Tween(p, 0.12, 0, function(k) pinSize(p, 1.3 - 0.3 * k) end) end)
  return pin
end

-- pins: list of { x, y, icon, title, text, time, kind = "milestone" | "danger" | nil, pinIcon }
function Canvas:SetPins(pins)
  for i, data in ipairs(pins) do
    local pin = self.pins[i]
    if not pin then
      pin = createPin(self.pinLayer)
      self.pins[i] = pin
    end
    local kind = PIN_LOOKS[data.kind] and data.kind or "normal"
    pin.look = PIN_LOOKS[kind]
    pin:SetFrameLevel(self.pinLayer:GetFrameLevel() + PIN_LEVEL[kind])
    local c, b = pin.look.color, pin.look.back
    pin.ring:SetVertexColor(c[1], c[2], c[3], 1)
    pin.back:SetVertexColor(b[1], b[2], b[3], 1)
    UI:StopTween(pin)
    pin:SetAlpha(1)
    pinSize(pin, 1)
    pin.px, pin.py = self:ToPixels(data.x, data.y)
    self:PlacePin(pin)
    if data.pinIcon and UI:SetIcon(pin.icon, data.pinIcon) then
      pin.icon:SetTexCoord(0, 1, 0, 1)
    else
      UI:SetIcon(pin.icon, data.icon)
      pin.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
    end
    pin.title, pin.text, pin.time = data.title, data.text, data.time
    pin.painted = nil
  end
  for i = #pins + 1, #self.pins do
    self.pins[i]:Hide()
    self.pins[i].time, self.pins[i].painted = nil, false
  end
  self.pinCount = #pins
  self:PaintPins()
end

-- Pins with a time are shown once the painted route has reached it; then they pop up.
function Canvas:PaintPins()
  local to = self.paintTo
  for i = 1, self.pinCount or 0 do
    local pin = self.pins[i]
    local show = not (to and pin.time and pin.time > to)
    if pin.painted ~= show then
      local pop = show and pin.painted == false
      pin.painted = show
      pin:SetShown(show)
      if pop then
        UI:Tween(pin, 0.35, 0, function(p)
          pin:SetAlpha(p)
          pinSize(pin, 1.9 - 0.9 * p)
        end)
      elseif not show then
        UI:StopTween(pin)
      end
    end
  end
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
