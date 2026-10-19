-- Journey Forever - Screenshot manager (spec F-003)
-- Reacts to recorded events (FC_EVENT_RECORDED), schedules screenshots through FC.ScreenshotQueue
-- and stores one record per request in the "screenshots" stream:
--   { id, seq, trigger, events = { eventId, ... }, requestedAt, capturedAt, fileStamp, status, error }
-- status: api_called | confirmed | failed | stale | left_zone | rejected | replaced | dropped_on_logout
-- fileStamp is the local time of the call (MMDDYY_HHMMSS), matching the client's file name
-- WoWScrnShot_<fileStamp>.jpg; the desktop app uses it to find the file.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

-- The triggers players can switch on and off, in the order of the settings and /fjshot. Quest and death start off.
local TRIGGER_OPTIONS = { "level", "achievement", "rare", "dungeon", "zone", "quest", "death" }
local triggerDefaults = {}
for _, name in ipairs(TRIGGER_OPTIONS) do triggerDefaults[name] = name ~= "quest" and name ~= "death" end

local Shots = FC:NewModule("Screenshots", { order = 50, defaults = {
  countdown = true,   -- on-screen countdown; hidden before the capture
  hideUI = "off",     -- hide the interface for the screenshot: "off", "all", "popups" (all but event popups)
  delay = 5,          -- seconds between the event and the screenshot (all automatic triggers)
  cooldown = 30,
  bypass = true,
  capacity = 50,
  triggers = triggerDefaults,
} })

FC.Storage:DefineStream("screenshots", 2000, "Interface\\Icons\\INV_Misc_Spyglass_02")

local TICK = 0.2
local CONFIRM_TIMEOUT = 5
local HIDE_BEFORE_CAPTURE = 0.15    -- seconds between hiding the countdown and taking the screenshot
local HIDE_UI_BEFORE_CAPTURE = 0.25 -- same, when the whole interface is hidden
local UI_RESTORE_TIMEOUT = 1.5      -- the interface is shown again at the latest after this time
local POPUP_SETTLE = 1.0            -- "popups": the screenshot waits this long after the popup appeared
local POPUP_WAIT = 3                -- "popups": how long to look for a popup after the event
local SNAPSHOT_EVERY = 1            -- "popups": seconds between snapshots of the visible interface
-- Frames that show an event's popup (level-up banner, toasts). Others are found as frames that appeared
-- right after the event.
local POPUP_FRAMES = { "EventToastManagerFrame", "LevelUpDisplay", "BossBanner", "ObjectiveTrackerTopBannerFrame" }

-------------------------------------------------------------------------------
-- Triggers: which recorded event types request a screenshot. Other modules can add their own.
--   def = { eventType, priority, maxAge, bypassable, identity = function(record), immediate }
-- The delay before capturing is the shared "delay" setting; immediate triggers ignore it.
-------------------------------------------------------------------------------

Shots.triggers = {}
Shots.triggerByEvent = {}

function Shots:RegisterTrigger(name, def)
  def.name = name
  self.triggers[name] = def
  if def.eventType then self.triggerByEvent[def.eventType] = def end
end

-- The test screenshot follows the delay and countdown like real triggers, but never waits for the cooldown.
Shots:RegisterTrigger("manual", { priority = 1, maxAge = 30, alwaysBypass = true, always = true })
Shots:RegisterTrigger("level", { eventType = "level_up", priority = 2, maxAge = 15, bypassable = true,
  identity = function(r) return "level:" .. tostring(r.data.level) end })
Shots:RegisterTrigger("dungeon", { eventType = "dungeon_completed", priority = 2, maxAge = 30, bypassable = true,
  identity = function(r) return "dungeon:" .. tostring(r.data.instanceID) end })
Shots:RegisterTrigger("rare", { eventType = "rare_killed", priority = 3, maxAge = 20, bypassable = true,
  identity = function(r) return "rare:" .. tostring(r.data.guid) end })
Shots:RegisterTrigger("achievement", { eventType = "achievement_earned", priority = 3, maxAge = 15,
  bypassable = true, identity = function(r) return "achievement:" .. tostring(r.data.achievementID) end })
