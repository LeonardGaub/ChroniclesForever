-- Forever Chronicle - Professions page (spec F-008)
-- Left: the character's professions with icon, skill bar and rank. Right: the known recipes of the selected
-- profession, grouped by category, with a search box and the capture status (complete / partial / not yet).

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI
local Util = FC.Util

local page = { id = "professions", labelKey = "TAB_PROFESSIONS", icon = "Interface\\Icons\\Trade_BlackSmithing", order = 28 }
local PROF_W, PROF_H, PROF_MAX = 236, 50, 8
local ROW_HEIGHT = 22

local STATUS_ICON = { complete = "ok", partial = "wait" }

local function Professions() return FC:GetModule("Professions") end

-------------------------------------------------------------------------------
-- Profession buttons (left)
-------------------------------------------------------------------------------

local function professionButton(parent, onClick)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(PROF_W, PROF_H)
  b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
  b.selection = UI:SelectionBorder(b)
  local bg = b:CreateTexture(nil, "BACKGROUND")
  bg:SetSize(38, 38)
  bg:SetPoint("LEFT", 4, 0)
  bg:SetColorTexture(0, 0, 0, 0.7)
  b.icon = b:CreateTexture(nil, "ARTWORK")
  b.icon:SetPoint("TOPLEFT", bg, 2, -2)
  b.icon:SetPoint("BOTTOMRIGHT", bg, -2, 2)
  b.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  b.name = b:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  b.name:SetPoint("TOPLEFT", bg, "TOPRIGHT", 8, -1)
  b.name:SetPoint("RIGHT", b, "RIGHT", -6, 0)
  b.name:SetJustifyH("LEFT")
  b.name:SetWordWrap(false)
  b.bar = UI:Bar(b, PROF_W - 58)
  b.bar:SetPoint("BOTTOMLEFT", bg, "BOTTOMRIGHT", 8, 1)
  b.bar:SetStatusBarColor(0.25, 0.4, 0.85)
  b:SetScript("OnClick", onClick)
  return b
end

local function updateProfessionButton(b, prof)
  b.skillLine = prof.skillLine
  UI:SetIcon(b.icon, prof.icon)
  b.name:SetText(prof.name or "?")
  local rank, maxRank = prof.rank or 0, prof.maxRank or 0
  b.bar:SetValue(maxRank > 0 and rank / maxRank or 0)
  local text = string.format("%d / %d", rank, maxRank)
  if (prof.modifier or 0) > 0 then text = string.format("%d (+%d) / %d", rank, prof.modifier, maxRank) end
  b.bar.text:SetText(text .. "  \194\183  " .. Professions().RankName(maxRank))
end

-------------------------------------------------------------------------------
-- Recipe rows (right): category headers and recipes
-------------------------------------------------------------------------------

local function createRow(row)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(18, 18)
  row.icon:SetPoint("LEFT", 14, 0)
  row.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)
  row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.text:SetPoint("LEFT", row.icon, "RIGHT", 8, 0)
  row.text:SetPoint("RIGHT", row, "RIGHT", -8, 0)
  row.text:SetJustifyH("LEFT")
  row.text:SetWordWrap(false)
  row.header = row:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  row.header:SetPoint("BOTTOMLEFT", 4, 3)
  row.header:SetPoint("RIGHT", row, "RIGHT", -8, 0)
  row.header:SetJustifyH("LEFT")
  row:EnableMouse(true)
  row:SetScript("OnEnter", function(r)
    if not r.recipe then return end
    GameTooltip:SetOwner(r, "ANCHOR_RIGHT")
    local ok = GameTooltip.SetSpellByID and pcall(GameTooltip.SetSpellByID, GameTooltip, r.recipe.id)
    if not ok then GameTooltip:SetText(r.recipe.name, 1, 1, 1) end
    GameTooltip:AddLine(string.format(L.RECIPE_ID, r.recipe.id), 0.6, 0.6, 0.6)
    GameTooltip:Show()
  end)
  row:SetScript("OnLeave", GameTooltip_Hide)
