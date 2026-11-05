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
  -- Like the game: the addon's files, then its ADDON_LOADED.
  local ns = {}
  for _, name in ipairs(ADDON_FILES) do
    local chunk = assert(load(ADDON_SRC[name], "@" .. name))
    chunk("ForeverChronicle", ns)
  end
  MOCK.fire("ADDON_LOADED", "ForeverChronicle")
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
  MOCK.fire("PLAYER_LOGIN")
  MOCK.fire("PLAYER_ENTERING_WORLD", isInitialLogin, isReloadingUi)
  return FC
end

local ME = "Player-4619-0112A417" -- the played character's GUID (UnitGUID("player") in the mock)

local function sessions() return S(ForeverChronicleDB.characters[ME].streams.sessions).records end
local function events() return S(ForeverChronicleDB.characters[ME].streams.events).records end

-- The played character's events of one type, oldest first.
local function eventsOfType(t)
  local out = {}
  for _, r in ipairs(events()) do if r.type == t then out[#out + 1] = r end end
  return out
end

-- Shows the window page with this id and returns it.
local function openPage(id)
  local UI = ForeverChronicle.UI
  for i, page in ipairs(UI.pages) do
    if page.id == id then
      UI:SelectPage(i)
      return page
    end
  end
end

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
  MOCK.deathRecap = { -- the older hit first: the newest timestamp is the killing blow
    { timestamp = time() - 2.5, event = "SWING_DAMAGE", sourceName = "Taragaman the Hungerer", amount = 180 },
    { timestamp = time() - 0.2, event = "SPELL_DAMAGE", sourceName = "Taragaman the Hungerer",
      sourceGUID = "Creature-0-4619-389-1-11520-00000ABC", spellName = "Uppercut", spellId = 10966,
      amount = 412, overkill = 37 },
  }
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
  check(death.data.killer == "Taragaman the Hungerer" and death.data.npcID == 11520 and death.data.spell == "Uppercut"
    and death.data.spellID == 10966 and death.data.damage == 412 and death.data.overkill == 37,
    "death cause from the recap's killing blow")
  check(FC:DescribeEvent(death) == "Getötet von Taragaman the Hungerer in Ragefire Chasm", "death text names the killer")
  check(FC:EventDetails(death)[1] == "Uppercut: 412 Schaden (37 Überschaden)", "death tooltip: the killing blow")
  check(events()[5].seq == 5, "seq numbers assigned")
  local stats = ForeverChronicleDB.characters[ME].stats
  check(stats.quests_completed == 1 and stats.deaths == 1 and stats.sessions == 1, "stats counted")

  -- Kills and experience (a level-up wraps the XP bar: rest of the old level is added).
  MOCK.fire("PARTY_KILL", ME, "Creature-1")
  MOCK.fire("PARTY_KILL", ME, "Creature-2")
  MOCK.xp = 1500; MOCK.fire("PLAYER_XP_UPDATE", "player")
  MOCK.xp, MOCK.xpMax = 4800, 5000; MOCK.fire("PLAYER_XP_UPDATE", "player")
  MOCK.xp, MOCK.xpMax = 200, 6000; MOCK.fire("PLAYER_XP_UPDATE", "player")
  MOCK.fire("PLAYER_XP_UPDATE", "target")
  check(stats.kills == 2, "kills counted (" .. tostring(stats.kills) .. ")")
  check(stats.xp_earned == 500 + 3300 + 400, "experience counted across a level-up (" .. tostring(stats.xp_earned) .. ")")
  check(FC.Util.FormatNumber(1234567) == "1.234.567", "German number format")
  check(FC.Util.FormatNumber(-123456) == "-123.456" and FC.Util.FormatNumber(-12) == "-12", "negative numbers")

  -- Pastimes: jumps from the ground only (not in the air, not swimming up), fish from fishing loot only.
  JumpOrAscendStart(); JumpOrAscendStart()
  MOCK.falling = true; JumpOrAscendStart(); MOCK.falling = false
  MOCK.swimming = true; JumpOrAscendStart(); MOCK.swimming = false
  MOCK.taxi = true; JumpOrAscendStart(); MOCK.taxi = false
  check(MOCK.jumps == 5 and stats.jumps == 2, "jumps counted, the game's jump still runs (" .. tostring(stats.jumps) .. ")")
  MOCK.fire("LOOT_OPENED", false, false)
  MOCK.fishingLoot = true
  MOCK.fire("LOOT_OPENED", true, false)
  MOCK.fire("LOOT_OPENED", false, false)
  MOCK.fishingLoot = MOCK.SECRET
  MOCK.fire("LOOT_OPENED", false, false)
  MOCK.fishingLoot = nil
  check(stats.fish_caught == 2, "fish counted from fishing loot only (" .. tostring(stats.fish_caught) .. ")")
  local caps = ForeverChronicleDB.diagnostics.capabilities
  check(caps.jumps.status == "confirmed" and caps.fishing.status == "confirmed", "jump and fishing capabilities confirmed")

  -- UI: open, visit every page, switch language, run commands.
  SlashCmdList.FOREVERCHRONICLE("")
  check(ForeverChronicleFrame and ForeverChronicleFrame:IsShown(), "window opens with /fj")
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end
  check(#FC.UI.pages == 5, "five pages registered")
  SlashCmdList.FOREVERCHRONICLE("lang en")
  check(FC.L.TAB_OVERVIEW == "Overview", "language switched to English")
  check(#ForeverChronicleFrame.Tabs == 5 and ForeverChronicleFrame.Tabs[2].page.icon ~= nil, "icon tabs, one per page")

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
  settingsPage = openPage("settings")
  check(#settingsPage.bars == 8, "storage bars on the settings page (" .. #settingsPage.bars .. ")")
  local testButton
  for _, control in ipairs(settingsPage.controls) do if type(rawget(control, "button")) == "table" then testButton = control.button end end
  check(testButton and testButton.text == FC.L.SHOT_TEST_BUTTON, "test screenshot button in the screenshot settings")
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
  local positions = S(ForeverChronicleDB.characters[ME].streams.positions).records
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
  local shots = S(ForeverChronicleDB.characters[ME].streams.screenshots).records
  for _, r in ipairs(shots) do print("    shot", r.trigger, r.status, #r.events) end
  check(#shots == 1 and #MOCK.screenshots == 1, "level-up and achievement produced one screenshot")
  check(shots[1].status == "confirmed" and #shots[1].events == 2 and shots[1].trigger == "level",
    "screenshot confirmed and linked to both events")
  check(type(shots[1].fileStamp) == "string" and #shots[1].fileStamp == 13, "file stamp stored (" .. tostring(shots[1].fileStamp) .. ")")
  check(MOCK.screenshots[1] >= levelUpAt + 5, "screenshot taken after the 5 s delay")
  ForeverChronicleDB.settings.modules.Screenshots.enabled = false -- the old main switch, switched off
  SAVED_OUT = save()

elseif PHASE == 2 then
  print("phase 2: /reload continues the session")
  startClient(false, true)
  check(#sessions() == 1, "no new session on reload")
  check(sessions()[1].endReason == "open" and sessions()[1].endedAt == nil, "session reopened")
  local shotSettings = ForeverChronicle:GetModule("Screenshots")
  check(shotSettings:GetSettings().enabled == nil and shotSettings:IsTriggerEnabled("level"),
    "no main switch any more: ticked triggers take screenshots")
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
  MOCK.advance(301)
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
  local stream = ForeverChronicleDB.characters[ME].streams.events
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
  check(Storage.IsPlainData('{a="[[ -- ]]",b="\\\\",c="x\\\ny"}'), "brackets and dashes inside strings accepted")
  for _, bad in ipairs({ '}while true do end{', '{a=("x"):rep(9)}', '{a=b}', '{a=1}}return{', '{a=#"x"}',
      '{[[ "]],(function() while true do end end)(),[[" ]]}', '{[==[ "]==],f(),[==[" ]==]}',
      '{a=1}--"\n,f(),{"', '{a="x}', '{a="x\n"}' }) do
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
  local char = ForeverChronicleDB.characters[ME]
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
  -- Hide the interface for the screenshot and show it again afterwards.
  FC:GetModule("Screenshots"):GetSettings().hideUI = "all"
  MOCK.advance(3)
  SlashCmdList.FOREVERCHRONICLESHOT("test")
  MOCK.advance(3.5)
  check(MOCK.uiVisibleAtCapture == false, "interface hidden when the screenshot is taken")
  check(UIParent:IsShown(), "interface shown again after the screenshot")
  MOCK.combat = true
  MOCK.advance(3)
  SlashCmdList.FOREVERCHRONICLESHOT("test")
  MOCK.advance(3.5)
  check(MOCK.uiVisibleAtCapture == true and MOCK.uiAlphaAtCapture == 0 and UIParent:GetAlpha() == 1,
    "in combat the interface is made transparent instead, and restored")
  MOCK.combat = false

  -- "Keep popups": everything transparent except the level-up banner, taken once the banner is shown.
  local shots = FC:GetModule("Screenshots")
  local settings = shots:GetSettings()
  settings.hideUI, settings.delay = "popups", 5
  -- A forbidden frame (like some of Blizzard's): any call except IsForbidden is an error, so it is skipped.
  local forbidden = CreateFrame("Frame", nil, UIParent)
  forbidden.IsForbidden = function() return true end
  forbidden.IsVisible = function() error("Attempt to access forbidden object from code tainted by an AddOn") end
  shots:UpdateSnapshots()
  check(shots.snapshot ~= nil and not shots.snapshot[forbidden], "forbidden frames are skipped")
  MOCK.advance(3)                                    -- past the snapshot interval (level-ups skip the cooldown)
  local before = #MOCK.screenshots
  MOCK.level = (MOCK.level or 22) + 1
  MOCK.fire("PLAYER_LEVEL_UP", MOCK.level)
  C_Timer.After(0.5, function() EventToastManagerFrame:Show() end)
  local levelUpAt = MOCK.now
  MOCK.advance(2.4)
  check(#MOCK.screenshots == before, "not taken the moment the banner appears (it settles for 2 s)")
  MOCK.advance(1.0)
  check(#MOCK.screenshots == before + 1 and MOCK.screenshots[#MOCK.screenshots] - levelUpAt < 3.4,
    "taken soon after the banner appeared, not after the 5 s delay")
  check(MOCK.uiAlphaAtCapture == 0 and MOCK.toastVisibleAtCapture, "everything hidden except the banner")
  check(UIParent:GetAlpha() == 1 and not EventToastManagerFrame:IsIgnoringParentAlpha(), "restored afterwards")
  check(MOCK.minimapVisibleAtCapture == false and Minimap:IsShown(),
    "the minimap (its arrow and quest areas ignore transparency) is hidden for the screenshot, then shown")
  EventToastManagerFrame:Hide()
  -- In combat a minimap the client protects stays as it is; one hidden just before combat returns afterwards.
  Minimap.IsProtected = function() return true end
  MOCK.combat = true
  shots:HideInterface(nil)
  check(Minimap:IsShown(), "a protected minimap is not hidden in combat")
  shots:RestoreInterface()
  MOCK.combat = false
  shots:HideInterface(nil)
  MOCK.combat = true
  shots:RestoreInterface()
  check(not Minimap:IsShown() and UIParent:GetAlpha() == 1, "combat started: the minimap waits")
  MOCK.combat = false
  MOCK.fire("PLAYER_REGEN_ENABLED")
  check(Minimap:IsShown() and not shots.minimapPending, "the minimap returns when combat ends")
  Minimap.IsProtected = nil
  local alert = CreateFrame("Frame", nil, UIParent)  -- e.g. an achievement toast without a known name
  alert:Hide()
  local baseline = shots:VisibleFrames()
  alert:Show()
  local found = shots:FindPopups(baseline)
  check(#found == 1 and found[1] == alert, "a frame that appeared after the event counts as its popup")
  alert:Hide()
  -- The pet bar (a pet summoned, or back after a flight) and a new target appear with play, not with the event.
  local petBar = CreateFrame("Frame", "PetActionBar", UIParent)
  local target = CreateFrame("Frame", "TargetFrame", UIParent)
  petBar:Hide()
  target:Hide()
  baseline = shots:VisibleFrames()
  petBar:Show()
  target:Show()
  alert:Show()
  found = shots:FindPopups(baseline)
  check(#found == 1 and found[1] == alert, "the pet bar and the target's frame are no popups")
  petBar:Hide()
  target:Hide()
  alert:Hide()
  settings.hideUI, settings.delay = "off", 2
  shots:UpdateSnapshots()
  SlashCmdList.FOREVERCHRONICLESHOT("status")
  SlashCmdList.FOREVERCHRONICLESHOT("api")
  SlashCmdList.FOREVERCHRONICLESHOT("bogus")

  -- Pending zone request (Thunder Bluff, waiting for cooldown) is reported on logout.
  MOCK.advance(5)
  SlashCmdList.FOREVERCHRONICLE("")
  for i = 1, #FC.UI.pages do FC.UI:SelectPage(i) end
  -- Chronicle: screenshots appear with their entry; test screenshots (no entry) as entries of their own.
  local chronicle = openPage("chronicle")
  local zoneItem, tests = nil, 0
  for _, item in ipairs(chronicle.items) do
    if item.event and item.event.type == "zone_discovered" and item.event.data.zone == "Durotar" then zoneItem = item end
    if not item.event and item.shot.trigger == "manual" then tests = tests + 1 end
  end
  check(zoneItem and zoneItem.shot and zoneItem.shot.status == "confirmed", "zone entry carries its screenshot")
  check(tests >= 3, "test screenshots listed as their own entries (" .. tests .. ")")
  local zoneRow
  for _, row in ipairs(chronicle.list.rows) do if row.shotRecord == zoneItem.shot then zoneRow = row end end
  check(zoneRow and zoneRow.shot:IsShown(), "screenshot marker shown on the zone entry")
  local all = #chronicle.items
  check(chronicle.shown[1].header and chronicle.shown[1].text == "Heute", "entries under a day heading")
  local milestone
  for _, item in ipairs(chronicle.items) do
    if item.event and item.event.type == "level_up" then milestone = item.highlight end
  end
  check(milestone == "milestone", "level-ups stand out as milestones")
  -- Category filter: hide exploration, then shift-click shows only exploration, shift-click again shows all.
  local zoneButton
  for _, b in ipairs(chronicle.filters) do if b.category == "exploration" then zoneButton = b end end
  local function hasZone()
    for _, item in ipairs(chronicle.items) do if item.event and item.event.type == "zone_discovered" then return true end end
  end
  check(zoneButton and hasZone(), "zones listed before filtering")
  zoneButton:GetScript("OnClick")(zoneButton)
  check(not hasZone() and not zoneButton.on and #chronicle.items < all, "exploration filter hides zones")
  zoneButton:GetScript("OnClick")(zoneButton)
  check(hasZone() and #chronicle.items == all, "exploration filter on again")
  IsShiftKeyDown = function() return true end
  zoneButton:GetScript("OnClick")(zoneButton)
  local onlyZones = #chronicle.items > 0
  for _, item in ipairs(chronicle.items) do
    if item.event and item.event.type ~= "zone_discovered" then onlyZones = false end
  end
  check(onlyZones, "shift-click shows only exploration")
  zoneButton:GetScript("OnClick")(zoneButton)
  IsShiftKeyDown = nil
  check(#chronicle.items == all, "shift-click again shows all")
  -- Search: by entry text or place, ignoring case.
  chronicle:SetSearch("DUROTAR")
  local foundZone = false
  for _, item in ipairs(chronicle.items) do if item == zoneItem or (item.event and item.event == zoneItem.event) then foundZone = true end end
  check(foundZone and #chronicle.items < all, "search finds Durotar (" .. #chronicle.items .. " of " .. all .. ")")
  chronicle:SetSearch("xyz no such entry")
  check(#chronicle.items == 0 and chronicle.emptyFiltered:IsShown(), "search without results says so")
  chronicle:SetSearch("")
  check(#chronicle.items == all, "empty search shows all")
  -- The filter icons fold in and out; the state is kept.
  chronicle:SetFiltersOpen(true, false)
  check(chronicle.filters[1]:IsShown() and FC.db.settings.modules.UI.chronicleFiltersOpen, "filter row unfolds")
  chronicle:SetFiltersOpen(false, false)
  check(not chronicle.filters[1]:IsShown() and chronicle.foldLabel.text == "Filter", "filter row folds")
  chronicle.filter:GetScript("OnClick")(chronicle.filter)
  local onlyShots = true
  for _, item in ipairs(chronicle.items) do
    if not (item.shot and (item.shot.status == "confirmed" or item.shot.status == "api_called")) then onlyShots = false end
  end
  check(onlyShots and #chronicle.items >= tests + 1 and #chronicle.items < all,
    "filter shows only entries with a screenshot (" .. #chronicle.items .. " of " .. all .. ")")
  chronicle.filter:GetScript("OnClick")(chronicle.filter)
  check(#chronicle.items == all, "filter off shows everything again")
  MOCK.fire("PLAYER_LOGOUT")
  check(statuses():find("zone:dropped_on_logout", 1, true), "pending request dropped on logout: " .. statuses())
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 6 then
  print("phase 6: position sampling")
  local FC = startClient(true, false)
  local function points() return S(ForeverChronicleDB.characters[ME].streams.positions).records end
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

if PHASE == 7 then
  print("phase 7: an older saved file (schema 1)")
  assert(load(SAVED))()
  startClient(true, false)
  check(ForeverChronicleDB.schemaVersion == 2 and ForeverChronicleDB.settings.modules.Positions.interval == 10,
    "schema upgraded, the saved interval kept")
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
  local page = openPage("map")
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
  local skull
  for _, pin in ipairs(page.canvas.pins) do
    if pin:IsShown() and pin.title and pin.title:find("Ragefire", 1, true) then skull = pin end
  end
  check(skull.icon.texture == "Interface\\TargetingFrame\\UI-TargetingFrame-Skull" and skull.look.ring == 21,
    "death pin: skull on a red disc")
  -- Previous / next event buttons step along the timeline marks.
  local mark = page.ticks[1].time
  page.current = page.range[1]
  page.nextEvent:GetScript("OnClick")(page.nextEvent)
  local stepped = page.current
  page.current = page.range[2]
  page.prevEvent:GetScript("OnClick")(page.prevEvent)
  check(stepped == mark and page.current == mark and not page.live, "event step buttons jump to the mark")
  FC.UI:FocusMap(dungeonTime + 2)
  ForeverChronicleDB.entrances = {}
  check(Route.Entrance(389) and Route.Entrance(389).mapID == 1413, "entrance derived from the route for older data")

  -- Playback from the start.
  page.current = page.range[1]
  page:TogglePlay()
  check(page.play.kind == "pause", "play button shows pause while playing")
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
  check(g.curve and g.curve.f > 0 and g.curve.f < 1 and g.curve.a and g.curve.b, "the glide names its line for curves")

  -- Curves through the points: they pass through both ends, stay straight on a straight line and cope with
  -- missing or doubled neighbours.
  local cx, cy = Route.CurvePoint(0, 0, 1, 0, 2, 1, 3, 1, 0)
  local ex, ey = Route.CurvePoint(0, 0, 1, 0, 2, 1, 3, 1, 1)
  check(cx == 1 and cy == 0 and math.abs(ex - 2) < 1e-9 and math.abs(ey - 1) < 1e-9, "curve passes through both ends")
  local sx, sy = Route.CurvePoint(0, 0, 1, 0, 2, 0, 3, 0, 0.25)
  check(math.abs(sx - 1.25) < 1e-9 and sy == 0, "evenly spaced points on a line stay a straight line")
  local mx, my = Route.CurvePoint(1, 0, 1, 0, 2, 1, 2, 1, 0.5)
  local ox, oy = Route.CurvePoint(0, 0, 1, 0, 1, 0, 3, 1, 0.5)
  check(mx == mx and my == my and ox == 1 and oy == 0, "missing neighbours and a zero-length line give numbers")
  local _, bend = Route.CurvePoint(0, 0, 1, 0, 2, 1, 3, 1, 0.5)
  check(math.abs(bend - 0.5) < 1e-9, "a symmetric bend passes the middle")
  local _, early = Route.CurvePoint(0, 0, 1, 0, 2, 1, 3, 1, 0.25)
  check(early < 0.25, "the curve leaves the first point along its line, not straight to the second")

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

  -- Zoomed in, lines are drawn as curves through their points, and the marker stays on them.
  local c = page.canvas
  local W, H = c.width, c.height
  local wavy = { { points = { { 0.40, 0.50, 1 }, { 0.45, 0.50, 2 }, { 0.48, 0.55, 3 }, { 0.53, 0.55, 4 } } } }
  c:DrawRoute(wavy)
  check(not c.smooth and #c.lineTimes == 3, "zoom 1: straight lines")
  c:SetView(4, W / 2 - 0.46 * W * 4, H / 2 - 0.52 * H * 4)
  c:RenderRoute()
  local n = #c.lineTimes
  check(c.smooth and n > 3, "zoomed in: curves (" .. n .. " pieces)")
  local chained = true
  for i = 2, n do
    local a, b = c.lines[i - 1].to, c.lines[i].from
    if math.abs(a[1] - b[1]) > 1e-6 or math.abs(a[2] - b[2]) > 1e-6 or c.lineTimes[i] < c.lineTimes[i - 1] then chained = false end
  end
  check(chained and c.lines[1].from[1] == 0.40 * W and math.abs(c.lines[n].to[1] - 0.53 * W) < 1e-6,
    "pieces join up from the first point to the last, in time order")
  local curve = { 0.40, 0.50, 0.45, 0.50, 0.48, 0.55, 0.53, 0.55, 0.5 }
  c:SetMarker(0.465, 0.525, curve)
  local px, py = Route.CurvePoint(0.40 * W, 0.50 * H, 0.45 * W, 0.50 * H, 0.48 * W, 0.55 * H, 0.53 * W, 0.55 * H, 0.5)
  local at = c.marker.at
  check(math.abs(at[1] - px) < 0.5 and math.abs(at[2] + py) < 0.5, "marker on the curve")
  c:ResetZoom()
  c:RenderRoute()
  check(not c.smooth and math.abs(c.marker.at[1] - 0.465 * W) < 1e-6, "zoomed out: marker back on the straight line")
  page:Redraw()
  check(page.tickCount >= 1 and #page.runs >= 1, "timeline ticks and zone bands (" .. page.tickCount .. ", " .. #page.runs .. ")")

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 10 then
  print("phase 10: rare enemies")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters[ME]
  local function rareEvents() return eventsOfType("rare_killed") end
  MOCK.advance(2)

  -- Rare as target, killed.
  local rare = "Creature-0-4619-1-1-3398-00001A2B"
  MOCK.units.target = { guid = rare, classification = "rareelite", name = "Gesharahan" }
  MOCK.fire("PLAYER_TARGET_CHANGED")
  MOCK.fire("PARTY_KILL", ME, rare)
  local events = rareEvents()
  check(#events == 1 and events[1].data.name == "Gesharahan" and events[1].data.npcID == 3398,
    "rare kill recorded with name and NPC ID")
  check(char.stats.rares_killed == 1, "rare stat counted")
  check(FC:DescribeEvent(events[1]) == "Seltenen Gegner besiegt: Gesharahan", "chronicle text")
  MOCK.advance(6)
  local shots = S(char.streams.screenshots).records
  check(shots[#shots].trigger == "rare" and shots[#shots].status == "confirmed", "screenshot for the rare kill")

  MOCK.fire("PARTY_KILL", ME, rare)
  check(#rareEvents() == 1, "a second kill report for the same rare is ignored")

  -- Normal mob: no event.
  MOCK.units.target = { guid = "Creature-0-4619-1-1-3035-00002222", classification = "normal", name = "Plainstrider" }
  MOCK.fire("PLAYER_TARGET_CHANGED")
  MOCK.fire("PARTY_KILL", ME, "Creature-0-4619-1-1-3035-00002222")
  check(#rareEvents() == 1, "normal mobs are not rare kills")

  -- Rare only seen on a nameplate.
  local rare2 = "Creature-0-4619-1-1-5865-00003333"
  MOCK.units.nameplate3 = { guid = rare2, classification = "rare", name = "Dishu" }
  MOCK.fire("NAME_PLATE_UNIT_ADDED", "nameplate3")
  MOCK.fire("PARTY_KILL", ME, rare2)
  check(#rareEvents() == 2, "rare seen on a nameplate")

  -- GUIDs hidden (secret): the dead rare target is used.
  local rare3 = "Creature-0-4619-1-1-3470-00004444"
  MOCK.units.target = { guid = rare3, classification = "rare", name = "Rathorian", dead = true }
  MOCK.fire("PARTY_KILL", MOCK.SECRET, MOCK.SECRET)
  check(#rareEvents() == 3 and rareEvents()[3].data.name == "Rathorian", "fallback when GUIDs are hidden")

  -- Trigger can be switched off.
  SlashCmdList.FOREVERCHRONICLESHOT("rare off")
  check(FC:GetModule("Screenshots"):GetSettings().triggers.rare == false, "/fjshot rare off")

  -- Dungeons: boss kills, and the first kill of the last boss.
  MOCK.instance, MOCK.zone = true, "Ragefire Chasm"
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  MOCK.advance(4)
  MOCK.fire("ENCOUNTER_START", 1443, "Oggleflint", 1, 5)
  MOCK.fire("ENCOUNTER_END", 1443, "Oggleflint", 1, 5, 1)
  MOCK.fire("BOSS_KILL", 1443, "Oggleflint")                   -- the same kill reported twice
  MOCK.fire("ENCOUNTER_END", 1444, "Taragaman the Hungerer", 1, 5, 0) -- a wipe
  local bosses = eventsOfType("boss_killed")
  check(#bosses == 1 and bosses[1].data.first == true and bosses[1].data.final == false
    and bosses[1].data.instance == "Ragefire Chasm" and bosses[1].location.instanceID == 389,
    "boss kill recorded once, a wipe is not a kill")
  check(FC:DescribeEvent(bosses[1]) == "Boss besiegt: Oggleflint (Ragefire Chasm)", "chronicle text: " .. FC:DescribeEvent(bosses[1]))
  local shotsBefore = #S(char.streams.screenshots).records
  MOCK.advance(20)
  MOCK.fire("ENCOUNTER_END", 1446, "Bazzalan", 1, 5, 1)
  local done = eventsOfType("dungeon_completed")
  check(#done == 1 and done[1].data.instance == "Ragefire Chasm" and done[1].data.boss == "Bazzalan"
    and eventsOfType("boss_killed")[2].data.final == true, "last boss: dungeon completed")
  check(FC:DescribeEvent(done[1]) == "Dungeon abgeschlossen: Ragefire Chasm (Bazzalan)", "completed text")
  MOCK.advance(8)
  local allShots = S(char.streams.screenshots).records
  local dungeonShots = 0
  for _, r in ipairs(allShots) do if r.trigger == "dungeon" and r.status == "confirmed" then dungeonShots = dungeonShots + 1 end end
  check(#allShots > shotsBefore and dungeonShots == 1, "screenshot for the completed dungeon")
  check(char.stats.bosses_killed == 2 and char.stats.dungeons_completed == 1, "boss and dungeon stats")
  MOCK.advance(60)
  MOCK.fire("ENCOUNTER_END", 1446, "Bazzalan", 1, 5, 1)          -- a second run
  check(#eventsOfType("dungeon_completed") == 1 and eventsOfType("boss_killed")[3].data.first == false,
    "only the first kill of the last boss completes the dungeon")
  MOCK.instance, MOCK.zone = nil, nil

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 11 then
  print("phase 11: professions")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters[ME]
  local P = FC:GetModule("Professions")

  local snap = char.snapshots.professions
  check(snap and #snap.list == 4 and snap.baseline, "four professions seen at login")
  local lw = P:Find(165)
  check(lw.name == "Leatherworking" and lw.maxRank == 150 and lw.rank == nil and lw.recipes == nil,
    "only name, icon and maximum are kept")
  check(#eventsOfType("profession_learned") == 0, "professions known at install are not reported as learned")
  MOCK.advance(6)
  check(#eventsOfType("profession_learned") == 0, "delayed login scan adds no events")

  -- Next rank trained (maximum 150 -> 225).
  MOCK.professions[6][4] = 225
  MOCK.fire("SKILL_LINES_CHANGED")
  MOCK.advance(2)
  local ranks = eventsOfType("profession_rank")
  check(#ranks == 1 and ranks[1].data.maxRank == 225 and lw.maxRank == 225, "rank event")
  check(FC:DescribeEvent(ranks[1]) == "Leatherworking: Experte", "rank text: " .. FC:DescribeEvent(ranks[1]))

  -- A new profession and an unlearned one.
  MOCK.professions[9] = { "Fishing", 136245, 1, 75, 1, 0, 356, 0, -1, 0, "Fishing" }
  MOCK.professionSlots[4] = 9
  MOCK.professionSlots[2] = nil
  MOCK.fire("CHAT_MSG_SKILL", "Your skill in Fishing has increased to 1.")
  MOCK.advance(2)
  local learnedProf = eventsOfType("profession_learned")
  check(#learnedProf == 1 and learnedProf[1].data.name == "Fishing", "profession_learned event")
  check(FC:DescribeEvent(learnedProf[1]) == "Beruf erlernt: Fishing", "learned text: " .. FC:DescribeEvent(learnedProf[1]))
  check(P:Find(182).active == false, "herbalism marked as unlearned")

  -- Learning herbalism again is reported again.
  MOCK.professionSlots[2] = 7
  MOCK.fire("SKILL_LINES_CHANGED")
  MOCK.advance(2)
  check(#eventsOfType("profession_learned") == 2 and P:Find(182).active, "relearned profession reported")

  -- Saved files from before 0.15 lose the recipes, the skill and the "recipe_learned" events.
  local old = { characters = { alt = {
    snapshots = { professions = { baseline = true, scannedAt = 1, list = {
      { skillLine = 165, name = "Leatherworking", icon = 1, rank = 126, maxRank = 150, kind = "primary", active = true,
        recipes = { status = "complete", list = { "2881,2550,134252,1,Light Leather" } } } } } },
    streams = { events = { nextSeq = 4, dropped = 0, records = {
      { seq = 1, type = "session_started" }, { seq = 2, type = "recipe_learned" }, { seq = 3, type = "level_up" } } } },
  } } }
  P.RemoveOldData(old)
  local altProf = old.characters.alt.snapshots.professions.list[1]
  check(altProf.recipes == nil and altProf.rank == nil and altProf.kind == nil and altProf.maxRank == 150,
    "old profession fields removed")
  local recs = old.characters.alt.streams.events.records
  check(#recs == 2 and recs[1].seq == 1 and recs[2].seq == 3 and old.characters.alt.streams.events.nextSeq == 4,
    "old recipe events removed, order and seq kept")

  -- The profession window still tells where crafted items come from.
  MOCK.fire("TRADE_SKILL_SHOW")
  check(FC:GetModule("Loot"):Source() == "craft", "items made at the profession window come from crafting")
  MOCK.fire("TRADE_SKILL_CLOSE")
  check(FC.Util.Fold("Ärmel ÖL Über") == "ärmel öl über", "umlauts folded for searching")

  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 12 then
  print("phase 12: character layer with an alt")
  local FC = startClient(true, false)
  -- An alt on the same account (all characters share the SavedVariables).
  ForeverChronicleDB.characters["Player-4619-0ALT0001"] = {
    info = { name = "Altie", level = 10, classFile = "MAGE", realm = "Classic Beta PvP", lastSeenAt = 1791900000 },
    stats = { kills = 5 }, state = {}, snapshots = {},
    streams = { events = { nextSeq = 2, dropped = 0, records = {
      { id = "alt1", seq = 1, type = "level_up", time = 1791900000, data = { level = 10 } } } } },
  }

  local entries = FC:ViewEntries()
  check(#entries == 2 and entries[1].played and entries[1].key == ME, "played character first")
  check(entries[2].key == "Player-4619-0ALT0001" and not entries[2].owner, "then the account's other characters")
  check(FC:IsViewingPlayed() and FC:ViewChar() == FC.char, "the window starts on the played character")

  FC.UI:Toggle()
  local UI = FC.UI
  check(UI.viewBar.name.text:find("Blind Bullseye", 1, true) and UI.viewBar.sub.text:find("Stufe 22", 1, true),
    "the bar shows the played character")
  check(not UI.viewBack:IsShown(), "no back button while viewing myself")
  check(ForeverChronicleFrame.portraitUnit == "player", "portrait: the played character")
  UI.viewBar:GetScript("OnClick")(UI.viewBar)
  local alt
  for _, row in ipairs(UI.viewRows.rows) do
    if row:IsShown() and row.key == "Player-4619-0ALT0001" then alt = row end
  end
  check(alt and alt.icon.texture == "Interface\\TargetingFrame\\UI-Classes-Circles", "the alt in the list, class emblem")

  -- The alt, then back to me.
  alt:GetScript("OnMouseUp")(alt)
  local ov = openPage("overview")
  local function link(slot) return rawget(slot, "link") end   -- mock frames return functions for unset fields
  check(ov.name.text:find("Altie", 1, true) and UI.viewBar.sub.text:find("Anderer Charakter", 1, true), "alt shown")
  check(UI.viewBack:IsShown(), "back button")
  check(link(ov.slots[1]) == nil, "the alt has no gear snapshot: empty slots")
  check(ForeverChronicleFrame.portraitClass == "MAGE", "portrait: the alt's class emblem")
  local overviewTab = ForeverChronicleFrame.Tabs[1]
  check(overviewTab.icon.texture == "Interface\\TargetingFrame\\UI-Classes-Circles", "overview tab icon follows")
  local chron = openPage("chronicle")
  check(#chron.items == 1, "alt's chronicle")

  -- Recording continues for the played character only.
  local mine = #S(ForeverChronicleDB.characters[ME].streams.events).records
  MOCK.fire("PLAYER_DEAD")
  check(#S(ForeverChronicleDB.characters[ME].streams.events).records == mine + 1, "events still recorded for me")
  check(#FC:ViewStream("events").records == 1, "the alt's data is not changed")

  UI.viewBack:GetScript("OnClick")(UI.viewBack)
  check(FC:IsViewingPlayed() and not UI.viewBack:IsShown(), "back to me")
  check(ForeverChronicleFrame.portraitUnit == "player", "portrait: back to the played character")
  openPage("overview")
  check(ov.gearPanel:IsShown() and ov.model:IsShown() and not ov.otherNote:IsShown() and link(ov.slots[1]) == nil,
    "live parts back (gear from the live inventory again)")
  local gear = ForeverChronicleDB.characters[ME].snapshots.gear
  check(gear and #gear.slots == 2 and gear.slots[1].slotName == "HeadSlot" and gear.slots[1].quality == 3,
    "my gear snapshot")
  for i = 1, #UI.pages do UI:SelectPage(i) end

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

if PHASE == 15 then
  print("phase 15: causes of death")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters[ME]
  local function lastDeath()
    local deaths = eventsOfType("player_died")
    return deaths[#deaths]
  end
  MOCK.advance(2)

  -- The recap arrives a moment after the death: the event is filled in then.
  MOCK.deathRecap = nil
  MOCK.fire("PLAYER_DEAD")
  check(lastDeath().data.killer == nil and FC:DescribeEvent(lastDeath()):find("^Gestorben"), "no recap yet: plain death")
  MOCK.deathRecap = { { timestamp = time(), event = "SWING_DAMAGE", sourceName = "Hogger",
    sourceGUID = "Creature-0-4619-0-1-448-00000001", amount = 96, overkill = 0 } }
  MOCK.advance(1)
  local hogger = lastDeath()
  check(hogger.data.killer == "Hogger" and hogger.data.npcID == 448 and hogger.data.spell == nil
    and hogger.data.overkill == nil, "late recap fills in the killer")
  check(FC:EventDetails(hogger)[1] == "Nahkampf: 96 Schaden", "melee blow in the tooltip")

  -- The next death while the client still holds the old recap: it is not used again.
  MOCK.advance(30)
  MOCK.fire("PLAYER_DEAD")
  MOCK.advance(5)
  check(lastDeath() ~= hogger and lastDeath().data.killer == nil, "an earlier death's recap is not reused")

  -- Environmental damage, with the location.
  MOCK.travel(1413, "The Barrens")
  MOCK.deathRecap = { { timestamp = time(), event = "ENVIRONMENTAL_DAMAGE", environmentalType = "Falling", amount = 1200 } }
  MOCK.fire("PLAYER_DEAD")
  local fall = lastDeath()
  check(fall.data.environment == "falling" and fall.data.killer == nil, "falling recorded as environment")
  check(FC:DescribeEvent(fall) == "Zu Tode gestürzt in Crossroads", "falling text")

  -- Secret values (Midnight rules) are left out.
  MOCK.advance(30)
  MOCK.deathRecap = { { timestamp = time(), sourceName = MOCK.SECRET, spellName = "Shadow Bolt", amount = MOCK.SECRET } }
  MOCK.fire("PLAYER_DEAD")
  check(lastDeath().data.killer == nil and lastDeath().data.spell == "Shadow Bolt" and lastDeath().data.damage == nil
    and FC:DescribeEvent(lastDeath()) == "Getötet von Shadow Bolt in Crossroads", "secret killer: the spell only")
  MOCK.deathRecap = MOCK.SECRET
  MOCK.advance(30)
  MOCK.fire("PLAYER_DEAD")
  MOCK.advance(5)
  check(lastDeath().data.spell == nil, "secret recap is ignored")
  check(char.stats.deaths == 5, "every death counted")
end

if PHASE == 16 then
  print("phase 16: mounts, teleports, revival, hearthstone, group, loot, moments")
  MOCK.bags[0] = { [1] = { itemID = 2589, count = 20, quality = 1, link = "|cffffffff|Hitem:2589::|h[Linen Cloth]|h|r" } }
  MOCK.items[2589] = { classID = 7, maxStack = 200 }
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters[ME]
  local function points() return char.streams.positions.records end
  local function lastPoint() return FC.Route.Parse(points()[#points()]) end
  MOCK.travel(1413, "The Barrens")
  MOCK.advance(6)

  -- Riding: the "M" flag, and a new point when the player mounts on the spot.
  local before = #points()
  MOCK.mounted = true
  MOCK.advance(2)
  check(#points() == before + 1 and lastPoint().mounted, "mounting starts a mounted point")
  MOCK.x = 0.47; MOCK.advance(2)
  check(points()[#points()]:find(",M,", 1, true) ~= nil, "flag M in the saved point")
  MOCK.mounted = false

  -- Hearthstone: a 10 s cast, then the player is far away: "J" and "H".
  MOCK.casting = { spellID = 8690, seconds = 10 }
  MOCK.fire("UNIT_SPELLCAST_START", "player", "cast-1", 8690)
  MOCK.advance(10)
  MOCK.casting = nil
  MOCK.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "cast-1", 8690)
  MOCK.x, MOCK.y = 0.20, 0.20
  MOCK.advance(1.5)
  local hearth = lastPoint()
  check(hearth.jump and hearth.cause == "H", "hearthstone teleport flagged (" .. points()[#points()] .. ")")
  -- A short cast never marks the next jump.
  MOCK.casting = { spellID = 133, seconds = 1.5 }
  MOCK.fire("UNIT_SPELLCAST_START", "player", "cast-2", 133)
  MOCK.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "cast-2", 133)
  MOCK.casting = nil
  MOCK.x, MOCK.y = 0.60, 0.60
  MOCK.advance(2)
  check(lastPoint().cause == nil, "a short cast marks nothing")
  -- A mage's teleport: another spell, after a loading screen.
  MOCK.casting = { spellID = 3567, seconds = 10 }
  MOCK.fire("UNIT_SPELLCAST_START", "player", "cast-3", 3567)
  MOCK.advance(10)
  MOCK.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "cast-3", 3567)
  MOCK.casting = nil
  MOCK.fire("LOADING_SCREEN_ENABLED")
  MOCK.advance(0.5)
  MOCK.travel(1454, "Orgrimmar")
  MOCK.fire("LOADING_SCREEN_DISABLED")
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  MOCK.advance(2)
  check(lastPoint().cause == "P" and lastPoint().jump, "teleport spell flagged P (" .. points()[#points()] .. ")")
  local thinned = table.concat(FC.Route.Thin(points()), ";")
  check(thinned:find(",JH,", 1, true) and thinned:find(",JP,", 1, true), "flagged points survive thinning")

  -- Death: release, run back, alive at the body.
  local function lastDeath() local d = eventsOfType("player_died"); return d[#d] end
  MOCK.fire("PLAYER_DEAD")
  MOCK.advance(20)
  MOCK.ghost = true
  MOCK.fire("PLAYER_ALIVE")
  MOCK.advance(60)
  MOCK.ghost = false
  MOCK.fire("PLAYER_UNGHOST")
  local d1 = lastDeath().data
  check(d1.releasedAt and d1.revivedAt - d1.releasedAt == 60 and d1.revive == "corpse", "corpse run recorded")
  -- Resurrected by a friend before releasing.
  MOCK.advance(30)
  MOCK.fire("PLAYER_DEAD")
  MOCK.fire("RESURRECT_REQUEST", "Gigel")
  MOCK.advance(10)
  MOCK.fire("PLAYER_ALIVE")
  local d2 = lastDeath()
  check(d2.data.revive == "player" and d2.data.reviver == "Gigel" and not d2.data.releasedAt, "resurrected by a player")
  local tip = FC:EventDetails(d2)
  check(tip and tip[#tip] == "Wiederbelebt von Gigel", "the resurrecter in the tooltip")
  -- The spirit healer.
  MOCK.advance(30)
  MOCK.fire("PLAYER_DEAD")
  MOCK.ghost = true
  MOCK.fire("PLAYER_ALIVE")
  MOCK.advance(20)
  MOCK.fire("CONFIRM_XP_LOSS")
  MOCK.ghost = false
  MOCK.fire("PLAYER_UNGHOST")
  check(lastDeath().data.revive == "spirit_healer", "spirit healer")
  -- PLAYER_ALIVE while alive (a login) changes nothing.
  MOCK.fire("PLAYER_ALIVE")
  check(lastDeath().data.revive == "spirit_healer", "alive players are not revived again")

  -- First mount (the collection was empty at the first scan), with its screenshot.
  MOCK.advance(60)
  local shots = #MOCK.screenshots
  MOCK.mountsCollected[6] = true
  MOCK.fire("NEW_MOUNT_ADDED", 6)
  MOCK.advance(8)
  local mounts = eventsOfType("mount_learned")
  check(#mounts == 1 and mounts[1].data.first and mounts[1].data.name == "Brown Horse"
    and FC:DescribeEvent(mounts[1]) == "Erstes Reittier: Brown Horse", "first mount recorded")
  check(#MOCK.screenshots == shots + 1, "first mount screenshot")
  MOCK.mountsCollected[14] = true
  MOCK.fire("NEW_MOUNT_ADDED", 14)
  MOCK.advance(2)
  mounts = eventsOfType("mount_learned")
  check(#mounts == 2 and not mounts[2].data.first, "second mount is no first")

  -- Hearthstone bound: once per new place.
  MOCK.bind = "Razor Hill"
  MOCK.fire("HEARTHSTONE_BOUND")
  MOCK.fire("HEARTHSTONE_BOUND")
  local homes = eventsOfType("hearth_set")
  check(#homes == 1 and FC:DescribeEvent(homes[1]) == "Ruhestein gebunden: Razor Hill", "hearthstone bound once")

  -- Group: one stretch per group, its end moved on.
  MOCK.group = { { name = "Gigel", realm = "", class = "MAGE", guid = "Player-4619-0AAAAAAA" } }
  MOCK.fire("GROUP_ROSTER_UPDATE")
  MOCK.advance(3)
  MOCK.group[2] = { name = "Thrall", realm = "Other Realm", class = "SHAMAN", guid = "Player-1-0BBBBBBB" }
  MOCK.fire("GROUP_ROSTER_UPDATE")
  MOCK.advance(65)
  local group = char.streams.group.records
  check(#group == 2, "two stretches (" .. #group .. ")")
  local Group = FC:GetModule("Group")
  local first, second = Group.Parse(group[1]), Group.Parse(group[2])
  check(#first.members == 1 and first.members[1].name == "Gigel" and first.members[1].class == "MAGE"
    and first.untilTime > first.time, "first stretch: Gigel")
  check(#second.members == 2 and second.untilTime > second.time, "second stretch moved on")
  check(group[2]:find("Thrall-Other Realm/SHAMAN/", 1, true), "other realm in the name")
  MOCK.group = {}
  MOCK.fire("GROUP_ROSTER_UPDATE")
  MOCK.advance(3)
  check(#char.streams.group.records == 2, "leaving the group closes the stretch")

  -- Loot: the first look takes what is carried as known (the cloth stays out).
  local function loot() return eventsOfType("item_obtained") end
  local function give(slot, id, quality, name, extra)
    MOCK.bags[0][slot] = { itemID = id, count = 1, quality = quality, icon = 130000 + id,
      link = "|cff0070dd|Hitem:" .. id .. "::|h[" .. name .. "]|h|r" }
    MOCK.items[id] = extra or { equipLoc = "INVTYPE_CHEST", classID = 4, maxStack = 1 }
    MOCK.fire("BAG_UPDATE_DELAYED")
  end
  check(#loot() == 0, "nothing recorded at the first look")
  give(2, 1000, 1, "Plain Shirt")                                   -- white gear: trash
  give(4, 1002, 3, "Blue Stack", { classID = 7, maxStack = 20 })    -- rare reagent: stacks
  give(11, 1008, 3, "Blue Recipe", { classID = 9, maxStack = 1 })   -- blue, but no gear
  MOCK.fire("LOOT_OPENED")
  give(5, 1003, 3, "Blue Vendor Sword")                             -- blue gear nobody wears: sold
  MOCK.fire("LOOT_CLOSED")
  check(#loot() == 0, "trash stays out")
  -- Blue gear from a boss counts, green never; the same item again does not.
  FC:GetModule("Dungeons").lastKill = { id = 1, name = "Bazzalan", time = time() }
  MOCK.fire("LOOT_OPENED")
  give(3, 1001, 2, "Green Boss Boots")
  give(6, 1004, 3, "Boss Gloves")
  MOCK.fire("LOOT_CLOSED")
  check(#loot() == 1 and loot()[1].data.source == "boss" and loot()[1].data.from == "Bazzalan"
    and loot()[1].data.name == "Boss Gloves", "blue from a boss, green from a boss stays out")
  FC:GetModule("Dungeons").lastKill = nil
  MOCK.bags[0][6] = nil; MOCK.fire("BAG_UPDATE_DELAYED")
  give(7, 1004, 3, "Boss Gloves")
  check(#loot() == 1, "an item seen before stays out")
  -- Blue gear put on within the hour mattered; green gear put on does not.
  give(8, 1005, 3, "Quest Belt")
  give(12, 1009, 2, "Green Bracers")
  MOCK.advance(600)
  MOCK.bags[0][8], MOCK.bags[0][12] = nil, nil
  MOCK.equippedIDs = { [6] = 1005, [9] = 1009 }
  MOCK.fire("BAG_UPDATE_DELAYED")
  MOCK.fire("PLAYER_EQUIPMENT_CHANGED", 6, true)
  MOCK.fire("PLAYER_EQUIPMENT_CHANGED", 9, true)
  check(#loot() == 2 and loot()[2].data.equipped and FC:DescribeEvent(loot()[2]):find("^Neue Ausrüstung"), "worn blue")
  -- The bank: taking things out is no loot.
  MOCK.fire("BANKFRAME_OPENED")
  give(9, 1006, 4, "Epic From The Bank")
  MOCK.fire("BANKFRAME_CLOSED")
  MOCK.advance(5)
  check(#loot() == 2, "bank withdrawals stay out")
  -- The first epic: a milestone with its own screenshot.
  MOCK.advance(40)
  shots = #MOCK.screenshots
  MOCK.fire("QUEST_TURNED_IN", 3513, 100, 0)
  give(10, 1007, 4, "Epic Reward")
  MOCK.advance(8)
  check(#loot() == 3 and loot()[3].data.first and loot()[3].data.source == "quest", "first epic from a quest")
  check(#MOCK.screenshots == shots + 1, "epic loot screenshot")

  -- Moments: with text from the command, at once; without text the window asks (no popup in the mock).
  MOCK.advance(40)
  shots = #MOCK.screenshots
  local momentAt = MOCK.now
  SlashCmdList.FOREVERCHRONICLE("moment Gigel tanzt auf dem Tisch")
  MOCK.advance(2)
  local moments = eventsOfType("moment")
  check(#moments == 1 and moments[1].data.text == "Gigel tanzt auf dem Tisch", "moment with its text (case kept)")
  check(#MOCK.screenshots == shots + 1 and MOCK.screenshots[#MOCK.screenshots] - momentAt < 1, "moment shot at once")
  local shotRecords = char.streams.screenshots.records
  check(shotRecords[#shotRecords].trigger == "moment" and shotRecords[#shotRecords].events[1] == moments[1].id,
    "the screenshot belongs to the moment")
  ForeverChronicle_CaptureMoment()
  MOCK.advance(3)
  moments = eventsOfType("moment")
  check(#moments == 2 and moments[2].data.text == nil and FC:DescribeEvent(moments[2]) == "Moment festgehalten",
    "keybinding: a moment without text")
  FC:GetModule("Moments"):SetText(moments[2], "  Sonnenuntergang\n ")
  check(moments[2].data.text == "Sonnenuntergang", "text added afterwards")

  MOCK.fire("PLAYER_LOGOUT")
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 17 then
  print("phase 17: kills with experience, level-up snapshot")
  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters[ME]
  local Util = FC.Util

  -- The matcher follows the client's format strings, numbered arguments in any order included.
  local name, xp = Util.FormatMatcher("%1$s stirbt, Ihr bekommt %2$d Erfahrung.")("Hogger stirbt, Ihr bekommt 120 Erfahrung.")
  check(name == "Hogger" and xp == 120, "German format string")
  name, xp = Util.FormatMatcher("Ihr bekommt %2$d Erfahrung von %1$s.")("Ihr bekommt 75 Erfahrung von Kobold.")
  check(name == "Kobold" and xp == 75, "arguments in another order come back in argument order")
  check(Util.FormatMatcher("%d%% done")("50% done") == 50 and Util.FormatMatcher(nil)("x") == nil, "%% and no format")

  local function kills()
    local out = {}
    for _, text in ipairs(S(char.streams.kills).records) do out[#out + 1] = FC:GetModule("Kills").Parse(text) end
    return out
  end
  MOCK.fire("CHAT_MSG_COMBAT_XP_GAIN", "Hogger dies, you gain 120 experience.")
  MOCK.advance(3)
  MOCK.fire("CHAT_MSG_COMBAT_XP_GAIN", "Mottled Boar dies, you gain 90 experience. (+45 exp Rested bonus)")
  MOCK.fire("CHAT_MSG_COMBAT_XP_GAIN", "Kobold Vermin dies, you gain 60 experience. (+30 exp Rested bonus, +6 group bonus)")
  MOCK.fire("CHAT_MSG_COMBAT_XP_GAIN", "Gamon, the Drunk dies, you gain 12 experience.")
  MOCK.fire("CHAT_MSG_COMBAT_XP_GAIN", "You gain 500 experience.") -- quest or exploration: no kill
  MOCK.fire("CHAT_MSG_COMBAT_XP_GAIN", MOCK.SECRET)
  local k = kills()
  check(#k == 4, "four kills recorded")
  check(k[1].name == "Hogger" and k[1].xp == 120 and k[1].rested == nil and k[1].time == time() - 3, "kill: time, xp, name")
  check(k[2].xp == 90 and k[2].rested == 45 and k[3].rested == 30, "rested bonus, also with a group bonus")
  check(k[4].name == "Gamon, the Drunk", "a name with a comma")
  check(char.stats.kill_xp == 282 and char.stats.rested_xp == 75, "kill and rested XP totals")

  MOCK.fire("QUEST_TURNED_IN", 3513, 450, 1500)
  check(char.stats.quest_xp == 450 and char.stats.quest_money == 1500, "quest XP and money totals")

  -- The level-up keeps a snapshot, with the time played on the finished level once the server told it.
  MOCK.advance(15) -- past the automatic /played after login
  MOCK.fire("TIME_PLAYED_MSG", 36000, 2000)
  MOCK.advance(100)
  MOCK.level = 23
  MOCK.fire("PLAYER_LEVEL_UP", 23)
  local ups = eventsOfType("level_up")
  local d = ups[#ups].data
  check(d.level == 23 and d.money == 123456 and d.stats.kill_xp == 282 and d.stats.quests_completed >= 1,
    "level-up snapshot: statistics and gold")
  check(d.gear[1] == "item:4385::::::::22:::::" and d.gear[16] == "item:2099::::::::22:::::", "level-up snapshot: gear")
  check(d.playedTotal == 36100 and d.levelPlayed == 2100, "level-up snapshot: time played")
  check(FC:DescribeEvent(ups[#ups]) == "Stufe 23 erreicht", "level-up text unchanged")

  -- Packed for the saved file and read back the same.
  MOCK.fire("PLAYER_LOGOUT")
  check(type(char.streams.kills.packed) == "table" and char.streams.kills.packed.kind == "lines", "kills packed as lines")
  check(#kills() == 4 and kills()[4].name == "Gamon, the Drunk", "kills read back after packing")
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

if PHASE == 18 then
  print("phase 18: PvP kills, killers, duels, battlegrounds")
  -- The client's PvP events, strings and functions (not in the shared mock).
  local PVP_EVENTS = { CHAT_MSG_SYSTEM = true, CHAT_MSG_COMBAT_HONOR_GAIN = true, PVP_MATCH_COMPLETE = true,
    UPDATE_BATTLEFIELD_SCORE = true, PLAYER_LEAVING_WORLD = true }
  local isValid = C_EventUtils.IsEventValid
  C_EventUtils.IsEventValid = function(e) return PVP_EVENTS[e] or isValid(e) end
  MOCK.allEventsValid = true
  COMBATLOG_HONORGAIN = "%s dies, honorable kill Rank: %s (%d Honor Points)"
  COMBATLOG_HONORGAIN_NO_RANK = "%s dies, honorable kill (%d Honor Points)"
  DUEL_WINNER_KNOCKOUT = "%1$s has defeated %2$s in a duel"
  DUEL_WINNER_RETREAT = "%2$s has fled from %1$s in a duel"
  local ROGUE, MAGE, DEAD = "Player-4619-0BADF00D", "Player-4619-0C0FFEE0", "Player-4619-0DEAD000"
  local PET = "Pet-0-4619-1-1-1-0000PET"
  local infos = {
    [ROGUE] = { "Rogue", "ROGUE", "Human", "Human", 2, "Gankzor", "" },
    [MAGE] = { "Mage", "MAGE", "Gnome", "Gnome", 3, "Frosty", "OtherRealm" },
    [DEAD] = { "Priest", "PRIEST", "Dwarf", "Dwarf", 2, "Deadguy", "" },
  }
  function GetPlayerInfoByGUID(guid) local p = infos[guid]; if p then return unpack(p) end end
  local isPlayer, level, class, isInInstance, position = UnitIsPlayer, UnitLevel, UnitClass, IsInInstance, UnitPosition
  local function enemy(u) return u == "nameplate1" or (u == "target" and MOCK.units.target ~= nil) end
  function UnitIsPlayer(u) return enemy(u) or isPlayer(u) end
  function UnitIsEnemy(_, u) return enemy(u) end
  function UnitLevel(u) if u == "nameplate1" then return 31 end return level(u) end
  function UnitClass(u) if u == "nameplate1" then return "Rogue", "ROGUE", 4 end return class(u) end
  function UnitRace(u) if u == "nameplate1" then return "Human", "Human", 1 end return "Tauren", "Tauren", 6 end
  function UnitFactionGroup(u) if enemy(u) then return "Alliance", "Alliance" end return "Horde", "Horde" end
  function GetGuildInfo(u) if u == "nameplate1" then return "Deathwatch", "Member", 5 end end
  function IsInInstance() if MOCK.pvp then return true, MOCK.pvp end return isInInstance() end
  function UnitPosition(u) if MOCK.pvp then return 1000, 1000, 0, 489 end return position(u) end
  C_PvP = { GetScoreInfoByPlayerGuid = function(guid)
    if guid == ME then return { killingBlows = 4, honorableKills = 11, deaths = 2, honorGained = 250, faction = 0 } end
  end }
  function GetBattlefieldWinner() return nil end

  local FC = startClient(true, false)
  local char = ForeverChronicleDB.characters[ME]
  local function kills() return eventsOfType("pvp_kill") end

  -- Open world: the player's own killing blow on a rogue seen as a nameplate; the honor message adds its rank.
  MOCK.units.nameplate1 = { guid = ROGUE, name = "Gankzor" }
  MOCK.fire("NAME_PLATE_UNIT_ADDED", "nameplate1")
  MOCK.fire("PARTY_KILL", ME, ROGUE)
  MOCK.advance(1)
  MOCK.fire("CHAT_MSG_COMBAT_HONOR_GAIN", "Gankzor dies, honorable kill Rank: Private (12 Honor Points)")
  local k = kills()
  check(#k == 1, "one PvP kill for the kill and its honor message")
  local d = k[1].data
  check(d.name == "Gankzor" and d.class == "ROGUE" and d.race == "Human" and d.level == 31 and d.guild == "Deathwatch"
    and d.faction == "Alliance", "victim: name, class, race, level, guild, faction")
  check(d.blow == "self" and d.rank == "Private" and d.honor == 12, "own killing blow, honor rank")
  check(FC:DescribeEvent(k[1]) == "Gankzor besiegt", "kill text")
  local lines = FC:EventDetails(k[1])
  check(lines and lines[1] == "Stufe 31 Human Rogue <Deathwatch>", "kill tooltip: who it was")

  -- The honor message first, PARTY_KILL after it: the pet's killing blow fills in the same kill.
  MOCK.advance(20)
  MOCK.units.pet = { guid = PET }
  MOCK.fire("CHAT_MSG_COMBAT_HONOR_GAIN", "Frosty dies, honorable kill (8 Honor Points)")
  MOCK.fire("PARTY_KILL", PET, MAGE)
  k = kills()
  check(#k == 2 and k[2].data.name == "Frosty" and k[2].data.honor == 8 and k[2].data.rank == nil, "honor message alone")
  check(k[2].data.blow == "pet" and k[2].data.class == "MAGE" and k[2].data.realm == "OtherRealm", "pet's blow merged in")

  -- Creatures are no PvP kills; hidden GUIDs fall back to the dead player in the target frame.
  MOCK.fire("PARTY_KILL", ME, "Creature-0-4619-1-1-3100-0000ABCD")
  MOCK.fire("PARTY_KILL", MOCK.SECRET, MOCK.SECRET)
  check(#kills() == 2, "no kill without a player victim")
  MOCK.units.target = { guid = DEAD, name = "Deadguy", dead = true }
  MOCK.fire("PARTY_KILL", MOCK.SECRET, MOCK.SECRET)
  MOCK.units.target = nil
  k = kills()
  check(#k == 3 and k[3].data.name == "Deadguy" and k[3].data.blow == nil and k[3].data.class == "PRIEST",
    "secret GUIDs: the dead player target")
  check(char.stats.pvp_kills == 3 and char.stats.pvp_killing_blows == 1, "PvP kill statistics")

  -- Killed by the rogue: the death names who it was.
  MOCK.advance(30)
  MOCK.deathRecap = { { timestamp = time() - 0.1, event = "SPELL_DAMAGE", sourceName = "Gankzor", sourceGUID = ROGUE,
    spellName = "Eviscerate", spellId = 2098, amount = 300 } }
  MOCK.fire("PLAYER_DEAD")
  local deaths = eventsOfType("player_died")
  local death = deaths[#deaths].data
  check(death.killer == "Gankzor" and death.killerType == "player" and death.killerClass == "ROGUE"
    and death.killerLevel == 31 and death.killerGuild == "Deathwatch" and death.battleground == nil, "killed by a player")
  lines = FC:EventDetails(deaths[#deaths])
  local found = false
  for _, l in ipairs(lines or {}) do if l == "Stufe 31 Human Rogue <Deathwatch>" then found = true end end
  check(found, "death tooltip names the killer")
  check(char.stats.pvp_deaths == 1, "PvP death statistic")
  MOCK.fire("PLAYER_ALIVE") -- came back before releasing (not a ghost)

  -- Duels: only the player's own, won, fled from and lost.
  MOCK.fire("CHAT_MSG_SYSTEM", "Blind has defeated Frosty in a duel")
  MOCK.fire("CHAT_MSG_SYSTEM", "Gankzor has fled from Blind in a duel")
  MOCK.fire("CHAT_MSG_SYSTEM", "Thrall has defeated Garrosh in a duel")
  MOCK.fire("CHAT_MSG_SYSTEM", "Gankzor has defeated Blind in a duel")
  MOCK.fire("CHAT_MSG_SYSTEM", "You have learned a new ability.")
  local duels = eventsOfType("duel")
  check(#duels == 3, "three duels of the player")
  check(duels[1].data.won and duels[1].data.name == "Frosty" and not duels[1].data.fled, "duel won")
  check(duels[2].data.won and duels[2].data.fled and duels[2].data.class == "ROGUE", "duel won, the opponent fled")
  check(duels[3].data.won == false and FC:DescribeEvent(duels[3]) == "Duell gegen Gankzor verloren", "duel lost")
  check(char.stats.duels_won == 2 and char.stats.duels_lost == 1, "duel statistics")

  -- A battleground with a friend: strangers of the battleground raid are no companions.
  MOCK.group = { { name = "Gigel", class = "WARRIOR", guid = "Player-4619-0F00F001" } }
  MOCK.fire("GROUP_ROSTER_UPDATE")
  MOCK.advance(3)
  local function lastStretch()
    local g = S(char.streams.group).records
    return FC:GetModule("Group").Parse(g[#g])
  end
  check(#lastStretch().members == 1, "grouped with the friend")
  local stretches = #S(char.streams.group).records
  MOCK.pvp, MOCK.zone, MOCK.mapID = "pvp", "Warsong Gulch", 1460
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  check(char.pvpMatch and char.pvpMatch.kind == "pvp" and char.pvpMatch.instanceID == 489
    and char.pvpMatch.name == "Warsong Gulch", "match started")
  table.insert(MOCK.group, { name = "Stranger", class = "MAGE", guid = "Player-4619-0F00F002" })
  table.insert(MOCK.group, { name = "Other", class = "PRIEST", guid = "Player-4619-0F00F003" })
  MOCK.fire("GROUP_ROSTER_UPDATE")
  MOCK.advance(3)
  check(#S(char.streams.group).records == stretches and #lastStretch().members == 1, "battleground raid: only the friend")

  -- Dying inside: marked as a battleground death, and the spirit guide brings the player back.
  MOCK.deathRecap = { { timestamp = time() - 0.1, sourceName = "Frosty", sourceGUID = MAGE, spellName = "Frostbolt", amount = 500 } }
  MOCK.fire("PLAYER_DEAD")
  deaths = eventsOfType("player_died")
  death = deaths[#deaths].data
  check(death.battleground == "pvp" and death.killerType == "player" and death.killerClass == "MAGE", "battleground death")
  MOCK.ghost = true
  MOCK.fire("PLAYER_ALIVE")
  MOCK.advance(25)
  MOCK.ghost = false
  MOCK.fire("PLAYER_UNGHOST")
  check(death.revive == "spirit_healer", "revived by the spirit guide")
  check(char.stats.pvp_deaths == 1 and char.stats.pvp_deaths_matches == 1, "match deaths counted apart")
  MOCK.fire("PARTY_KILL", ME, ROGUE)
  check(#kills() == 3, "kills inside a match are left to the score board")

  MOCK.advance(600)
  MOCK.fire("PVP_MATCH_COMPLETE", 0, 900)
  local bgs = eventsOfType("battleground")
  check(#bgs == 1, "match recorded at its end")
  local bg = bgs[1].data
  check(bg.result == "won" and bg.killingBlows == 4 and bg.honorableKills == 11 and bg.deaths == 2 and bg.honor == 250
    and bg.duration == 900 and bg.mapID == 1460 and bg.faction == "Horde", "match: result and score")
  check(FC:DescribeEvent(bgs[1]) == "Sieg in Warsong Gulch", "match text")
  local Shots = FC:GetModule("Screenshots")
  check(Shots:IsTriggerEnabled("pvp") and Shots:IsTriggerEnabled("battleground"), "PvP screenshots on by default")
  check(Shots.triggers.battleground.filter(bgs[1]) and not Shots.triggers.battleground.filter({ data = { result = "lost" } }),
    "screenshot for a won match only")
  check(not Shots.triggers.death.filter(deaths[#deaths]), "no death screenshots inside a match")
  MOCK.fire("PLAYER_LEAVING_WORLD")
  MOCK.pvp, MOCK.zone, MOCK.mapID = nil, nil, nil
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  check(char.pvpMatch == nil and #eventsOfType("battleground") == 1, "leaving after the end adds nothing")
  check(char.stats.battlegrounds == 1 and char.stats.battlegrounds_won == 1, "battleground statistics")

  -- A match left before its end, through a /reload in between: recorded where it was left.
  MOCK.pvp, MOCK.zone, MOCK.mapID = "pvp", "Warsong Gulch", 1460
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  MOCK.advance(120)
  MOCK.fire("UPDATE_BATTLEFIELD_SCORE")
  MOCK.fire("PLAYER_LEAVING_WORLD")
  MOCK.pvp, MOCK.zone, MOCK.mapID = nil, nil, nil
  MOCK.advance(5)
  MOCK.fire("PLAYER_ENTERING_WORLD", false, false)
  bgs = eventsOfType("battleground")
  check(#bgs == 2 and bgs[2].data.result == "left" and bgs[2].location.zone == "Warsong Gulch"
    and bgs[2].data.duration == 120 and bgs[2].data.killingBlows == 4, "match left early")
  check(char.stats.battlegrounds == 2 and char.stats.battlegrounds_won == 1, "a left match is no win")

  -- What the samples say, for checking the sources in Forever.
  local pvp = ForeverChronicleDB.diagnostics.pvp
  check(pvp.counts.party_kill >= 5 and pvp.counts.honor_message == 2 and pvp.counts.match_entered == 2
    and #pvp.samples <= 40, "signal counts and samples kept")
  for _, key in ipairs({ "pvp_kills", "pvp_deaths", "duels", "battlegrounds" }) do
    check(ForeverChronicleDB.diagnostics.capabilities[key].status == "confirmed", "capability confirmed: " .. key)
  end
  MOCK.fire("PLAYER_LOGOUT")
  local errors = 0
  for _, l in ipairs(ForeverChronicleDB.diagnostics.log) do if l:find("%[error%]") then errors = errors + 1; print("    " .. l) end end
  check(errors == 0, "no errors logged")
end

print("PHASE " .. PHASE .. " PASSED")
