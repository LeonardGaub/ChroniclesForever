-- Journey Forever - Map page (spec F-005, in-game)
-- Route replay on the client's own map art: map and session selection, route and event toggles,
-- time slider, play/pause with speeds, live mode (follows the newest point) and focus from the Chronicle.
-- 1x playback = one minute of play time per second; time without points is skipped.
--
-- The route is painted up to the shown moment: all of it, or only the last 15 minutes with older parts
-- fading out. Lines are coloured by character level, by session or in one colour (blue = flight path).
-- The slider is a timeline: a coloured band per zone in its track, ticks above it for level-ups, deaths,
-- rares, achievements, new zones, boss kills and completed dungeons. Breaks between sessions are collapsed.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util
local Route = FC.Route

local page = { id = "map", labelKey = "TAB_MAP", icon = "Interface\\Icons\\INV_Misc_Map_01", order = 25 }
local CANVAS_W, CANVAS_H = 780, 520
local BASE_SPEED = 60
local SPEEDS = { 1, 2, 4, 10 }
local TRAIL_SECONDS = 15 * 60
local COLOR_MODES = { "level", "session", "plain" }
local LEGEND_ROWS = 10

-- Route colours; blue stays reserved for flight paths. Neighbouring levels and sessions get different ones.
local PALETTE = {
  { 1, 0.82, 0 }, { 0.45, 1, 0.35 }, { 1, 0.42, 0.3 }, { 0.85, 0.5, 1 }, { 1, 1, 1 }, { 1, 0.62, 0.1 },
}
-- Slider bands per zone (muted, so the thumb stays visible) and ticks per event type.
local ZONE_COLORS = {
  { 0.62, 0.47, 0.25 }, { 0.33, 0.52, 0.3 }, { 0.3, 0.43, 0.6 }, { 0.6, 0.33, 0.33 },
  { 0.52, 0.52, 0.28 }, { 0.45, 0.35, 0.6 }, { 0.28, 0.52, 0.52 }, { 0.65, 0.42, 0.3 },
}
local INSTANCE_COLOR = { 0.22, 0.18, 0.28 }
local TICK_COLORS = {
  level_up = { 1, 0.82, 0 }, player_died = { 1, 0.2, 0.2 }, rare_killed = { 0.8, 0.45, 1 },
  achievement_earned = { 1, 0.55, 0.1 }, zone_discovered = { 0.45, 0.85, 1 },
  boss_killed = { 0.8, 0.55, 0.3 }, dungeon_completed = { 1, 1, 1 },
}
local TRACK_INSET = 8 -- the slider thumb's centre never reaches the track's ends
local MAX_BANDS, MAX_TICKS = 600, 300

-------------------------------------------------------------------------------
-- Small controls
-------------------------------------------------------------------------------

local I = "Interface\\Icons\\"

-- Classic page arrows around a label: [<] label [>]
local function cycler(parent, width, onStep)
  local prev = UI:ArrowButton(parent, "Prev", function() onStep(-1) end)
  local label = parent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  label:SetWidth(width)
  label:SetWordWrap(false)
  label:SetPoint("LEFT", prev, "RIGHT", 2, 0)
  local nextB = UI:ArrowButton(parent, "Next", function() onStep(1) end)
  nextB:SetPoint("LEFT", label, "RIGHT", 2, 0)
  return { prev = prev, label = label, next = nextB }
end

-- Media glyphs drawn from plain textures: triangles are squares with two corners pulled together
-- (vertex offsets). kind: "play", "pause", "prev" (|<), "next" (>|).
local GLYPH_COLOR = { 1, 0.82, 0 }

local function triangle(tex, size, pointsRight)
  tex:SetSize(size * 0.8, size)
  local half = size / 2
  if pointsRight then
    tex:SetVertexOffset(1, 0, 0)
    tex:SetVertexOffset(2, 0, 0)
    tex:SetVertexOffset(3, 0, -half)
    tex:SetVertexOffset(4, 0, half)
  else
    tex:SetVertexOffset(1, 0, -half)
    tex:SetVertexOffset(2, 0, half)
    tex:SetVertexOffset(3, 0, 0)
    tex:SetVertexOffset(4, 0, 0)
  end
end

