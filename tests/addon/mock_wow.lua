-- Minimal mock of the WoW client API for running the addon outside the game.
-- Frames accept any method call (no-op) unless a specific behaviour is defined below.

local SECRET = setmetatable({}, { __tostring = function() return "SECRET" end })
MOCK = { now = 1000, timers = {}, chat = {}, eventFrames = {}, SECRET = SECRET, clock = 1791960000 }

function issecretvalue(v) return v == SECRET end
function GetTime() return MOCK.now end
function time() return MOCK.clock + math.floor(MOCK.now) end
function date(fmt, t) return os.date(fmt, t or time()) end -- mock clock, keeps fixtures deterministic
unpack = table.unpack
function strtrim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
tinsert = table.insert
UISpecialFrames = {}
SlashCmdList = {}
NUM_CHAT_WINDOWS = 2
SOUNDKIT = { IG_CHARACTER_INFO_OPEN = 1, IG_CHARACTER_INFO_CLOSE = 2, IG_CHARACTER_INFO_TAB = 3 }
function PlaySound() end
math.randomseed(42)

C_Timer = {
  After = function(s, fn) table.insert(MOCK.timers, { at = MOCK.now + s, fn = fn }) end,
}
function C_Timer.NewTicker(s, fn)
  local ticker = { cancelled = false }
  function ticker:Cancel() self.cancelled = true end
  local function tick()
    if ticker.cancelled then return end
    fn()
    if not ticker.cancelled then C_Timer.After(s, tick) end
  end
  C_Timer.After(s, tick)
  return ticker
end

function MOCK.advance(seconds)
  local target = MOCK.now + seconds
  while true do
    table.sort(MOCK.timers, function(a, b) return a.at < b.at end)
    local t = MOCK.timers[1]
    if not t or t.at > target then break end
    table.remove(MOCK.timers, 1)
    MOCK.now = t.at
    t.fn()
  end
  MOCK.now = target
end

-------------------------------------------------------------------------------
-- Frames
-------------------------------------------------------------------------------

local VALID_EVENTS = {}
for e in ([[ADDON_LOADED PLAYER_LOGIN PLAYER_ENTERING_WORLD PLAYER_LOGOUT TIME_PLAYED_MSG PLAYER_LEVEL_UP
  QUEST_TURNED_IN PLAYER_DEAD ACHIEVEMENT_EARNED ZONE_CHANGED_NEW_AREA PLAYER_CONTROL_GAINED
  LOADING_SCREEN_ENABLED LOADING_SCREEN_DISABLED SCREENSHOT_SUCCEEDED SCREENSHOT_FAILED
  PARTY_KILL PLAYER_XP_UPDATE PLAYER_TARGET_CHANGED UPDATE_MOUSEOVER_UNIT NAME_PLATE_UNIT_ADDED
  SKILL_LINES_CHANGED CHAT_MSG_SKILL TRADE_SKILL_SHOW TRADE_SKILL_LIST_UPDATE TRADE_SKILL_DATA_SOURCE_CHANGED
  TRADE_SKILL_CLOSE NEW_RECIPE_LEARNED PLAYER_EQUIPMENT_CHANGED]]):gmatch("%S+") do
  VALID_EVENTS[e] = true
end

local regionMT = { __index = function() return function() end end }
local function newRegion()
  local r = { shown = true }
  r.SetText = function(self, t) self.text = t end
  r.SetTexture = function(self, t) self.texture = t end
  r.SetTextColor = function(self, red, g, b) self.color = { red, g, b } end
  r.GetText = function(self) return self.text end
  r.Show = function(self) self.shown = true end
  r.Hide = function(self) self.shown = false end
  r.SetShown = function(self, v) self.shown = v and true or false end
  r.IsShown = function(self) return self.shown end
  r.IsVisible = function(self) return self.shown end
  r.GetWidth = function() return 360 end
  r.GetStringWidth = function(self) return #(self.text or "") * 6 end
  r.GetStringHeight = function() return 12 end
  r.GetChecked = function(self) return self.checked end
  r.SetChecked = function(self, v) self.checked = v end
  return setmetatable(r, regionMT)
end

