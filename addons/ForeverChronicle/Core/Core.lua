-- Journey Forever - Core
-- Namespace, module registry, event dispatch, internal messages and timers.
--
-- Extension model: every feature is a module created with FC:NewModule(). A module can
--   * declare `defaults` (its settings, stored under settings.modules[name])
--   * register game events and internal messages
--   * register event types (FC:RegisterEventType), stats (FC:RegisterStat),
--     capabilities (FC:RegisterCapability), options (FC:RegisterOption) and commands (FC:RegisterCommand)
-- The core never needs to know about individual modules.

local ADDON, FC = ...
_G.ForeverChronicle = FC

FC.VERSION = (C_AddOns and C_AddOns.GetAddOnMetadata and C_AddOns.GetAddOnMetadata(ADDON, "Version")) or "dev"
FC.SCHEMA_VERSION = 2 -- 2: streams packed in the saved file (Core/Storage.lua)

-------------------------------------------------------------------------------
-- Error-safe calls
-------------------------------------------------------------------------------

local function errorHandler(err)
  if FC.Diagnostics then
    FC.Diagnostics:Log("error", tostring(err))
  end
  return err
end

-- Calls fn(...) and logs errors instead of raising them, so one tracker cannot break others.
function FC:SafeCall(fn, ...)
  return xpcall(fn, errorHandler, ...)
end

-------------------------------------------------------------------------------
-- Modules
-------------------------------------------------------------------------------

FC.modules = {}
FC.moduleOrder = {}

local Module = {}
Module.__index = Module

-- Register a game event. handler is a method name (string) or a function(module, event, ...).
function Module:RegisterEvent(event, handler)
  return FC:RegisterEventHandler(event, self, handler or event)
end

-- Register an internal message (sent with FC:SendMessage).
function Module:RegisterMessage(message, handler)
  FC.messages[message] = FC.messages[message] or {}
  table.insert(FC.messages[message], { module = self, handler = handler or message })
end

-- This module's settings table (defaults already applied).
function Module:GetSettings()
  return FC.db.settings.modules[self.name]
end

function FC:NewModule(name, opts)
  assert(not self.modules[name], "module already exists: " .. name)
  local module = setmetatable({ name = name, order = (opts and opts.order) or 100,
    defaults = (opts and opts.defaults) or {} }, Module)
  self.modules[name] = module
  table.insert(self.moduleOrder, module)
  -- A module from an addon that loads after this one (a companion addon): the saved variables
  -- are already there, so its settings get their defaults right away.
  if self.db then
    self.db.settings.modules[name] = self.Util.MergeDefaults(self.db.settings.modules[name] or {}, module.defaults)
  end
  return module
end

function FC:GetModule(name)
  return self.modules[name]
end

local function sortedModules()
  table.sort(FC.moduleOrder, function(a, b)
    if a.order ~= b.order then return a.order < b.order end
    return a.name < b.name
  end)
  return FC.moduleOrder
end

-- Calls module[method](module) on all modules in order.
local function callModules(method)
  for _, module in ipairs(sortedModules()) do
    if type(module[method]) == "function" then
      FC:SafeCall(module[method], module)
    end
  end
end

-------------------------------------------------------------------------------
-- Game events
-------------------------------------------------------------------------------

local eventFrame = CreateFrame("Frame")
local eventHandlers = {}   -- event -> list of { module, handler }
FC.eventStatus = {}        -- event -> "registered" | "invalid"

function FC:RegisterEventHandler(event, module, handler)
  if not eventHandlers[event] then
    if C_EventUtils and C_EventUtils.IsEventValid then
      local ok, valid = pcall(C_EventUtils.IsEventValid, event)
      if ok and valid == false then
        self.eventStatus[event] = "invalid"
        if self.Diagnostics then self.Diagnostics:Log("warn", "unknown event " .. event) end
        return false
      end
    end
    local ok = pcall(eventFrame.RegisterEvent, eventFrame, event)
    if not ok then
      self.eventStatus[event] = "invalid"
      return false
    end
    self.eventStatus[event] = "registered"
    eventHandlers[event] = {}
  end
  table.insert(eventHandlers[event], { module = module, handler = handler })
  return true
end

local function dispatch(list, name, ...)
  for i = 1, #list do
    local entry = list[i]
    local fn = entry.handler
    if type(fn) == "string" then fn = entry.module[fn] end
    if type(fn) == "function" then
      FC:SafeCall(fn, entry.module, name, ...)
    end
  end
end

eventFrame:SetScript("OnEvent", function(_, event, ...)
  if event == "ADDON_LOADED" then
    if ... == ADDON then FC:OnAddonLoaded() end
    return
  elseif event == "PLAYER_LOGIN" then
    FC:OnPlayerLogin()
  end
  local list = eventHandlers[event]
  if list then dispatch(list, event, ...) end
  -- After every logout handler (the last samples, the friends share): pack the data for the saved file.
  if event == "PLAYER_LOGOUT" and FC.db then FC:SafeCall(function() FC.Storage:PrepareSave() end) end
end)
eventFrame:RegisterEvent("ADDON_LOADED")
eventFrame:RegisterEvent("PLAYER_LOGIN")
eventFrame:RegisterEvent("PLAYER_LOGOUT")

-------------------------------------------------------------------------------
-- Internal messages
-------------------------------------------------------------------------------

FC.messages = {}

function FC:SendMessage(message, ...)
  local list = self.messages[message]
  if list then dispatch(list, message, ...) end
end

-------------------------------------------------------------------------------
-- Timers
-------------------------------------------------------------------------------

function FC:After(seconds, fn)
  C_Timer.After(seconds, function() FC:SafeCall(fn) end)
end

-- Runs fn after `seconds` unless a call with the same owner and key is already waiting.
function FC:Debounce(owner, key, seconds, fn)
  if owner[key] then return end
  owner[key] = true
  self:After(seconds, function()
    owner[key] = nil
    fn()
  end)
end

function FC:NewTicker(seconds, fn)
  return C_Timer.NewTicker(seconds, function() FC:SafeCall(fn) end)
end

-------------------------------------------------------------------------------
-- Lifecycle
-------------------------------------------------------------------------------

-- Saved variables are available: set up storage, settings and module defaults.
function FC:OnAddonLoaded()
  self.Storage:Initialize()
  for _, module in ipairs(sortedModules()) do
    self.db.settings.modules[module.name] = self.Util.MergeDefaults(
      self.db.settings.modules[module.name] or {}, module.defaults)
  end
  self:ApplyLanguage()
  callModules("OnInitialize")
end

-- Character data is available: open the character record and enable modules.
function FC:OnPlayerLogin()
  self.Storage:OpenCharacter()
  callModules("OnEnable")
  self.Diagnostics:RunProbes()
  self.ready = true
  self:SendMessage("FC_READY")
end

function FC:Print(msg)
  local frame = DEFAULT_CHAT_FRAME or ChatFrame1
  if frame then frame:AddMessage("|cffffd100Journey Forever|r: " .. tostring(msg)) end
end