local function setGlyph(b, kind)
  b.kind = kind
  local g, s = b.glyph, b.glyphSize
  for _, t in ipairs(g) do
    t:ClearAllPoints()
    t:Show()
    for v = 1, 4 do t:SetVertexOffset(v, 0, 0) end
  end
  if kind == "play" then
    triangle(g[1], s, true)
    g[1]:SetPoint("CENTER", 1, 0)
    g[2]:Hide()
  elseif kind == "pause" then
    for i = 1, 2 do g[i]:SetSize(s * 0.3, s) end
    g[1]:SetPoint("CENTER", -s * 0.25, 0)
    g[2]:SetPoint("CENTER", s * 0.25, 0)
  else
    triangle(g[1], s, kind == "next")
    g[2]:SetSize(2, s)
    if kind == "next" then
      g[1]:SetPoint("CENTER", -1, 0)
      g[2]:SetPoint("LEFT", g[1], "RIGHT", 1, 0)
    else
      g[1]:SetPoint("CENTER", 1, 0)
      g[2]:SetPoint("RIGHT", g[1], "LEFT", -1, 0)
    end
  end
end

-- Square button (the game's square button art) with a gold media glyph.
local function mediaButton(parent, size, kind, onClick)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(size, size)
  b:SetNormalTexture("Interface\\Buttons\\UI-SquareButton-Up")
  b:SetPushedTexture("Interface\\Buttons\\UI-SquareButton-Down")
  b:SetHighlightTexture("Interface\\Buttons\\UI-SquareButton-Highlight", "ADD")
  b.selection = UI:SelectionBorder(b)
  b.glyph = { b:CreateTexture(nil, "OVERLAY"), b:CreateTexture(nil, "OVERLAY") }
  b.glyphSize = math.floor(size * 0.42)
  for _, t in ipairs(b.glyph) do t:SetColorTexture(GLYPH_COLOR[1], GLYPH_COLOR[2], GLYPH_COLOR[3], 1) end
  b.SetGlyph = setGlyph
  b:SetScript("OnMouseDown", function(btn) for _, t in ipairs(btn.glyph) do t:SetAlpha(0.7) end end)
  b:SetScript("OnMouseUp", function(btn) for _, t in ipairs(btn.glyph) do t:SetAlpha(1) end end)
  b:SetScript("OnClick", onClick)
  b:SetGlyph(kind)
  return b
end

-- "● Live" button: the dot pulses red while following the player, grey otherwise.
local function liveButton(parent, onClick)
  local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  b:SetSize(66, 22)
  b:SetText(L.MAP_LIVE)
  UI:Track(b, "MAP_LIVE")
  local fs = b.GetFontString and b:GetFontString()
  if type(fs) == "table" then
    fs:ClearAllPoints()
    fs:SetPoint("CENTER", 7, 0)
  end
  b.dot = UI:Circle(b, "OVERLAY", 7, 9)
  b.dot:SetPoint("LEFT", 11, 0)
  b.selection = UI:SelectionBorder(b)
  UI:Tooltip(b, "MAP_LIVE", "MAP_LIVE_TIP")
  b:SetScript("OnClick", onClick)
  local clock = 0
  b:SetScript("OnUpdate", function(btn, dt)
    if not btn.on then return end
    clock = clock + dt
    btn.dot:SetAlpha(0.55 + 0.45 * math.abs(math.sin(clock * 2.5)))
  end)
  function b:SetLive(on)
    self.on = on
    if on then self.dot:SetVertexColor(1, 0.15, 0.1) else self.dot:SetVertexColor(0.5, 0.5, 0.5); self.dot:SetAlpha(1) end
    UI:SetSelected(self, on)
  end
  return b
end

local function createSlider(parent)
  local s = CreateFrame("Slider", nil, parent, "BackdropTemplate")
  if BACKDROP_SLIDER_8_8 then s:SetBackdrop(BACKDROP_SLIDER_8_8) end
  s:SetOrientation("HORIZONTAL")
  s:SetHeight(17)
  s:SetHitRectInsets(0, 0, -8, -8)
  s:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
  s:SetMinMaxValues(0, 1)
  s:SetValueStep(1)
  s:SetObeyStepOnDrag(true)
  return s
end

-- Cursor position from the left edge of a frame, in its own units.
local function cursorX(frame)
  local x = GetCursorPosition()
  return x / frame:GetEffectiveScale() - (frame:GetLeft() or 0)
end

-- Index of the last entry whose [1] is <= t (0 if none); list sorted by [1].
local function lastAtOrBefore(list, t) return Util.BinarySearch(list, t, 1) end

local function settings()
  return FC.db.settings.map
end

-------------------------------------------------------------------------------
-- Page
-------------------------------------------------------------------------------

function page:Create(c)
  self.points, self.views, self.viewIndex, self.sessionIndex = {}, {}, 1, 0
  self.speedIndex, self.live, self.playing = 1, true, false
  self:CreateTopRow(c)
  self:CreateCanvas(c)
  self:CreateControlBar(c)
  c:SetScript("OnUpdate", function(_, elapsed) self:OnUpdate(elapsed) end)
  self:SyncSpeed()
  self:SyncPlay()
end

-- Top row: map and session cyclers, colour mode, trail, route and event toggles, help.
function page:CreateTopRow(c)
  self.mapSel = cycler(c, 190, function(step) self:StepMap(step) end)
  self.mapSel.prev:SetPoint("TOPLEFT", 14, -8)
  self.sessionSel = cycler(c, 220, function(step) self:StepSession(step) end)
  self.sessionSel.prev:SetPoint("LEFT", self.mapSel.next, "RIGHT", 18, 0)
  local function toggle(icon, title, line, onChange)
    local b = UI:IconButton(c, 28, icon, title, line)
    b:SetScript("OnClick", function(btn)
      UI:SetToggle(btn, not btn.on)
      if onChange then onChange(btn.on) end
      self.dirty = true
      self:Refresh()
    end)
    UI:SetToggle(b, true)
    return b
  end
  self.help = UI:IconButton(c, 28, I .. "INV_Misc_QuestionMark", "MAP_HELP_TITLE", "MAP_HELP")
  self.help:SetPoint("TOPRIGHT", -14, -8)
  self.eventToggle = toggle(I .. "INV_Misc_Note_01", "MAP_EVENTS")
  self.eventToggle:SetPoint("RIGHT", self.help, "LEFT", -12, 0)
  self.routeToggle = toggle(I .. "INV_Boots_05", "MAP_ROUTE")
  self.routeToggle:SetPoint("RIGHT", self.eventToggle, "LEFT", -6, 0)
  self.trailToggle = toggle(I .. "INV_Misc_PocketWatch_01", "MAP_TRAIL", "MAP_TRAIL_TIP",
    function(on) settings().trail = on end)
  self.trailToggle:SetPoint("RIGHT", self.routeToggle, "LEFT", -12, 0)
  UI:SetToggle(self.trailToggle, settings().trail)
  self.colorButton = UI:IconButton(c, 28, I .. "INV_Misc_Gem_Variety_02",
    function() return string.format(L.MAP_COLORS, L["MAP_COLORS_" .. self:ColorMode()]) end, "MAP_COLORS_TIP",
    function(btn)
      local mode = self:ColorMode()
      local next = COLOR_MODES[1]
      for i, m in ipairs(COLOR_MODES) do if m == mode then next = COLOR_MODES[i % #COLOR_MODES + 1] end end
      settings().colors = next
      self.dirty = true
      self:Refresh()
      if GameTooltip:IsOwned(btn) then btn:GetScript("OnEnter")(btn) end
    end)
  self.colorButton:SetPoint("RIGHT", self.trailToggle, "LEFT", -6, 0)
end

-- The map with a thin frame and a notice box in its top-left corner (no art, dungeon, elsewhere).
function page:CreateCanvas(c)
  self.canvas = UI.MapCanvas.New(c, CANVAS_W, CANVAS_H)
  self.canvas.frame:SetPoint("TOP", 0, -42)
  local border = c:CreateTexture(nil, "BORDER")
  border:SetPoint("TOPLEFT", self.canvas.frame, -1, 1)
  border:SetPoint("BOTTOMRIGHT", self.canvas.frame, 1, -1)
  border:SetColorTexture(0.6, 0.5, 0.3, 0.8)

  local noticeFrame = CreateFrame("Frame", nil, self.canvas.frame)
  noticeFrame:SetPoint("TOPLEFT", 8, -8)
  noticeFrame:SetFrameLevel(self.canvas.frame:GetFrameLevel() + 6)
  local nbg = noticeFrame:CreateTexture(nil, "BACKGROUND")
  nbg:SetAllPoints()
  nbg:SetColorTexture(0, 0, 0, 0.75)
  self.notice = noticeFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  self.notice:SetPoint("TOPLEFT", 8, -6)
  self.noticeFrame = noticeFrame
end

-- Bottom bar: previous event, play/pause, next event | speeds | timeline | time | live
function page:CreateControlBar(c)
  local bar = CreateFrame("Frame", nil, c, "BackdropTemplate")
  bar:SetPoint("TOPLEFT", self.canvas.frame, "BOTTOMLEFT", -1, -5)
  bar:SetPoint("TOPRIGHT", self.canvas.frame, "BOTTOMRIGHT", 1, -5)
  bar:SetHeight(36)
  UI:Backdrop(bar, { bgFile = UI.WHITE, edgeFile = UI.WHITE, edgeSize = 1 }, { 0, 0, 0, 0.45 }, { 0.6, 0.5, 0.3, 0.5 })
  self.prevEvent = mediaButton(bar, 24, "prev", function() self:StepEvent(-1) end)
  self.prevEvent:SetPoint("LEFT", 6, 0)
  UI:Tooltip(self.prevEvent, "MAP_PREV_EVENT", "MAP_STEP_TIP")
  self.play = mediaButton(bar, 28, "play", function() self:TogglePlay() end)
  self.play:SetPoint("LEFT", self.prevEvent, "RIGHT", 4, 0)
  UI:Tooltip(self.play, function() return self.playing and L.MAP_PAUSE or L.MAP_PLAY end)
  self.nextEvent = mediaButton(bar, 24, "next", function() self:StepEvent(1) end)
  self.nextEvent:SetPoint("LEFT", self.play, "RIGHT", 4, 0)
  UI:Tooltip(self.nextEvent, "MAP_NEXT_EVENT", "MAP_STEP_TIP")
  self.speedButtons = {}
  local prev = self.nextEvent
  for i, speed in ipairs(SPEEDS) do
    local b = CreateFrame("Button", nil, bar, "UIPanelButtonTemplate")
    b:SetSize(34, 20)
    b:SetText(speed .. "\195\151")
    b:SetPoint("LEFT", prev, "RIGHT", i == 1 and 12 or 3, 0)
    b.selection = UI:SelectionBorder(b)
    b:SetScript("OnClick", function() self.speedIndex = i; self:SyncSpeed() end)
    UI:Tooltip(b, "MAP_SPEED", "MAP_SPEED_TIP")
    self.speedButtons[i] = b
    prev = b
  end
  self.liveButton = liveButton(bar, function()
    self.live, self.playing = true, false
    self.sessionIndex = 0
    self.dirty = true
    self:SyncPlay()
    self:Refresh()
  end)
  self.liveButton:SetPoint("RIGHT", -6, 0)
  self.time = bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  self.time:SetPoint("RIGHT", self.liveButton, "LEFT", -8, 0)
  self.time:SetWidth(112)
  self.time:SetJustifyH("RIGHT")
  self.slider = createSlider(bar)
  self.slider:SetPoint("LEFT", prev, "RIGHT", 12, -4)
  self.slider:SetPoint("RIGHT", self.time, "LEFT", -8, -4)
  self.slider:SetScript("OnValueChanged", function(_, value, userInput)
    if self.updatingSlider or not self.timeline then return end
    if userInput == false then return end
    self.live = false
    self.current = Route.ValueToTime(self.timeline, value)
    self:UpdateMarker()
  end)

  -- Timeline: zone bands inside the slider track, event ticks just above it.
  local slider = self.slider
  self.bands = UI:Pool(function() return slider:CreateTexture(nil, "ARTWORK", nil, -2) end)
  self.separators = UI:Pool(function() return slider:CreateTexture(nil, "ARTWORK", nil, -1) end)
  self.ticks, self.tickCount = {}, 0
  self.tickBar = CreateFrame("Frame", nil, bar)
  self.tickBar:SetPoint("BOTTOMLEFT", self.slider, "TOPLEFT", 0, 0)
  self.tickBar:SetPoint("BOTTOMRIGHT", self.slider, "TOPRIGHT", 0, 0)
  self.tickBar:SetHeight(9)
  self.tickBar:EnableMouse(true)
  self.tickBar:SetScript("OnMouseUp", function()
    local tick = self:HoveredTick()
    if tick then self:JumpTo(tick.time) end
  end)
end

-------------------------------------------------------------------------------
-- Route colours
-------------------------------------------------------------------------------

function page:ColorMode()
  local mode = settings().colors
  for _, m in ipairs(COLOR_MODES) do if m == mode then return m end end
  return COLOR_MODES[1]
end

-- Level changes of the viewed character, sorted: list of { time, level }.
local function levelChanges()
  local list = {}
  for _, r in ipairs(FC:ViewStream("events").records) do
    local level = r.type == "level_up" and type(r.data) == "table" and tonumber(r.data.level)
    if level and r.time then list[#list + 1] = { r.time, level } end
  end
  table.sort(list, function(a, b) return a[1] < b[1] end)
  return list
end

function page:LevelAt(t)
  local list = self.levels
  local i = lastAtOrBefore(list, t)
  if i > 0 then return list[i][2] end
  if list[1] then return list[1][2] - 1 end
  return tonumber(FC:ViewChar().info and FC:ViewChar().info.level) or 1
end

-- Session number (1 = oldest) at time t.
function page:SessionAt(t)
  return math.max(1, lastAtOrBefore(self.sessionStarts, t))
end

local function paletteColor(n)
  local c = PALETTE[(n - 1) % #PALETTE + 1]
  return c[1], c[2], c[3], 0.95
end

-- color(seg, time) for the canvas; nil keeps the default (gold, flight paths blue).
function page:RouteColor()
  local mode = self:ColorMode()
  if mode == "plain" then return nil end
  return function(seg, t)
    if seg.taxi then return nil end
    if mode == "level" then return paletteColor(self:LevelAt(t)) end
    return paletteColor(self:SessionAt(t))
  end
end

-- Legend for the colours used by the drawn segments (newest LEGEND_ROWS).
function page:Legend(segments)
  local mode = self:ColorMode()
  if mode == "plain" then return nil end
  local used, order = {}, {}
  local function add(t)
    local key = mode == "level" and self:LevelAt(t) or self:SessionAt(t)
    if not used[key] then used[key] = true; order[#order + 1] = key end
  end
  -- Every level or session a segment passes through, not only those at its ends.
  local changes = mode == "level" and self.levels or self.sessionStarts
  for _, seg in ipairs(segments) do
    if not seg.taxi and seg.points[1] then
      local t0, t1 = seg.points[1][3], seg.points[#seg.points][3]
      add(t0)
      for _, change in ipairs(changes) do
        if change[1] > t0 and change[1] <= t1 then add(change[1]) end
      end
      add(t1)
    end
  end
  table.sort(order)
  local items = {}
  for i = math.max(1, #order - LEGEND_ROWS + 1), #order do
    local key = order[i]
    local r, g, b = paletteColor(key)
    local text = mode == "level" and string.format(L.MAP_LEVEL, key)
      or Util.FormatTime(self.sessionStarts[key] and self.sessionStarts[key][1] or 0)
    items[#items + 1] = { r, g, b, text }
  end
  return items
end

-------------------------------------------------------------------------------
-- Data
-------------------------------------------------------------------------------

local function sessionLabel(s)
  return string.format(L.MAP_SESSION, Util.FormatTime(s.startedAt), Util.FormatDuration(s.endedAt - s.startedAt))
end

-- Called when the page is shown and once per second while it is visible.
function page:Refresh()
  local points, version = Route.Points()
  if version ~= self.version or self.lang ~= FC:GetLanguage() then
    self.version, self.lang, self.points, self.dirty = version, FC:GetLanguage(), points, true
  end
  self.sessions = Route.Sessions()
  if self.sessionIndex > #self.sessions then self.sessionIndex = 0 end
  self.sessionSel.label:SetText(self.sessionIndex == 0 and L.MAP_ALL_SESSIONS or sessionLabel(self.sessions[self.sessionIndex]))

  if #self.points == 0 then
    local here = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
    if here then self.canvas:SetMap(here) end
    self.canvas:DrawRoute({})
    self.canvas:SetPins({})
    self.canvas:SetMarker(nil)
    self.canvas:SetLegend(nil)
    self.mapSel.label:SetText("")
    self:ShowNotice(L.MAP_NO_POINTS)
    return
  end

  self:UpdateRange()
  if self.live then self.current = self.range[2] end
  if self.dirty then self:Redraw() end
  if (self.slider:GetWidth() or 0) ~= self.timelineWidth then self:DrawTimeline() end
  self:UpdateMarker()
end

function page:UpdateRange()
  if self.sessionIndex == 0 then
    local last = self.points[#self.points]
    self.range = { self.points[1].time, math.max(last.endTime, self.points[1].time + 1) }
  else
    local s = self.sessions[self.sessionIndex]
    self.range = { s.startedAt, math.max(s.endedAt, s.startedAt + 1) }
  end
  if not self.current then self.current = self.range[1] end
end

function page:Redraw()
  self.dirty = false
  self.levels = levelChanges()
  self.sessionStarts = {}
  for i = #self.sessions, 1, -1 do self.sessionStarts[#self.sessionStarts + 1] = { self.sessions[i].startedAt } end

  self.views = Route.Views(self.points)
  local known = false
  for _, v in ipairs(self.views) do if v == self.viewMap then known = true end end
  if not known then
    local p = Route.PointAt(self.points, self.current or self.range[2])
    self.viewMap = Route.ZoneFor(p) or self.views[1]
  end
  for i, v in ipairs(self.views) do if v == self.viewMap then self.viewIndex = i end end
  local hasArt = self.canvas:SetMap(self.viewMap)
  local info = FC:MapInfo(self.viewMap)
  self.mapSel.label:SetText((info and info.name) or tostring(self.viewMap))
  self.artNotice = not hasArt and L.MAP_NO_ART or nil

  local segments = self.routeToggle.on and Route.Segments(self.points, self.viewMap, self.range[1], self.range[2]) or {}
  self.canvas:DrawRoute(segments, self:RouteColor())
  self.canvas:SetLegend(self:Legend(segments))

  local pins = {}
  if self.eventToggle.on then
    for _, r in ipairs(FC:ViewStream("events").records) do
      -- Events inside dungeons are shown at the dungeon entrance.
      local spot = r.location and r.time >= self.range[1] and r.time <= self.range[2] and Route.Locate(r.location)
      if spot then
        local x, y = Route.Project(spot, self.viewMap)
        if x then
          local text, icon = FC:DescribeEvent(r)
          local def = FC.eventTypes[r.type]
          pins[#pins + 1] = { x = x, y = y, icon = icon, title = text, text = Util.FormatTime(r.time), time = r.time,
            kind = def and def.highlight, pinIcon = def and def.pinIcon }
        end
      end
    end
  end
  self.canvas:SetPins(pins)

  self.timeline = Route.Timeline(self.points, self.range[1], self.range[2])
  self.updatingSlider = true
  self.slider:SetMinMaxValues(0, self.timeline.total)
  self.updatingSlider = false
  self:DrawTimeline()
end

-------------------------------------------------------------------------------
-- Timeline (slider)
-------------------------------------------------------------------------------

local function placeOnTrack(self, region, x, y)
  region:ClearAllPoints()
  region:SetPoint("LEFT", self.slider, "LEFT", TRACK_INSET + x, y or 0)
end

function page:DrawTimeline()
  local width = self.slider:GetWidth() or 0
  self.timelineWidth = width
  local inner = width - 2 * TRACK_INSET
  local tl = self.timeline
  local bandCount, sepCount, tickCount = 0, 0, 0
  self.runs = {}
  if inner > 0 and tl and self.range then
    local function xOf(t) return Route.TimeToValue(tl, t) / tl.total * inner end

    local colorOf, nextColor = {}, 0
    self.runs = Route.ZoneRuns(self.points, self.range[1], self.range[2])
    for _, run in ipairs(self.runs) do
      local x0, x1 = xOf(run.from), xOf(run.to)
      if x1 - x0 >= 0.5 and bandCount < MAX_BANDS then
        local color = INSTANCE_COLOR
        if not run.instanceID then
          if not colorOf[run.mapID or 0] then
            nextColor = nextColor % #ZONE_COLORS + 1
            colorOf[run.mapID or 0] = ZONE_COLORS[nextColor]
          end
          color = colorOf[run.mapID or 0]
        end
        bandCount = bandCount + 1
        local band = self.bands:Get(bandCount)
        band:SetColorTexture(color[1], color[2], color[3], 0.9)
        band:SetSize(math.max(1, x1 - x0), 5)
        placeOnTrack(self, band, x0)
        band:Show()
      end
    end

    -- Collapsed breaks (logouts, long pauses) as dark marks.
    for i = 2, #tl.intervals do
      sepCount = sepCount + 1
      local sep = self.separators:Get(sepCount)
      sep:SetColorTexture(0, 0, 0, 0.9)
      sep:SetSize(2, 9)
      placeOnTrack(self, sep, tl.intervals[i].offset / tl.total * inner - 1)
      sep:Show()
    end

    for _, r in ipairs(FC:ViewStream("events").records) do
      local color = TICK_COLORS[r.type]
      if color and r.time and r.time >= self.range[1] and r.time <= self.range[2] and tickCount < MAX_TICKS then
        tickCount = tickCount + 1
        local tick = self.ticks[tickCount]
        if not tick then
          tick = { tex = self.tickBar:CreateTexture(nil, "OVERLAY") }
          self.ticks[tickCount] = tick
        end
        tick.px, tick.time, tick.record = TRACK_INSET + xOf(r.time), r.time, r
        tick.tex:SetColorTexture(color[1], color[2], color[3], 1)
        tick.tex:SetSize(2, 7)
        tick.tex:ClearAllPoints()
        tick.tex:SetPoint("BOTTOMLEFT", self.tickBar, "BOTTOMLEFT", tick.px - 1, 1)
        tick.tex:Show()
      end
    end
  end
  self.bands:HideFrom(bandCount + 1)
  self.separators:HideFrom(sepCount + 1)
  for i = tickCount + 1, #self.ticks do self.ticks[i].tex:Hide() end
  self.tickCount = tickCount
end

function page:HoveredTick()
  if not (self.tickBar.IsMouseOver and self.tickBar:IsMouseOver()) then return nil end
  local x, best, bestDist = cursorX(self.tickBar), nil, nil
  for i = 1, self.tickCount do
    local tick = self.ticks[i]
    local d = math.abs(tick.px - x)
    if d <= 5 and (not bestDist or d < bestDist) then best, bestDist = tick, d end
  end
  return best
end

-- Tooltip over the timeline: the event under the cursor (ticks) or the zone at that time (slider).
function page:UpdateHover()
  local owner, title, line
  local tick = self:HoveredTick()
  if tick then
    owner, title, line = self.tickBar, (FC:DescribeEvent(tick.record)), Util.FormatTime(tick.time)
  elseif self.timeline and self.slider.IsMouseOver and self.slider:IsMouseOver() then
    local inner = (self.timelineWidth or 0) - 2 * TRACK_INSET
    if inner > 0 then
      local v = math.max(0, math.min(1, (cursorX(self.slider) - TRACK_INSET) / inner)) * self.timeline.total
      local t = Route.ValueToTime(self.timeline, v)
      for _, run in ipairs(self.runs or {}) do
        if t >= run.from and t <= run.to then
          local info = run.mapID and FC:MapInfo(run.mapID)
          title = run.instanceID and FC:InstanceName(run.instanceID) or (info and info.name)
          break
        end
      end
      owner, line = self.slider, date(L.DATETIME_SECONDS, t)
      title = title or line
    end
  end
  local key = owner and (tostring(title) .. tostring(line)) or nil
  if key == self.hoverKey then return end
  self.hoverKey = key
  if not owner then
    if self.hoverOwner and GameTooltip:IsOwned(self.hoverOwner) then GameTooltip:Hide() end
    self.hoverOwner = nil
    return
  end
  self.hoverOwner = owner
  GameTooltip:SetOwner(owner, "ANCHOR_TOP")
  GameTooltip:SetText(title, 1, 0.82, 0)
  if line and line ~= title then GameTooltip:AddLine(line, 1, 1, 1) end
  GameTooltip:Show()
end

-------------------------------------------------------------------------------
-- Marker
-------------------------------------------------------------------------------

function page:ShowNotice(text)
  if text then
    self.notice:SetText(text)
    self.noticeFrame:SetSize(self.notice:GetStringWidth() + 16, self.notice:GetStringHeight() + 12)
    self.noticeFrame:Show()
  else
    self.noticeFrame:Hide()
  end
end

-- The route line the marker glides along (Route.Glide's curve) on the shown map, for the canvas to keep the
-- marker on the curve it draws: { x0, y0, x1, y1, x2, y2, x3, y3, f }, a missing neighbour as the line's end.
function page:MarkerCurve(curve)
  if not curve then return nil end
  local x1, y1 = Route.Project(curve.a, self.viewMap)
  local x2, y2 = Route.Project(curve.b, self.viewMap)
  if not (x1 and x2) then return nil end
  local x0, y0 = x1, y1
  if curve.before then x0, y0 = Route.Project(curve.before, self.viewMap) end
  local x3, y3 = x2, y2
  if curve.after then x3, y3 = Route.Project(curve.after, self.viewMap) end
  return { x0 or x1, y0 or y1, x1, y1, x2, y2, x3 or x2, y3 or y2, curve.f }
end

function page:UpdateMarker()
  if not self.current or #self.points == 0 then return end
  if self.timeline then
    self.updatingSlider = true
    self.slider:SetValue(Route.TimeToValue(self.timeline, self.current))
    self.updatingSlider = false
  end
  self.time:SetText(date(L.DATETIME_SECONDS, self.current))
  local trail = settings().trail
  self.canvas:SetPaint(trail and self.current - TRAIL_SECONDS or nil, self.current, trail)

  local p = Route.PointAt(self.points, self.current)
  if not p then return end
  -- Inside a dungeon the client gives no position: show the dungeon entrance instead, if known.
  local shown = Route.Locate(p)
  local instanceName = p.instanceID and FC:InstanceName(p.instanceID)
  if not shown then
    self.canvas:SetMarker(nil)
    self:ShowNotice(instanceName and string.format(L.MAP_INSTANCE, instanceName) or nil)
    return
  end
  -- Between two connected points the marker moves along the drawn line.
  if not shown.entrance then
    local glide = Route.Glide(self.points, self.current)
    if glide and glide.x and glide.mapID == shown.mapID then shown = glide end
  end
  -- Follow the player's zone. A map picked by hand stays until the player changes zones.
  local zone = Route.ZoneFor(p)
  local movedZone = zone ~= self.lastZone
  self.lastZone = zone
  local x, y = Route.Project(shown, self.viewMap)
  if zone and zone ~= self.viewMap and movedZone then
    self.viewMap = zone
    self:Redraw()
    x, y = Route.Project(shown, self.viewMap)
  end
  self.canvas:SetMarker(x, y, x and self:MarkerCurve(shown.curve))
  if x then
    self:ShowNotice(instanceName and string.format(L.MAP_INSTANCE_ENTRANCE, instanceName) or self.artNotice)
  else
    local info = FC:MapInfo(shown.mapID)
    self:ShowNotice(string.format(L.MAP_ELSEWHERE, info and info.name or tostring(shown.mapID)))
  end
end

-------------------------------------------------------------------------------
-- Selection and playback
-------------------------------------------------------------------------------

function page:StepMap(step)
  if #self.views == 0 then return end
  self.viewIndex = (self.viewIndex - 1 + step) % #self.views + 1
  self.viewMap = self.views[self.viewIndex]
  self:Redraw()
  self:UpdateMarker()
end

-- A session is shown at its end (the whole route painted); Play starts it from the beginning.
function page:StepSession(step)
  local count = #(self.sessions or {}) + 1
  self.sessionIndex = (self.sessionIndex + step) % count
  self.live, self.playing = false, false
  self.current = nil
  self.dirty = true
  self:SyncPlay()
  self:Refresh()
  if self.range then self.current = self.range[2]; self:UpdateMarker() end
end

function page:SyncSpeed()
  for i, b in ipairs(self.speedButtons) do UI:SetSelected(b, i == self.speedIndex) end
end

function page:SyncPlay()
  self.play:SetGlyph(self.playing and "pause" or "play")
  self.liveButton:SetLive(self.live)
end

-- Jumps to the previous (dir -1) or next (dir 1) mark on the timeline.
function page:StepEvent(dir)
  if not self.current then return end
  local best
  for i = 1, self.tickCount or 0 do
    local t = self.ticks[i].time
    if dir < 0 and t < self.current - 1 and (not best or t > best) then best = t end
    if dir > 0 and t > self.current + 1 and (not best or t < best) then best = t end
  end
  if best then self:JumpTo(best) end
end

function page:TogglePlay()
  if #self.points == 0 or not self.timeline then return end
  self.playing = not self.playing
  if self.playing then
    self.live = false
    if not self.current or Route.TimeToValue(self.timeline, self.current) >= self.timeline.total - 1 then
      self.current = Route.ValueToTime(self.timeline, 0)
    end
  end
  self:SyncPlay()
end

-- Shows a moment without changing the selected session.
function page:JumpTo(t)
  self.live, self.playing = false, false
  self.current = t
  self:SyncPlay()
  self:UpdateMarker()
end

-- Playback runs on the timeline, so breaks between sessions are skipped.
function page:OnUpdate(elapsed)
  self:UpdateHover()
  if not self.playing or not self.timeline then return end
  local tl = self.timeline
  local v = Route.TimeToValue(tl, self.current) + SPEEDS[self.speedIndex] * BASE_SPEED * elapsed
  if v >= tl.total then
    v = tl.total
    self.playing = false
    self:SyncPlay()
  end
  self.current = Route.ValueToTime(tl, v)
  self:UpdateMarker()
end

-- Another character is shown: start over on its newest moment and its zone.
function page:OnViewChanged()
  self.live, self.playing = true, false
  self.sessionIndex, self.current, self.viewMap, self.lastZone, self.version = 0, nil, nil, nil, nil
  self:SyncPlay()
end

-- Shows the given moment (e.g. clicked in the Chronicle).
function page:FocusTime(t)
  self.live, self.playing = false, false
  self.sessionIndex = 0
  for i, s in ipairs(Route.Sessions()) do
    if t >= s.startedAt and t <= s.endedAt then self.sessionIndex = i end
  end
  self.dirty = true
  self.current = t
  self.viewMap = nil
  self:SyncPlay()
  self:Refresh()
  self.current = t
  self:UpdateMarker()
end

UI:RegisterPage(page)

-- Opens the map on the given moment (e.g. clicked in the Chronicle).
function UI:FocusMap(t)
  if self:ShowPage(page.id) and self.frame then page:FocusTime(t) end
end
