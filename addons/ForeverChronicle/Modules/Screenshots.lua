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

local Shots = FC:NewModule("Screenshots", { order = 50, defaults = {
  enabled = true,
  countdown = true,   -- on-screen countdown; hidden before the capture
  hideUI = false,     -- hide the whole interface for the screenshot (not possible in combat)
  delay = 5,          -- seconds between the event and the screenshot (all automatic triggers)
  cooldown = 30,
  bypass = true,
  capacity = 50,
  triggers = { level = true, achievement = true, rare = true, zone = true, quest = false, death = false },
} })

FC.Storage:DefineStream("screenshots", 2000, "Interface\\Icons\\INV_Misc_Spyglass_02")

local TICK = 0.2
local CONFIRM_TIMEOUT = 5
local HIDE_BEFORE_CAPTURE = 0.15    -- seconds between hiding the countdown and taking the screenshot
local HIDE_UI_BEFORE_CAPTURE = 0.25 -- same, when the whole interface is hidden
local UI_RESTORE_TIMEOUT = 1.5      -- the interface is shown again at the latest after this time

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
  self.queue = FC.ScreenshotQueue.New({ capacity = s.capacity, cooldown = s.cooldown, minGap = 2, coalesceWindow = 2 })
end

function Shots:IsTriggerEnabled(name)
  local s = self:GetSettings()
  local def = self.triggers[name]
  if def and def.always then return true end
  return s.enabled and s.triggers[name] == true
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
  local hidden = self:HideInterface()
  FC:After(hidden and HIDE_UI_BEFORE_CAPTURE or HIDE_BEFORE_CAPTURE, function()
    self.capturing = false
    self:TakeScreenshot(req)
  end)
end

-- Hides the interface like Alt+Z. The client does not allow this in combat; the screenshot then shows the UI.
-- Returns true if the interface was hidden. It is always shown again (confirmation, failure or timeout).
function Shots:HideInterface()
  if not self:GetSettings().hideUI or self.uiHidden or not UIParent:IsVisible() then return false end
  if InCombatLockdown and InCombatLockdown() then
    FC.Diagnostics:Log("info", "interface not hidden for the screenshot: in combat")
    return false
  end
  local useVisibility = type(SetUIVisibility) == "function"
  local ok = pcall(function()
    if useVisibility then SetUIVisibility(false) else UIParent:Hide() end
  end)
  if not ok then return false end
  self.uiHidden = { useVisibility = useVisibility }
  FC:After(UI_RESTORE_TIMEOUT, function() self:RestoreInterface() end)
  return true
end

function Shots:RestoreInterface()
  local hidden = self.uiHidden
  if not hidden then return end
  self.uiHidden = nil
  pcall(function()
    if hidden.useVisibility then SetUIVisibility(true) else UIParent:Show() end
  end)
end

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
-- Status and settings helpers (used by the UI and /fcshot)
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
-- Options (shown on the Screenshots page)
-------------------------------------------------------------------------------

local function settings() return Shots:GetSettings() end

FC:RegisterOptionSection("screenshots", "SECTION_SHOT_TRIGGERS", 20, "Interface\\Icons\\INV_Misc_Spyglass_02")
FC:RegisterOption({ section = "screenshots", type = "toggle", labelKey = "OPT_SHOT_ENABLED", order = 1,
  get = function() return settings().enabled end, set = function(v) settings().enabled = v end })
for i, name in ipairs({ "level", "achievement", "rare", "zone", "quest", "death" }) do
  FC:RegisterOption({ section = "screenshots", type = "toggle", labelKey = "OPT_SHOT_" .. name:upper(), order = 1 + i,
    get = function() return settings().triggers[name] end, set = function(v) settings().triggers[name] = v end })
end
FC:RegisterOption({ section = "screenshots", type = "toggle", labelKey = "OPT_SHOT_HIDE_UI",
  tooltipKey = "OPT_SHOT_HIDE_UI_TIP", order = 8,
  get = function() return settings().hideUI end, set = function(v) settings().hideUI = v end })
FC:RegisterOption({ section = "screenshots", type = "toggle", labelKey = "OPT_SHOT_COUNTDOWN",
  tooltipKey = "OPT_SHOT_COUNTDOWN_TIP", order = 9,
  get = function() return settings().countdown end, set = function(v) settings().countdown = v end })
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
-- /fcshot (spec F-003)
-------------------------------------------------------------------------------

local function onOff(v) return v and L.SHOT_ON or L.SHOT_OFF end

local function printStatus()
  local s = settings()
  FC:Print(string.format(L.SHOT_STATUS_LINE, onOff(s.enabled), Shots.queue:Count(), s.delay, s.cooldown, onOff(s.bypass)))
  local parts = {}
  for _, name in ipairs({ "level", "achievement", "rare", "zone", "quest", "death" }) do
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
    Shots:Request("manual", {})
    FC:Print(L.SHOT_TEST_QUEUED)
  elseif cmd == "on" or cmd == "off" then
    s.enabled = (cmd == "on")
    printStatus()
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

SLASH_FOREVERCHRONICLESHOT1 = "/fcshot"
SlashCmdList.FOREVERCHRONICLESHOT = function(msg) FC:SafeCall(handle, msg) end
FC:RegisterCommand("shot", "CMD_SHOT", handle, 60)
