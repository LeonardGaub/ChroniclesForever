-- Scenario phases. PHASE is set by run.js; SAVED holds the SavedVariables text of the previous phase.

-- Streams are packed in the saved table after a logout; tests read them like the addon does.
local function S(stream) return ForeverChronicle.Storage.Unpack(stream) end

local function check(cond, msg)
  if not cond then error("CHECK FAILED: " .. msg, 2) end
  print("  ok  " .. msg)
end

local function loadAddon()
  if SAVED then assert(load(SAVED, "=SavedVariables"))() end
  MOCK.clock = MOCK.clock + (PHASE_OFFSET or 0)
  -- Like the game: the main addon's files, its ADDON_LOADED, then the companion addon's files.
  local ns, other, mainLoaded = {}, {}, false
  for _, name in ipairs(ADDON_FILES) do
    local addon = ADDON_OF and ADDON_OF[name] or "ForeverChronicle"
    if addon ~= "ForeverChronicle" and not mainLoaded then
      MOCK.fire("ADDON_LOADED", "ForeverChronicle")
      mainLoaded = true
    end
    local chunk = assert(load(ADDON_SRC[name], "@" .. name))
    chunk(addon, addon == "ForeverChronicle" and ns or other)
  end
  if not mainLoaded then MOCK.fire("ADDON_LOADED", "ForeverChronicle") end
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
  MOCK.fire("PLAYER_LOGIN")
  MOCK.fire("PLAYER_ENTERING_WORLD", isInitialLogin, isReloadingUi)
  return FC
end

