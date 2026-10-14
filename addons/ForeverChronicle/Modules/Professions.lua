-- Journey Forever - Professions module (spec F-008)
-- Snapshot of the character's professions (skill, maximum) and of the recipes it knows.
--
-- Professions are read with the Mainline API at login, on skill changes and via /fj professions.
-- Recipes can only be read while the profession window is open: they are captured on TRADE_SKILL_SHOW /
-- TRADE_SKILL_LIST_UPDATE (at most once per 5 s) from the unfiltered recipe list, so search text, filters
-- and collapsed categories in the window do not matter. Linked, guild and NPC professions are never captured.
--
-- snapshots.professions = {
--   baseline,  -- true after the first scan: professions appearing later become "profession_learned" events
--   list = { { skillLine, name, icon, rank, maxRank, modifier, kind = "primary" | "secondary", active,
--              firstSeenAt, updatedAt,
--              recipes = { status = "complete" | "partial", updatedAt, total, unreadable,
--                          format = 2, list = { "recipeID,categoryID,icon,quality,name" },
--                          categories = { "id,parentID,name" } } } },
-- quality: item quality of what the recipe creates (0 poor ... 5 legendary), empty if unknown (e.g. enchants).
-- Format 1 (v0.10.0) had no quality field: "recipeID,categoryID,icon,name".
-- }

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local Professions = FC:NewModule("Professions", { order = 35 })

local CAPTURE_INTERVAL = 5   -- seconds between two recipe captures
local LOGIN_DELAY = 5        -- profession data can arrive late after login

-------------------------------------------------------------------------------
-- Registrations
-------------------------------------------------------------------------------

local ICON = "Interface\\Icons\\Trade_BlackSmithing"

FC:RegisterCapability("professions", "CAP_PROFESSIONS", function()
  return type(GetProfessions) == "function" and type(GetProfessionInfo) == "function"
end)
FC:RegisterCapability("recipes", "CAP_RECIPES", function()
  local api = C_TradeSkillUI
  return api ~= nil and type(api.GetAllRecipeIDs) == "function" and type(api.GetRecipeInfo) == "function"
    and type(api.GetBaseProfessionInfo) == "function" and FC.eventStatus.TRADE_SKILL_SHOW == "registered"
end)

FC:RegisterEventType("profession_learned", {
  icon = ICON,
  getIcon = function(r) return r.data.icon end,
  format = function(r) return string.format(L.EVT_PROFESSION_LEARNED, r.data.name or "?") end,
})
FC:RegisterEventType("profession_rank", {
  icon = ICON,
  getIcon = function(r) return r.data.icon end,
  format = function(r)
    return string.format(L.EVT_PROFESSION_RANK, r.data.name or "?", Professions.RankName(r.data.maxRank))
  end,
})
FC:RegisterEventType("recipe_learned", {
  icon = "Interface\\Icons\\INV_Scroll_03",
  getIcon = function(r) return r.data.icon end,
  format = function(r) return string.format(L.EVT_RECIPE_LEARNED, r.data.name or ("#" .. tostring(r.data.recipeID))) end,
})

FC:RegisterStat("recipes_known", { labelKey = "STAT_RECIPES", order = 25, icon = "Interface\\Icons\\INV_Scroll_03",
  compute = function() return Professions:CountRecipes() end,
  fromRecord = function(char) return Professions:CountRecipes(char) end })

-------------------------------------------------------------------------------
-- Helpers
-------------------------------------------------------------------------------

-- Classic rank names by maximum skill (Apprentice 75 ... Artisan 300). Unknown maximums show the number.
local RANKS = { [75] = "RANK_APPRENTICE", [150] = "RANK_JOURNEYMAN", [225] = "RANK_EXPERT", [300] = "RANK_ARTISAN" }

function Professions.RankName(maxRank)
  local key = RANKS[maxRank]
  return key and L[key] or tostring(maxRank or "?")
end

-- Calls fn(...) safely; returns its plain (non-secret) results or nothing.
local function call(fn, ...)
  if type(fn) ~= "function" then return nil end
  return Util.SafeValues(fn, ...)
end

local function api(name)
  return C_TradeSkillUI and C_TradeSkillUI[name]
end

-- The professions snapshot of a character (default: the played one). Other characters' snapshots are
-- read-only (alts from this account, friends from the desktop app).
function Professions:GetSnapshot(char)
  if char and char ~= FC.char then
    local snap = type(char.snapshots) == "table" and char.snapshots.professions
    if type(snap) ~= "table" or type(snap.list) ~= "table" then return { list = {} } end
    return snap
  end
  local snap = FC.Storage:GetSnapshot("professions")
  snap.list = snap.list or {}
  return snap
