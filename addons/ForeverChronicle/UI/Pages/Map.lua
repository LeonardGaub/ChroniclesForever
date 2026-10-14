-- Forever Chronicle - Map page (spec F-005, in-game)
-- Route replay on the client's own map art: map and session selection, route and event toggles,
-- time slider, play/pause with speeds, live mode (follows the newest point) and focus from the Chronicle.
-- 1x playback = one minute of play time per second; time without points is skipped.

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Route = FC.Route

local page = { id = "map", labelKey = "TAB_MAP", icon = "Interface\\Icons\\INV_Misc_Map_01", order = 25 }
local CANVAS_W, CANVAS_H = 780, 520
local BASE_SPEED = 60
local SPEEDS = { 1, 2, 4, 10 }

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

local function createSlider(parent)
  local ok, s = pcall(CreateFrame, "Slider", nil, parent, "BackdropTemplate")
  if not ok then s = CreateFrame("Slider", nil, parent) end
  if s.SetBackdrop and BACKDROP_SLIDER_8_8 then s:SetBackdrop(BACKDROP_SLIDER_8_8) end
  s:SetOrientation("HORIZONTAL")
  s:SetHeight(17)
  s:SetHitRectInsets(0, 0, -8, -8)
  s:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
  s:SetMinMaxValues(0, 1)
  s:SetValueStep(1)
  if s.SetObeyStepOnDrag then s:SetObeyStepOnDrag(true) end
  return s
end

-------------------------------------------------------------------------------
-- Page
-------------------------------------------------------------------------------

