-- Journey Forever - Chronicle page
-- The most recent recorded events, newest first, under a heading per day. Text and icon come from the event
-- type registry; milestones (level-ups, achievements, dungeons ...) and deaths stand out (def.highlight).
-- Screenshots are shown with the entry that triggered them (a marker with the screenshot's status; details in the
-- row tooltip). Screenshots without an entry (test screenshots) appear as their own entries.
--
-- Top: a search box, "only entries with a screenshot" and a foldable row of filter buttons, one per event
-- category (Shift-click shows only that one). Entries that are new since the page was last seen pop in one
-- after the other. Two looks (option): a parchment page ("book") or the dark window background ("classic").

local ADDON, FC = ...
local L = FC.L
local UI = FC.UI

local page = { id = "chronicle", labelKey = "TAB_CHRONICLE", icon = "Interface\\Icons\\INV_Misc_Book_09", order = 20 }
local ROW_H, MILESTONE_H, HEADER_H = 30, 44, 30
local MAX_ROWS = 200
local POP_MAX, POP_STEP, POP_TIME = 12, 0.11, 0.35 -- at most this many rows pop in, one every POP_STEP seconds
local SHOT_ICON = "Interface\\Icons\\INV_Misc_Spyglass_02"
local FILTER_SIZE = 28
local FILTERS_Y = 10 + FILTER_SIZE + 8                    -- top of the foldable filter row
local PAPER_Y_CLOSED, PAPER_Y_OPEN = FILTERS_Y, FILTERS_Y + FILTER_SIZE + 8
local SEARCH_W = 260

local STATUS_ICON = { confirmed = "ok", api_called = "wait" }
local TAKEN = { confirmed = true, api_called = true }
-- Several requests can name the same event (e.g. one was replaced); the best one is shown.
local RANK = { confirmed = 3, api_called = 2 }

local function settings() return FC.db.settings.modules.UI end

-------------------------------------------------------------------------------
-- Looks: fonts and colours per style and row kind (normal, milestone, danger, header)
-------------------------------------------------------------------------------

local STYLES = {
  classic = {
    title = { "GameFontHighlight", 1, 1, 1 },
    milestone = { "GameFontNormalLarge", 1, 0.82, 0 },
    danger = { "GameFontHighlight", 1, 0.45, 0.4 },
    sub = { "GameFontDisableSmall", 0.6, 0.6, 0.6 },
    header = { "GameFontNormal", 1, 0.82, 0 },
    line = { 1, 0.82, 0, 0.25 },
    hover = { 1, 0.82, 0, 0.08 },
    accent = { milestone = { 1, 0.82, 0 }, danger = { 0.9, 0.15, 0.1 } },
    accentAlpha = 0.16,
    shadow = true,
  },
  book = {
    title = { "GameFontHighlight", 0.18, 0.11, 0.04 },
    milestone = { "QuestTitleFont", 0.42, 0.2, 0 },
    danger = { "GameFontHighlight", 0.55, 0.08, 0.04 },
    sub = { "GameFontHighlightSmall", 0.36, 0.27, 0.17 },
    header = { "QuestTitleFont", 0.38, 0.2, 0.04 },
    line = { 0.38, 0.24, 0.1, 0.45 },
    hover = { 0.45, 0.28, 0.08, 0.10 },
    accent = { milestone = { 0.75, 0.5, 0.1 }, danger = { 0.6, 0.1, 0.05 } },
    accentAlpha = 0.22,
    shadow = false,
  },
}

local function style() return STYLES[settings().chronicleStyle] or STYLES.book end

local function applyFont(fs, spec, st)
  fs:SetFontObject(UI:Font(spec[1], "GameFontHighlight"))
  fs:SetTextColor(spec[2], spec[3], spec[4])
  if st.shadow then fs:SetShadowOffset(1, -1) else fs:SetShadowOffset(0, 0) end
end

