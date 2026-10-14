-- Forever Chronicle - Gear module
-- Snapshot of the equipped items, so the gear can be shown for characters that are not being played (alts,
-- friends via the desktop app). Read at login and whenever the equipment changes.
--
-- snapshots.gear = { updatedAt, slots = { { slot, slotName, link, item, icon, quality } } }
--   slot: inventory slot ID; link: item link (the game builds tooltips from it); quality: 0 poor ... 7 heirloom

local ADDON, FC = ...
local Util = FC.Util

local Gear = FC:NewModule("Gear", { order = 36 })

-- The slots of the character window (same order as on the overview).
Gear.SLOTS = { "HeadSlot", "NeckSlot", "ShoulderSlot", "BackSlot", "ChestSlot", "ShirtSlot", "TabardSlot",
  "WristSlot", "HandsSlot", "WaistSlot", "LegsSlot", "FeetSlot", "Finger0Slot", "Finger1Slot", "Trinket0Slot",
  "Trinket1Slot", "MainHandSlot", "SecondaryHandSlot", "RangedSlot" }

FC:RegisterCapability("gear", "CAP_GEAR", function()
  return type(GetInventoryItemLink) == "function" and type(GetInventorySlotInfo) == "function"
end)

-- Reads the equipped items; the snapshot only changes when the gear did.
function Gear:Scan()
  local slots, signature = {}, {}
  for _, name in ipairs(self.SLOTS) do
    local id = Util.SafeValue("number", GetInventorySlotInfo, name)
    local link = id and Util.SafeValue("string", GetInventoryItemLink, "player", id)
    if link then
      local icon = Util.SafeValue(nil, GetInventoryItemTexture, "player", id)
      slots[#slots + 1] = { slot = id, slotName = name, link = link, item = tonumber(link:match("item:(%d+)")),
        icon = (type(icon) == "number" or type(icon) == "string") and icon or nil,
        quality = Util.SafeValue("number", GetInventoryItemQuality, "player", id) }
      signature[#signature + 1] = id .. "=" .. link
    end
  end
  signature = table.concat(signature, ";")
  local snap = FC.Storage:GetSnapshot("gear")
  if snap.signature ~= signature then
    snap.slots, snap.signature, snap.updatedAt = slots, signature, time()
  end
  if #slots > 0 then FC:ConfirmCapability("gear") end
  return #slots
end

-- The gear of a character as { [slotID] = entry } (default: the played character's snapshot).
function Gear:BySlot(char)
  local snap
  if not char or char == FC.char then
    snap = FC.Storage:GetSnapshot("gear")
  elseif type(char.snapshots) == "table" then
    snap = char.snapshots.gear
  end
  local out = {}
  for _, entry in ipairs(type(snap) == "table" and type(snap.slots) == "table" and snap.slots or {}) do
    if type(entry) == "table" and type(entry.slot) == "number" then out[entry.slot] = entry end
  end
  return out
end

function Gear:ScheduleScan(delay)
  if self.pending then return end
  self.pending = true
  FC:After(delay or 1, function()
    self.pending = nil
    self:Scan()
  end)
end

function Gear:OnEnable()
  self:Scan()
  self:ScheduleScan(3) -- item data can arrive a moment after login
end

Gear:RegisterEvent("PLAYER_EQUIPMENT_CHANGED", function(self) self:ScheduleScan() end)
