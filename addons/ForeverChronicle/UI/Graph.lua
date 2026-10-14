-- Forever Chronicle - bar graph
-- One bar per value, a zero line (negative values are drawn below it in red), the largest value as a
-- label, hour labels under the bars and a tooltip per bar.

local ADDON, FC = ...
local UI = FC.UI

local Graph = {}
Graph.__index = Graph

local LABEL_H = 14   -- space for the hour labels under the bars
local TOP_PAD = 14   -- space for the max label

function UI:BarGraph(parent, width, height)
  local self = setmetatable({ bars = {}, labels = {} }, Graph)
  local f = CreateFrame("Frame", nil, parent)
  f:SetSize(width, height)
  self.frame, self.width, self.height = f, width, height

  local bg = f:CreateTexture(nil, "BACKGROUND")
  bg:SetAllPoints()
  bg:SetColorTexture(0, 0, 0, 0.35)

  self.zero = f:CreateTexture(nil, "ARTWORK", nil, 2)
  self.zero:SetHeight(1)
  self.zero:SetColorTexture(1, 0.82, 0, 0.35)

  self.maxLabel = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  self.maxLabel:SetPoint("TOPLEFT", 4, -2)
  self.empty = f:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  self.empty:SetPoint("CENTER")
  return self
end

-- labels, values: lists of the same length; color = { r, g, b }; format(value) -> text; tooltip(i) -> title, line
function Graph:SetData(labels, values, color, format, tooltip, emptyText)
  format = format or function(v) return tostring(v) end
  local n = #values
  local maxV, minV = 0, 0
  for _, v in ipairs(values) do
    if v > maxV then maxV = v end
    if v < minV then minV = v end
  end
  local hasData = maxV ~= 0 or minV ~= 0
  self.empty:SetText(emptyText or "")
  self.empty:SetShown(not hasData)
  self.maxLabel:SetText(hasData and format(maxV ~= 0 and maxV or minV) or "")

  local plotH = self.height - LABEL_H - TOP_PAD
  local range = math.max(maxV - minV, 1)
  local zeroY = LABEL_H + plotH * (-minV / range) -- from the bottom
  self.zero:ClearAllPoints()
  self.zero:SetPoint("BOTTOMLEFT", self.frame, "BOTTOMLEFT", 0, zeroY)
  self.zero:SetPoint("RIGHT", self.frame, "RIGHT")

  local slot = n > 0 and (self.width / n) or self.width
  local barW = math.max(2, slot * 0.7)
  for i = 1, n do
    local bar = self.bars[i]
    if not bar then
      bar = CreateFrame("Frame", nil, self.frame)
      bar.tex = bar:CreateTexture(nil, "ARTWORK")
      bar.tex:SetAllPoints()
      bar:EnableMouse(true)
      UI:Tooltip(bar, function(b) return b.title end, function(b) return b.line end)
      self.bars[i] = bar
      self.labels[i] = self.frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    end
    local v = values[i]
    local h = math.max(1, plotH * math.abs(v) / range)
    local x = (i - 1) * slot + (slot - barW) / 2
    bar:ClearAllPoints()
    bar:SetSize(barW, v == 0 and 1 or h)
    if v >= 0 then
      bar:SetPoint("BOTTOMLEFT", self.frame, "BOTTOMLEFT", x, zeroY)
      bar.tex:SetColorTexture(color[1], color[2], color[3], v == 0 and 0.25 or 0.9)
    else
      bar:SetPoint("TOPLEFT", self.frame, "BOTTOMLEFT", x, zeroY)
      bar.tex:SetColorTexture(0.85, 0.2, 0.2, 0.9)
    end
    if tooltip then bar.title, bar.line = tooltip(i) end
    bar:Show()
    local label = self.labels[i]
    label:ClearAllPoints()
    label:SetPoint("BOTTOM", self.frame, "BOTTOMLEFT", x + barW / 2, 1)
    label:SetText(labels[i] or "")
    label:Show()
  end
  for i = n + 1, #self.bars do
    self.bars[i]:Hide()
    self.labels[i]:Hide()
  end
end
