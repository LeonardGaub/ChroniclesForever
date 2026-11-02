-- Journey Forever - Loot module
-- Notable items ("item_obtained"): what a player would tell a friend about, not every drop. After each change of the
-- bags the items carried (bags + equipped) are counted again; an item ID whose count went up was obtained. Where it
-- came from is told by what was open or happened just before: the loot window (a boss, a rare enemy, fishing or
-- anything else), a quest turn-in, the profession window, a vendor, the mailbox, a trade or the auction house.
--
-- Trash or treasure, in this order:
--   1. Never: items taken out of the bank, items the character had before (each item ID counts once), quest items
--      and anything that stacks (reagents, potions, food, cloth, ...).
--   2. Epic and better: always. The first epic is a milestone and has its own screenshot trigger.
--   3. Rare (blue) gear that mattered, if "blueGear" is on: when it drops from a boss or a rare enemy, or when the
--      player puts it on within EQUIP_WITHIN of getting it (recorded when it is put on). Blue gear that goes to
--      the vendor or the auction house stays out.
--   4. Everything else (junk, white and green items, blue items that are no gear) is trash.
--
-- Event data: item, link, name, quality, icon, source = "boss" | "rare" | "fishing" | "loot" | "quest" | "craft" |
-- "vendor" | "mail" | "trade" | "auction" | "other", from (boss or rare name), equipped (put on: rule 3),
-- obtainedAt (when it was obtained, for rule 3), first (the first epic).

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Loot = FC:NewModule("Loot", { order = 38, defaults = { blueGear = true } })

local RARE, EPIC = 3, 4
local QUEST_CLASS = 12
local KILL_WITHIN = 180     -- seconds: loot this soon after a boss or rare kill comes from it
local AFTER_WINDOW = 3      -- seconds a closed window still counts (the bags update a moment later)
local EQUIP_WITHIN = 3600   -- seconds: blue gear put on within this time mattered
local EQUIP_SLOTS = 19

FC:RegisterCapability("loot", "CAP_LOOT", function()
  return C_Container ~= nil and type(C_Container.GetContainerItemInfo) == "function"
    and FC.eventStatus.BAG_UPDATE_DELAYED == "registered"
end)

FC:RegisterEventCategory("loot", { labelKey = "CAT_LOOT", icon = "Interface\\Icons\\INV_Misc_Bag_10", order = 55 })

FC:RegisterEventType("item_obtained", {
  icon = "Interface\\Icons\\INV_Misc_Bag_10", category = "loot",
  getIcon = function(r) return r.data.icon end,
  format = function(r)
    local item = r.data.link or r.data.name or ("#" .. tostring(r.data.item))
    return string.format(r.data.equipped and L.EVT_ITEM_EQUIPPED or L.EVT_ITEM_OBTAINED, item)
  end,
  details = function(r)
    local d = r.data
    local source = d.source and L["LOOT_SOURCE_" .. d.source:upper()]
    if not source then return nil end
    return { d.from and string.format(L.LOOT_FROM, source, d.from) or source }
  end,
})

-------------------------------------------------------------------------------
-- Where items come from
-------------------------------------------------------------------------------

Loot.open = {}       -- window -> true while open, or the time it closed

local WINDOWS = {
  LOOT_OPENED = { "loot", true }, LOOT_CLOSED = { "loot", false },
  MERCHANT_SHOW = { "vendor", true }, MERCHANT_CLOSED = { "vendor", false },
  MAIL_SHOW = { "mail", true }, MAIL_CLOSED = { "mail", false },
  TRADE_SHOW = { "trade", true }, TRADE_CLOSED = { "trade", false },
  AUCTION_HOUSE_SHOW = { "auction", true }, AUCTION_HOUSE_CLOSED = { "auction", false },
  BANKFRAME_OPENED = { "bank", true }, BANKFRAME_CLOSED = { "bank", false },
}

for event, def in pairs(WINDOWS) do
  Loot:RegisterEvent(event, function(self)
    self.open[def[1]] = def[2] or time()
    if event == "LOOT_OPENED" then self.fishing = Util.SafeValue("boolean", IsFishingLoot) == true end
  end)
end

function Loot:IsOpen(window)
  local v = self.open[window]
  return v == true or (type(v) == "number" and time() - v <= AFTER_WINDOW)
end

Loot:RegisterEvent("QUEST_TURNED_IN", function(self) self.questAt = time() end)

-- The source of items obtained now: (source, from), or "bank" for items taken out of the bank.
function Loot:Source()
  local now = time()
  if self:IsOpen("bank") then return "bank" end
  if self:IsOpen("loot") then
    if self.fishing then return "fishing" end
    local boss = FC:GetModule("Dungeons").lastKill
    if boss and now - boss.time <= KILL_WITHIN then return "boss", boss.name end
    local rare = FC:GetModule("Rares").lastKill
    if rare and now - rare.time <= KILL_WITHIN then return "rare", rare.name end
    return "loot"
  end
  if self.questAt and now - self.questAt <= AFTER_WINDOW then return "quest" end
  local professions = FC:GetModule("Professions")
  if professions and professions.windowOpen then return "craft" end
  for _, window in ipairs({ "vendor", "mail", "trade", "auction" }) do
    if self:IsOpen(window) then return window end
  end
  return "other"
end

-------------------------------------------------------------------------------
-- What the character carries
-------------------------------------------------------------------------------

local function bagCount()
  return (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4)
end

