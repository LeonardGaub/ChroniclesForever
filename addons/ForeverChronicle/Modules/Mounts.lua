-- Journey Forever - Mounts module
-- New mounts ("mount_learned"): the mount journal's collected mounts are compared with the ones known before.
-- The first run takes the collection as known without events; data.first marks the character's very first mount
-- (it has its own screenshot trigger). Riding itself is the "M" flag of the route (Modules/Positions.lua).

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Mounts = FC:NewModule("Mounts", { order = 34 })

FC:RegisterCapability("mounts", "CAP_MOUNTS", function()
  return C_MountJournal ~= nil and type(C_MountJournal.GetMountIDs) == "function"
end)

FC:RegisterEventType("mount_learned", {
  icon = "Interface\\Icons\\Ability_Mount_RidingHorse", category = "loot", highlight = "milestone",
  getIcon = function(r) return r.data.icon end,
  format = function(r)
    return string.format(r.data.first and L.EVT_FIRST_MOUNT or L.EVT_MOUNT_LEARNED, r.data.name or "?")
  end,
})

-- mountID -> { name, spellID, icon } of the collected mounts, or nil when the client has no mount journal.
function Mounts:Collected()
  local api = C_MountJournal
  local ids = api and Util.SafeValue("table", api.GetMountIDs)
  if not ids then return nil end
  local out = {}
  for _, id in ipairs(ids) do
    id = Util.Plain(id)
    if type(id) == "number" then
      local name, spellID, icon, _, _, _, _, _, _, _, collected = Util.SafeValues(api.GetMountInfoByID, id)
      if collected == true then
        out[id] = { name = type(name) == "string" and name or nil, spellID = type(spellID) == "number" and spellID or nil,
          icon = (type(icon) == "number" or type(icon) == "string") and icon or nil }
      end
    end
  end
  return out
end

function Mounts:Scan()
  local collected = self:Collected()
  if not collected then return end
  local state = FC.Storage:GetState("Mounts")
  local first = state.known == nil
  state.known = state.known or {}
  for id, mount in pairs(collected) do
    if not state.known[id] then
      state.known[id] = true
      if not first then
        FC:Record("mount_learned", { mountID = id, name = mount.name, spellID = mount.spellID, icon = mount.icon,
          first = (state.count or 0) == 0 or nil })
      end
      state.count = (state.count or 0) + 1
    end
  end
  FC:ConfirmCapability("mounts")
end

function Mounts:ScheduleScan()
  FC:Debounce(self, "pending", 1, function() self:Scan() end)
end

function Mounts:OnEnable()
  self:Scan()
end

Mounts:RegisterEvent("NEW_MOUNT_ADDED", function(self) self:ScheduleScan() end)
Mounts:RegisterEvent("COMPANION_LEARNED", function(self) self:ScheduleScan() end)
Mounts:RegisterEvent("PLAYER_MOUNT_DISPLAY_CHANGED", function(self) self:ScheduleScan() end)