function page:Create(c)
  self.points, self.views, self.viewIndex, self.sessionIndex = {}, {}, 1, 0
  self.speedIndex, self.live, self.playing = 1, true, false

  -- Top row: map, session, icon toggles, help
  self.mapSel = cycler(c, 190, function(step) self:StepMap(step) end)
  self.mapSel.prev:SetPoint("TOPLEFT", 14, -8)
  self.sessionSel = cycler(c, 220, function(step) self:StepSession(step) end)
  self.sessionSel.prev:SetPoint("LEFT", self.mapSel.next, "RIGHT", 18, 0)
  local function toggle(icon, title)
    local b = UI:IconButton(c, 28, icon, title, nil)
    b:SetScript("OnClick", function(btn)
      UI:SetToggle(btn, not btn.on)
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

  -- Map
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

  -- Bottom row: play, speeds, slider, time, live
  self.play = UI:ArrowButton(c, "Next", function() self:TogglePlay() end)
  self.play:SetSize(30, 30)
  self.play.selection = UI:SelectionBorder(self.play)
  UI:Tooltip(self.play, function() return self.playing and L.MAP_PAUSE or L.MAP_PLAY end)
  self.play:SetPoint("TOPLEFT", self.canvas.frame, "BOTTOMLEFT", 0, -10)
  self.speedButtons = {}
  local prev = self.play
  for i, speed in ipairs(SPEEDS) do
    local b = CreateFrame("Button", nil, c, "UIPanelButtonTemplate")
    b:SetSize(38, 22)
    b:SetText(speed .. "\195\151")
    b:SetPoint("LEFT", prev, "RIGHT", i == 1 and 10 or 4, 0)
    b.selection = UI:SelectionBorder(b)
    b:SetScript("OnClick", function() self.speedIndex = i; self:SyncSpeed() end)
    UI:Tooltip(b, "MAP_SPEED", "MAP_SPEED_TIP")
    self.speedButtons[i] = b
    prev = b
  end
  self.live = true
  self.liveButton = UI:IconButton(c, 30, I .. "Ability_EyeOfTheOwl", "MAP_LIVE", "MAP_LIVE_TIP", function()
    self.live, self.playing = true, false
    self.sessionIndex = 0
    self.dirty = true
    self:SyncPlay()
    self:Refresh()
  end)
  self.liveButton:SetPoint("TOPRIGHT", self.canvas.frame, "BOTTOMRIGHT", 0, -10)
  self.time = c:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  self.time:SetPoint("RIGHT", self.liveButton, "LEFT", -10, 0)
  self.time:SetWidth(120)
  self.time:SetJustifyH("RIGHT")
  self.slider = createSlider(c)
  self.slider:SetPoint("LEFT", prev, "RIGHT", 14, 0)
  self.slider:SetPoint("RIGHT", self.time, "LEFT", -10, 0)
  self.slider:SetScript("OnValueChanged", function(_, value, userInput)
    if self.updatingSlider or not self.range then return end
    if userInput == false then return end
    self.live = false
    self.current = self.range[1] + math.floor(value)
    self:UpdateMarker()
  end)

  c:SetScript("OnUpdate", function(_, elapsed) self:OnUpdate(elapsed) end)
  self:SyncSpeed()
  self:SyncPlay()
end

-------------------------------------------------------------------------------
-- Data
-------------------------------------------------------------------------------

local function sessionLabel(s)
  return string.format(L.MAP_SESSION, FC.Util.FormatTime(s.startedAt), FC.Util.FormatDuration(s.endedAt - s.startedAt))
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
    local here = C_Map and FC.Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
    if here then self.canvas:SetMap(here) end
    self.canvas:DrawRoute({})
    self.canvas:SetPins({})
    self.canvas:SetMarker(nil)
    self.mapSel.label:SetText("")
    self:ShowNotice(L.MAP_NO_POINTS)
    return
  end

  self:UpdateRange()
  if self.live then self.current = self.range[2] end
  if self.dirty then self:Redraw() end
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
  self.updatingSlider = true
  self.slider:SetMinMaxValues(0, self.range[2] - self.range[1])
  self.updatingSlider = false
  if not self.current then self.current = self.range[1] end
end

function page:Redraw()
  self.dirty = false
  self.views = Route.Views(self.points)
  local known = false
  for _, v in ipairs(self.views) do if v == self.viewMap then known = true end end
  if not known then
    local p = Route.PointAt(self.points, self.current or self.range[2])
    self.viewMap = Route.ZoneFor(p) or self.views[1]
  end
  for i, v in ipairs(self.views) do if v == self.viewMap then self.viewIndex = i end end
  local hasArt = self.canvas:SetMap(self.viewMap)
  local info = FC.db.maps and FC.db.maps[tostring(self.viewMap)]
  self.mapSel.label:SetText((info and info.name) or tostring(self.viewMap))
  self.artNotice = not hasArt and L.MAP_NO_ART or nil

  local segments = self.routeToggle.on and Route.Segments(self.points, self.viewMap, self.range[1], self.range[2]) or {}
  self.canvas:DrawRoute(segments)

  local pins = {}
  if self.eventToggle.on then
    for _, r in ipairs(FC.Storage:GetStream("events").records) do
      local loc = r.location
      if loc and loc.mapID and loc.x and r.time >= self.range[1] and r.time <= self.range[2] then
        local x, y = Route.Project({ mapID = loc.mapID, x = loc.x, y = loc.y }, self.viewMap)
        if x then
          local text, icon = FC:DescribeEvent(r)
          pins[#pins + 1] = { x = x, y = y, icon = icon, title = text, text = FC.Util.FormatTime(r.time) }
        end
      end
    end
  end
  self.canvas:SetPins(pins)
end

function page:ShowNotice(text)
  if text then
    self.notice:SetText(text)
    self.noticeFrame:SetSize(self.notice:GetStringWidth() + 16, self.notice:GetStringHeight() + 12)
    self.noticeFrame:Show()
  else
    self.noticeFrame:Hide()
  end
end

function page:UpdateMarker()
  if not self.current or #self.points == 0 then return end
  self.updatingSlider = true
  self.slider:SetValue(self.current - self.range[1])
  self.updatingSlider = false
  self.time:SetText(date(L.DATETIME_SECONDS, self.current))

  local p = Route.PointAt(self.points, self.current)
  if not p then return end
  if p.instanceID then
    self.canvas:SetMarker(nil)
    local name = FC.db.instances and FC.db.instances[tostring(p.instanceID)] or ("#" .. p.instanceID)
    self:ShowNotice(string.format(L.MAP_INSTANCE, name))
    return
  end
  -- Follow the player's zone. A map picked by hand stays until the player changes zones.
  local zone = Route.ZoneFor(p)
  local movedZone = zone ~= self.lastZone
  self.lastZone = zone
  local x, y = Route.Project(p, self.viewMap)
  if zone and zone ~= self.viewMap and movedZone then
    self.viewMap = zone
    self:Redraw()
    x, y = Route.Project(p, self.viewMap)
  end
  self.canvas:SetMarker(x, y)
  if x then
    self:ShowNotice(self.artNotice)
  else
    local info = FC.db.maps and FC.db.maps[tostring(p.mapID)]
    self:ShowNotice(string.format(L.MAP_ELSEWHERE, info and info.name or tostring(p.mapID)))
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

function page:StepSession(step)
  local count = #(self.sessions or {}) + 1
  self.sessionIndex = (self.sessionIndex + step) % count
  self.live, self.playing = false, false
  self.current = nil
  self.dirty = true
  self:SyncPlay()
  self:Refresh()
  if self.range then self.current = self.range[1]; self:UpdateMarker() end
end

function page:SyncSpeed()
  for i, b in ipairs(self.speedButtons) do UI:SetSelected(b, i == self.speedIndex) end
end

function page:SyncPlay()
  UI:SetSelected(self.play, self.playing)
  UI:SetToggle(self.liveButton, self.live)
end

function page:TogglePlay()
  if #self.points == 0 then return end
  self.playing = not self.playing
  if self.playing then
    self.live = false
    if not self.current or self.current >= self.range[2] then self.current = self.range[1] end
  end
  self:SyncPlay()
end

function page:OnUpdate(elapsed)
  if not self.playing or not self.range then return end
  local step = SPEEDS[self.speedIndex] * BASE_SPEED * elapsed
  local t = self.current + step
  local p = Route.PointAt(self.points, t)
  if not p or t > p.endTime + step then
    local nextTime = Route.NextTimeAfter(self.points, self.current)
    if nextTime and nextTime > t then t = nextTime end -- skip time without points
  end
  if t >= self.range[2] then
    t = self.range[2]
    self.playing = false
    self:SyncPlay()
  end
  self.current = t
  self:UpdateMarker()
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

function UI:FocusMap(t)
  for i, p in ipairs(self.pages) do
    if p == page then
      if not (self.frame and self.frame:IsShown()) then self:Toggle() end
      self:SelectPage(i)
      page:FocusTime(t)
      return
    end
  end
end
