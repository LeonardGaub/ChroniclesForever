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

serializeValue = function(v) return serialize(v) end

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
  check(#FC.UI.pages == 7, "seven pages registered")
  SlashCmdList.FOREVERCHRONICLE("lang en")
  check(FC.L.TAB_OVERVIEW == "Overview", "language switched to English")
  check(#ForeverChronicleFrame.Tabs == 7 and ForeverChronicleFrame.Tabs[2].page.icon ~= nil, "icon tabs, one per page")

  -- Minimap button: shown, clicks toggle the window / open settings, can be hidden, dragging saves the angle.
  local mm = ForeverChronicleMinimapButton
  check(mm and mm:IsShown(), "minimap button shown")
  mm:GetScript("OnClick")(mm, "LeftButton")
  check(not ForeverChronicleFrame:IsShown(), "left-click closes the window")
  mm:GetScript("OnClick")(mm, "RightButton")
  local settingsPage = FC.UI.pages[FC.UI.current]
  check(ForeverChronicleFrame:IsShown() and settingsPage.id == "settings", "right-click opens the settings")
  MOCK.cursorX, MOCK.cursorY = 0, 100
  mm:GetScript("OnDragStart")(mm)
  mm:GetScript("OnUpdate")(mm)
  mm:GetScript("OnDragStop")(mm)
  check(math.abs(FC.db.settings.modules.MinimapButton.angle - 90) < 1e-6, "dragging saves the angle")
  FC.db.settings.modules.MinimapButton.show = false
  FC:GetModule("MinimapButton"):Update()
  check(not mm:IsShown(), "minimap button can be hidden")
  FC.db.settings.modules.MinimapButton.show = true
  FC:GetModule("MinimapButton"):Update()
  FC.UI:SelectPage(1)
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

  -- Graphs: line over the last 2 hours of played time, switchable.
  local spans, length = FC.Metrics:PlayedWindow(7200)
  check(#spans == 1 and length > 600 and length < 7200, "played window covers the session (" .. length .. " s)")
  FC.UI:SelectPage(1)
  local ov = FC.UI.pages[1]
  ov.graphVersion = nil
  ov:RefreshGraph()
  local pts = ov.graph.points
  check(#pts >= 3 and pts[1].value == 0 and pts[#pts].value == 4200 and pts[#pts].x == length,
    "XP line from 0 to the earned 4200 (" .. #pts .. " points)")
  check(ov.graph.lineCount == #pts - 1 and ov.graphTitle.text == "Gesammelte Erfahrung", "XP line drawn")
  check(ov.graphSubtitle.text:find("+4.200", 1, true), "subtitle shows the change: " .. ov.graphSubtitle.text)
  check(ov.graph.ticks[1]:IsShown() and ov.graph.ticks[1].text:match("^%d%d:%d%d$"), "time labels")
  check(ov.graph:ShowPointAt(ov.graph.plotW) == pts[#pts] and ov.graph.dot:IsShown(), "hover shows the nearest point")
  ov:StepGraph(1)
  check(FC.db.settings.overviewGraph == "kills" and ov.graphTitle.text == "Getötete Gegner" and
    ov.graph.points[#ov.graph.points].value == 2, "switch to kills graph")
  ov:StepGraph(1)
  check(ov.graph.points[#ov.graph.points].value == 1, "quests graph counts the completed quest")
  ov:StepGraph(1)
  check(FC.db.settings.overviewGraph == "gold" and ov.graph.points[1].value == 123456, "gold graph shows the money held")
  ov:StepGraph(1)
  check(FC.db.settings.overviewGraph == "xp", "switching wraps around")
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
  -- Recipes for the desktop fixture: open the leatherworking window once.
  MOCK.openProfession(165)
  MOCK.advance(1)
  MOCK.closeProfession()
  MOCK.advance(300)
  -- Graph window: the last 2 hours of played time join both sessions; a short window stays in the last one.
  local Metrics = ForeverChronicle.Metrics
  local spans, length = Metrics:PlayedWindow(7200)
  check(#spans == 2 and spans[2].x == spans[1].to - spans[1].from and length == spans[2].x + spans[2].to - spans[2].from,
    "window joins two sessions (" .. length .. " s)")
  check(Metrics.TimeAt(spans, spans[2].x + 10) == spans[2].from + 10, "window position -> clock time")
  local short, shortLength = Metrics:PlayedWindow(200)
  check(#short == 1 and shortLength == 200 and short[1].to - short[1].from == 200, "short window")
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
  MOCK.fire("PLAYER_DEAD")
  local entrance = ForeverChronicleDB.entrances and ForeverChronicleDB.entrances["389"]
  check(entrance and entrance.source == "walked" and entrance.mapID == 1413 and entrance.x == 0.5 and entrance.y == 0.4,
    "dungeon entrance learned where the player walked in")
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
  -- Continent points (between zones) belong to the smallest known zone that contains them.
  FC.db.maps["1454"] = { continent = 1414, minX = 0.43, maxX = 0.45, minY = 0.73, maxY = 0.75 }
  check(Route.ZoneFor({ mapID = 1414, x = 0.44, y = 0.74 }) == 1454, "continent point -> smallest zone")
  check(Route.ZoneFor({ mapID = 1414, x = 0.9, y = 0.1 }) == 1414, "no zone contains it -> continent")
  check(Route.ZoneFor({ mapID = 1413, x = 0.5, y = 0.5 }) == 1413, "zone point keeps its zone")
  local zx, zy = Route.Project({ mapID = 1414, x = 0.44, y = 0.74 }, 1413)
  check(math.abs(zx - 0.5) < 1e-9 and math.abs(zy - 0.5) < 1e-9, "continent point projected onto the zone")
  FC.db.maps["1454"] = nil

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

  -- Clicking a Chronicle entry inside the dungeon shows the dungeon entrance (user request).
  page:StepMap(1)                                   -- some other map first
  FC.UI:FocusMap(dungeonTime)
  check(not page.live and page.viewMap == 1413 and page.canvas.marker:IsShown(),
    "dungeon moment opens the entrance zone (" .. tostring(page.viewMap) .. ")")
  check(page.notice.text:find("Ragefire", 1, true) and page.notice.text:find("Eingang", 1, true),
    "notice: " .. tostring(page.notice.text))
  local deathPin = false
  for _, pin in ipairs(page.canvas.pins) do
    if pin:IsShown() and pin.title and pin.title:find("Ragefire", 1, true) then deathPin = true end
  end
  check(deathPin, "death inside the dungeon is pinned at the entrance")
  ForeverChronicleDB.entrances = nil
  check(Route.Entrance(389) and Route.Entrance(389).mapID == 1413, "entrance derived from the route for older data")

  -- Playback from the start.
  page.current = page.range[1]
  page:TogglePlay()
  for _ = 1, 20 do page:OnUpdate(0.1) end
  check(page.current > page.range[1], "playback advances")
  page:TogglePlay()
  local before = page.sessionIndex
  page:StepSession(1)
  check(page.sessionIndex ~= before and page.sessionSel.label.text ~= nil, "session filter steps (" .. before .. " -> " .. page.sessionIndex .. ")")

  -- Between zones the client reports only the continent: the map still opens a zone (user request).
  MOCK.mapID, MOCK.x, MOCK.y = 1414, 0.44, 0.74
  MOCK.advance(4)
  local continentTime = MOCK.clock + math.floor(MOCK.now) - 1
  MOCK.mapID, MOCK.x, MOCK.y = 1411, 0.5, 0.5
  MOCK.advance(4)
  FC.UI:FocusMap(continentTime)
  check(Route.PointAt(Route.Points(), continentTime).mapID == 1414, "continent point recorded")
  check((page.viewMap == 1413 or page.viewMap == 1411) and page.canvas.marker:IsShown(),
    "continent moment opens the zone (" .. tostring(page.viewMap) .. ")")
  page:StepMap(1)
  page:StepMap(1)
  local picked = page.viewMap
  page.current = continentTime + 2
  page:UpdateMarker()
  check(page.viewMap == picked, "a map picked by hand stays while the zone does not change")
  page.current = continentTime + 5
  page:UpdateMarker()
  check(page.viewMap == 1411, "follows the player into the next zone (" .. tostring(page.viewMap) .. ")")
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end

  -- The encounter journal's entrance (when the client has it) replaces the learned one.
  MOCK.travel(1454, "Orgrimmar")
  MOCK.x, MOCK.y = 0.6, 0.6
  MOCK.advance(3)
  local journal = ForeverChronicleDB.entrances["389"]
  check(journal and journal.source == "journal" and journal.mapID == 1454 and journal.x == 0.5195, "journal entrance")
  FC.UI:FocusMap(dungeonTime)
  check(page.viewMap == 1454 and page.canvas.marker:IsShown(), "dungeon moment shown at the journal entrance")
  FC:GetModule("Positions"):LearnEntrance(389, { time = time(), mapID = 1413, x = 0.1, y = 0.1 }, time())
  check(ForeverChronicleDB.entrances["389"].source == "journal", "walking in does not replace a journal entrance")

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

if PHASE == 11 then
  print("phase 11: professions and recipes")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters["Player-4619-0112A417"]
  local P = FC:GetModule("Professions")
  local function evts(t)
    local out = {}
    for _, r in ipairs(char.streams.events.records) do if r.type == t then out[#out + 1] = r end end
    return out
  end

  local snap = char.snapshots.professions
  check(snap and #snap.list == 4 and snap.baseline, "four professions captured at login")
  local lw = P:Find(165)
  check(lw.name == "Leatherworking" and lw.rank == 126 and lw.maxRank == 150 and lw.kind == "primary",
    "leatherworking skill and rank")
  check(P:Find(129).kind == "secondary" and P:Find(185).kind == "secondary", "first aid and cooking are secondary")
  check(#evts("profession_learned") == 0, "professions known at install are not reported as learned")
  check(lw.recipes == nil, "no recipes before a profession window was opened")
  MOCK.advance(6)
  check(#evts("profession_learned") == 0, "delayed login scan adds no events")

  -- Opening the window captures the learned recipes from the unfiltered list.
  MOCK.openProfession(165)
  check(lw.recipes == nil, "capture waits for the list to settle")
  MOCK.advance(1)
  check(lw.recipes and lw.recipes.status == "complete" and #lw.recipes.list == 4 and lw.recipes.total == 6,
    "learned recipes captured (" .. (lw.recipes and #lw.recipes.list or 0) .. " of 6)")
  check(lw.recipes.format == 2 and lw.recipes.list[1] == "2881,2550,134252,1,Light Leather",
    "compact recipe format with item quality: " .. lw.recipes.list[1])
  check(lw.recipes.list[2] == "3816,2550,134366,1,Cured Light Hide", "quality from the item ID when there is no link")
  check(lw.recipes.list[4] == "9058,2552,133150,2,Handstitched Leather Cloak", "uncommon (green) recipe")
  local old = P.ParseRecipe("2881,2550,134252,Light Leather")
  check(old.name == "Light Leather" and old.quality == nil, "format 1 recipes (v0.10.0) still readable")
  local cats = P.ParseCategories(lw.recipes.categories)
  check(cats[2550].name == "Materials" and cats[2550].parent == 2549 and cats[2549].name == "Leatherworking",
    "categories stored with their parents")
  check(ForeverChronicleDB.diagnostics.capabilities.recipes.status == "confirmed", "recipes capability confirmed")

  -- At most one capture per 5 seconds.
  local captured = P.lastCapture
  MOCK.fire("TRADE_SKILL_LIST_UPDATE")
  MOCK.advance(1)
  check(P.lastCapture == captured, "no second capture within 5 s")
  MOCK.advance(5)
  check(P.lastCapture > captured, "captured again after 5 s")

  -- Learning a recipe: chronicle event and a new capture.
  MOCK.recipes[165][5].learned = true
  MOCK.fire("NEW_RECIPE_LEARNED", 2149)
  local learned = evts("recipe_learned")
  check(#learned == 1 and learned[1].data.name == "Handstitched Leather Boots" and learned[1].data.recipeID == 2149,
    "recipe_learned event")
  check(FC:DescribeEvent(learned[1]) == "Rezept gelernt: Handstitched Leather Boots", "recipe event text")
  MOCK.advance(6)
  check(#lw.recipes.list == 5, "new recipe in the snapshot")

  -- Unreadable recipe info: partial snapshot that keeps what was known.
  MOCK.recipes[165][1].broken = true
  MOCK.fire("TRADE_SKILL_LIST_UPDATE")
  MOCK.advance(6)
  check(lw.recipes.status == "partial" and lw.recipes.unreadable == 1 and #lw.recipes.list == 5,
    "partial capture keeps earlier recipes")
  MOCK.recipes[165][1].broken = nil
  MOCK.closeProfession()

  -- Window closed before the capture ran: nothing is captured.
  MOCK.openProfession(185)
  MOCK.closeProfession()
  MOCK.advance(6)
  check(P:Find(185).recipes == nil, "no capture after the window was closed")

  -- Another player's linked profession and professions the character does not have are ignored.
  MOCK.linked = true
  MOCK.openProfession(185)
  MOCK.advance(6)
  check(P:Find(185).recipes == nil, "linked profession not captured")
  MOCK.closeProfession()
  MOCK.linked = nil
  MOCK.openProfession(197)
  MOCK.advance(6)
  check(P:Find(197) == nil, "profession the character does not have is ignored")
  MOCK.closeProfession()
  MOCK.openProfession(185)
  MOCK.advance(1)
  check(P:Find(185).recipes and #P:Find(185).recipes.list == 1, "cooking recipes captured")
  MOCK.closeProfession()

  -- Next rank trained (maximum 150 -> 225).
  MOCK.professions[6][4] = 225
  MOCK.fire("SKILL_LINES_CHANGED")
  MOCK.advance(2)
  local ranks = evts("profession_rank")
  check(#ranks == 1 and ranks[1].data.maxRank == 225 and lw.maxRank == 225, "rank event")
  check(FC:DescribeEvent(ranks[1]) == "Leatherworking: Experte", "rank text: " .. FC:DescribeEvent(ranks[1]))

  -- A new profession and an unlearned one.
  MOCK.professions[9] = { "Fishing", 136245, 1, 75, 1, 0, 356, 0, -1, 0, "Fishing" }
  MOCK.professionSlots[4] = 9
  MOCK.professionSlots[2] = nil
  MOCK.fire("CHAT_MSG_SKILL", "Your skill in Fishing has increased to 1.")
  MOCK.advance(2)
  local learnedProf = evts("profession_learned")
  check(#learnedProf == 1 and learnedProf[1].data.name == "Fishing", "profession_learned event")
  check(P:Find(182).active == false and P:Find(182).unlearnedAt, "herbalism marked as unlearned")
  check(#P:GetActive() == 4 and P:GetActive()[1].skillLine == 165, "active professions, primary first")
  local stat
  for _, def in ipairs(FC.statDefs) do if def.key == "recipes_known" then stat = def end end
  check(FC:GetStatValue(stat) == 6, "recipes stat (" .. tostring(FC:GetStatValue(stat)) .. ")")

  -- In-game page: profession buttons, recipes grouped by category, search.
  FC.UI:Toggle()
  local index
  for i, pg in ipairs(FC.UI.pages) do if pg.id == "professions" then index = i end end
  FC.UI:SelectPage(index)
  local page = FC.UI.pages[index]
  local buttons = 0
  for _, b in ipairs(page.buttons) do if b:IsShown() then buttons = buttons + 1 end end
  check(buttons == 4 and page.selected == 165 and page.title.text == "Leatherworking", "profession buttons")
  local function shownRows()
    local n = 0
    for _, row in ipairs(page.list.rows) do if row:IsShown() then n = n + 1 end end
    return n
  end
  check(shownRows() == 8, "3 category headers and 5 recipes (" .. shownRows() .. ")")
  check(page.list.rows[1].header.text == "Armor" and page.list.rows[2].text.text == "Handstitched Leather Boots",
    "categories sorted, recipes below their category")
  local green, white = page.list.rows[2].text.color, page.list.rows[8].text.color
  check(green[1] == 0.12 and green[2] == 1 and white[1] == 1 and white[3] == 1, "recipe names in item quality colour")
  check(page.status.text:find("unvollst", 1, true) ~= nil, "status shows the partial capture: " .. page.status.text)
  page.search:SetText("hide")
  page.search:GetScript("OnTextChanged")(page.search)
  check(shownRows() == 3 and page.status.text:find("2 angezeigt", 1, true), "search filters recipes")
  page.buttons[4]:GetScript("OnClick")(page.buttons[4])
  check(page.selected == 356 and page.recipeEmpty.text:find("Sammelberufe", 1, true), "profession without recipes")

  SlashCmdList.FOREVERCHRONICLE("professions")
  local found = false
  for _, line in ipairs(MOCK.chat) do if line:find("Leatherworking 126/225", 1, true) then found = true end end
  check(found, "/fc professions lists the professions")

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 12 then
  print("phase 12: character layer with an alt and a friend's characters")
  local FC = startClient(true, false)
  local me = "Player-4619-0112A417"
  -- An alt on the same account (all characters share the SavedVariables).
  ForeverChronicleDB.characters["Player-4619-0ALT0001"] = {
    info = { name = "Altie", level = 10, classFile = "MAGE", realm = "Classic Beta PvP", lastSeenAt = 1791900000 },
    stats = { kills = 5 }, state = {}, snapshots = {},
    streams = { events = { nextSeq = 2, dropped = 0, records = {
      { id = "alt1", seq = 1, type = "level_up", time = 1791900000, data = { level = 10 } } } } },
  }

  local entries = FC:ViewEntries()
  check(#entries == 4 and entries[1].played and entries[1].key == me, "played character first")
  check(entries[2].key == "Player-4619-0ALT0001" and not entries[2].owner, "then the account's other characters")
  check(entries[3].owner == 'Bob "the" Friend' and entries[3].char.info.name == "Thrall"
    and entries[4].owner == 'Bob "the" Friend', "then the friend's characters, names exactly as shared")
  check(FC:IsViewingPlayed() and FC:ViewChar() == FC.char, "the window starts on the played character")

  -- Chooser: header, played, alt, friend header, friend.
  FC.UI:Toggle()
  local UI = FC.UI
  check(UI.viewBar.name.text:find("Blind Bullseye", 1, true) and UI.viewBar.sub.text:find("Stufe 22", 1, true),
    "the bar shows the played character")
  check(not UI.viewBack:IsShown(), "no back button while viewing myself")
  check(ForeverChronicleFrame.portraitUnit == "player", "portrait: the played character")
  UI.viewBar:GetScript("OnClick")(UI.viewBar)
  local rows = {}
  for _, row in ipairs(UI.viewRows.rows) do if row:IsShown() then rows[#rows + 1] = row end end
  check(#rows == 6 and rows[1].header.text == "Meine Charaktere" and rows[4].header.text:find("Bob", 1, true),
    "list: my characters, then the friend's (" .. #rows .. " rows)")
  check(rows[2].name.text:find("du spielst", 1, true) and rows[3].key == "Player-4619-0ALT0001", "rows")
  check(rows[3].icon.texture == "Interface\\TargetingFrame\\UI-Classes-Circles", "class emblem in the rows")

  -- Choose the friend's character.
  rows[5]:GetScript("OnMouseUp")(rows[5])
  check(not FC:IsViewingPlayed() and FC:ViewOwner():find("Bob", 1, true) and not UI.viewList:IsShown(), "friend chosen")
  check(UI.viewBack:IsShown() and UI.viewBar.sub.text:find("Charakter von", 1, true)
    and UI.viewBar.sub.text:find("nur lesen", 1, true), "bar says whose character it is, back button")
  check(UI.viewBar.name.text:find("Thrall", 1, true), "the bar shows the friend's character")
  check(ForeverChronicleFrame.portraitClass == "HUNTER" and rawget(ForeverChronicleFrame, "portraitUnit") == nil,
    "portrait: the friend's class emblem")

  local function page(id)
    for i, p in ipairs(UI.pages) do if p.id == id then UI:SelectPage(i); return p end end
  end
  local ov = page("overview")
  check(ov.name.text:find("Thrall", 1, true) and ov.details.text:find("Charakter von", 1, true), "overview header")
  check(ov.otherNote:IsShown() and ov.gearPanel:IsShown() and not ov.model:IsShown() and not ov.xp:IsShown(),
    "model and live parts hidden, gear shown")
  local function link(slot) return rawget(slot, "link") end   -- mock frames return functions for unset fields
  local head = ov.slots[1]
  check(link(head) and link(head):find("Green Tinted Goggles", 1, true) and head.icon.texture == 133001,
    "the friend's gear from the shared snapshot")
  check(link(ov.slots[2]) == nil, "empty slot stays empty")
  local kills, tracked
  for _, tile in ipairs(ov.tiles) do
    if tile.def.key == "kills" then kills = tile.value.text end
    if tile.def.key == "tracked_time" then tracked = tile.value.text end
  end
  check(tracked and tracked ~= "-", "friend stats (tracked " .. tostring(tracked) .. ")")

  local chron = page("chronicle")
  local shown = 0
  for _, row in ipairs(chron.list.rows) do if row:IsShown() then shown = shown + 1 end end
  local friendEvents = #FC:ViewStream("events").records
  check(friendEvents > 0 and shown == friendEvents, "friend's chronicle (" .. shown .. " entries)")

  local map = page("map")
  check(#map.points >= 8 and map.viewMap == 1413 and map.canvas.marker:IsShown(), "friend's route on the map")

  local prof = page("professions")
  local profButtons = 0
  for _, b in ipairs(prof.buttons) do if b:IsShown() then profButtons = profButtons + 1 end end
  check(profButtons == 4 and prof.title.text == "Herbalism", "friend's professions (" .. profButtons .. ")")
  local shots = page("screenshots")
  check(shots.empty:IsShown(), "no screenshots for the friend in game")

  -- Recording continues for the played character only.
  local mine = #ForeverChronicleDB.characters[me].streams.events.records
  MOCK.fire("PLAYER_DEAD")
  check(#ForeverChronicleDB.characters[me].streams.events.records == mine + 1, "events still recorded for me")
  check(#FC:ViewStream("events").records == friendEvents, "the friend's data is not changed")

  -- The alt, then back to me.
  FC:SetView("Player-4619-0ALT0001")
  page("overview")
  check(ov.name.text:find("Altie", 1, true) and UI.viewBar.sub.text:find("Anderer Charakter", 1, true), "alt shown")
  check(link(ov.slots[1]) == nil, "the alt has no gear snapshot: empty slots")
  check(ForeverChronicleFrame.portraitClass == "MAGE", "portrait: the alt's class emblem")
  local overviewTab = ForeverChronicleFrame.Tabs[1]
  check(overviewTab.icon.texture == "Interface\\TargetingFrame\\UI-Classes-Circles", "overview tab icon follows")
  page("chronicle")
  shown = 0
  for _, row in ipairs(chron.list.rows) do if row:IsShown() then shown = shown + 1 end end
  check(shown == 1, "alt's chronicle")
  UI.viewBack:GetScript("OnClick")(UI.viewBack)
  check(FC:IsViewingPlayed() and not UI.viewBack:IsShown(), "back to me")
  check(ForeverChronicleFrame.portraitUnit == "player", "portrait: back to the played character")
  page("overview")
  check(ov.gearPanel:IsShown() and ov.model:IsShown() and not ov.otherNote:IsShown() and link(ov.slots[1]) == nil,
    "live parts back (gear from the live inventory again)")
  local gear = ForeverChronicleDB.characters[me].snapshots.gear
  check(gear and #gear.slots == 2 and gear.slots[1].slotName == "HeadSlot" and gear.slots[1].quality == 3,
    "my gear snapshot")
  for i = 1, #UI.pages do UI:SelectPage(i) end

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 13 then
  print("phase 13: data for friends (Share module, cloud sync)")
  local FC = startClient(true, false)
  local me = "Player-4619-0112A417"
  local Share = FC:GetModule("Share")
  -- Some play: a route over two sessions, events.
  for i = 1, 8 do MOCK.x = 0.30 + i * 0.01; MOCK.advance(2) end
  MOCK.fire("PLAYER_DEAD")
  ForeverChronicleDB.characters["Player-4619-0ALT0001"] = {
    info = { name = "Altie", level = 10, classFile = "MAGE", lastSeenAt = 1791900000 }, stats = { kills = 5 },
    streams = {}, snapshots = {}, state = {} }

  MOCK.fire("PLAYER_LOGOUT")
  local data = ForeverChronicleShareDB
  check(type(data) == "table" and data.format == 1 and data.name == "Blind" and #data.characters == 2,
    "written on logout: both characters, name defaults to the character's")
  local mine = data.characters[1]
  check(mine.info.name == "Blind" and mine.info.key == me and mine.stats.kills == ForeverChronicleDB.characters[me].stats.kills,
    "info and stats")
  check(#mine.streams.events.records >= 2 and #mine.streams.positions.records >= 8, "chronicle and route")
  check(mine.snapshots.gear and #mine.snapshots.gear.slots == 2, "gear")
  check(data.maps["1413"] and data.maps["1414"], "maps of the route and their continent")
  check(mine.streams.screenshots == nil, "no screenshots")
  -- What the game writes as SavedVariables\ForeverChronicle_Share.lua (test data for the sync script).
  SAVED_OUT = "\nForeverChronicleShareDB = " .. serializeValue(ForeverChronicleShareDB) .. "\n"

  -- Limits: only the newest events, only the newest sessions' route.
  Share.EVENTS = 1
  data = Share:Build()
  check(#data.characters[1].streams.events.records == 1, "event limit")
  Share.EVENTS = 200

  -- Categories and characters can be switched off.
  local s = Share:GetSettings()
  s.cats.routes, s.cats.gear, s.cats.stats = false, false, false
  s.chars["Player-4619-0ALT0001"] = false
  s.name = "Leon"
  data = Share:Build()
  mine = data.characters[1]
  check(#data.characters == 1 and data.name == "Leon", "alt excluded, own name")
  check(mine.streams.positions == nil and mine.snapshots.gear == nil and mine.stats == nil, "categories off")
  check(mine.streams.events ~= nil and mine.streams.sessions ~= nil and mine.snapshots.professions ~= nil,
    "the other categories stay on")
  s.cats.routes, s.cats.gear, s.cats.stats = true, true, true
  s.chars["Player-4619-0ALT0001"] = nil

  -- Settings page: the name field and one check box per character.
  FC.UI:Toggle()
  local settings
  for i, p in ipairs(FC.UI.pages) do if p.id == "settings" then settings = p; FC.UI:SelectPage(i) end end
  local nameRow, charRow
  for _, control in ipairs(settings.controls) do
    if rawget(control, "box") then nameRow = control end
    if rawget(control, "boxes") then charRow = control end
  end
  check(nameRow and nameRow.box.text == "Leon", "name field shows the setting")
  nameRow.box:SetText("  Leonard ")
  nameRow.box:GetScript("OnEnterPressed")(nameRow.box)
  check(Share:GetSettings().name == "Leonard", "name saved (trimmed)")
  check(charRow and #charRow.boxes == 2, "one check box per character")
  local alt
  for _, cb in ipairs(charRow.boxes) do if cb.key == "Player-4619-0ALT0001" then alt = cb end end
  alt:SetChecked(false)
  alt:GetScript("OnClick")(alt)
  check(Share:GetSettings().chars["Player-4619-0ALT0001"] == false and #Share:Build().characters == 1,
    "unticking a character stops sharing it")
  alt:SetChecked(true)
  alt:GetScript("OnClick")(alt)
  check(Share:GetSettings().chars["Player-4619-0ALT0001"] == nil, "ticking shares it again")

  -- What the sync script delivers to friends: the share data as one friend of ForeverChronicleFriends.
  data = Share:Build()
  ForeverChronicleFriends = { friends = { { name = data.name, characters = data.characters } }, maps = data.maps,
    instances = data.instances, entrances = data.entrances }
  local entry
  for _, e in ipairs(FC:ViewEntries()) do if e.owner == "Leonard" and e.char.info.name == "Blind" then entry = e end end
  check(entry ~= nil, "a shared character appears in a friend's chooser")
  FC:SetView(entry.key)
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end
  local ov = FC.UI.pages[1]
  FC.UI:SelectPage(1)
  check(ov.name.text:find("Blind", 1, true) and rawget(ov.slots[1], "link"), "overview of the shared character")

  -- Without the data addon nothing is written.
  ForeverChronicleShareDB = nil
  MOCK.shareMissing = true
  check(Share:Write() == false and ForeverChronicleShareDB == nil, "nothing written without ForeverChronicle_Share")
  SlashCmdList.FOREVERCHRONICLE("share")
  local said = false
  for _, line in ipairs(MOCK.chat) do if line:find("nicht aktiv", 1, true) then said = true end end
  check(said, "/fc share explains that the data addon is missing")

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

print("PHASE " .. PHASE .. " PASSED")