Shots:RegisterTrigger("zone", { eventType = "zone_discovered", priority = 4, maxAge = 60,
  identity = function(r) return "zone:" .. tostring(r.data.zoneKey) end })
Shots:RegisterTrigger("quest", { eventType = "quest_completed", priority = 5, maxAge = 60,
  identity = function(r) return "quest:" .. tostring(r.data.questID) end })
Shots:RegisterTrigger("death", { eventType = "player_died", priority = 6, maxAge = 30 })

FC:RegisterCapability("screenshots", "CAP_SCREENSHOTS", function() return type(Screenshot) == "function" end)

-------------------------------------------------------------------------------
-- Queue handling
-------------------------------------------------------------------------------

function Shots:OnInitialize()
  local s = self:GetSettings()
  s.enabled = nil -- no main switch any more (0.15.0): each ticked trigger takes screenshots
  if s.hideUI == true then s.hideUI = "all" elseif s.hideUI ~= "all" and s.hideUI ~= "popups" then s.hideUI = "off" end
  self.queue = FC.ScreenshotQueue.New({ capacity = s.capacity, cooldown = s.cooldown, minGap = 2, coalesceWindow = 2 })
end

function Shots:OnEnable()
  self:UpdateSnapshots()
end

function Shots:IsTriggerEnabled(name)
  local s = self:GetSettings()
  local def = self.triggers[name]
  if def and def.always then return true end
  return s.triggers[name] == true
end

local function newRecord(req, status)
  return {
    id = Util.NewId(), trigger = req.trigger, events = req.eventIds, status = status,
    requestedAt = req.requestedAtWall,
  }
end

-- Outcome for requests that were not captured.
function Shots:OnRequestDone(req, outcome)
  FC.Storage:Append("screenshots", newRecord(req, outcome))
  FC.Diagnostics:Log("info", string.format("screenshot %s: %s", req.trigger, outcome))
end

function Shots:Request(triggerName, eventIds, record)
  local def = self.triggers[triggerName]
  if not def or not self:IsTriggerEnabled(triggerName) then return nil end
  local s = self:GetSettings()
  local req = {
    trigger = triggerName, priority = def.priority, eventIds = eventIds or {},
    delay = def.immediate and 0 or s.delay,
    maxAge = def.maxAge,
    bypassCooldown = def.alwaysBypass or (def.bypassable and s.bypass) or false,
    identity = record and def.identity and def.identity(record) or nil,
    zoneKey = triggerName == "zone" and record and record.data.zoneKey or nil,
    requestedAtWall = time(),
  }
  if s.hideUI == "popups" and not def.always then
    req.baseline, req.watchUntil = self.previousSnapshot or self.snapshot, GetTime() + POPUP_WAIT
  end
  local result = self.queue:Add(req, GetTime(), function(r, outcome) self:OnRequestDone(r, outcome) end)
  self:StartTicker()
  return result
end

function Shots:StartTicker()
  if self.ticker then return end
  self.ticker = FC:NewTicker(TICK, function() self:Tick() end)
end

function Shots:StopTicker()
  if self.ticker then self.ticker:Cancel() end
  self.ticker = nil
end

function Shots:Tick()
  local now = GetTime()
  self:WatchPopups(now)
  local travel = FC:GetModule("Travel")
  local zoneKey = travel and travel:CurrentZone()
  self.queue:Expire(now, { zoneKey = zoneKey }, function(r, outcome) self:OnRequestDone(r, outcome) end)
  local state = { loading = FC.loadingScreen, onTaxi = travel and travel:IsOnTaxi() }
  local req = not self.capturing and self.queue:Next(now, state)
  if req then
    self:Capture(req, now)
  else
    self:UpdateCountdown(self.queue:TimeUntilNext(now, state))
  end
  if self.queue:Count() == 0 and not self.capturing then self:StopTicker() end
end

function Shots:UpdateCountdown(seconds)
  local countdown = FC.UI and FC.UI.Countdown
  if not countdown then return end
  if seconds == nil or not self:GetSettings().countdown then
    countdown:Hide()
  else
    countdown:ShowRemaining(seconds)
  end
