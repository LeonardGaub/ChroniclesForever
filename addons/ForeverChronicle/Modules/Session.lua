-- Forever Chronicle - Session module (spec F-004)
-- Sessions, reload detection and server-reported played time.
--
-- Session records live in the "sessions" stream and are updated in place:
--   { id, seq, startedAt, endedAt, endReason, reloads, startLevel, endLevel,
--     playedTotal, playedLevel, playedAt }
-- endReason: "open" while playing, "logout" after the last save (logout or /reload),
-- "incomplete" if a session was found still open at the next login.
-- A client crash loses everything after the last save; the session then ends at that save.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Session = FC:NewModule("Session", { order = 20, defaults = { autoPlayed = true } })

FC.Storage:DefineStream("sessions", 1000)

local PLAYED_REQUEST_DELAY = 10
local PLAYED_TIMEOUT = 10

-------------------------------------------------------------------------------
-- Registrations
-------------------------------------------------------------------------------

FC:RegisterCapability("played_time", "CAP_PLAYED", function()
  return type(RequestTimePlayed) == "function"
end)

FC:RegisterEventType("session_started", {
  icon = "Interface\\Icons\\INV_Misc_PocketWatch_01",
  format = function() return L.EVT_SESSION_STARTED end,
})

FC:RegisterStat("sessions", { labelKey = "STAT_SESSIONS", order = 10 })
FC:RegisterStat("tracked_time", { labelKey = "STAT_TRACKED_TIME", order = 11, format = "duration",
  compute = function() return Session:GetTrackedSeconds() end })
FC:RegisterStat("played_total", { labelKey = "STAT_PLAYED_TOTAL", order = 12, format = "duration" })

FC:RegisterOption({ module = "Session", key = "autoPlayed", type = "toggle", column = 2,
  labelKey = "OPT_AUTO_PLAYED", tooltipKey = "OPT_AUTO_PLAYED_TIP", order = 20 })

FC:RegisterCommand("played", "CMD_PLAYED", function()
  if type(RequestTimePlayed) == "function" then RequestTimePlayed() end
end, 50)

-------------------------------------------------------------------------------
-- Session records
-------------------------------------------------------------------------------

local function sessionRecords()
  return FC.Storage:GetStream("sessions").records
end

local function lastSession()
  local records = sessionRecords()
  return records[#records]
end

function Session:GetCurrent()
  return self.current
end

function Session:GetTrackedSeconds()
  local total = 0
  for _, s in ipairs(sessionRecords()) do
    local stop = s.endedAt or time()
    if stop > s.startedAt then total = total + (stop - s.startedAt) end
  end
  return total
end

function Session:Start()
  local level = FC.char.info.level
  local record = FC.Storage:Append("sessions", {
    id = Util.NewId(), startedAt = time(), endReason = "open", reloads = 0, startLevel = level, endLevel = level,
  })
  self:Activate(record)
  FC:IncrementStat("sessions")
  FC:Record("session_started", { level = level })
  self.requestPlayedOnce = true
end

function Session:Activate(record)
  self.current = record
  FC.sessionId = record.id
  FC.sessionStartedAt = record.startedAt
end

function Session:OnEnteringWorld(_, isInitialLogin, isReloadingUi)
  if self.current then return end -- loading screen within the session
  isInitialLogin, isReloadingUi = Util.Plain(isInitialLogin), Util.Plain(isReloadingUi)
  local last = lastSession()

  if isReloadingUi == true and last then
    -- /reload: continue the session that the logout handler closed provisionally.
    last.endedAt, last.endReason = nil, "open"
    last.reloads = (last.reloads or 0) + 1
    self:Activate(last)
  else
    if last and last.endReason == "open" then
      last.endReason = "incomplete"
      last.endedAt = last.endedAt or last.startedAt
    end
    self:Start()
  end

  if self.requestPlayedOnce and self:GetSettings().autoPlayed then
    self.requestPlayedOnce = false
    FC:After(PLAYED_REQUEST_DELAY, function() self:RequestPlayedQuietly() end)
  end
end

function Session:OnLogout()
  local s = self.current
  if s then
    s.endedAt = time()
    s.endReason = "logout"
    s.endLevel = FC.char.info.level
  end
  FC.Storage:TrimAll()
end

-------------------------------------------------------------------------------
-- Played time
-- Chat output is suppressed by unregistering TIME_PLAYED_MSG on chat frames during our own
-- request (confirmed in Phase 0). No Blizzard function is replaced, so nothing is tainted.
-------------------------------------------------------------------------------

function Session:RequestPlayedQuietly()
  if type(RequestTimePlayed) ~= "function" then return end
  local frames = {}
  for i = 1, (NUM_CHAT_WINDOWS or 10) do
    local cf = _G["ChatFrame" .. i]
    if cf and cf.IsEventRegistered and Util.SafeValue("boolean", cf.IsEventRegistered, cf, "TIME_PLAYED_MSG") then
      cf:UnregisterEvent("TIME_PLAYED_MSG")
      frames[#frames + 1] = cf
    end
  end
  if #frames == 0 then return end -- nothing to suppress safely; wait for a manual /played

  local pending = { frames = frames }
  self.pendingPlayed = pending
  local function restore()
    if pending.restored then return end
    pending.restored = true
    for _, cf in ipairs(pending.frames) do pcall(cf.RegisterEvent, cf, "TIME_PLAYED_MSG") end
    if self.pendingPlayed == pending then self.pendingPlayed = nil end
  end
  pending.restore = restore
  if not pcall(RequestTimePlayed) then restore() return end
  FC:After(PLAYED_TIMEOUT, restore)
end

function Session:OnTimePlayed(_, total, level)
  total, level = Util.Plain(total), Util.Plain(level)
  if type(total) == "number" then
    local s = self.current
    if s then
      s.playedTotal, s.playedLevel, s.playedAt = total, level, time()
    end
    FC:SetStat("played_total", total)
    FC:ConfirmCapability("played_time")
  end
  -- Re-register the chat frames on the next frame so they do not receive this event.
  if self.pendingPlayed then FC:After(0.5, self.pendingPlayed.restore) end
end

Session:RegisterEvent("PLAYER_ENTERING_WORLD", "OnEnteringWorld")
Session:RegisterEvent("PLAYER_LOGOUT", "OnLogout")
Session:RegisterEvent("TIME_PLAYED_MSG", "OnTimePlayed")