end

local function updateRow(row, item)
  local isHeader = item.header ~= nil
  row.header:SetShown(isHeader)
  row.icon:SetShown(not isHeader)
  row.text:SetShown(not isHeader)
  row.recipe = item.recipe
  if isHeader then
    row.header:SetText(item.header)
  else
    UI:SetIcon(row.icon, item.recipe.icon ~= "" and item.recipe.icon or nil)
    row.text:SetText(item.recipe.name)
    -- Name in the colour of the item it creates (white when unknown, e.g. enchants).
    local r, g, b = UI:QualityColor(item.recipe.quality)
    if r then row.text:SetTextColor(r, g, b) else row.text:SetTextColor(1, 1, 1) end
  end
end

-- Recipes of a profession as list items, grouped by category (alphabetical), filtered by search text.
local function recipeItems(prof, search)
  local recipes = prof.recipes
  if not recipes then return {}, 0 end
  local P = Professions()
  local categories = P.ParseCategories(recipes.categories)
  local groups, order, shown = {}, {}, 0
  search = search and search ~= "" and search:lower() or nil
  for _, text in ipairs(recipes.list) do
    local recipe = P.ParseRecipe(text, recipes.format)
    if recipe and (not search or recipe.name:lower():find(search, 1, true)) then
      local cat = recipe.category and categories[recipe.category]
      local name = cat and cat.name or L.RECIPE_CATEGORY_OTHER
      if not groups[name] then
        groups[name] = {}
        order[#order + 1] = name
      end
      table.insert(groups[name], recipe)
      shown = shown + 1
    end
  end
  table.sort(order)
  local items = {}
  for _, name in ipairs(order) do
    items[#items + 1] = { header = name }
    table.sort(groups[name], function(a, b) return a.name < b.name end)
    for _, recipe in ipairs(groups[name]) do items[#items + 1] = { recipe = recipe } end
  end
  return items, shown
end

-------------------------------------------------------------------------------
-- Page
-------------------------------------------------------------------------------

function page:Create(c)
  self.content = c
  self.buttons = {}
  self.profHeader = UI:Header(c, "PROF_HEADER", "Interface\\Icons\\Trade_BlackSmithing")
  self.profHeader:SetPoint("TOPLEFT", 14, -12)
  self.profHeader.line:SetPoint("RIGHT", c, "LEFT", 14 + PROF_W, 0)
  for i = 1, PROF_MAX do
    local b = professionButton(c, function(btn)
      self.selected = btn.skillLine
      self.signature = nil
      self:Refresh()
    end)
    b:SetPoint("TOPLEFT", self.profHeader, "BOTTOMLEFT", 0, -10 - (i - 1) * (PROF_H + 6))
    b:Hide()
    self.buttons[i] = b
  end
  self.hint = UI:Label(c, "PROF_HINT", "GameFontDisableSmall")
  self.hint:SetPoint("BOTTOMLEFT", 14, 12)
  self.hint:SetWidth(PROF_W)
  self.empty = UI:Label(c, "PROF_NONE", "GameFontDisable")
  self.empty:SetPoint("TOPLEFT", self.profHeader, "BOTTOMLEFT", 0, -14)
  self.empty:SetWidth(PROF_W)

  -- Right side: selected profession, status, search, recipes.
  local x = 14 + PROF_W + 24
  self.title = c:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  self.title:SetPoint("TOPLEFT", x, -10)
  self.title:SetJustifyH("LEFT")
  self.statusIcon = c:CreateTexture(nil, "ARTWORK")
  self.statusIcon:SetSize(14, 14)
  self.statusIcon:SetPoint("TOPLEFT", self.title, "BOTTOMLEFT", 0, -6)
  self.status = c:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  self.status:SetPoint("LEFT", self.statusIcon, "RIGHT", 6, 0)
  self.status:SetJustifyH("LEFT")

  local ok, search = pcall(CreateFrame, "EditBox", nil, c, "SearchBoxTemplate")
  if not ok then search = CreateFrame("EditBox", nil, c, "InputBoxTemplate") end
  search:SetSize(180, 20)
  search:SetAutoFocus(false)
  search:SetPoint("TOPRIGHT", -36, -14)
  search:SetScript("OnTextChanged", function(box, ...)
    if SearchBoxTemplate_OnTextChanged then pcall(SearchBoxTemplate_OnTextChanged, box, ...) end
    self.signature = nil
    self:Refresh()
  end)
  self.search = search

  self.list = UI:List(c, ROW_HEIGHT, createRow, updateRow)
  self.list.scroll:SetPoint("TOPLEFT", x, -58)
  self.list.scroll:SetPoint("BOTTOMRIGHT", -28, 8)
  self.recipeEmpty = c:CreateFontString(nil, "OVERLAY", "GameFontDisable")
  self.recipeEmpty:SetPoint("TOPLEFT", self.list.scroll, "TOPLEFT", 4, -8)
  self.recipeEmpty:SetPoint("RIGHT", c, "RIGHT", -36, 0)
  self.recipeEmpty:SetJustifyH("LEFT")
end

-- Status line of the selected profession's recipe snapshot.
local function statusText(prof, shown)
  local recipes = prof.recipes
  if not recipes then return L.RECIPES_NOT_CAPTURED, "bad" end
  local text = string.format(L.RECIPES_STATUS, L["RECIPES_" .. recipes.status:upper()], #recipes.list,
    Util.FormatTime(recipes.updatedAt))
  if shown ~= #recipes.list then text = text .. "  \194\183  " .. string.format(L.RECIPES_SHOWN, shown) end
  return text, STATUS_ICON[recipes.status] or "bad"
end

function page:Refresh()
  local P = Professions()
  local char = FC:ViewChar()
  local active = P:GetActive(char)
  local snap = P:GetSnapshot(char)
  local search = self.search:GetText()
  if type(search) ~= "string" then search = "" end
  -- Rebuild only when something changed (refresh runs every second while the window is open).
  local selectedProf
  for _, prof in ipairs(active) do
    if prof.skillLine == self.selected then selectedProf = prof end
  end
  selectedProf = selectedProf or active[1]
  self.selected = selectedProf and selectedProf.skillLine
  local signature = table.concat({ tostring(FC:ViewKey()), tostring(snap.scannedAt), tostring(self.selected), search,
    FC:GetLanguage(),
    tostring(selectedProf and selectedProf.recipes and selectedProf.recipes.updatedAt), #active }, "|")
  if signature == self.signature then return end
  self.signature = signature

  for i, b in ipairs(self.buttons) do
    local prof = active[i]
    if prof then
      updateProfessionButton(b, prof)
      UI:SetSelected(b, prof.skillLine == self.selected)
      b:Show()
    else
      b:Hide()
    end
  end
  self.empty:SetShown(#active == 0)

  if not selectedProf then
    self.title:SetText("")
    self.status:SetText("")
    self.statusIcon:Hide()
    self.list:SetItems({})
    self.recipeEmpty:SetText("")
    return
  end
  self.title:SetText(selectedProf.name or "?")
  local items, shown = recipeItems(selectedProf, search)
  local text, icon = statusText(selectedProf, shown)
  self.status:SetText(text)
  self.statusIcon:Show()
  UI:SetIcon(self.statusIcon, UI.STATUS_ICONS[icon])
  self.list:SetItems(items)
  if not selectedProf.recipes then
    self.recipeEmpty:SetText(L.RECIPES_HOWTO)
  elseif #items == 0 then
    self.recipeEmpty:SetText(search ~= "" and L.RECIPES_NO_MATCH or L.RECIPES_NONE)
  else
    self.recipeEmpty:SetText("")
  end
end

UI:RegisterPage(page)