local function sessions() return S(ForeverChronicleDB.characters["Player-4619-0112A417"].streams.sessions).records end
local function events() return S(ForeverChronicleDB.characters["Player-4619-0112A417"].streams.events).records end

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
  check(ForeverChronicleFrame and ForeverChronicleFrame:IsShown(), "window opens with /fj")
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
  check(#FC.UI.pages[settingsIndex].bars == 6, "storage bars on the settings page (" .. #FC.UI.pages[settingsIndex].bars .. ")")
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
  local positions = S(ForeverChronicleDB.characters["Player-4619-0112A417"].streams.positions).records
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
  local shots = S(ForeverChronicleDB.characters["Player-4619-0112A417"].streams.screenshots).records
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
  check(#S(stream).records == 5, "trimmed to cap on logout")
  check(stream.dropped == stream.nextSeq - 1 - 5, "dropped records counted (" .. stream.dropped .. ")")
  check(stream.records[1].seq == stream.nextSeq - 5, "remaining records are the newest")

  -- Packing for the saved file: the client cannot load a file with more than ~262,000 distinct constants.
  local Storage = FC.Storage
  local odd = { id = "a\"b\\c\nd\r\t\1ü", n = -12.5, big = 123456789012, tiny = 1e-7, yes = true, no = false,
    ["end"] = 1, ["two words"] = 2, [7] = "seven", list = { 1, 2, { x = 3 } }, nested = { deeper = { "ok" } } }
  local s1 = { nextSeq = 3, dropped = 0, records = { odd, { id = "second" } } }
  Storage.Pack(s1)
  check(#s1.records == 0 and s1.packed.kind == "tables" and #s1.packed.chunks == 1, "table records packed")
  Storage.Unpack(s1)
  local r = s1.records[1]
  check(#s1.records == 2 and r.id == odd.id and r.n == -12.5 and r.big == 123456789012 and r.tiny == 1e-7
    and r.yes == true and r.no == false and r["end"] == 1 and r["two words"] == 2 and r[7] == "seven"
    and r.list[3].x == 3 and r.nested.deeper[1] == "ok" and s1.records[2].id == "second", "round trip keeps every value")
  local lines = { nextSeq = 1001, dropped = 0, records = {} }
  for i = 1, 1000 do lines.records[i] = string.format("%d,1413,0.%04d,0.5000,,,", 1000 + i, i) end
  Storage.Pack(lines)
  check(lines.packed.kind == "lines" and #lines.packed.chunks == 3, "compact records: 400 per string")
  Storage.Unpack(lines)
  check(#lines.records == 1000 and lines.records[1000] == "2000,1413,0.1000,0.5000,,,", "compact records back in order")

  -- Friends' data arrives packed: only plain data is ever compiled.
  check(Storage.IsPlainData('{a=1,["b c"]=-2.5e+3,[3]=true,d={nil,false}},{e="x\\"y"}'), "plain data accepted")
  for _, bad in ipairs({ '}while true do end{', '{a=("x"):rep(9)}', '{a=b}', '{a=1}}return{', '{a=#"x"}' }) do
    check(not Storage.IsPlainData(bad), "code rejected: " .. bad)
  end
  local evil = { nextSeq = 1, records = {}, packed = { format = 1, kind = "tables", chunks = { '}while true do end{' } } }
  Storage.Unpack(evil)
  check(#evil.records == 0 and evil.unreadable and evil.unreadable[1] == '}while true do end{', "code is kept, not run")

  -- A character far over the limit: 300,000 route points and 12,000 events end up in a few hundred strings.
  local big = { streams = { positions = { nextSeq = 300001, dropped = 0, records = {} },
    events = { nextSeq = 12001, dropped = 0, records = {} } } }
  for i = 1, 300000 do big.streams.positions.records[i] = string.format("%d,1413,0.5,0.5,,,", i) end
  for i = 1, 12000 do big.streams.events.records[i] = { id = "e" .. i, seq = i, time = i, type = "quest_completed",
    data = { questID = i } } end
  Storage.PackCharacter(big)
  local strings = #big.streams.positions.packed.chunks + #big.streams.events.packed.chunks
  check(strings == 750 + 120, "packed into " .. strings .. " strings")
  Storage.UnpackCharacter(big)
  check(#big.streams.positions.records == 300000 and big.streams.events.records[12000].data.questID == 12000,
    "and unpacked completely")
end
if PHASE == 5 then
  print("phase 5: zones, flights and screenshot rules")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters["Player-4619-0112A417"]
  local function shots() return S(char.streams.screenshots).records end
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
  check(FC:GetModule("Screenshots"):GetSettings().delay == 2, "/fjshot delay sets the delay")
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
  local function points() return S(ForeverChronicleDB.characters["Player-4619-0112A417"].streams.positions).records end
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
  -- The mock moves the player from the login spot to the walk start in one step: a teleport.
  check(#segs == 2 and #segs[1].points == 1 and #segs[2].points >= 20, "Barrens walk, split at the jump (" .. #segs .. ")")
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
  local function deathPin()
    for _, pin in ipairs(page.canvas.pins) do
      if pin:IsShown() and pin.title and pin.title:find("Ragefire", 1, true) then return true end
    end
    return false
  end
  check(not deathPin(), "the death two seconds later is not painted yet")
  FC.UI:FocusMap(dungeonTime + 2)
  check(deathPin(), "death inside the dungeon is pinned at the entrance")
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

  -- Hearthstone within the same map: the point after the loading screen is flagged and not connected.
  MOCK.x, MOCK.y = 0.2, 0.2
  MOCK.advance(2)
  MOCK.fire("LOADING_SCREEN_ENABLED")
  MOCK.x, MOCK.y = 0.8, 0.8
  MOCK.advance(3)
  MOCK.fire("LOADING_SCREEN_DISABLED")
  MOCK.advance(3)
  local records = FC:ViewStream("positions").records
  check(records[#records]:find(",J,", 1, true) and not records[#records - 1]:find("J", 1, true),
    "first sample after a loading screen flagged (" .. records[#records] .. ")")
  local hearth = Route.Segments(Route.Points(), 1454)
  check(#hearth[#hearth].points == 1, "hearthstone starts a new route line")
  -- Older routes without the flag: a step faster than any mount is a teleport, a normal step is not.
  local function seg(x2, dt)
    return #Route.Segments({ { time = 0, endTime = 0, mapID = 1413, x = 0.1, y = 0.1 },
      { time = dt, endTime = dt, mapID = 1413, x = x2, y = 0.1 } }, 1413)
  end
  check(seg(0.6, 3) == 2 and seg(0.11, 2) == 1 and seg(0.6, 100) == 1, "teleport recognised by speed")

  -- Thinning: a straight walk at an even pace keeps its ends; a turn and a change of pace are kept.
  local function walkRecs(steps, t0)
    local out = {}
    for _, s in ipairs(steps) do out[#out + 1] = string.format("%d,1413,%.4f,%.4f,,,", t0 + s[1], s[2], s[3]) end
    return out
  end
  local straight, turn, pace = {}, {}, {}
  for i = 0, 20 do straight[#straight + 1] = { i * 2, 0.3 + i * 0.002, 0.5 } end
  for i = 0, 10 do turn[#turn + 1] = { i * 2, 0.3 + i * 0.002, 0.5 } end
  for i = 1, 10 do turn[#turn + 1] = { 20 + i * 2, 0.32, 0.5 + i * 0.002 } end
  for i = 0, 10 do pace[#pace + 1] = { i * 2, 0.3 + i * 0.002, 0.5 } end
  for i = 1, 10 do pace[#pace + 1] = { 20 + i * 2, 0.32 + i * 0.006, 0.5 } end -- mounted up halfway
  check(#Route.Thin(walkRecs(straight, 1000)) == 2, "straight walk at an even pace thinned to its ends")
  local turned = Route.Thin(walkRecs(turn, 1000))
  check(#turned == 3 and turned[2]:find("^1020,"), "the corner of a turn is kept")
  check(#Route.Thin(walkRecs(pace, 1000)) == 3, "a change of pace is kept (replay timing)")
  local long = {}
  for i = 0, 100 do long[#long + 1] = { i * 2, 0.1 + i * 0.001, 0.5 } end
  local longKept = Route.Thin(walkRecs(long, 1000))
  local maxGap = 0
  for i = 2, #longKept do maxGap = math.max(maxGap, tonumber(longKept[i]:match("^(%d+)")) - tonumber(longKept[i - 1]:match("^(%d+)"))) end
  check(maxGap <= Route.THIN_MAX_SECONDS, "kept points stay close enough in time to keep the line (" .. maxGap .. ")")

  -- Archive: old points are read before the positions stream.
  local beforeCount = #Route.Points()
  FC:GetModule("Positions"):Archive(walkRecs(turn, 1000))
  local archived = Route.Points()
  check(#archived == beforeCount + 3 and archived[1].time == 1000 and archived[4].time > 1020,
    "archived points come first (" .. #archived .. " vs " .. beforeCount .. ")")
  check(#FC:ViewStream("routeArchive").records == 1 and FC:ViewStream("routeArchive").records[1]:find(";", 1, true),
    "archive stores many points per record")

  -- Gliding marker: between two connected points it moves along the line; across a teleport it does not.
  local g = Route.Glide(archived, 1010)
  check(g and math.abs(g.x - 0.31) < 1e-6 and g.y == 0.5, "marker glides along the line")
  local jumpPts = { { time = 0, endTime = 0, mapID = 1413, x = 0.1, y = 0.1 },
    { time = 4, endTime = 4, mapID = 1413, x = 0.9, y = 0.1, jump = true } }
  check(Route.Glide(jumpPts, 1).x == 0.1, "no gliding across a teleport")

  -- Timeline: breaks are collapsed.
  local tlPts = { { time = 0, endTime = 100 }, { time = 1000, endTime = 1100 } }
  local tl = Route.Timeline(tlPts, 0, 1100)
  check(#tl.intervals == 2 and tl.total == 200, "timeline collapses the break (" .. tl.total .. ")")
  check(Route.TimeToValue(tl, 1050) == 150 and Route.ValueToTime(tl, 150) == 1050 and Route.TimeToValue(tl, 500) == 100,
    "timeline maps time and slider value")

  -- Painting: the route is drawn up to the shown moment; the trail shows only its last minutes.
  page.sessionIndex, page.live, page.dirty = 0, true, true
  page:Refresh()
  page.viewMap = 1413                                -- the Barrens walk
  page:Redraw()
  page:UpdateMarker()
  local function shownLines()
    local n = 0
    for _, line in ipairs(page.canvas.lines) do if line:IsShown() then n = n + 1 end end
    return n
  end
  local times = page.canvas.lineTimes
  local all = shownLines()
  local mid = times[math.floor(#times / 2)]
  page.canvas:SetPaint(mid - 6, mid, true)
  local trail = shownLines()
  page.canvas:SetPaint(nil, times[1] - 1)
  check(all == #times and all > 3 and trail >= 1 and trail < all and shownLines() == 0,
    "painting: all " .. all .. ", trail " .. trail .. ", before the start " .. shownLines())
  page:UpdateMarker()
  check(shownLines() == all, "painting follows the shown moment again")

  -- Zoom: the route is drawn again at the new detail shortly after zooming.
  check(page.canvas.rendered.zoom == 1, "route drawn for zoom 1")
  page.canvas:ZoomAtCursor(2)
  check(page.canvas.renderAt ~= nil, "zoom schedules a new drawing")
  page.canvas:RenderRoute()
  check(page.canvas.rendered.zoom == 2 and page.canvas.renderAt == nil, "route drawn again at zoom 2")
  page.canvas:ResetZoom()
  check(page.tickCount >= 1 and #page.runs >= 1, "timeline ticks and zone bands (" .. page.tickCount .. ", " .. #page.runs .. ")")

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
    for _, r in ipairs(S(char.streams.events).records) do if r.type == "rare_killed" then out[#out + 1] = r end end
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
  local shots = S(char.streams.screenshots).records
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
  check(FC:GetModule("Screenshots"):GetSettings().triggers.rare == false, "/fjshot rare off")

  -- Dungeons: the probe on entering, boss kills, and the first kill of the last boss.
  local function ofType(t)
    local out = {}
    for _, r in ipairs(S(char.streams.events).records) do if r.type == t then out[#out + 1] = r end end
    return out
  end
  MOCK.instance, MOCK.zone = true, "Ragefire Chasm"
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  MOCK.advance(4)
  local probe = ForeverChronicleDB.dungeonProbe and ForeverChronicleDB.dungeonProbe["389"]
  check(probe and probe.map == 213 and probe.mapSource == "journal" and probe.position == nil and probe.artTiles == 12
    and probe.journalID == 226 and probe.journalBosses == 4 and probe.lastEncounterID == 1446 and #probe.bossPins == 2,
    "dungeon probe: map from the journal, no position, art, bosses (" .. FC:GetModule("Dungeons"):Describe(probe or {}) .. ")")
  MOCK.fire("ENCOUNTER_START", 1443, "Oggleflint", 1, 5)
  MOCK.fire("ENCOUNTER_END", 1443, "Oggleflint", 1, 5, 1)
  MOCK.fire("BOSS_KILL", 1443, "Oggleflint")                   -- the same kill reported twice
  MOCK.fire("ENCOUNTER_END", 1444, "Taragaman the Hungerer", 1, 5, 0) -- a wipe
  local bosses = ofType("boss_killed")
  check(#bosses == 1 and bosses[1].data.first == true and bosses[1].data.final == false
    and bosses[1].data.instance == "Ragefire Chasm" and bosses[1].location.instanceID == 389,
    "boss kill recorded once, a wipe is not a kill")
  check(FC:DescribeEvent(bosses[1]) == "Boss besiegt: Oggleflint (Ragefire Chasm)", "chronicle text: " .. FC:DescribeEvent(bosses[1]))
  local shotsBefore = #S(char.streams.screenshots).records
  MOCK.advance(20)
  MOCK.fire("ENCOUNTER_END", 1446, "Bazzalan", 1, 5, 1)
  local done = ofType("dungeon_completed")
  check(#done == 1 and done[1].data.instance == "Ragefire Chasm" and done[1].data.boss == "Bazzalan"
    and ofType("boss_killed")[2].data.final == true, "last boss: dungeon completed")
  check(FC:DescribeEvent(done[1]) == "Dungeon abgeschlossen: Ragefire Chasm (Bazzalan)", "completed text")
  MOCK.advance(8)
  local allShots = S(char.streams.screenshots).records
  local dungeonShots = 0
  for _, r in ipairs(allShots) do if r.trigger == "dungeon" and r.status == "confirmed" then dungeonShots = dungeonShots + 1 end end
  check(#allShots > shotsBefore and dungeonShots == 1, "screenshot for the completed dungeon")
  check(char.stats.bosses_killed == 2 and char.stats.dungeons_completed == 1, "boss and dungeon stats")
  MOCK.advance(60)
  MOCK.fire("ENCOUNTER_END", 1446, "Bazzalan", 1, 5, 1)          -- a second run
  check(#ofType("dungeon_completed") == 1 and ofType("boss_killed")[3].data.first == false,
    "only the first kill of the last boss completes the dungeon")
  check(#probe.encounters >= 3 and probe.encounters[1]:find("^start,1443"), "encounters noted in the probe")
  MOCK.instance, MOCK.zone = nil, nil

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
    for _, r in ipairs(S(char.streams.events).records) do if r.type == t then out[#out + 1] = r end end
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
  check(found, "/fj professions lists the professions")

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
  local mine = #S(ForeverChronicleDB.characters[me].streams.events).records
  MOCK.fire("PLAYER_DEAD")
  check(#S(ForeverChronicleDB.characters[me].streams.events).records == mine + 1, "events still recorded for me")
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
  -- What the game writes as SavedVariables\ForeverChronicle_Share.lua (test data for the sync script), taken
  -- before the checks below unpack streams.
  local shareText = "\nForeverChronicleShareDB = " .. serializeValue(ForeverChronicleShareDB) .. "\n"
  local data = ForeverChronicleShareDB
  for _, name in ipairs({ "events", "positions", "sessions" }) do
    check(data.characters[1].streams[name].packed ~= nil, "share stream packed: " .. name)
  end
  check(type(data) == "table" and data.format == 2 and data.name == "Blind" and #data.characters == 2,
    "written on logout: both characters, name defaults to the character's")
  local mine = data.characters[1]
  check(mine.info.name == "Blind" and mine.info.key == me and mine.stats.kills == ForeverChronicleDB.characters[me].stats.kills,
    "info and stats")
  check(#S(mine.streams.events).records >= 2 and #S(mine.streams.positions).records >= 8, "chronicle and route")
  check(mine.snapshots.gear and #mine.snapshots.gear.slots == 2, "gear")
  check(data.maps["1413"] and data.maps["1414"], "maps of the route and their continent")
  check(mine.streams.screenshots == nil, "no screenshots")
  SAVED_OUT = shareText

  -- Limits: only the newest events, only the newest sessions' route.
  Share.EVENTS = 1
  data = Share:Build()
  check(#S(data.characters[1].streams.events).records == 1, "event limit")
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
  check(said, "/fj share explains that the data addon is missing")

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 14 then
  print("phase 14: the main addon alone (CurseForge build)")
  local FC = startClient(true, false)
  check(FC.ready and FC:GetModule("Share") == nil and #FC.viewSources == 0, "no friends parts loaded")
  local sections = {}
  for _, section in ipairs(FC.optionSections) do sections[section.key] = true end
  check(not sections.share, "no sharing settings")
  MOCK.travel(1413, "The Barrens")
  for i = 1, 6 do MOCK.x = 0.30 + i * 0.01; MOCK.advance(2) end
  MOCK.fire("PLAYER_DEAD")
  FC.UI:Toggle()
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end
  FC.UI.viewBar:GetScript("OnClick")(FC.UI.viewBar)
  local rows = 0
  for _, row in ipairs(FC.UI.viewRows.rows) do if row:IsShown() then rows = rows + 1 end end
  check(rows == 2, "chooser: my characters only, no friends note (" .. rows .. " rows)")
  local caps = {}
  for _, cap in ipairs(FC.Diagnostics:GetCapabilities()) do caps[cap.key] = true end
  check(not caps.share, "no sharing capability")
  MOCK.fire("PLAYER_LOGOUT")
  check(rawget(_G, "ForeverChronicleShareDB") == nil, "no data for friends written")
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

print("PHASE " .. PHASE .. " PASSED")
