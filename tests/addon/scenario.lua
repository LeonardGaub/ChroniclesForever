-- Scenario phases. PHASE is set by run.js; SAVED holds the SavedVariables text of the previous phase.

local function check(cond, msg)
  if not cond then error("CHECK FAILED: " .. msg, 2) end
  print("  ok  " .. msg)
end

local function loadAddon()
  if SAVED then assert(load(SAVED, "=SavedVariables"))() end
  MOCK.clock = MOCK.clock + (PHASE_OFFSET or 0)
  local ns = {}
  for _, name in ipairs(ADDON_FILES) do
    local chunk = assert(load(ADDON_SRC[name], "@" .. name))
    chunk("ForeverChronicle", ns)
  end
  return ns
end

-- Serializes a value the way the client writes SavedVariables.
local function serialize(v, indent)
  indent = indent or ""
  local t = type(v)
  if t == "string" then return string.format("%q", v):gsub("\\\n", "\\n") end
  if t == "number" or t == "boolean" then return tostring(v) end
  if t ~= "table" then return "nil" end
  local out, n = { "{\n" }, #v
  for i = 1, n do out[#out + 1] = indent .. "\t" .. serialize(v[i], indent .. "\t") .. ", -- [" .. i .. "]\n" end
  local keys = {}
  for k in pairs(v) do
    if not (type(k) == "number" and k >= 1 and k <= n and k % 1 == 0) then keys[#keys + 1] = k end
  end
  table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
  for _, k in ipairs(keys) do
    local key = type(k) == "string" and string.format("[%q]", k) or "[" .. tostring(k) .. "]"
    out[#out + 1] = indent .. "\t" .. key .. " = " .. serialize(v[k], indent .. "\t") .. ",\n"
  end
  out[#out + 1] = indent .. "}"
  return table.concat(out)
end

local function save()
  return "\nForeverChronicleDB = " .. serialize(ForeverChronicleDB) .. "\n"
end

local function startClient(isInitialLogin, isReloadingUi)
  local FC = loadAddon()
  MOCK.fire("ADDON_LOADED", "ForeverChronicle")
  MOCK.fire("PLAYER_LOGIN")
  MOCK.fire("PLAYER_ENTERING_WORLD", isInitialLogin, isReloadingUi)
  return FC
end

local function sessions() return ForeverChronicleDB.characters["Player-4619-0112A417"].streams.sessions.records end
local function events() return ForeverChronicleDB.characters["Player-4619-0112A417"].streams.events.records end

if PHASE == 1 then
  print("phase 1: first login, gameplay, UI")
  local FC = startClient(true, false)
  check(FC.ready, "addon ready after login")
  check(ForeverChronicleDB.settings.language == "deDE", "default language German")
  check(#sessions() == 1 and sessions()[1].endReason == "open", "session started")

  MOCK.advance(10.1)
  check(not ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "chat frame unregistered during request")
  MOCK.advance(3)
  check(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "chat frame re-registered")
  local printed = false
  for _, l in ipairs(MOCK.chat) do if l:find("^PLAYED") then printed = true end end
  check(not printed, "played time not printed to chat")
  check(sessions()[1].playedTotal == 74113, "played time stored on session")

  MOCK.advance(60)
  MOCK.fire("QUEST_TURNED_IN", 3513, 2550, 0)
  MOCK.advance(30)
  MOCK.instance = true; MOCK.zone = "Ragefire Chasm"
  MOCK.fire("PLAYER_DEAD")
  MOCK.instance = nil; MOCK.zone = nil
  MOCK.advance(30)
  MOCK.level = 23
  levelUpAt = MOCK.now
  MOCK.fire("PLAYER_LEVEL_UP", 23)
  MOCK.fire("ACHIEVEMENT_EARNED", 6, false)
  MOCK.fire("QUEST_TURNED_IN", MOCK.SECRET, 1, 1) -- secret value must be ignored safely

  local types = {}
  for _, r in ipairs(events()) do types[#types + 1] = r.type end
  check(table.concat(types, ",") == "session_started,quest_completed,player_died,level_up,achievement_earned",
    "events recorded in order: " .. table.concat(types, ","))
  local quest = events()[2]
  check(quest.data.title == "The Runaway Shipment" and quest.location.mapID == 1413 and quest.location.x == 0.4403,
    "quest has title and rounded position")
  local death = events()[3]
  check(death.location.zone == "Ragefire Chasm" and death.location.mapID == nil and death.location.instanceID == 389
    and death.location.quality == "zone_only", "death in instance is zone-only with instance ID")
  check(events()[5].seq == 5, "seq numbers assigned")
  local stats = ForeverChronicleDB.characters["Player-4619-0112A417"].stats
  check(stats.quests_completed == 1 and stats.deaths == 1 and stats.levels_gained == 1 and stats.sessions == 1, "stats counted")

  -- Kills and experience (a level-up wraps the XP bar: rest of the old level is added).
  MOCK.fire("PARTY_KILL", "Player-4619-0112A417", "Creature-1")
  MOCK.fire("PARTY_KILL", "Player-4619-0112A417", "Creature-2")
  MOCK.xp = 1500; MOCK.fire("PLAYER_XP_UPDATE", "player")
  MOCK.xp, MOCK.xpMax = 4800, 5000; MOCK.fire("PLAYER_XP_UPDATE", "player")
  MOCK.xp, MOCK.xpMax = 200, 6000; MOCK.fire("PLAYER_XP_UPDATE", "player")
  MOCK.fire("PLAYER_XP_UPDATE", "target")
  check(stats.kills == 2, "kills counted (" .. tostring(stats.kills) .. ")")
  check(stats.xp_earned == 500 + 3300 + 400, "experience counted across a level-up (" .. tostring(stats.xp_earned) .. ")")
  check(FC.Util.FormatNumber(1234567) == "1.234.567", "German number format")

  -- UI: open, visit every page, switch language, run commands.
  SlashCmdList.FOREVERCHRONICLE("")
  check(ForeverChronicleFrame and ForeverChronicleFrame:IsShown(), "window opens with /fc")
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end
  check(#FC.UI.pages == 6, "six pages registered")
  SlashCmdList.FOREVERCHRONICLE("lang en")
  check(FC.L.TAB_OVERVIEW == "Overview", "language switched to English")
  check(#ForeverChronicleFrame.Tabs == 6 and ForeverChronicleFrame.Tabs[2].page.icon ~= nil, "icon tabs, one per page")
  local overview = FC.UI.pages[1]
  FC.UI:SelectPage(1)
  check(overview.name.text:find("Blind Bullseye", 1, true) ~= nil, "full name with last name: " .. tostring(overview.name.text))
  local tileNames = {}
  for _, tile in ipairs(overview.tiles) do tileNames[#tileNames + 1] = tile.def.key end
  local names = table.concat(tileNames, ",")
  check(names:find("kills", 1, true) and names:find("xp_earned", 1, true) and not names:find("levels_gained", 1, true)
    and not names:find("reload", 1, true) and not names:find("screenshots", 1, true),
    "tiles: kills and XP, no levels/reloads/screenshots (" .. names .. ")")
  local kills
  for _, tile in ipairs(overview.tiles) do if tile.def.key == "kills" then kills = tile end end
  check(kills.value.text == "2" and kills.name.text ~= nil, "tile shows name and value")
  check(#overview.slots == 19 and overview.slots[1].border ~= nil, "19 gear slots")
  local settingsIndex
  for i, pg in ipairs(FC.UI.pages) do if pg.id == "settings" then settingsIndex = i end end
  FC.UI:SelectPage(settingsIndex)
  check(#FC.UI.pages[settingsIndex].bars == 5, "storage bars on the settings page (" .. #FC.UI.pages[settingsIndex].bars .. ")")
  SlashCmdList.FOREVERCHRONICLE("lang de")
  SlashCmdList.FOREVERCHRONICLE("status")
  SlashCmdList.FOREVERCHRONICLE("help")
  SlashCmdList.FOREVERCHRONICLE("nonsense")
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")

  -- Walk north-east for two minutes, then stand still.
  for i = 1, 12 do
    MOCK.x, MOCK.y = 0.4403 + i * 0.004, 0.5913 - i * 0.003
    MOCK.advance(10)
  end
  MOCK.advance(600)
  MOCK.fire("PLAYER_LOGOUT")
  check(sessions()[1].endReason == "logout" and sessions()[1].endedAt, "session closed on logout")
  local positions = ForeverChronicleDB.characters["Player-4619-0112A417"].streams.positions.records
  check(#positions >= 12 and #positions <= 20, "route sampled (" .. #positions .. " points)")
  local lastFields = {}
  for f in (positions[#positions] .. ","):gmatch("([^,]*),") do lastFields[#lastFields + 1] = f end
  check(#lastFields == 7 and lastFields[2] == "1413" and lastFields[5] ~= "", "standing still extends the last point")
  check(ForeverChronicleDB.maps["1413"].continent == 1414 and ForeverChronicleDB.maps["1413"].minX == 0.4,
    "map geometry recorded")

  -- Graphs: XP per played hour from the metrics stream, switchable.
  local sum = 0
  for _, v in pairs(FC.Metrics:HourlyDeltas("xp")) do sum = sum + v end
  check(sum == 4200, "XP time series matches the earned XP (" .. sum .. ")")
  local hours = FC.Metrics:PlayedHours(12)
  check(#hours >= 1 and #hours <= 12, "played hours (" .. #hours .. ")")
  FC.UI:SelectPage(1)
  local ov = FC.UI.pages[1]
  ov.graphVersion = nil
  ov:RefreshGraph()
  local shownBars = 0
  for _, bar in ipairs(ov.graph.bars) do if bar:IsShown() then shownBars = shownBars + 1 end end
  check(shownBars == #hours and ov.graphTitle.text == "Erfahrung pro Stunde", "XP graph drawn (" .. shownBars .. " bars)")
  ov:StepGraph(1)
  check(FC.db.settings.overviewGraph == "kills" and ov.graphTitle.text == "Getötete Gegner pro Stunde", "switch to kills graph")
  ov:StepGraph(-2)
  check(FC.db.settings.overviewGraph == "gold", "switching wraps around")
  local shots = ForeverChronicleDB.characters["Player-4619-0112A417"].streams.screenshots.records
  for _, r in ipairs(shots) do print("    shot", r.trigger, r.status, #r.events) end
  check(#shots == 1 and #MOCK.screenshots == 1, "level-up and achievement produced one screenshot")
  check(shots[1].status == "confirmed" and #shots[1].events == 2 and shots[1].trigger == "level",
    "screenshot confirmed and linked to both events")
  check(type(shots[1].fileStamp) == "string" and #shots[1].fileStamp == 13, "file stamp stored (" .. tostring(shots[1].fileStamp) .. ")")
  check(MOCK.screenshots[1] >= levelUpAt + 5, "screenshot taken after the 5 s delay")
  SAVED_OUT = save()

elseif PHASE == 2 then
  print("phase 2: /reload continues the session")
  startClient(false, true)
  check(#sessions() == 1, "no new session on reload")
  check(sessions()[1].endReason == "open" and sessions()[1].endedAt == nil, "session reopened")
  check(sessions()[1].reloads == 1, "reload counted")
  check(#events() == 5, "no new events on reload")
  MOCK.advance(120)
  MOCK.fire("PLAYER_LOGOUT")
  SAVED_OUT = save()

elseif PHASE == 3 then
  print("phase 3: later login starts a new session")
  startClient(true, false)
  check(#sessions() == 2, "second session")
  check(sessions()[1].endReason == "logout", "first session stays closed")
  check(events()[6].type == "session_started" and events()[6].seq == 6, "session_started appended with next seq")
  MOCK.advance(300)
  MOCK.fire("PLAYER_LOGOUT")
  SAVED_OUT = save()

elseif PHASE == 4 then
  print("phase 4: retention cap drops oldest records")
  local FC = startClient(true, false)
  FC.Storage.streams.events.cap = 5
  for i = 1, 10 do MOCK.fire("PLAYER_DEAD") end
  local stream = ForeverChronicleDB.characters["Player-4619-0112A417"].streams.events
  check(#stream.records <= 5 * 1.1 + 1, "stream trimmed (" .. #stream.records .. " records)")
  MOCK.fire("PLAYER_LOGOUT")
  check(#stream.records == 5, "trimmed to cap on logout")
  check(stream.dropped == stream.nextSeq - 1 - 5, "dropped records counted (" .. stream.dropped .. ")")
  check(stream.records[1].seq == stream.nextSeq - 5, "remaining records are the newest")
end
if PHASE == 5 then
  print("phase 5: zones, flights and screenshot rules")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters["Player-4619-0112A417"]
  local function shots() return char.streams.screenshots.records end
  local function statuses()
    local s = {}
    for _, r in ipairs(shots()) do s[#s + 1] = r.trigger .. ":" .. r.status end
    return table.concat(s, ",")
  end
  local function lastEvent() local r = events(); return r[#r] end

  check(FC.char.state.Travel.known["map:1413"].initial, "starting zone is known without an event")
  MOCK.advance(6)
  check(lastEvent().type == "session_started", "no discovery for the starting zone")

  -- New zone: discovered after the dwell time, screenshot after the delay.
  MOCK.travel(1411, "Durotar")
  MOCK.advance(4.9)
  check(lastEvent().type == "session_started", "not discovered before the dwell time")
  MOCK.advance(0.3)
  check(lastEvent().type == "zone_discovered" and lastEvent().data.zone == "Durotar", "Durotar discovered after 5 s")
  MOCK.advance(6)
  check(statuses() == "zone:confirmed", "zone screenshot taken: " .. statuses())
  local firstShotAt = MOCK.screenshots[1]

  -- Flying over a zone does not discover it; landing does.
  MOCK.taxi = true
  MOCK.travel(1454, "Orgrimmar")
  MOCK.advance(8)
  check(lastEvent().data.zone == "Durotar", "no discovery while on a taxi")
  MOCK.taxi = false
  MOCK.fire("PLAYER_CONTROL_GAINED")
  MOCK.advance(5.2)
  check(lastEvent().data.zone == "Orgrimmar", "discovered after landing")

  -- Cooldown: the Orgrimmar screenshot waits until 30 s after the previous one.
  MOCK.advance(10)
  check(#MOCK.screenshots == 1, "zone screenshot waits for the cooldown")
  MOCK.advance(20)
  check(#MOCK.screenshots == 2 and MOCK.screenshots[2] >= firstShotAt + 30, "taken after the cooldown")

  -- Leaving a zone before its screenshot is taken drops the request.
  MOCK.travel(1412, "Mulgore")
  MOCK.advance(5.2)
  check(lastEvent().data.zone == "Mulgore", "Mulgore discovered")
  MOCK.travel(1456, "Thunder Bluff")
  MOCK.advance(1)
  check(statuses():find("zone:left_zone", 1, true), "request dropped after leaving the zone: " .. statuses())

  -- Level-ups skip the cooldown (bypass) but still wait for the delay.
  local before = #MOCK.screenshots
  MOCK.level = 24
  local t = MOCK.now
  MOCK.fire("PLAYER_LEVEL_UP", 24)
  MOCK.advance(2)
  check(ForeverChronicleCountdown:IsShown() and ForeverChronicleCountdown.text.text:find("^Screenshot in [34] s$") ~= nil,
    "countdown shown during the delay (" .. tostring(ForeverChronicleCountdown.text.text) .. ")")
  MOCK.advance(3.5)
  check(MOCK.countdownVisibleAtCapture == false, "countdown hidden when the screenshot is taken")
  check(#MOCK.screenshots == before + 1 and MOCK.screenshots[#MOCK.screenshots] - t < 6, "level-up skips the cooldown")

  -- Delay setting and test command.
  SlashCmdList.FOREVERCHRONICLESHOT("delay 2")
  check(FC:GetModule("Screenshots"):GetSettings().delay == 2, "/fcshot delay sets the delay")
  MOCK.advance(3)
  SlashCmdList.FOREVERCHRONICLESHOT("test")
  MOCK.advance(1)
  check(not statuses():find("manual:", 1, true) and ForeverChronicleCountdown:IsShown(),
    "test screenshot waits for the delay with countdown")
  MOCK.advance(1.5)
  check(statuses():find("manual:", 1, true), "test screenshot taken after the delay")
  -- Hide the interface for the screenshot (not in combat) and show it again afterwards.
  FC:GetModule("Screenshots"):GetSettings().hideUI = true
  MOCK.advance(3)
  SlashCmdList.FOREVERCHRONICLESHOT("test")
  MOCK.advance(3.5)
  check(MOCK.uiVisibleAtCapture == false, "interface hidden when the screenshot is taken")
  check(UIParent:IsShown(), "interface shown again after the screenshot")
  MOCK.combat = true
  MOCK.advance(3)
  SlashCmdList.FOREVERCHRONICLESHOT("test")
  MOCK.advance(3.5)
  check(MOCK.uiVisibleAtCapture == true and UIParent:IsShown(), "in combat the interface stays visible")
  MOCK.combat = false
  FC:GetModule("Screenshots"):GetSettings().hideUI = false
  SlashCmdList.FOREVERCHRONICLESHOT("status")
  SlashCmdList.FOREVERCHRONICLESHOT("api")
  SlashCmdList.FOREVERCHRONICLESHOT("bogus")

  -- Pending zone request (Thunder Bluff, waiting for cooldown) is reported on logout.
  MOCK.advance(5)
  SlashCmdList.FOREVERCHRONICLE("")
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end
  MOCK.fire("PLAYER_LOGOUT")
  check(statuses():find("zone:dropped_on_logout", 1, true), "pending request dropped on logout: " .. statuses())
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 6 then
  print("phase 6: position sampling")
  local FC = startClient(true, false)
  local function points() return ForeverChronicleDB.characters["Player-4619-0112A417"].streams.positions.records end
  MOCK.advance(2)
  local start = #points()
  check(start == 1, "first point after entering the world")
  MOCK.advance(60)
  check(#points() == 1, "standing still adds no points")
  MOCK.x = 0.47
  MOCK.advance(10)
  check(#points() == 2, "moving adds a point")
  MOCK.taxi = true; MOCK.x = 0.50
  MOCK.advance(10)
  check(points()[3]:find(",T,", 1, true), "taxi flag stored: " .. points()[3])
  MOCK.taxi = false
  MOCK.instance = true; MOCK.zone = "Ragefire Chasm"
  MOCK.advance(10)
  check(points()[4]:find(",,,,,389$") or points()[4]:find(",,,%d*,,389$"), "dungeon point is zone-only: " .. points()[4])
  check(ForeverChronicleDB.instances["389"] == "Ragefire Chasm", "instance name recorded")
  MOCK.advance(30)
  check(#points() == 4, "staying in the dungeon extends the point")
  MOCK.instance = nil; MOCK.zone = nil
  FC.db.settings.modules.Positions.enabled = false
  FC:GetModule("Positions"):Restart()
  MOCK.x = 0.6
  MOCK.advance(30)
  check(#points() == 4, "no sampling when disabled")
end

if PHASE == 7 or PHASE == 8 then
  print("phase " .. PHASE .. ": position interval settings migration")
  assert(load(SAVED))()
  local before = ForeverChronicleDB.settings.modules.Positions.interval
  startClient(true, false)
  local s = ForeverChronicleDB.settings.modules.Positions
  if PHASE == 7 then
    check(before == 10 and s.interval == 2 and s.rev == 2, "old default 10 s moved to 2 s")
  else
    check(before == 5 and s.interval == 5 and s.rev == 2, "user's own choice (5 s) kept")
  end
end

if PHASE == 9 then
  print("phase 9: in-game map")
  local FC = startClient(true, false)
  local Route = FC.Route

  local p = Route.Parse("100,1413,0.1,0.2,160,T,")
  check(p and p.taxi and p.endTime == 160 and p.x == 0.1, "parse point")
  check(Route.Parse("100,,,,,,389").instanceID == 389, "parse dungeon point")
  check(Route.Parse("garbage") == false and Route.Parse("100,1413,0.1,,,,") == false, "reject malformed points")

  -- Walk east through the Barrens, visit a dungeon, then go to Durotar.
  MOCK.advance(2)
  for i = 1, 20 do
    MOCK.x, MOCK.y = 0.30 + i * 0.01, 0.40
    MOCK.advance(2)
  end
  MOCK.instance, MOCK.zone = true, "Ragefire Chasm"
  MOCK.advance(4)
  local dungeonTime = MOCK.clock + math.floor(MOCK.now) - 2
  MOCK.instance, MOCK.zone = nil, nil
  MOCK.mapID, MOCK.x = 1411, 0.5
  MOCK.advance(4)

  local points = Route.Points()
  check(#points >= 20, "points read from the stream (" .. #points .. ")")
  local again = Route.Points()
  check(again == points, "unchanged stream returns the cached list")
  local segs = Route.Segments(points, 1413)
  check(#segs == 1 and #segs[1].points >= 20, "one Barrens segment (" .. #segs .. ")")
  local views = table.concat(Route.Views(points), ",")
  check(views == "1413,1411,1414", "views: zones then continent (" .. views .. ")")
  local cx, cy = Route.Project({ mapID = 1413, x = 0.5, y = 0.5 }, 1414)
  check(math.abs(cx - 0.44) < 1e-9 and math.abs(cy - 0.74) < 1e-9, "projection onto the continent")

  -- Window: open the map page.
  SlashCmdList.FOREVERCHRONICLE("")
  local index
  for i, pg in ipairs(FC.UI.pages) do if pg.id == "map" then index = i end end
  FC.UI:SelectPage(index)
  local page = FC.UI.pages[index]
  check(page.live and page.viewMap == 1411, "live view shows the current map")
  check(page.canvas.marker:IsShown(), "position marker shown")
  check(page.canvas.tiles[12] and page.canvas.tiles[12]:IsShown(), "map art tiles from the client")
  check(page.canvas.overlays[1] and page.canvas.overlays[1]:IsShown(), "explored overlays drawn")

  page:StepMap(-1)
  check(page.viewMap == 1413, "previous map: The Barrens")
  page:Refresh()

  -- Zoom: limits, point under the cursor stays, reset.
  local canvas = page.canvas
  MOCK.cursorX, MOCK.cursorY = 390, -260          -- centre of the 780 x 520 map
  canvas:ZoomAtCursor(2)
  check(canvas.zoom == 2 and canvas.content.scale == 2, "zoomed in (" .. canvas.zoom .. ")")
  check(math.abs(canvas.offX + 390) < 1e-6 and math.abs(canvas.offY + 260) < 1e-6, "zoom keeps the point under the cursor")
  for _ = 1, 20 do canvas:ZoomAtCursor(2) end
  check(canvas.zoom == 6, "zoom limited to 6x")
  canvas:SetView(2, 500, 500)
  check(canvas.offX == 0 and canvas.offY == 0, "panning is limited to the map")
  canvas:ResetZoom()
  check(canvas.zoom == 1 and canvas.offX == 0, "right-click resets the zoom")

  -- Icon toggle hides the route.
  page.routeToggle:GetScript("OnClick")(page.routeToggle)
  local visible = 0
  for _, line in ipairs(page.canvas.lines) do if line:IsShown() then visible = visible + 1 end end
  check(not page.routeToggle.on and visible == 0, "route toggle hides the lines")
  page.routeToggle:GetScript("OnClick")(page.routeToggle)
  check(page.viewMap == 1413 and page.notice.text:find("Durotar", 1, true) == nil and page.noticeFrame:IsShown(),
    "a map picked by hand stays while live (" .. tostring(page.notice.text) .. ")")
  local shown = 0
  for _, line in ipairs(page.canvas.lines) do if line:IsShown() then shown = shown + 1 end end
  check(shown >= 10, "route lines drawn (" .. shown .. ")")

  -- Clicking a Chronicle entry inside the dungeon shows the dungeon notice.
  FC.UI:FocusMap(dungeonTime)
  check(not page.live and page.noticeFrame:IsShown() and page.notice.text:find("Ragefire", 1, true),
    "dungeon moment shows notice: " .. tostring(page.notice.text))
  check(not page.canvas.marker:IsShown(), "no marker inside the dungeon")

  -- Playback from the start.
  page.current = page.range[1]
  page:TogglePlay()
  for _ = 1, 20 do page:OnUpdate(0.1) end
  check(page.current > page.range[1], "playback advances")
  page:TogglePlay()
  local before = page.sessionIndex
  page:StepSession(1)
  check(page.sessionIndex ~= before and page.sessionSel.label.text ~= nil, "session filter steps (" .. before .. " -> " .. page.sessionIndex .. ")")
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 10 then
  print("phase 10: rare enemies")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters["Player-4619-0112A417"]
  local function rareEvents()
    local out = {}
    for _, r in ipairs(char.streams.events.records) do if r.type == "rare_killed" then out[#out + 1] = r end end
    return out
  end
  local me = "Player-4619-0112A417"
  MOCK.advance(2)

  -- Rare as target, killed.
  local rare = "Creature-0-4619-1-1-3398-00001A2B"
  MOCK.units.target = { guid = rare, classification = "rareelite", name = "Gesharahan" }
  MOCK.fire("PLAYER_TARGET_CHANGED")
  MOCK.fire("PARTY_KILL", me, rare)
  local events = rareEvents()
  check(#events == 1 and events[1].data.name == "Gesharahan" and events[1].data.npcID == 3398,
    "rare kill recorded with name and NPC ID")
  check(char.stats.rares_killed == 1, "rare stat counted")
  check(FC:DescribeEvent(events[1]) == "Seltenen Gegner besiegt: Gesharahan", "chronicle text")
  MOCK.advance(6)
  local shots = char.streams.screenshots.records
  check(shots[#shots].trigger == "rare" and shots[#shots].status == "confirmed", "screenshot for the rare kill")

  MOCK.fire("PARTY_KILL", me, rare)
  check(#rareEvents() == 1, "a second kill report for the same rare is ignored")

  -- Normal mob: no event.
  MOCK.units.target = { guid = "Creature-0-4619-1-1-3035-00002222", classification = "normal", name = "Plainstrider" }
  MOCK.fire("PLAYER_TARGET_CHANGED")
  MOCK.fire("PARTY_KILL", me, "Creature-0-4619-1-1-3035-00002222")
  check(#rareEvents() == 1, "normal mobs are not rare kills")

  -- Rare only seen on a nameplate.
  local rare2 = "Creature-0-4619-1-1-5865-00003333"
  MOCK.units.nameplate3 = { guid = rare2, classification = "rare", name = "Dishu" }
  MOCK.fire("NAME_PLATE_UNIT_ADDED", "nameplate3")
  MOCK.fire("PARTY_KILL", me, rare2)
  check(#rareEvents() == 2, "rare seen on a nameplate")

  -- GUIDs hidden (secret): the dead rare target is used.
  local rare3 = "Creature-0-4619-1-1-3470-00004444"
  MOCK.units.target = { guid = rare3, classification = "rare", name = "Rathorian", dead = true }
  MOCK.fire("PARTY_KILL", MOCK.SECRET, MOCK.SECRET)
  check(#rareEvents() == 3 and rareEvents()[3].data.name == "Rathorian", "fallback when GUIDs are hidden")

  -- Trigger can be switched off.
  SlashCmdList.FOREVERCHRONICLESHOT("rare off")
  check(FC:GetModule("Screenshots"):GetSettings().triggers.rare == false, "/fcshot rare off")

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

print("PHASE " .. PHASE .. " PASSED")