end

-- The countdown (and, if enabled, the whole interface) is hidden first and the screenshot taken a few
-- frames later, so neither shows up in the image.
function Shots:Capture(req, now)
  self.queue:MarkCaptured(req, now)
  self.capturing = true
  self:UpdateCountdown(nil)
  local hidden = self:HideInterface(req)
  FC:After(hidden and HIDE_UI_BEFORE_CAPTURE or HIDE_BEFORE_CAPTURE, function()
    self.capturing = false
    self:TakeScreenshot(req)
  end)
end

-------------------------------------------------------------------------------
-- Hiding the interface for the screenshot
--   "all":    like Alt+Z (SetUIVisibility). The client blocks that in combat; then the interface is made
--             transparent instead (names above characters stay visible then).
--   "popups": the interface is made transparent, except the frames that show the event's popup (the level-up
--             banner, an achievement toast), and the screenshot is taken once the popup is fully shown.
-- Transparency (SetAlpha) is allowed in combat and does not change how Blizzard's frames work. The minimap's
-- arrow, blips and quest areas are drawn by the client and ignore transparency, so the minimap is hidden
-- instead (unless the client protects it in combat). Everything is restored right after the screenshot, at
-- the latest after UI_RESTORE_TIMEOUT.
-------------------------------------------------------------------------------

local function ownFrame(frame)
  local ui = FC.UI
  return frame == (ui and ui.frame) or frame == _G.ForeverChronicleCountdown or frame == GameTooltip
end

-- Some interface frames are forbidden to addons: calling any of their methods (even IsVisible) is an error.
-- They are skipped; only IsForbidden may be asked.
local function usable(frame)
  if type(frame) ~= "table" or type(frame.IsVisible) ~= "function" then return false end
  if type(frame.IsForbidden) == "function" then
    local ok, forbidden = pcall(frame.IsForbidden, frame)
    if not ok or forbidden then return false end
  end
  return true
end

local function visibleFrame(frame)
  if not usable(frame) then return false end
  local ok, visible = pcall(frame.IsVisible, frame)
  return ok and visible == true
end

-- Direct children of UIParent that are visible now (frame -> true).
function Shots:VisibleFrames()
  local visible = {}
  local children = { UIParent:GetChildren() }
  for _, frame in ipairs(children) do
    if visibleFrame(frame) and not ownFrame(frame) then visible[frame] = true end
  end
  return visible
end

-- Keeps two snapshots of the visible interface while "popups" is chosen, so a request can compare with how
-- the screen looked a moment before its event (Blizzard may show the popup before our event handler runs).
function Shots:UpdateSnapshots()
  local mode = self:GetSettings().hideUI
  if mode ~= "popups" then
    if self.snapshotTicker then self.snapshotTicker:Cancel() end
    self.snapshotTicker, self.snapshot, self.previousSnapshot = nil, nil, nil
    return
  end
  if self.snapshotTicker then return end
  local function take()
    self.previousSnapshot, self.snapshot = self.snapshot, self:VisibleFrames()
  end
  take()
  self.snapshotTicker = FC:NewTicker(SNAPSHOT_EVERY, take)
end