-------------------------------------------------------------------------------
-- Days
-------------------------------------------------------------------------------

local function noon(t)
  local d = date("*t", t)
  return time({ year = d.year, month = d.month, day = d.day, hour = 12 }), d
end

local function dayLabel(t)
  local n, d = noon(t)
  local days = math.floor((noon(time()) - n) / 86400 + 0.5)
  if days == 0 then return L.CHRONICLE_TODAY end
  if days == 1 then return L.CHRONICLE_YESTERDAY end
  return string.format("%s, %s", L["WEEKDAY_" .. d.wday] or "", date(L.DATE_FORMAT, t))
end

-------------------------------------------------------------------------------
-- Rows
-------------------------------------------------------------------------------

local function better(a, b)
  return (RANK[a.status] or 1) > (RANK[b.status] or 1)
end

local function shotTime(rec) return rec.capturedAt or rec.requestedAt or 0 end

-- Name of a screenshot trigger ("Level-up", ...). FC.L returns the key itself for unknown triggers.
local function triggerLabel(trigger)
  local key = "TRIGGER_" .. tostring(trigger):upper()
  local text = L[key]
  return text ~= key and text or L.TRIGGER_MANUAL
end

local function createRow(row)
  -- Milestones and deaths: a colour wash from the left and a thin stripe.
  row.accent = row:CreateTexture(nil, "BACKGROUND", nil, 1)
  row.accent:SetPoint("TOPLEFT")
  row.accent:SetPoint("BOTTOMRIGHT", row, "BOTTOM", 80, 0)
  row.stripe = row:CreateTexture(nil, "BORDER")
  row.stripe:SetPoint("TOPLEFT")
  row.stripe:SetPoint("BOTTOMLEFT")
  row.stripe:SetWidth(3)

  row.iconFrame = row:CreateTexture(nil, "BORDER", nil, 1)
  row.icon = row:CreateTexture(nil, "ARTWORK")
  UI:CropIcon(row.icon)
  row.iconFrame:SetPoint("TOPLEFT", row.icon, -2, 2)
  row.iconFrame:SetPoint("BOTTOMRIGHT", row.icon, 2, -2)

  -- Screenshot marker on the right: spyglass icon with the screenshot's status in its corner.
  row.shot = row:CreateTexture(nil, "ARTWORK")
  row.shot:SetSize(22, 22)
  row.shot:SetPoint("RIGHT", -8, 0)
  UI:CropIcon(row.shot)
  row.shotStatus = row:CreateTexture(nil, "OVERLAY")
  row.shotStatus:SetSize(13, 13)
  row.shotStatus:SetPoint("BOTTOMRIGHT", row.shot, "BOTTOMRIGHT", 4, -3)

  row.text = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.text:SetPoint("TOPLEFT", row.icon, "TOPRIGHT", 8, -1)
  row.text:SetPoint("RIGHT", row, "RIGHT", -38, 0)
  row.text:SetJustifyH("LEFT")
  row.text:SetWordWrap(false)
  row.sub = row:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  row.sub:SetPoint("BOTTOMLEFT", row.icon, "BOTTOMRIGHT", 8, 1)
  row.sub:SetPoint("RIGHT", row, "RIGHT", -38, 0)
  row.sub:SetJustifyH("LEFT")
  row.sub:SetWordWrap(false)

  -- Day heading: text with a line on each side (book) or a line to the right (classic).
  row.header = row:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  row.header:SetWordWrap(false)
  row.lineL = row:CreateTexture(nil, "ARTWORK")
  row.lineL:SetHeight(1)
  row.lineR = row:CreateTexture(nil, "ARTWORK")
  row.lineR:SetHeight(1)

  -- Gold glow while a new entry pops in.
  row.flash = row:CreateTexture(nil, "BACKGROUND", nil, 2)
  row.flash:SetAllPoints()
  row.flash:SetAlpha(0)

  row.hl = row:CreateTexture(nil, "HIGHLIGHT")
  row.hl:SetAllPoints()

  -- Click: show this moment on the map.
  row:EnableMouse(true)
  row:SetScript("OnMouseUp", function(r)
    if r.time and UI.FocusMap then UI:FocusMap(r.time) end
  end)
  row:SetScript("OnEnter", function(r)
    if not r.time then return end
    GameTooltip:SetOwner(r, "ANCHOR_CURSOR")
    GameTooltip:SetText(r.title or "", 1, 0.82, 0)
    for _, line in ipairs(r.record and FC:EventDetails(r.record) or {}) do
      GameTooltip:AddLine(line, 1, 1, 1, true)
    end
    local shot = r.shotRecord
    if shot then
      GameTooltip:AddLine(string.format(L.CHRONICLE_SHOT_LINE, L["SHOT_STATUS_" .. shot.status:upper()]), 1, 1, 1)
      if shot.fileStamp and TAKEN[shot.status] then
        GameTooltip:AddLine("WoWScrnShot_" .. shot.fileStamp, 0.7, 0.7, 0.7)
        GameTooltip:AddLine(L.CHRONICLE_SHOT_HINT, 0.7, 0.7, 0.7, true)
      end
    end
    GameTooltip:AddLine(L.CHRONICLE_CLICK_HINT, 1, 1, 1)
    GameTooltip:Show()
  end)
  row:SetScript("OnLeave", GameTooltip_Hide)
