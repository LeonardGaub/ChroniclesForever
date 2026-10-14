-- Journey Forever - line graph
-- A value over time: one line through the points, the largest and smallest value as labels, clock times
-- along the bottom, faint vertical lines where play sessions were joined, and a tooltip with the value
-- under the cursor.

local ADDON, FC = ...
local UI = FC.UI

local Graph = {}
Graph.__index = Graph

local LABEL_H = 14   -- space for the time labels under the plot
local TOP_PAD = 14   -- space for the max label
local THICKNESS = 2

function UI:LineGraph(parent, width, height)
  local self = setmetatable({ lines = {}, ticks = {}, breaks = {}, points = {} }, Graph)
  local f = CreateFrame("Frame", nil, parent)
  f:SetSize(width, height)
  self.frame = f

  local bg = f:CreateTexture(nil, "BACKGROUND")
  bg:SetAllPoints()
  bg:SetColorTexture(0, 0, 0, 0.35)

  local plot = CreateFrame("Frame", nil, f)
  plot:SetPoint("TOPLEFT", 0, -TOP_PAD)
  plot:SetPoint("BOTTOMRIGHT", 0, LABEL_H)
  self.plot, self.plotW, self.plotH = plot, width, height - TOP_PAD - LABEL_H

  self.base = plot:CreateTexture(nil, "ARTWORK", nil, 1)
  self.base:SetHeight(1)
  self.base:SetColorTexture(1, 0.82, 0, 0.3)

  self.maxLabel = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.maxLabel:SetPoint("TOPLEFT", 4, -2)
  self.minLabel = plot:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.minLabel:SetPoint("BOTTOMLEFT", 4, 3)
  self.empty = f:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  self.empty:SetPoint("CENTER")

  -- Hover: dot on the nearest point and a tooltip with its time and value.
  self.dot = plot:CreateTexture(nil, "OVERLAY")
  self.dot:SetSize(7, 7)
  self.dot:SetTexture("Interface\\Buttons\\WHITE8X8")
  self.dot:Hide()
  plot:EnableMouse(true)
  plot:SetScript("OnEnter", function() self.hovering = true end)
  plot:SetScript("OnLeave", function()
    self.hovering = false
    self.dot:Hide()
    GameTooltip:Hide()
  end)
  plot:SetScript("OnUpdate", function()
    if not self.hovering then return end
    local left, scale = plot:GetLeft(), plot:GetEffectiveScale()
    if not left then return end
    self:ShowPointAt(GetCursorPosition() / scale - left)
  end)
  return self
end

local function line(self, i)
  local l = self.lines[i]
  if not l then
    l = self.plot:CreateLine(nil, "ARTWORK", nil, 3)
    l:SetThickness(THICKNESS)
    self.lines[i] = l
  end
  return l
end

-- points: { { x, value, time } } ascending by x (x in seconds of the window); length: window length in seconds.
-- opts = { color = { r, g, b }, format(value) -> text, emptyText, ticks = { { x, label } }, breaks = { x },
--          tooltip(point) -> title, line }
function Graph:SetData(points, length, opts)
  local format = opts.format or function(v) return tostring(v) end
  self.points, self.opts, self.format = points, opts, format
  local minV, maxV
  for _, p in ipairs(points) do
    if not minV or p.value < minV then minV = p.value end
    if not maxV or p.value > maxV then maxV = p.value end
  end
  local hasData = #points >= 2 and length > 0
  self.empty:SetText(opts.emptyText or "")
  self.empty:SetShown(not hasData)
  self.maxLabel:SetText(hasData and format(maxV) or "")
  self.minLabel:SetText(hasData and maxV ~= minV and format(minV) or "")
  self.base:SetShown(hasData)

  local range = (hasData and maxV > minV) and (maxV - minV) or 1
  local function pos(p)
    return self.plotW * p.x / math.max(length, 1), self.plotH * (p.value - (minV or 0)) / range
  end
  self.pos = pos
  self.base:ClearAllPoints()
  self.base:SetPoint("BOTTOMLEFT", self.plot, "BOTTOMLEFT", 0, 0)
  self.base:SetPoint("RIGHT", self.plot, "RIGHT")

  local n = 0
  if hasData then
    local c = opts.color or { 1, 0.82, 0 }
    for i = 2, #points do
      local x1, y1 = pos(points[i - 1])
      local x2, y2 = pos(points[i])
      n = n + 1
      local l = line(self, n)
      l:SetColorTexture(c[1], c[2], c[3], 0.95)
      l:SetStartPoint("BOTTOMLEFT", self.plot, x1, y1)
      l:SetEndPoint("BOTTOMLEFT", self.plot, x2, y2)
      l:Show()
    end
    self.dot:SetVertexColor(c[1], c[2], c[3])
  end
  for i = n + 1, #self.lines do self.lines[i]:Hide() end
  self.lineCount = n

  -- Session joins.
  local breaks = hasData and opts.breaks or {}
  for i, bx in ipairs(breaks) do
    local b = self.breaks[i]
    if not b then
      b = self.plot:CreateTexture(nil, "ARTWORK", nil, 2)
      b:SetWidth(1)
      b:SetColorTexture(1, 1, 1, 0.15)
      self.breaks[i] = b
    end
    b:ClearAllPoints()
    b:SetPoint("TOPLEFT", self.plot, "TOPLEFT", self.plotW * bx / math.max(length, 1), 0)
    b:SetPoint("BOTTOM", self.plot, "BOTTOM")
    b:Show()
  end
  for i = #breaks + 1, #self.breaks do self.breaks[i]:Hide() end

  -- Time labels.
  local ticks = hasData and opts.ticks or {}
  for i, t in ipairs(ticks) do
    local label = self.ticks[i]
    if not label then
      label = self.frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
      self.ticks[i] = label
    end
    local x = self.plotW * t.x / math.max(length, 1)
    label:ClearAllPoints()
    if i == 1 then
      label:SetPoint("BOTTOMLEFT", self.frame, "BOTTOMLEFT", x + 2, 1)
    elseif i == #ticks then
      label:SetPoint("BOTTOMRIGHT", self.frame, "BOTTOMLEFT", x - 2, 1)
    else
      label:SetPoint("BOTTOM", self.frame, "BOTTOMLEFT", x, 1)
    end
    label:SetText(t.label)
    label:Show()
  end
  for i = #ticks + 1, #self.ticks do self.ticks[i]:Hide() end
end

-- Highlights the point nearest to plot x coordinate px and shows its tooltip.
function Graph:ShowPointAt(px)
  local points = self.points
  if #points < 2 or not self.pos then return end
  local best, bestD
  for _, p in ipairs(points) do
    local x = self.pos(p)
    local d = math.abs(x - px)
    if not bestD or d < bestD then best, bestD = p, d end
  end
  local x, y = self.pos(best)
  self.dot:ClearAllPoints()
  self.dot:SetPoint("CENTER", self.plot, "BOTTOMLEFT", x, y)
  self.dot:Show()
  if self.opts.tooltip then
    local title, text = self.opts.tooltip(best)
    GameTooltip:SetOwner(self.plot, "ANCHOR_CURSOR")
    GameTooltip:SetText(title, 1, 0.82, 0)
    if text then GameTooltip:AddLine(text, 1, 1, 1) end
    GameTooltip:Show()
  end
  return best
end