local frameMT = { __index = function() return function() end end }
function CreateFrame(kind, name, parent, template)
  local f = newRegion()
  f.events, f.scripts, f.name = {}, {}, name
  f.RegisterEvent = function(self, e)
    if not VALID_EVENTS[e] and not MOCK.allEventsValid then error("Attempt to register unknown event \"" .. e .. "\"") end
    self.events[e] = true
    MOCK.eventFrames[self] = true
  end
  f.UnregisterEvent = function(self, e) self.events[e] = nil end
  f.IsEventRegistered = function(self, e) return self.events[e] == true end
  f.SetScript = function(self, k, fn) self.scripts[k] = fn end
  f.GetScript = function(self, k) return self.scripts[k] end
  f.GetName = function(self) return self.name end
  f.CreateFontString = function() return newRegion() end
  f.CreateLine = function() return newRegion() end
  f.GetFrameLevel = function() return 1 end
  f.GetEffectiveScale = function() return 1 end
  f.GetLeft = function() return 0 end
  f.GetTop = function() return 0 end
  f.GetCenter = function() return 0, 0 end
  f.SetScale = function(self, s) self.scale = s end
  f.CreateTexture = function() return newRegion() end
  f.GetChecked = function(self) return self.checked end
  f.SetChecked = function(self, v) self.checked = v end
  f.Show = function(self) self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
  f.Hide = function(self) self.shown = false; if self.scripts.OnHide then self.scripts.OnHide(self) end end
  f.SetShown = function(self, v) if v then self:Show() else self:Hide() end end
  if template == "ButtonFrameTemplate" then
    f.Inset = CreateFrame("Frame")
    f.SetPortraitToUnit = function(self, unit) self.portraitUnit, self.portraitClass = unit, nil end
    f.SetPortraitToClassIcon = function(self, class) self.portraitUnit, self.portraitClass = nil, class end
  end
  if name then _G[name] = f end
  return setmetatable(f, frameMT)
end

function MOCK.fire(event, ...)
  for f in pairs(MOCK.eventFrames) do
    if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event, ...) end
    if f == ChatFrame1 and f.events[event] and event == "TIME_PLAYED_MSG" then
      table.insert(MOCK.chat, "PLAYED " .. tostring((...)))
    end
  end
end

UIParent = CreateFrame("Frame")
Minimap = CreateFrame("Frame")
ChatFrame1 = CreateFrame("Frame")
ChatFrame1.AddMessage = function(_, m) table.insert(MOCK.chat, m) end
MOCK.allEventsValid = true
ChatFrame1:RegisterEvent("TIME_PLAYED_MSG")
MOCK.allEventsValid = false
ChatFrame2 = CreateFrame("Frame")
DEFAULT_CHAT_FRAME = ChatFrame1
GameTooltip = CreateFrame("Frame")
function GameTooltip_Hide() end

C_EventUtils = { IsEventValid = function(e) return VALID_EVENTS[e] == true end }
C_MapExplorationInfo = {
  GetExploredMapTextures = function()
    return { { textureWidth = 300, textureHeight = 200, offsetX = 10, offsetY = 20, isShownByMouseOver = false,
      fileDataIDs = { 200001, 200002 } } }
  end,
}

-------------------------------------------------------------------------------
-- Game API
-------------------------------------------------------------------------------

MOCK.level = 22
function GetBuildInfo() return "1.60.1", "70374", "Oct 12 2026", 16001 end
function GetLocale() return "enUS" end
MOCK.units = {}
function UnitGUID(u)
  if u == "player" then return "Player-4619-0112A417" end
  if MOCK.units[u] then return MOCK.units[u].guid end
  return SECRET
end
function UnitClassification(u) return MOCK.units[u] and MOCK.units[u].classification or "normal" end
function UnitIsDead(u) return MOCK.units[u] and MOCK.units[u].dead or false end
function UnitName(u) if MOCK.units[u] then return MOCK.units[u].name end return "Blind", "Bullseye" end
function GetRealmName() return "Classic Beta PvP" end
function GetNormalizedRealmName() return "ClassicBetaPvP" end
function UnitClass() return "Hunter", "HUNTER", 3 end
function UnitRace() return "Tauren", "Tauren", 6 end
function UnitFactionGroup() return "Horde", "Horde" end
function UnitLevel() return MOCK.level end
function GetServerTime() return time() end
function GetRealZoneText() return MOCK.zone or "The Barrens" end
function UnitOnTaxi() return MOCK.taxi == true end
function GetSubZoneText() if MOCK.instance then return "" end return MOCK.subzone or "Crossroads" end
function IsInInstance() return MOCK.instance and true or false, MOCK.instance and "party" or "none" end
function UnitPosition() if MOCK.instance then return nil, nil, nil, 389 end return -2382.5, -1838.6, 0, 1 end
C_Map = {
  GetBestMapForUnit = function() if MOCK.instance then return nil end return MOCK.mapID or 1413 end,
  GetMapInfo = function(id)
    if id == 1414 then return { mapID = 1414, name = "Kalimdor", mapType = 2, parentMapID = 947 } end
    if id == 947 then return { mapID = 947, name = "Azeroth", mapType = 1, parentMapID = 0 } end
    return { mapID = id, name = MOCK.zone or "The Barrens", mapType = 3, parentMapID = 1414 }
  end,
  GetMapRectOnMap = function() return 0.40, 0.48, 0.70, 0.78 end,
  GetMapArtLayers = function() return { { layerWidth = 1002, layerHeight = 668, tileWidth = 256, tileHeight = 256 } } end,
  GetMapArtLayerTextures = function() local t = {} for i = 1, 12 do t[i] = 100000 + i end return t end,
  GetPlayerMapPosition = function()
    return { x = MOCK.x or 0.440279, y = MOCK.y or 0.591297, GetXY = function(s) return s.x, s.y end }
  end,
}
C_QuestLog = { GetTitleForQuestID = function(id) return id == 3513 and "The Runaway Shipment" or nil end }
function GetAchievementInfo(id) return id, "Level 10", 10, true, 10, 14, 26, "Reach level 10", 0, 236565 end
MOCK.screenshots = {}
function IsShiftKeyDown() return false end
function InCombatLockdown() return MOCK.combat == true end
function UnitXP() return MOCK.xp or 1000 end
function UnitXPMax() return MOCK.xpMax or 5000 end
function GetXPExhaustion() return 2500 end
function GetMoney() return 123456 end
function GetCoinTextureString(m) return tostring(m) .. "c" end
local SLOT_IDS = { HeadSlot = 1, NeckSlot = 2, ShoulderSlot = 3, ShirtSlot = 4, ChestSlot = 5, WaistSlot = 6,
  LegsSlot = 7, FeetSlot = 8, WristSlot = 9, HandsSlot = 10, Finger0Slot = 11, Finger1Slot = 12, Trinket0Slot = 13,
  Trinket1Slot = 14, BackSlot = 15, MainHandSlot = 16, SecondaryHandSlot = 17, RangedSlot = 18, TabardSlot = 19 }