-- itemID -> { count, link, quality, icon } over the bags and the equipped items, or nil before the bags are loaded.
function Loot:Carried()
  local api = C_Container
  if not api or (Util.SafeValue("number", api.GetContainerNumSlots, 0) or 0) == 0 then return nil end
  local items = {}
  local function add(id, count, link, quality, icon)
    local it = items[id]
    if not it then
      it = { count = 0, link = link, quality = quality, icon = icon }
      items[id] = it
    end
    it.count = it.count + count
  end
  for bag = 0, bagCount() do
    for slot = 1, Util.SafeValue("number", api.GetContainerNumSlots, bag) or 0 do
      local info = Util.SafeValue("table", api.GetContainerItemInfo, bag, slot)
      local id = info and Util.Plain(info.itemID)
      if type(id) == "number" then
        local count = Util.Plain(info.stackCount)
        add(id, type(count) == "number" and count or 1, Util.Plain(info.hyperlink), Util.Plain(info.quality),
          Util.Plain(info.iconFileID))
      end
    end
  end
  for slot = 1, EQUIP_SLOTS do
    local id = Util.SafeValue("number", GetInventoryItemID, "player", slot)
    if id then add(id, 1) end
  end
  return items
end

-- What kind of item: classID, equippable (gear, not bags), stackable. nil values when the client does not know yet.
function Loot.Kind(itemID)
  local _, _, _, equipLoc, _, classID = Util.SafeValues(C_Item and C_Item.GetItemInfoInstant or GetItemInfoInstant, itemID)
  local maxStack = C_Item and C_Item.GetItemMaxStackSizeByID and Util.SafeValue("number", C_Item.GetItemMaxStackSizeByID, itemID)
  local gear = type(equipLoc) == "string" and equipLoc ~= "" and equipLoc ~= "INVTYPE_BAG"
    and equipLoc ~= "INVTYPE_NON_EQUIP_IGNORE" and equipLoc ~= "INVTYPE_AMMO"
  return type(classID) == "number" and classID or nil, gear, maxStack and maxStack > 1
end

-------------------------------------------------------------------------------
-- Notable or not
-------------------------------------------------------------------------------

local function state()
  local s = FC.Storage:GetState("Loot")
  s.seen = s.seen or {}     -- itemID -> true: items the character had (only those that could be notable)
  return s
end

-- Could this item ever be notable? Only those are remembered as seen (the list stays small).
local function candidate(quality, gear, stackable, classID)
  if stackable or classID == QUEST_CLASS or type(quality) ~= "number" then return false end
  return quality >= EPIC or (quality == RARE and gear)
end

local function itemName(link)
  return type(link) == "string" and link:match("|h%[(.-)%]|h") or nil
end

function Loot:Obtained(id, it, source, from)
  local s, settings = state(), self:GetSettings()
  local classID, gear, stackable = Loot.Kind(id)
  if stackable == nil then stackable = it.count > 1 end
  if not candidate(it.quality, gear, stackable, classID) or s.seen[id] then return end
  s.seen[id] = true
  if source == "bank" then return end
  local data = { item = id, link = it.link, name = itemName(it.link), quality = it.quality, icon = it.icon,
    source = source, from = from }
  if it.quality >= EPIC then
    if not s.epic then s.epic, data.first = true, true end
    FC:Record("item_obtained", data)
  elseif settings.blueGear then
    if source == "boss" or source == "rare" then
      FC:Record("item_obtained", data)
    else
      data.obtainedAt = time()
      self.pending[id] = data
    end
  end
end

function Loot:Scan()
  local items = self:Carried()
  if not items then return end
  local before = self.carried
  self.carried = items
  if not before then
    -- The first look this session: what is carried now is known. The very first run remembers all of it.
    local s = state()
    if not s.baseline then
      for id, it in pairs(items) do
        local classID, gear, stackable = Loot.Kind(id)
        if candidate(it.quality, gear, stackable, classID) then s.seen[id] = true end
      end
      s.baseline = time()
    end
    return
  end
  local source, from
  for id, it in pairs(items) do
    if it.count > (before[id] and before[id].count or 0) and it.link then
      if not source then source, from = self:Source() end
      self:Obtained(id, it, source, from)
    end
  end
end

-- Blue gear put on within EQUIP_WITHIN of getting it.
Loot:RegisterEvent("PLAYER_EQUIPMENT_CHANGED", function(self, _, slot)
  slot = Util.Plain(slot)
  local id = type(slot) == "number" and Util.SafeValue("number", GetInventoryItemID, "player", slot)
  local data = id and self.pending[id]
  if not data then return end
  self.pending[id] = nil
  if time() - data.obtainedAt <= EQUIP_WITHIN then
    data.equipped = true
    FC:Record("item_obtained", data)
  end
end)

Loot.pending = {}

function Loot:OnEnable()
  FC:After(5, function() self:Scan() end) -- item data arrives a moment after login
end

Loot:RegisterEvent("BAG_UPDATE_DELAYED", function(self)
  if self.carried then self:Scan() end
end)

-------------------------------------------------------------------------------
-- Options
-------------------------------------------------------------------------------

FC:RegisterOptionSection("loot", "SECTION_LOOT", 18, "Interface\\Icons\\INV_Misc_Bag_10")
FC:RegisterOption({ section = "loot", module = "Loot", key = "blueGear", type = "toggle", labelKey = "OPT_LOOT_BLUE",
  tooltipKey = "OPT_LOOT_BLUE_TIP", order = 1 })
