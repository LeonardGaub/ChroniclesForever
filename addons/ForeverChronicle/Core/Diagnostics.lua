-- Journey Forever - Diagnostics
-- A small rotating log and the capability registry.
--
-- Capability status:
--   missing   - required API/event does not exist in this client
--   present   - API/event exists, but the feature has not been observed working yet
--   confirmed - observed working at least once on this client build (persisted)

local ADDON, FC = ...

local Diagnostics = {}
FC.Diagnostics = Diagnostics

local LOG_CAP = 300
local early = {} -- log lines written before the database is loaded

function Diagnostics:Log(level, msg)
  local line = string.format("%s [%s] %s", date("%Y-%m-%d %H:%M:%S"), level, tostring(msg))
  local log = FC.db and FC.db.diagnostics.log or early
  log[#log + 1] = line
  if #log > LOG_CAP then table.remove(log, 1) end
  if FC.db and FC.db.settings.debug then
    FC:Print("|cff999999" .. line .. "|r")
  elseif level == "error" and FC.ready and not self.errorHinted then
    self.errorHinted = true
    FC:Print("|cffff4040" .. FC.L.DIAG_ERROR_HINT .. "|r")
  end
end

function Diagnostics:GetLog()
  return FC.db and FC.db.diagnostics.log or early
end

-------------------------------------------------------------------------------
-- Capabilities
-------------------------------------------------------------------------------

Diagnostics.capabilities = {} -- key -> { key, label, probe, order }
local order = 0

-- probe(): returns true if everything the feature needs exists in this client.
function FC:RegisterCapability(key, labelKey, probe)
  order = order + 1
  Diagnostics.capabilities[key] = { key = key, labelKey = labelKey, probe = probe, order = order }
end

-- Marks a capability as observed working. Called by modules the first time real data arrives.
function FC:ConfirmCapability(key)
  local stored = self.db.diagnostics.capabilities[key]
  if stored and stored.status == "confirmed" and stored.build == FC.Util.ClientBuild() then return end
  self.db.diagnostics.capabilities[key] = { status = "confirmed", confirmedAt = time(), build = FC.Util.ClientBuild() }
  Diagnostics:Log("info", "capability confirmed: " .. key)
end

function Diagnostics:RunProbes()
  for key, cap in pairs(self.capabilities) do
    local ok, available = pcall(cap.probe)
    cap.available = ok and available == true
    if not cap.available then
      self:Log("warn", "capability missing: " .. key)
    end
  end
end

-- Sorted list of { key, label, status, confirmedAt } for the UI.
function Diagnostics:GetCapabilities()
  local list = {}
  for key, cap in pairs(self.capabilities) do
    local stored = FC.db.diagnostics.capabilities[key]
    local status = "missing"
    if cap.available then
      status = (stored and stored.status == "confirmed") and "confirmed" or "present"
    end
    list[#list + 1] = { key = key, label = FC.L[cap.labelKey], status = status,
      confirmedAt = stored and stored.confirmedAt, order = cap.order }
  end
  table.sort(list, function(a, b) return a.order < b.order end)
  return list
end