function GetInventorySlotInfo(name) return SLOT_IDS[name], "Interface\\PaperDoll\\UI-PaperDoll-Slot-" .. name end
function GetInventoryItemTexture(_, id) if id == 1 or id == 16 then return 133000 + id end end
function GetInventoryItemQuality(_, id) if id == 1 or id == 16 then return 3 end end
MOCK.gearLinks = {
  [1] = "|cff0070dd|Hitem:4385::::::::22:::::|h[Green Tinted Goggles]|h|r",
  [16] = "|cff0070dd|Hitem:2099::::::::22:::::|h[Dwarven Hand Cannon]|h|r",
}
function GetInventoryItemLink(_, id) return MOCK.gearLinks[id] end
-- Which addons are loaded (the data-only addon ForeverChronicle_Share is loaded unless a test says otherwise).
C_AddOns = { IsAddOnLoaded = function(name) return name == "ForeverChronicle_Share" and not MOCK.shareMissing end }
local QUALITY_COLORS = { [1] = { 1, 1, 1 }, [2] = { 0.12, 1, 0 }, [3] = { 0, 0.44, 0.87 } }
function GetItemQualityColor(q) local c = QUALITY_COLORS[q] or QUALITY_COLORS[3]; return c[1], c[2], c[3] end
function GetCursorPosition() return MOCK.cursorX or 0, MOCK.cursorY or 0 end
function Screenshot()
  table.insert(MOCK.screenshots, MOCK.now)
  MOCK.countdownVisibleAtCapture = ForeverChronicleCountdown ~= nil and ForeverChronicleCountdown:IsShown()
  MOCK.uiVisibleAtCapture = UIParent:IsShown()
  C_Timer.After(0.3, function() MOCK.fire("SCREENSHOT_SUCCEEDED") end)
end

-- Moves the player to another zone and fires the zone event.
function MOCK.travel(mapID, zone)
  MOCK.mapID, MOCK.zone = mapID, zone
  MOCK.fire("ZONE_CHANGED_NEW_AREA")
end

function RequestTimePlayed() C_Timer.After(0.2, function() MOCK.fire("TIME_PLAYED_MSG", 74113, 7574) end) end

-------------------------------------------------------------------------------
-- Professions (Mainline API, values as reported by the Phase 0 probe)
-------------------------------------------------------------------------------

MOCK.professions = {
  [6] = { "Leatherworking", 136247, 126, 150, 1, 48, 165, 0, -1, 0, "Leatherworking" },
  [7] = { "Herbalism", 136246, 59, 150, 2, 50, 182, 0, -1, 0, "Herbalism" },
  [5] = { "First Aid", 135966, 23, 75, 1, 46, 129, 0, -1, 0, "First Aid" },
  [8] = { "Cooking", 133971, 13, 75, 1, 53, 185, 0, -1, 0, "Cooking" },
}
MOCK.professionSlots = { 6, 7, 5, nil, 8, nil, nil }
function GetProfessions()
  local s = MOCK.professionSlots
  return s[1], s[2], s[3], s[4], s[5], s[6], s[7]
end
function GetProfessionInfo(i) local p = MOCK.professions[i]; if p then return unpack(p) end end