end

function Professions:Find(skillLine)
  for _, prof in ipairs(self:GetSnapshot().list) do
    if prof.skillLine == skillLine then return prof end
  end
end

-- Active professions, primary first, then by name.
function Professions:GetActive(char)
  local out = {}
  for _, prof in ipairs(self:GetSnapshot(char).list) do
    if prof.active then out[#out + 1] = prof end
  end
  table.sort(out, function(a, b)
    if a.kind ~= b.kind then return a.kind == "primary" end
    return (a.name or "") < (b.name or "")
  end)
  return out
end

function Professions:CountRecipes(char)
  local n = 0
  for _, prof in ipairs(self:GetActive(char)) do
    if prof.recipes then n = n + #prof.recipes.list end
  end
  return n
end

local RECIPE_FORMAT = 2

-- Recipe string -> table. format: the recipe list's format (nil = 1, before item quality was stored).
function Professions.ParseRecipe(text, format)
  local id, cat, icon, quality, name
  if (format or 1) >= 2 then
    id, cat, icon, quality, name = text:match("^(%d+),(%d*),([^,]*),(%d*),(.*)$")
  else
    id, cat, icon, name = text:match("^(%d+),(%d*),([^,]*),(.*)$")
  end
  if not id then return nil end
  return { id = tonumber(id), category = tonumber(cat), icon = tonumber(icon) or icon, quality = tonumber(quality),
    name = name }
end

local function formatRecipe(r)
  local icon = r.icon and tostring(r.icon):gsub(",", "") or ""
  return string.format("%d,%s,%s,%s,%s", r.id, r.category or "", icon, r.quality or "", r.name)
end

-- Item quality by hyperlink colour (works without the item being cached).
local LINK_QUALITY = { ["9d9d9d"] = 0, ffffff = 1, ["1eff00"] = 2, ["0070dd"] = 3, a335ee = 4, ff8000 = 5,
  e6cc80 = 6, ["00ccff"] = 7 }

-- Quality of the item a recipe creates, or nil (enchants, data not loaded yet).
local function recipeQuality(id)
  local link, itemID
  local ok, out = pcall(api("GetRecipeOutputItemData"), id)
  if ok and type(out) == "table" then link, itemID = Util.Plain(out.hyperlink), Util.Plain(out.itemID) end
  if type(link) ~= "string" and api("GetRecipeItemLink") then link = call(api("GetRecipeItemLink"), id) end
  if type(link) == "string" then
    local color = link:match("|c%x%x(%x%x%x%x%x%x)")
    local q = color and LINK_QUALITY[color:lower()]
    if q then return q end
    itemID = itemID or tonumber(link:match("item:(%d+)"))
  end
  if type(itemID) == "number" and C_Item and C_Item.GetItemQualityByID then
    local q = call(C_Item.GetItemQualityByID, itemID)
    if type(q) == "number" then return q end
  end
end

-- "id,parentID,name" list -> { [id] = { name, parent } }
function Professions.ParseCategories(list)
  local out = {}
  for _, text in ipairs(list or {}) do
    local id, parent, name = text:match("^(%d+),(%d*),(.*)$")
    if id then out[tonumber(id)] = { name = name, parent = tonumber(parent) } end
  end
  return out
end

-------------------------------------------------------------------------------
-- Profession snapshot
-------------------------------------------------------------------------------

-- Reads all professions. Returns the number found, or nil if the API is missing.
-- The first scan that finds something (or the one shortly after login) sets the baseline: professions the
-- character already had are not reported as newly learned.
function Professions:Scan(setBaseline)
  if type(GetProfessions) ~= "function" then return nil end
  local snap = self:GetSnapshot()
  local slots = Util.Pack(call(GetProfessions))
  local now, seen, found = time(), {}, 0
  for slot = 1, math.max(slots.n or 0, 7) do
    local index = slots[slot]
    if type(index) == "number" then
      local name, icon, rank, maxRank, _, _, skillLine, modifier = call(GetProfessionInfo, index)
      if type(skillLine) == "number" and type(name) == "string" then
        found = found + 1
        seen[skillLine] = true
        self:Update(snap, skillLine, {
          name = name, icon = icon, rank = rank, maxRank = maxRank, modifier = modifier,
          kind = slot <= 2 and "primary" or "secondary",
        }, now)
      end
    end
  end
  -- A profession no longer listed was unlearned. Only trusted when the scan found something at all,
  -- so an empty answer while the client is still loading does not remove anything.
  if found > 0 then
    for _, prof in ipairs(snap.list) do
      if prof.active and not seen[prof.skillLine] then
        prof.active = false
        prof.unlearnedAt = now
      end
    end
    FC:ConfirmCapability("professions")
  end
  snap.baseline = snap.baseline or found > 0 or setBaseline == true
  snap.scannedAt = now
  return found
end

function Professions:Update(snap, skillLine, info, now)
  local prof = self:Find(skillLine)
  if not prof then
    prof = { skillLine = skillLine, firstSeenAt = now }
    table.insert(snap.list, prof)
    if snap.baseline then
      FC:Record("profession_learned", { skillLine = skillLine, name = info.name, icon = info.icon })
    end
  elseif not prof.active and snap.baseline then
    FC:Record("profession_learned", { skillLine = skillLine, name = info.name, icon = info.icon })
  elseif snap.baseline and type(info.maxRank) == "number" and type(prof.maxRank) == "number"
      and info.maxRank > prof.maxRank then
    FC:Record("profession_rank", { skillLine = skillLine, name = info.name, icon = info.icon, maxRank = info.maxRank })
  end
  prof.active, prof.unlearnedAt = true, nil
  prof.name, prof.icon, prof.kind = info.name, info.icon, info.kind
  prof.rank, prof.maxRank, prof.modifier = info.rank, info.maxRank, info.modifier
  prof.updatedAt = now
  return prof
end

function Professions:ScheduleScan(delay, setBaseline)
  if self.scanPending then return end
  self.scanPending = true
  FC:After(delay or 1, function()
    self.scanPending = nil
    self:Scan(setBaseline)
  end)
end

-------------------------------------------------------------------------------
-- Recipe snapshot (only while the profession window is open)
-------------------------------------------------------------------------------

local function categoryLine(id, seen, out)
  -- The category and its parents, so the desktop can show the full grouping.
  for _ = 1, 5 do
    if not id or seen[id] then return end
    seen[id] = true
    local ok, info = pcall(api("GetCategoryInfo"), id)
    if not ok or type(info) ~= "table" or type(info.name) ~= "string" then return end
    local parent = type(info.parentCategoryID) == "number" and info.parentCategoryID or nil
    out[#out + 1] = string.format("%d,%s,%s", id, parent or "", info.name)
    id = parent
  end
end

-- Returns a result code: ok | no_api | closed | not_ready | foreign | not_own.
function Professions:CaptureRecipes()
  if not (api("GetAllRecipeIDs") and api("GetRecipeInfo") and api("GetBaseProfessionInfo")) then return "no_api" end
  if not self.windowOpen then return "closed" end
  if api("IsTradeSkillReady") and call(api("IsTradeSkillReady")) == false then return "not_ready" end
  -- Never another player's, a guild or an NPC profession.
  if call(api("IsTradeSkillLinked")) or call(api("IsTradeSkillGuild")) or call(api("IsNPCCrafting")) then
    return "foreign"
  end
  local base = call(api("GetBaseProfessionInfo"))
  local skillLine = type(base) == "table" and base.professionID
  if type(skillLine) ~= "number" then return "not_ready" end
  local prof = self:Find(skillLine)
  if not (prof and prof.active) then
    self:Scan()
    prof = self:Find(skillLine)
    if not (prof and prof.active) then return "not_own" end
  end

  self.lastCapture = GetTime()
  local ids = call(api("GetAllRecipeIDs"))
  if type(ids) ~= "table" then return "not_ready" end
  local learned, unreadable = {}, 0
  -- Earlier capture by recipe ID: keeps qualities that cannot be read right now, and recipes of a partial read.
  local previous, before = prof.recipes, {}
  for _, text in ipairs(previous and previous.list or {}) do
    local r = self.ParseRecipe(text, previous.format)
    if r then before[r.id] = r end
  end
  local hasCategoryInfo = api("GetCategoryInfo") ~= nil
  local categories, catSeen = {}, {}
  for _, id in ipairs(ids) do
    local ok, info = pcall(api("GetRecipeInfo"), id)
    if ok and type(info) == "table" and not Util.IsSecret(info.learned) then
      if info.learned and type(info.name) == "string" then
        local cat = type(info.categoryID) == "number" and info.categoryID or nil
        local icon = (type(info.icon) == "number" or type(info.icon) == "string") and info.icon or nil
        local quality = recipeQuality(id) or (before[id] and before[id].quality)
        learned[id] = formatRecipe({ id = id, category = cat, icon = icon, quality = quality, name = info.name })
        if cat and hasCategoryInfo then categoryLine(cat, catSeen, categories) end
      end
    else
      unreadable = unreadable + 1
    end
  end

  local status = unreadable == 0 and "complete" or "partial"
  -- A partial capture never removes recipes that an earlier capture found.
  if status == "partial" and previous then
    for id, r in pairs(before) do
      if not learned[id] then learned[id] = formatRecipe(r) end
    end
    if #categories == 0 then categories = previous.categories end
  end
  local list = {}
  for _, text in pairs(learned) do list[#list + 1] = text end
  table.sort(list, function(a, b) return tonumber(a:match("^(%d+)")) < tonumber(b:match("^(%d+)")) end)

  prof.recipes = { status = status, updatedAt = time(), total = #ids, unreadable = unreadable,
    format = RECIPE_FORMAT, list = list, categories = categories }
  if status == "complete" then FC:ConfirmCapability("recipes") end
  FC:SendMessage("FC_PROFESSIONS_UPDATED", skillLine)
  return "ok", prof
end

function Professions:ScheduleCapture()
  if self.capturePending then return end
  self.capturePending = true
  local wait = math.max(0.5, (self.lastCapture or -math.huge) + CAPTURE_INTERVAL - GetTime())
  FC:After(wait, function()
    self.capturePending = nil
    if self.windowOpen then self:CaptureRecipes() end
  end)
end

-------------------------------------------------------------------------------
-- Events
-------------------------------------------------------------------------------

function Professions:OnEnable()
  self:Scan()
  self:ScheduleScan(LOGIN_DELAY, true)
end

Professions:RegisterEvent("SKILL_LINES_CHANGED", function(self) self:ScheduleScan() end)
Professions:RegisterEvent("CHAT_MSG_SKILL", function(self) self:ScheduleScan() end)

Professions:RegisterEvent("TRADE_SKILL_SHOW", function(self)
  self.windowOpen = true
  self:ScheduleCapture()
end)
Professions:RegisterEvent("TRADE_SKILL_LIST_UPDATE", function(self)
  if self.windowOpen then self:ScheduleCapture() end
end)
Professions:RegisterEvent("TRADE_SKILL_DATA_SOURCE_CHANGED", function(self)
  if self.windowOpen then self:ScheduleCapture() end
end)
Professions:RegisterEvent("TRADE_SKILL_CLOSE", function(self) self.windowOpen = false end)

-- A recipe was learned (trainer, recipe item, ...). Its name comes from the recipe or spell API.
Professions:RegisterEvent("NEW_RECIPE_LEARNED", function(self, _, recipeID)
  recipeID = Util.Plain(recipeID)
  if type(recipeID) ~= "number" then return end
  local name, icon
  local ok, info = pcall(api("GetRecipeInfo"), recipeID)
  if ok and type(info) == "table" then name, icon = Util.Plain(info.name), Util.Plain(info.icon) end
  if type(name) ~= "string" and C_Spell and C_Spell.GetSpellName then name = call(C_Spell.GetSpellName, recipeID) end
  if type(name) ~= "string" and GetSpellInfo then name, _, icon = call(GetSpellInfo, recipeID) end
  FC:Record("recipe_learned", { recipeID = recipeID, name = type(name) == "string" and name or nil,
    icon = (type(icon) == "number" or type(icon) == "string") and icon or nil })
  self:ScheduleScan()
  if self.windowOpen then self:ScheduleCapture() end
end)

-------------------------------------------------------------------------------
-- /fj professions
-------------------------------------------------------------------------------

FC:RegisterCommand("professions", "CMD_PROFESSIONS", function()
  local found = Professions:Scan()
  if found == nil then
    FC:Print(L.PROF_NO_API)
    return
  end
  if Professions.windowOpen then Professions:CaptureRecipes() end
  local active = Professions:GetActive()
  if #active == 0 then
    FC:Print(L.PROF_NONE)
    return
  end
  for _, prof in ipairs(active) do
    local recipes = prof.recipes
    local detail = recipes and string.format(L.PROF_RECIPES_LINE, #recipes.list, L["RECIPES_" .. recipes.status:upper()])
      or L.PROF_RECIPES_NOT_CAPTURED
    FC:Print(string.format("%s %d/%d - %s", prof.name, prof.rank or 0, prof.maxRank or 0, detail))
  end
end, 50)