end

local function updateHeader(row, item, st)
  for _, r in ipairs({ row.icon, row.iconFrame, row.text, row.sub, row.shot, row.shotStatus, row.accent, row.stripe }) do
    r:Hide()
  end
  row.time, row.title, row.shotRecord, row.record = nil, nil, nil, nil
  row.hl:SetColorTexture(0, 0, 0, 0)
  applyFont(row.header, st.header, st)
  row.header:SetText(item.text)
  row.header:Show()
  row.header:ClearAllPoints()
  row.lineL:ClearAllPoints()
  row.lineR:ClearAllPoints()
  local c = st.line
  row.lineL:SetColorTexture(c[1], c[2], c[3], c[4])
  row.lineR:SetColorTexture(c[1], c[2], c[3], c[4])
  -- Heading and lines share one vertical centre (2 px below the row's centre).
  if st == STYLES.book then
    row.header:SetPoint("CENTER", 0, -2)
    row.lineL:SetPoint("LEFT", row, "LEFT", 30, -2)
    row.lineL:SetPoint("RIGHT", row.header, "LEFT", -12, 0)
    row.lineR:SetPoint("LEFT", row.header, "RIGHT", 12, 0)
    row.lineR:SetPoint("RIGHT", row, "RIGHT", -30, -2)
    row.lineL:Show()
  else
    row.header:SetPoint("LEFT", 6, -2)
    row.lineR:SetPoint("LEFT", row.header, "RIGHT", 10, 0)
    row.lineR:SetPoint("RIGHT", row, "RIGHT", -8, -2)
    row.lineL:Hide()
  end
  row.lineR:Show()
end

-- item = { event = record } or { shot = screenshot record without an entry }; item.shot is set on events with one.
local function updateRow(row, item)
  local st = style()
  row.flash:SetColorTexture(1, 0.82, 0, 0.35)
  if item.header then return updateHeader(row, item, st) end
  row.header:Hide()
  row.lineL:Hide()
  row.lineR:Hide()
  row.hl:SetColorTexture(unpack(st.hover))

  local text, icon, when, where
  if item.event then
    local record = item.event
    text, icon = FC:DescribeEvent(record)
    where = record.location and (record.location.subzone or record.location.zone)
    when = record.time
  else
    text, icon, when = triggerLabel(item.shot.trigger), SHOT_ICON, shotTime(item.shot)
  end
  local kind = item.highlight
  local big = kind == "milestone"

  row.icon:SetSize(big and 34 or 24, big and 34 or 24)
  row.icon:ClearAllPoints()
  row.icon:SetPoint("LEFT", big and 10 or 8, 0)
  UI:SetIcon(row.icon, icon)
  row.icon:Show()
  local accent = kind and st.accent[kind]
  if accent then
    row.iconFrame:SetColorTexture(accent[1], accent[2], accent[3], 0.9)
    row.iconFrame:Show()
    UI:Gradient(row.accent, "HORIZONTAL", accent[1], accent[2], accent[3], st.accentAlpha, accent[1], accent[2], accent[3], 0)
    row.accent:Show()
    row.stripe:SetColorTexture(accent[1], accent[2], accent[3], 0.9)
    row.stripe:Show()
  else
    row.iconFrame:Hide()
    row.accent:Hide()
    row.stripe:Hide()
  end

  applyFont(row.text, big and st.milestone or (kind == "danger" and st.danger) or st.title, st)
  applyFont(row.sub, st.sub, st)
  row.text:SetText(text)
  row.text:Show()
  local whenText = date(L.TIME_FORMAT, when or 0)
  row.sub:SetText(where and (whenText .. UI.SEP .. where) or whenText)
  row.sub:Show()
  row.time, row.title, row.shotRecord, row.record = when, text, item.shot, item.event

  local shot = item.shot
  row.shot:SetShown(shot ~= nil)
  row.shotStatus:SetShown(shot ~= nil)
  if shot then
    UI:SetIcon(row.shot, SHOT_ICON)
    row.shot:SetDesaturated(not TAKEN[shot.status])
    row.shot:SetAlpha(TAKEN[shot.status] and 1 or 0.5)
    UI:SetIcon(row.shotStatus, UI.STATUS_ICONS[STATUS_ICON[shot.status] or "bad"])
  end
end

local function rowHeight(item)
  if item.header then return HEADER_H end
  return item.highlight == "milestone" and MILESTONE_H or ROW_H
end

-------------------------------------------------------------------------------
-- Items
-------------------------------------------------------------------------------

-- Screenshot records of the viewed character: event id -> best record, plus records without an event.
local function indexShots(stream)
  local byEvent, loose = {}, {}
  for _, rec in ipairs(stream.records) do
    local ids = type(rec.events) == "table" and rec.events or {}
    if #ids == 0 then
      loose[#loose + 1] = rec
    end
    for _, id in ipairs(ids) do
      local known = byEvent[id]
      if not known or better(rec, known) then byEvent[id] = rec end
    end
  end
  return byEvent, loose
end

-- Lower case for searching, including the German umlauts (string.lower leaves non-ASCII letters alone).
local UMLAUTS = { ["\195\132"] = "\195\164", ["\195\150"] = "\195\182", ["\195\156"] = "\195\188" }
local function fold(s)
  return (string.lower(s):gsub("\195[\132\150\156]", UMLAUTS))
end

local function matches(query, ...)
  if not query then return true end
  for i = 1, select("#", ...) do
    local s = select(i, ...)
    if type(s) == "string" and fold(s):find(query, 1, true) then return true end
  end
  return false
end

-- Newest first: events (each with its screenshot) and screenshots without an entry, at most MAX_ROWS.
-- hidden: category -> true for categories switched off; onlyShots: only entries with a taken screenshot;
-- search: text the entry or its place must contain. Also returns the number of events per category
-- (for the filter tooltips).
local function buildItems(hidden, onlyShots, search)
  local query = search and search ~= "" and fold(search) or nil
  local events = FC:ViewStream("events").records
  local byEvent, loose = indexShots(FC:ViewStream("screenshots"))
  local items, counts = {}, {}
  for i = #events, 1, -1 do
    local record = events[i]
    local category = FC:EventCategory(record)
    if category then counts[category] = (counts[category] or 0) + 1 end
    local shot = byEvent[record.id]
    if #items < MAX_ROWS and not (category and hidden[category])
      and (not onlyShots or (shot and TAKEN[shot.status])) then
      local loc = record.location
      if not query or matches(query, (FC:DescribeEvent(record)), loc and loc.zone, loc and loc.subzone) then
        local def = FC.eventTypes[record.type]
        items[#items + 1] = { event = record, shot = shot, time = record.time or 0, highlight = def and def.highlight }
      end
    end
  end
  -- Loose screenshots inside the shown time range (all of them if the list is not full).
  local oldest = #items >= MAX_ROWS and items[#items].time or -math.huge
  for _, rec in ipairs(loose) do
    local label = triggerLabel(rec.trigger)
    if shotTime(rec) >= oldest and (not onlyShots or TAKEN[rec.status]) and matches(query, label) then
      items[#items + 1] = { shot = rec, time = shotTime(rec) }
    end
  end
  table.sort(items, function(a, b) return a.time > b.time end)
  for i = #items, MAX_ROWS + 1, -1 do items[i] = nil end
  return items, counts
end

-- The list shown: a heading before the first entry of each day.
local function withHeaders(items)
  local out, day = {}, nil
  for _, item in ipairs(items) do
    local d = date("%Y-%m-%d", item.time)
    if d ~= day then
      day = d
      out[#out + 1] = { header = true, text = dayLabel(item.time), time = item.time }
    end
    out[#out + 1] = item
  end
  return out
end

-------------------------------------------------------------------------------
-- Page
-------------------------------------------------------------------------------

function page:Create(c)
  self.container = c

  -- Top bar: the foldable filter header (left), search (middle), "only with screenshot" (right).
  self.foldButton = CreateFrame("Button", nil, c)
  self.foldButton:SetSize(200, FILTER_SIZE)
  self.foldButton:SetPoint("TOPLEFT", 12, -10)
  self.foldIcon = self.foldButton:CreateTexture(nil, "ARTWORK")
  self.foldIcon:SetSize(16, 16)
  self.foldIcon:SetPoint("LEFT", 2, 0)
  self.foldLabel = self.foldButton:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  self.foldLabel:SetPoint("LEFT", self.foldIcon, "RIGHT", 6, 0)
  self.foldButton:SetHighlightTexture("Interface\\Buttons\\UI-PlusButton-Hilight", "ADD")
  local hl = self.foldButton:GetHighlightTexture()
  if type(hl) == "table" then
    hl:ClearAllPoints()
    hl:SetAllPoints(self.foldIcon)
  end
  self.foldButton:SetScript("OnClick", function() self:SetFiltersOpen(not settings().chronicleFiltersOpen, true) end)
  UI:Tooltip(self.foldButton, "CHRONICLE_FILTERS", "CHRONICLE_FILTERS_TIP")

  self.filter = UI:IconButton(c, FILTER_SIZE, SHOT_ICON, "CHRONICLE_ONLY_SHOTS", "CHRONICLE_ONLY_SHOTS_TIP", function(btn)
    self.onlyShots = not self.onlyShots
    UI:SetToggle(btn, self.onlyShots)
    self:Refresh()
  end)
  self.filter:SetPoint("TOPRIGHT", -14, -10)
  UI:SetToggle(self.filter, false)

  self:CreateSearch(c)
  self.searchBox:SetPoint("RIGHT", self.filter, "LEFT", -14, 0)

  -- The filter icons, one per event category, in the foldable row under the bar.
  self.filters = {}
  local prev
  for _, cat in ipairs(FC.eventCategories) do
    local b = UI:IconButton(c, FILTER_SIZE, cat.icon, function() return L[cat.labelKey] end, function(btn)
      local n = self.counts and self.counts[cat.key] or 0
      return string.format(L.CHRONICLE_FILTER_TIP, n)
    end, function(btn) self:ClickFilter(cat.key) end)
    if prev then b:SetPoint("LEFT", prev, "RIGHT", 6, 0) else b:SetPoint("TOPLEFT", 16, -FILTERS_Y) end
    b.category = cat.key
    self.filters[#self.filters + 1] = b
    prev = b
  end

  -- The page: parchment (book) or nothing (classic) behind the list.
  local paper = CreateFrame("Frame", nil, c, "BackdropTemplate")
  paper:SetPoint("TOPLEFT", 6, -PAPER_Y_CLOSED)
  paper:SetPoint("BOTTOMRIGHT", -6, 6)
  self.paper = paper
  self.parchment = paper:CreateTexture(nil, "BACKGROUND")
  self.parchment:SetPoint("TOPLEFT", 4, -4)
  self.parchment:SetPoint("BOTTOMRIGHT", -4, 4)
  self.vignette = {}
  for _, side in ipairs({ "TOP", "BOTTOM", "LEFT", "RIGHT" }) do
    local v = paper:CreateTexture(nil, "BACKGROUND", nil, 1)
    v.side = side
    self.vignette[#self.vignette + 1] = v
  end

  self.list = UI:List(paper, rowHeight, createRow, updateRow)
  self.list.scroll:SetPoint("TOPLEFT", 10, -8)
  self.list.scroll:SetPoint("BOTTOMRIGHT", -30, 8)

  self.empty = UI:Label(paper, "CHRONICLE_EMPTY", "GameFontDisable")
  self.empty:SetPoint("CENTER")
  self.emptyShots = UI:Label(paper, "SHOT_NONE", "GameFontDisable")
  self.emptyShots:SetPoint("CENTER")
  self.emptyFiltered = UI:Label(paper, "CHRONICLE_FILTERED", "GameFontDisable")
  self.emptyFiltered:SetPoint("CENTER")

  self:ApplyStyle()
  self:SyncFilters()
  self:SetFiltersOpen(settings().chronicleFiltersOpen, false)
end

-- Search box: the game's search box (magnifier, clear button, grey hint) where available.
function page:CreateSearch(c)
  local ok, box = pcall(CreateFrame, "EditBox", nil, c, "SearchBoxTemplate")
  if not ok or not box then box = CreateFrame("EditBox", nil, c, "InputBoxTemplate") end
  box:SetSize(SEARCH_W, 20)
  box:SetAutoFocus(false)
  box:SetMaxLetters(60)
  -- The template's own hint text, or our own grey hint while the box is empty and not focused.
  local hint = type(box.Instructions) == "table" and box.Instructions
  if not hint then
    hint = box:CreateFontString(nil, "OVERLAY", "GameFontDisable")
    hint:SetPoint("LEFT", 4, 0)
    box.fcHint = hint
  end
  hint:SetText(L.CHRONICLE_SEARCH)
  UI:Track(hint, "CHRONICLE_SEARCH")
  local function changed(b)
    local text = b:GetText() or ""
    if b.fcHint then b.fcHint:SetShown(text == "" and not (b.HasFocus and b:HasFocus() == true)) end
    self:SetSearch(text)
  end
  box:HookScript("OnTextChanged", changed)
  box:HookScript("OnEditFocusGained", changed)
  box:HookScript("OnEditFocusLost", changed)
  box:HookScript("OnEnterPressed", function(b) b:ClearFocus() end)
  box:HookScript("OnEscapePressed", function(b) b:ClearFocus() end)
  self.searchBox = box
end

-- Shows only entries whose text or place contains `text` (ignoring case); "" shows all.
function page:SetSearch(text)
  text = strtrim and strtrim(text or "") or (text or "")
  if text == (self.search or "") then return end
  self.search = text
  self:Refresh()
end

-- Folds the filter icons in or out; the page below follows (animated when asked).
function page:SetFiltersOpen(open, animate)
  settings().chronicleFiltersOpen = open and true or false
  self.foldIcon:SetTexture(open and "Interface\\Buttons\\UI-MinusButton-Up" or "Interface\\Buttons\\UI-PlusButton-Up")
  local from = self.foldShare or (open and 0 or 1)
  local to = open and 1 or 0
  local function step(p)
    local share = from + (to - from) * p
    self.foldShare = share
    self.paper:SetPoint("TOPLEFT", 6, -(PAPER_Y_CLOSED + (PAPER_Y_OPEN - PAPER_Y_CLOSED) * share))
    for _, b in ipairs(self.filters) do
      b:SetAlpha(share)
      b:SetShown(share > 0.01)
    end
  end
  if animate then UI:Tween(self.foldButton, 0.18, 0, step) else UI:StopTween(self.foldButton); step(1) end
  self:UpdateFoldLabel()
end

-- "Filters", or "Filters (2 hidden)" while categories are switched off.
function page:UpdateFoldLabel()
  local hidden = 0
  for _, cat in ipairs(FC.eventCategories) do if settings().chronicleHidden[cat.key] then hidden = hidden + 1 end end
  self.foldLabel:SetText(hidden > 0 and string.format(L.CHRONICLE_FILTERS_HIDDEN, hidden) or L.CHRONICLE_FILTERS)
end

-- Darker, aged edges of the parchment: side -> gradient orientation and its alpha at the start and the end
-- (bottom/left to top/right).
local VIGNETTE = {
  LEFT = { "HORIZONTAL", 0.35, 0 }, RIGHT = { "HORIZONTAL", 0, 0.35 },
  BOTTOM = { "VERTICAL", 0.35, 0 }, TOP = { "VERTICAL", 0, 0.35 },
}
local VIGNETTE_COLOR = { 0.3, 0.18, 0.05 }

-- Parchment candidates, the first one the client has is used.
local PARCHMENT = {
  { file = "Interface\\AchievementFrame\\UI-Achievement-Parchment-Horizontal" },
  { atlas = "QuestBG-Parchment" },
  { file = "Interface\\Stationery\\StationeryTest1" },
}

function page:ApplyStyle()
  local book = settings().chronicleStyle ~= "classic"
  local paper = self.paper
  if book then
    if not UI:SetTextureFirst(self.parchment, PARCHMENT) then self.parchment:SetColorTexture(0.86, 0.76, 0.56, 1) end
    self.parchment:SetVertexColor(1, 1, 1, 1)
    UI:Backdrop(paper, { edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 14,
      insets = { left = 4, right = 4, top = 4, bottom = 4 } }, nil, { 0.42, 0.29, 0.15, 1 })
    for _, v in ipairs(self.vignette) do
      local orientation, from, to = unpack(VIGNETTE[v.side])
      local r, g, b = unpack(VIGNETTE_COLOR)
      v:ClearAllPoints()
      v:SetPoint(v.side, self.parchment, v.side)
      if orientation == "HORIZONTAL" then
        v:SetPoint("TOP", self.parchment, "TOP")
        v:SetPoint("BOTTOM", self.parchment, "BOTTOM")
        v:SetWidth(36)
      else
        v:SetPoint("LEFT", self.parchment, "LEFT")
        v:SetPoint("RIGHT", self.parchment, "RIGHT")
        v:SetHeight(28)
      end
      UI:Gradient(v, orientation, r, g, b, from, r, g, b, to)
      v:Show()
    end
    self.parchment:Show()
  else
    self.parchment:Hide()
    for _, v in ipairs(self.vignette) do v:Hide() end
    UI:Backdrop(paper, nil)
  end
  local st = style()
  for _, label in ipairs({ self.empty, self.emptyShots, self.emptyFiltered }) do
    label:SetTextColor(st.sub[2], st.sub[3], st.sub[4])
  end
end

function UI:RestyleChronicle()
  if not page.paper then return end
  page:ApplyStyle()
  page.lastKey = nil
  UI:RefreshCurrent()
end

-- Click: switch the category on or off. Shift-click: show only this category (again: show all).
function page:ClickFilter(key)
  local hidden = settings().chronicleHidden
  if IsShiftKeyDown and IsShiftKeyDown() then
    local alreadyAlone = not hidden[key]
    for _, cat in ipairs(FC.eventCategories) do
      if cat.key ~= key and not hidden[cat.key] then alreadyAlone = false end
    end
    for _, cat in ipairs(FC.eventCategories) do
      hidden[cat.key] = (not alreadyAlone and cat.key ~= key) or nil
    end
  else
    hidden[key] = (not hidden[key]) or nil
  end
  self:SyncFilters()
  self:Refresh()
end

function page:SyncFilters()
  local hidden = settings().chronicleHidden
  for _, b in ipairs(self.filters) do UI:SetToggle(b, not hidden[b.category]) end
  if self.foldLabel then self:UpdateFoldLabel() end
end

-- New entries since the page was last seen pop in, oldest first; their day headings come with them.
function page:PopIn(shown, seen)
  local rows = self.list.rows
  for _, row in ipairs(rows) do
    UI:StopTween(row, true)
    UI:StopTween(row.flash, true)
  end
  local order = {}
  for i, item in ipairs(shown) do
    if #order >= POP_MAX then break end
    local next = shown[i + 1]
    local isNew = item.time > seen and (not item.header or (next and not next.header and next.time > seen))
    if isNew then order[#order + 1] = i end
  end
  for k = #order, 1, -1 do
    local row = rows[order[k]]
    local delay = (#order - k) * POP_STEP
    UI:Tween(row, POP_TIME, delay, function(p)
      row:SetAlpha(p)
      row:SetPoint("TOPLEFT", (1 - p) * -22, -row.y)
    end)
    if not shown[order[k]].header then
      UI:Tween(row.flash, 1.1, delay + POP_TIME * 0.6, function(p) row.flash:SetAlpha(1 - p) end)
    end
  end
end

-- Rebuilt when events or screenshots change (a screenshot's status changes in place), the filters, the
-- style or the language.
function page:Refresh()
  local events, shots = FC:ViewStream("events"), FC:ViewStream("screenshots")
  local last = shots.records[#shots.records]
  local hidden = settings().chronicleHidden
  local hiddenKey = {}
  for _, cat in ipairs(FC.eventCategories) do if hidden[cat.key] then hiddenKey[#hiddenKey + 1] = cat.key end end
  local key = table.concat({ tostring(FC:ViewKey()), tostring(events.nextSeq), tostring(shots.nextSeq),
    tostring(last and last.status), tostring(self.onlyShots), tostring(self.search), table.concat(hiddenKey, ","),
    tostring(settings().chronicleStyle), tostring(FC:GetLanguage()), date("%Y%m%d") }, ":")
  if self.lastKey == key then return end -- nothing new
  self.lastKey = key
  self:UpdateFoldLabel()
  local items, counts = buildItems(hidden, self.onlyShots, self.search)
  local shown = withHeaders(items)
  self.items, self.shown, self.counts = items, shown, counts
  self.list:SetItems(shown)

  local viewKey = tostring(FC:ViewKey())
  local seenAll = settings().chronicleSeen
  local seen = seenAll[viewKey] or -math.huge
  self:PopIn(shown, seen)
  if items[1] and items[1].time > seen then seenAll[viewKey] = items[1].time end

  local filtered = #hiddenKey > 0 or (self.search or "") ~= ""
  self.empty:SetShown(#items == 0 and not self.onlyShots and not filtered)
  self.emptyShots:SetShown(#items == 0 and self.onlyShots == true and not filtered)
  self.emptyFiltered:SetShown(#items == 0 and filtered)
end

function page:OnViewChanged()
  self.lastKey = nil
end

UI:RegisterPage(page)