MOCK.recipes = {
  [165] = {
    { recipeID = 2881, name = "Light Leather", categoryID = 2550, icon = 134252, learned = true },
    { recipeID = 3816, name = "Cured Light Hide", categoryID = 2550, icon = 134366, learned = true },
    { recipeID = 3817, name = "Cured Medium Hide", categoryID = 2550, icon = 134354, learned = true },
    { recipeID = 9058, name = "Handstitched Leather Cloak", categoryID = 2552, icon = 133150, learned = true },
    { recipeID = 2149, name = "Handstitched Leather Boots", categoryID = 2553, icon = 132539, learned = false },
    { recipeID = 3753, name = "Handstitched Leather Belt", categoryID = 2553, icon = 132493, learned = false },
  },
  [185] = {
    { recipeID = 2538, name = "Charred Wolf Meat", categoryID = 2600, icon = 133974, learned = true },
  },
}
MOCK.categories = {
  [2549] = { categoryID = 2549, name = "Leatherworking", parentCategoryID = nil },
  [2550] = { categoryID = 2550, name = "Materials", parentCategoryID = 2549 },
  [2552] = { categoryID = 2552, name = "Cloaks", parentCategoryID = 2549 },
  [2553] = { categoryID = 2553, name = "Armor", parentCategoryID = 2549 },
  [2600] = { categoryID = 2600, name = "Cooking", parentCategoryID = nil },
}
MOCK.tradeSkill = nil -- skill line shown in the open profession window
C_TradeSkillUI = {
  GetAllRecipeIDs = function()
    local out = {}
    for _, r in ipairs(MOCK.recipes[MOCK.tradeSkill] or {}) do out[#out + 1] = r.recipeID end
    return out
  end,
  GetRecipeInfo = function(id)
    for _, list in pairs(MOCK.recipes) do
      for _, r in ipairs(list) do
        if r.recipeID == id then
          if r.broken then error("recipe data not loaded") end
          return r
        end
      end
    end
  end,
  GetBaseProfessionInfo = function() return { professionID = MOCK.tradeSkill or 0 } end,
  GetCategoryInfo = function(id) return MOCK.categories[id] end,
  IsTradeSkillReady = function() return true end,
  IsTradeSkillLinked = function() return MOCK.linked == true, nil end,
  IsTradeSkillGuild = function() return false end,
  IsNPCCrafting = function() return false end,
}
-- Created item: hyperlink (colour = quality), only an item ID (quality from the item cache), or nothing.
local OUTPUT = {
  [2881] = { itemID = 2318, hyperlink = "|cffffffff|Hitem:2318::::::::22:::::|h[Light Leather]|h|r" },
  [3816] = { itemID = 4231 },
  [3817] = { itemID = 4233, hyperlink = "|cffffffff|Hitem:4233::::::::22:::::|h[Cured Medium Hide]|h|r" },
  [9058] = { itemID = 7276, hyperlink = "|cff1eff00|Hitem:7276::::::::22:::::|h[Handstitched Leather Cloak]|h|r" },
  [2149] = { itemID = 2302, hyperlink = "|cff1eff00|Hitem:2302::::::::22:::::|h[Handstitched Leather Boots]|h|r" },
}
C_TradeSkillUI.GetRecipeOutputItemData = function(id) return OUTPUT[id] or {} end
-- Encounter journal: Orgrimmar lists the Ragefire Chasm entrance (journal 226 = instance 389).
C_EncounterJournal = {
  GetDungeonEntrancesForMap = function(mapID)
    if mapID ~= 1454 then return {} end
    return { { journalInstanceID = 226, name = "Ragefire Chasm", position = { x = 0.5195, y = 0.4911 } } }
  end,
}
function EJ_GetInstanceInfo(id)
  if id == 226 then return "Ragefire Chasm", "", 0, 0, 0, 0, 213, "", false, 389 end
end
CLASS_ICON_TCOORDS = { HUNTER = { 0, 0.25, 0.25, 0.5 }, MAGE = { 0.25, 0.49609375, 0, 0.25 },
  WARRIOR = { 0, 0.25, 0, 0.25 } }
C_Item = { GetItemQualityByID = function(itemID) return itemID == 4231 and 1 or nil end }
C_Spell = { GetSpellName = function(id) return id == 2149 and "Handstitched Leather Boots" or nil end }

-- Opens / closes the profession window of a skill line.
function MOCK.openProfession(skillLine)
  MOCK.tradeSkill = skillLine
  MOCK.fire("TRADE_SKILL_SHOW")
  MOCK.fire("TRADE_SKILL_LIST_UPDATE")
end
function MOCK.closeProfession()
  MOCK.tradeSkill = nil
  MOCK.fire("TRADE_SKILL_CLOSE")
end