-- Popup frames visible now that were not visible in the baseline snapshot: the known ones (they may sit deeper
-- than UIParent's children), plus any child of UIParent that appeared. Without a baseline, known ones only.
function Shots:FindPopups(baseline)
  local found, seen = {}, {}
  for _, name in ipairs(POPUP_FRAMES) do
    local frame = _G[name]
    if visibleFrame(frame) and not (baseline and baseline[frame]) then
      found[#found + 1], seen[frame] = frame, true
    end
  end
  if baseline then
    for frame in pairs(self:VisibleFrames()) do
      if not baseline[frame] and not seen[frame] then found[#found + 1], seen[frame] = frame, true end
    end
  end
  return found
end

local function frameName(frame)
  local ok, name = pcall(frame.GetName, frame)
  return ok and name or "unnamed frame"
end

-- While a request waits: once its popup shows, the screenshot is taken POPUP_SETTLE seconds later (sooner
-- than the general delay, so the popup is still on screen). Without a popup the general delay applies.
function Shots:WatchPopups(now)
  for _, item in ipairs(self.queue.items) do
    if item.watchUntil and not item.popups and now <= item.watchUntil then
      local popups = self:FindPopups(item.baseline)
      if #popups > 0 then
        item.popups = popups
        item.eligibleAt = math.min(item.eligibleAt, now + POPUP_SETTLE)
        local names = {}
        for _, f in ipairs(popups) do names[#names + 1] = frameName(f) end
        FC.Diagnostics:Log("info", string.format("screenshot %s: popup %s after %.1f s", item.trigger,
          table.concat(names, ", "), now - item.createdAt))
      end
    end
  end
end

-- Returns true if the interface was hidden. It is always shown again (confirmation, failure or timeout).
function Shots:HideInterface(req)
  local mode = self:GetSettings().hideUI
  if (mode ~= "all" and mode ~= "popups") or self.uiHidden or not UIParent:IsVisible() then return false end
  local inCombat = InCombatLockdown and InCombatLockdown()
  local hidden = {}
  local ok = pcall(function()
    if mode == "all" and not inCombat and type(SetUIVisibility) == "function" then
      SetUIVisibility(false)
      hidden.visibility = true
      return
    end
    hidden.alpha = UIParent:GetAlpha()
    hidden.kept = {}
    if mode == "popups" then
      for _, frame in ipairs(req and req.popups or self:FindPopups(nil)) do
        if visibleFrame(frame) and frame.SetIgnoreParentAlpha then
          hidden.kept[#hidden.kept + 1] = { frame = frame, ignored = frame.IsIgnoringParentAlpha and frame:IsIgnoringParentAlpha() }
          frame:SetIgnoreParentAlpha(true)
        end
      end
    end
    UIParent:SetAlpha(0)
    if usable(Minimap) and Minimap:IsShown() then
      if inCombat and Minimap:IsProtected() then
        FC.Diagnostics:Log("info", "screenshot: the minimap is protected in combat and stays visible")
      else
        Minimap:Hide()
        hidden.minimap = true
      end
    end
  end)
  if not ok then
    self.uiHidden = hidden
    self:RestoreInterface()
    FC.Diagnostics:Log("warn", "interface could not be hidden for the screenshot")
    return false
  end
  self.uiHidden = hidden
  FC:After(UI_RESTORE_TIMEOUT, function() self:RestoreInterface() end)
  return true
end

function Shots:RestoreInterface()
  local hidden = self.uiHidden
  if not hidden then return end
  self.uiHidden = nil
  pcall(function()
    if hidden.visibility then SetUIVisibility(true) end
    if hidden.alpha then UIParent:SetAlpha(hidden.alpha) end
    for _, k in ipairs(hidden.kept or {}) do k.frame:SetIgnoreParentAlpha(k.ignored and true or false) end
  end)
  if hidden.minimap then self:ShowMinimap() end
end

-- If combat started meanwhile and the client protects the minimap, it comes back when combat ends.
function Shots:ShowMinimap()
  self.minimapPending = InCombatLockdown and InCombatLockdown() and Minimap:IsProtected() or false
  if not self.minimapPending then pcall(Minimap.Show, Minimap) end
end

Shots:RegisterEvent("PLAYER_REGEN_ENABLED", function(self)
  if self.minimapPending then self:ShowMinimap() end
end)

function Shots:TakeScreenshot(req)
  local rec = newRecord(req, "api_called")
  rec.capturedAt = time()
  rec.fileStamp = date("%m%d%y_%H%M%S", rec.capturedAt)
  FC.Storage:Append("screenshots", rec)
  req.record = rec

  local ok, err = pcall(Screenshot)
  if not ok then
    rec.status, rec.error = "failed", tostring(err)
    FC.Diagnostics:Log("error", "Screenshot() failed: " .. tostring(err))
    self:RestoreInterface()
    return
  end
  self.awaiting = rec
  FC:After(CONFIRM_TIMEOUT, function()
    if self.awaiting == rec then self.awaiting = nil end -- stays "api_called": no confirmation from the client
  end)
end

-------------------------------------------------------------------------------
-- Events
-------------------------------------------------------------------------------

Shots:RegisterMessage("FC_EVENT_RECORDED", function(self, _, record)
  local def = self.triggerByEvent[record.type]
  if def then self:Request(def.name, { record.id }, record) end
end)

Shots:RegisterEvent("SCREENSHOT_SUCCEEDED", function(self)
  self:RestoreInterface()
  local rec = self.awaiting
  if not rec then return end -- a screenshot taken by the player, not by us
  self.awaiting = nil
  rec.status = "confirmed"
  FC:IncrementStat("screenshots")
  FC:ConfirmCapability("screenshots")
end)

Shots:RegisterEvent("SCREENSHOT_FAILED", function(self)
  self:RestoreInterface()
  local rec = self.awaiting
  if not rec then return end
  self.awaiting = nil
  rec.status = "failed"
  FC.Diagnostics:Log("warn", "screenshot failed (client reported SCREENSHOT_FAILED)")
end)

Shots:RegisterEvent("PLAYER_LOGOUT", function(self)
  self.queue:Drain(function(r, outcome) self:OnRequestDone(r, outcome) end)
  self:UpdateCountdown(nil)
  self:RestoreInterface()
end)

-------------------------------------------------------------------------------
-- Status and settings helpers (used by the UI and /fjshot)
-------------------------------------------------------------------------------

function Shots:GetRecent(limit, stream)
  local records = (stream or FC.Storage:GetStream("screenshots")).records
  local out = {}
  for i = #records, math.max(1, #records - (limit or 20) + 1), -1 do out[#out + 1] = records[i] end
  return out
end

function Shots:SetCooldown(seconds)
  self:GetSettings().cooldown = seconds
  self.queue.cooldown = seconds
end

-------------------------------------------------------------------------------
-- Options (shown on the Settings page)
-------------------------------------------------------------------------------

local function settings() return Shots:GetSettings() end

FC:RegisterOptionSection("screenshots", "SECTION_SHOT_TRIGGERS", 20, "Interface\\Icons\\INV_Misc_Spyglass_02")
for i, name in ipairs(TRIGGER_OPTIONS) do
  FC:RegisterOption({ section = "screenshots", type = "toggle", labelKey = "OPT_SHOT_" .. name:upper(), order = 1 + i,
    tooltipKey = name == "dungeon" and "OPT_SHOT_DUNGEON_TIP" or nil,
    get = function() return settings().triggers[name] end, set = function(v) settings().triggers[name] = v end })
end
FC:RegisterOption({ section = "screenshots", type = "choice", labelKey = "OPT_SHOT_HIDE_UI",
  tooltipKey = "OPT_SHOT_HIDE_UI_TIP", order = 9, buttonWidth = 82,
  choices = { { value = "off", labelKey = "OPT_SHOT_HIDE_OFF" }, { value = "all", labelKey = "OPT_SHOT_HIDE_ALL" },
    { value = "popups", labelKey = "OPT_SHOT_HIDE_POPUPS" } },
  get = function() return settings().hideUI end,
  set = function(v) settings().hideUI = v; Shots:UpdateSnapshots() end })
FC:RegisterOption({ section = "screenshots", type = "toggle", labelKey = "OPT_SHOT_COUNTDOWN",
  tooltipKey = "OPT_SHOT_COUNTDOWN_TIP", order = 10,
  get = function() return settings().countdown end, set = function(v) settings().countdown = v end })

-- A test screenshot with the current delay, countdown and hide settings.
function Shots:TestShot()
  self:Request("manual", {})
  FC:Print(L.SHOT_TEST_QUEUED)
end
FC:RegisterOption({ section = "screenshots", type = "button", labelKey = "SHOT_TEST_BUTTON",
  tooltipKey = "SHOT_TEST_TIP", order = 11, onClick = function() Shots:TestShot() end })
FC:RegisterOption({ section = "screenshots", column = 2, type = "choice", labelKey = "OPT_SHOT_DELAY", order = 9,
  choices = { { value = 0, text = "0 s" }, { value = 2, text = "2 s" }, { value = 5, text = "5 s" }, { value = 10, text = "10 s" } },
  get = function() return settings().delay end, set = function(v) settings().delay = v end })
FC:RegisterOption({ section = "screenshots", column = 2, type = "toggle", labelKey = "OPT_SHOT_BYPASS",
  tooltipKey = "OPT_SHOT_BYPASS_TIP", order = 10,
  get = function() return settings().bypass end, set = function(v) settings().bypass = v end })
FC:RegisterOption({ section = "screenshots", column = 2, type = "choice", labelKey = "OPT_SHOT_COOLDOWN", order = 11,
  choices = { { value = 10, text = "10 s" }, { value = 30, text = "30 s" }, { value = 60, text = "60 s" } },
  get = function() return settings().cooldown end, set = function(v) Shots:SetCooldown(v) end })
FC:RegisterOption({ section = "screenshots", column = 2, type = "choice", labelKey = "OPT_SHOT_DWELL", order = 12,
  choices = { { value = 3, text = "3 s" }, { value = 5, text = "5 s" }, { value = 10, text = "10 s" } },
  get = function() return FC.db.settings.modules.Travel.dwellSeconds end,
  set = function(v) FC.db.settings.modules.Travel.dwellSeconds = v end })

-------------------------------------------------------------------------------
-- /fjshot (spec F-003)
-------------------------------------------------------------------------------

local function onOff(v) return v and L.SHOT_ON or L.SHOT_OFF end

local function printStatus()
  local s = settings()
  FC:Print(string.format(L.SHOT_STATUS_LINE, Shots.queue:Count(), s.delay, s.cooldown, onOff(s.bypass)))
  local parts = {}
  for _, name in ipairs(TRIGGER_OPTIONS) do
    parts[#parts + 1] = L["TRIGGER_" .. name:upper()] .. ": " .. onOff(s.triggers[name])
  end
  FC:Print("  " .. table.concat(parts, ", "))
  local last = Shots:GetRecent(1)[1]
  if last then
    FC:Print("  " .. string.format(L.SHOT_LAST, Util.FormatTime(last.capturedAt or last.requestedAt),
      L["SHOT_STATUS_" .. last.status:upper()]))
  end
end

local function handle(msg)
  local cmd, arg = (msg or ""):lower():match("^(%S*)%s*(.-)$")
  local s = settings()
  if cmd == "" or cmd == "status" then
    printStatus()
  elseif cmd == "api" then
    FC:Print(string.format(L.SHOT_API_LINE, type(Screenshot) == "function" and L.SHOT_ON or L.SHOT_OFF,
      tostring(FC.eventStatus.SCREENSHOT_SUCCEEDED), tostring(FC.eventStatus.SCREENSHOT_FAILED)))
  elseif cmd == "test" then
    Shots:TestShot()
  elseif Shots.triggers[cmd] and cmd ~= "manual" and (arg == "on" or arg == "off") then
    s.triggers[cmd] = (arg == "on")
    printStatus()
  elseif cmd == "cooldown" and tonumber(arg) then
    Shots:SetCooldown(math.max(0, math.floor(tonumber(arg))))
    printStatus()
  elseif cmd == "delay" and tonumber(arg) then
    s.delay = math.max(0, math.min(60, tonumber(arg)))
    printStatus()
  elseif cmd == "dwell" and tonumber(arg) then
    FC.db.settings.modules.Travel.dwellSeconds = math.max(0, math.floor(tonumber(arg)))
    FC:Print(L.SHOT_SET_OK)
  elseif cmd == "bypass" and (arg == "on" or arg == "off") then
    s.bypass = (arg == "on")
    printStatus()
  else
    FC:Print(L.SHOT_USAGE)
  end
end

SLASH_FOREVERCHRONICLESHOT1 = "/fjshot"
SlashCmdList.FOREVERCHRONICLESHOT = function(msg) FC:SafeCall(handle, msg) end
FC:RegisterCommand("shot", "CMD_SHOT", handle, 60)
