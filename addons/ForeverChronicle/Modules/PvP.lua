-- Journey Forever - PvP module
-- Fights with other players, for the chronicle and the cinematic replay. The open world gets one event per fight;
-- a battleground or arena match is one event with its totals.
--   pvp_kill      an enemy player died by the player's or the group's hand (outside matches)
--                 { name, realm, guid, class, className, race, raceName, level, guild, faction,
--                   blow = "self" | "pet" (the player's pet) | "group" (by = who) | nil (unknown, e.g. an assist),
--                   rank, honor (from the honor message, when the client sends one) }
--   duel          a duel the player fought to its end { name, class, ..., won, fled (the loser ran away) }
--   battleground  one battleground or arena match, recorded when it ends or the player leaves it
--                 { kind = "pvp" | "arena", name, mapID, instanceID, startedAt, duration,
--                   result = "won" | "lost" | "left" | nil, killingBlows, honorableKills, deaths, honor, damage, healing }
-- Deaths (player_died, Modules/Progress.lua): a player's killing blow adds killerType = "player" (or "pet"),
-- killerGUID, killerClass, killerClassName, killerRace, killerRaceName, killerLevel, killerGuild, killerFaction,
-- killerRealm; a death inside a match gets battleground = "pvp" | "arena" (the replay can treat those lightly).
-- Inside a match the battleground's spirit guide brings the player back (revive = "spirit_healer").
--
-- Sources (Forever blocks the combat log for addons): PARTY_KILL (attacker and victim GUIDs), the honor message
-- (CHAT_MSG_COMBAT_HONOR_GAIN, names the victim), the death recap's killing blow, the system message at a duel's
-- end and the match's score board. Players seen as target, mouseover or nameplate are remembered for their level
-- and guild. None of these was seen in Forever yet (2026-11-04): each signal's first sightings are kept as short
-- samples in FC.db.diagnostics.pvp (counts and up to 40 lines) to check them.

local ADDON, FC = ...
local Util = FC.Util
local L = FC.L

local PvP = FC:NewModule("PvP", { order = 33 })

local SAME_KILL = 10          -- seconds in which PARTY_KILL and the honor message tell of the same kill
local RECAP_RETRIES = { 0.6, 1.6, 3.2 }
local MAX_SEEN = 200          -- players remembered
local MAX_SAMPLES = 40        -- sample lines kept in FC.db.diagnostics.pvp
local SAMPLES_PER_SIGNAL = 3
local SCORE_EVERY = 30        -- seconds between score board reads during a match
local MATCH_STALE = 3 * 3600  -- a saved match older than this is closed
local TEAM = { Horde = 0, Alliance = 1 }
local BANNER = { Horde = "Interface\\Icons\\INV_BannerPVP_01", Alliance = "Interface\\Icons\\INV_BannerPVP_02" }

-------------------------------------------------------------------------------
-- Registrations
-------------------------------------------------------------------------------

FC:RegisterCapability("pvp_kills", "CAP_PVP_KILLS", function()
  return FC.eventStatus.PARTY_KILL == "registered" or FC.eventStatus.CHAT_MSG_COMBAT_HONOR_GAIN == "registered"
end)
FC:RegisterCapability("pvp_deaths", "CAP_PVP_DEATHS", function()
  return FC.eventStatus.PLAYER_DEAD == "registered" and type(C_DeathRecap) == "table"
    and type(C_DeathRecap.GetRecapEvents) == "function"
end)
FC:RegisterCapability("duels", "CAP_DUELS", function()
  return FC.eventStatus.CHAT_MSG_SYSTEM == "registered" and type(DUEL_WINNER_KNOCKOUT) == "string"
end)
FC:RegisterCapability("battlegrounds", "CAP_BATTLEGROUNDS", function()
  return type(IsInInstance) == "function" and (FC.eventStatus.PVP_MATCH_COMPLETE == "registered"
    or FC.eventStatus.UPDATE_BATTLEFIELD_SCORE == "registered")
end)

FC:RegisterEventCategory("pvp", { labelKey = "CAT_PVP", icon = "Interface\\Icons\\Ability_DualWield", order = 65 })

-- "Level 34 Undead Rogue <Guild>" from a player's fields (prefix "killer" for a death's killer).
local function playerLine(d, prefix)
  local function f(key) return d[prefix and (prefix .. key:sub(1, 1):upper() .. key:sub(2)) or key] end
  local parts = {}
  local level = f("level")
  if type(level) == "number" then parts[#parts + 1] = string.format(L.PVP_LEVEL, level > 0 and level or "??") end
  parts[#parts + 1] = f("raceName") or f("race")
  parts[#parts + 1] = f("className") or f("class")
  if f("guild") then parts[#parts + 1] = "<" .. f("guild") .. ">" end
  return #parts > 0 and table.concat(parts, " ") or nil
end
PvP.PlayerLine = playerLine

FC:RegisterEventType("pvp_kill", {
  icon = "Interface\\Icons\\Ability_DualWield", category = "pvp", highlight = "milestone",
  format = function(r) return string.format(L.EVT_PVP_KILL, r.data.name or "?") end,
  details = function(r)
    local d, lines = r.data, {}
    lines[#lines + 1] = playerLine(d)
    if d.blow == "group" and d.by then lines[#lines + 1] = string.format(L.PVP_BLOW_BY, d.by)
    elseif d.blow == "pet" then lines[#lines + 1] = L.PVP_BLOW_PET end
    if d.honor then
      lines[#lines + 1] = d.rank and string.format(L.PVP_HONOR_RANK, d.rank, d.honor) or string.format(L.PVP_HONOR, d.honor)
    end
    return #lines > 0 and lines or nil
  end,
})
FC:RegisterEventType("duel", {
  icon = "Interface\\Icons\\Ability_Warrior_Challange", category = "pvp",
  format = function(r)
    local d = r.data
    local key = d.won and (d.fled and "EVT_DUEL_WON_FLED" or "EVT_DUEL_WON") or (d.fled and "EVT_DUEL_FLED" or "EVT_DUEL_LOST")
    return string.format(L[key], d.name or "?")
  end,
  details = function(r) local line = playerLine(r.data); return line and { line } or nil end,
})
FC:RegisterEventType("battleground", {
  icon = "Interface\\Icons\\INV_BannerPVP_01", category = "pvp", highlight = "milestone",
  getIcon = function(r) return BANNER[r.data.faction] end,
  format = function(r)
    local d = r.data
    local key = ({ won = "EVT_BG_WON", lost = "EVT_BG_LOST", left = "EVT_BG_LEFT" })[d.result] or "EVT_BG_PLAYED"
    return string.format(L[key], d.name or "?")
  end,
  details = function(r)
    local d, lines = r.data, {}
    if d.killingBlows or d.honorableKills or d.deaths then
      lines[#lines + 1] = string.format(L.BG_SCORE, d.killingBlows or "?", d.honorableKills or "?", d.deaths or "?")
    end
    if d.honor and d.honor > 0 then lines[#lines + 1] = string.format(L.BG_HONOR, d.honor) end
    return #lines > 0 and lines or nil
  end,
})

-- Statistics are kept as data (the level-up snapshot copies them); none is shown yet:
--   pvp_kills, pvp_killing_blows, pvp_deaths (open world), pvp_deaths_matches, duels_won, duels_lost,
--   battlegrounds, battlegrounds_won, arenas, arenas_won

-------------------------------------------------------------------------------
-- Helpers
-------------------------------------------------------------------------------

local function str(v)
  v = Util.Plain(v)
  return type(v) == "string" and v ~= "" and v or nil
end

local function num(v)
  v = Util.Plain(v)
  return type(v) == "number" and v or nil
end

-- "Name-Realm" -> "Name"
local function baseName(name)
  return type(name) == "string" and (name:match("^([^%-]+)") or name) or nil
end

-- What kind of GUID a value is, for the samples: "Player", "Creature", "Pet", ..., "secret" or "none".
local function guidKind(v)
  if Util.IsSecret(v) then return "secret" end
  if type(v) ~= "string" then return "none" end
  return v:match("^(%a+)%-") or "?"
end

function PvP:MyGUID()
  return (FC.char and FC.char.info and FC.char.info.guid) or Util.SafeValue("string", UnitGUID, "player")
end

-- "pvp" (battleground) or "arena" while inside a match, else nil.
function PvP:MatchKind()
  local inside, kind = Util.SafeValues(IsInInstance)
  if inside == true and (kind == "pvp" or kind == "arena") then return kind end
  return nil
end

-- Counts each signal and keeps its first few sightings as sample lines (to check the sources in Forever).
function PvP:Note(signal, detail)
  local diag = FC.db and FC.db.diagnostics
  if not diag then return end
  diag.pvp = diag.pvp or { counts = {}, samples = {} }
  local pvp = diag.pvp
  local n = (pvp.counts[signal] or 0) + 1
  pvp.counts[signal] = n
  if n == 1 then FC.Diagnostics:Log("info", "pvp signal: " .. signal .. (detail and (" " .. detail) or "")) end
  if n <= SAMPLES_PER_SIGNAL then
    table.insert(pvp.samples, string.format("%s %s %s", date("%Y-%m-%d %H:%M:%S"), signal, detail or ""))
    while #pvp.samples > MAX_SAMPLES do table.remove(pvp.samples, 1) end
  end
end

-------------------------------------------------------------------------------
-- Players seen (GUID -> { name, realm, level, class, className, race, raceName, guild, faction })
-------------------------------------------------------------------------------

PvP.seen, PvP.seenOrder, PvP.byName = {}, {}, {}

function PvP:Remember(unit)
  if Util.SafeValue("boolean", UnitIsPlayer, unit) ~= true then return end
  local guid = Util.SafeValue("string", UnitGUID, unit)
  if not guid or not guid:find("^Player%-") or guid == self:MyGUID() then return end
  local name, realm = Util.SafeValues(UnitName, unit)
  if type(name) ~= "string" or name == "" then return end
  local entry = self.seen[guid]
  if not entry then
    entry = {}
    self.seen[guid] = entry
    table.insert(self.seenOrder, guid)
    if #self.seenOrder > MAX_SEEN then
      local old = table.remove(self.seenOrder, 1)
      local e = self.seen[old]
      self.seen[old] = nil
      if e and self.byName[e.name] == old then self.byName[e.name] = nil end
    end
  end
  entry.name, entry.realm = name, str(realm) or entry.realm
  local level = Util.SafeValue("number", UnitLevel, unit)
  if level and level ~= 0 then entry.level = level end -- -1: too high to see ("??")
  local className, classFile = Util.SafeValues(UnitClass, unit)
  entry.className, entry.class = str(className) or entry.className, str(classFile) or entry.class
  local raceName, raceFile = Util.SafeValues(UnitRace, unit)
  entry.raceName, entry.race = str(raceName) or entry.raceName, str(raceFile) or entry.race
  entry.guild = str((Util.SafeValues(GetGuildInfo, unit))) or entry.guild
  entry.faction = str((Util.SafeValues(UnitFactionGroup, unit))) or entry.faction
  self.byName[name] = guid
  if Util.SafeValue("boolean", UnitIsEnemy, "player", unit) == true and not self.enemyNoted then
    self.enemyNoted = true -- once per session: what the client tells of enemy players
    self:Note("enemy_player", string.format("level=%s class=%s race=%s guild=%s", tostring(entry.level),
      tostring(entry.class), tostring(entry.race), tostring(entry.guild)))
  end
end

PvP:RegisterEvent("PLAYER_TARGET_CHANGED", function(self) self:Remember("target") end)
PvP:RegisterEvent("UPDATE_MOUSEOVER_UNIT", function(self) self:Remember("mouseover") end)
PvP:RegisterEvent("NAME_PLATE_UNIT_ADDED", function(self, _, unit)
  unit = Util.Plain(unit)
  if type(unit) == "string" then self:Remember(unit) end
end)

-- Everything known of a player: the client's own record of the GUID, then what was seen of them.
function PvP:Describe(guid)
  local seen = self.seen[guid] or {}
  local className, classFile, raceName, raceFile, _, name, realm = Util.SafeValues(GetPlayerInfoByGUID, guid)
  return {
    guid = guid, name = str(name) or seen.name, realm = str(realm) or seen.realm,
    class = str(classFile) or seen.class, className = str(className) or seen.className,
    race = str(raceFile) or seen.race, raceName = str(raceName) or seen.raceName,
    level = seen.level, guild = seen.guild, faction = seen.faction,
  }
end

-------------------------------------------------------------------------------
-- Kills (open world)
-------------------------------------------------------------------------------

PvP.recent = {} -- base name -> { record, at }: the kill PARTY_KILL and the honor message both report

function PvP:RecentKill(name)
  local r = name and self.recent[baseName(name)]
  if r and time() - r.at <= SAME_KILL then return r.record end
  return nil
end

function PvP:Kill(victim, blow, by)
  if not victim.name then return nil end
  local record = self:RecentKill(victim.name)
  if record then -- the second report of the same kill fills in what the first lacked
    for k, v in pairs(victim) do if record.data[k] == nil then record.data[k] = v end end
    if blow and not record.data.blow then
      record.data.blow, record.data.by = blow, by
      if blow == "self" then FC:IncrementStat("pvp_killing_blows") end
    end
    FC:SendMessage("FC_EVENT_UPDATED", record)
    return record
  end
  victim.blow, victim.by = blow, by
  record = FC:Record("pvp_kill", victim)
  if not record then return nil end
  self.recent[baseName(victim.name)] = { record = record, at = time() }
  FC:IncrementStat("pvp_kills")
  if blow == "self" then FC:IncrementStat("pvp_killing_blows") end
  FC:ConfirmCapability("pvp_kills")
  return record
end

-- GUIDs hidden by the client: the dead enemy player in the target frame.
function PvP:DeadPlayerTarget()
  if Util.SafeValue("boolean", UnitIsDead, "target") ~= true then return nil end
  if Util.SafeValue("boolean", UnitIsPlayer, "target") ~= true then return nil end
  self:Remember("target")
  local guid = Util.SafeValue("string", UnitGUID, "target")
  return guid and guid:find("^Player%-") and guid or nil
end

PvP:RegisterEvent("PARTY_KILL", function(self, _, attackerGUID, targetGUID)
  local attacker, target = Util.Plain(attackerGUID), Util.Plain(targetGUID)
  self:Note("party_kill", "attacker=" .. guidKind(attackerGUID) .. " target=" .. guidKind(targetGUID))
  if type(target) ~= "string" then
    target = self:DeadPlayerTarget()
    if not target then return end
  elseif not target:find("^Player%-") then
    return
  end
  local match = self:MatchKind()
  self:Note("party_kill_player", "attacker=" .. guidKind(attackerGUID) .. " match=" .. tostring(match))
  if match then return end -- inside a match the score board counts
  local blow, by
  if type(attacker) == "string" then
    if attacker == self:MyGUID() then
      blow = "self"
    elseif attacker == Util.SafeValue("string", UnitGUID, "pet") then
      blow = "pet"
    else
      blow = "group"
      by = attacker:find("^Player%-") and self:Describe(attacker).name or nil
    end
  end
  self:Kill(self:Describe(target), blow, by)
end)

-- The honor message: "Name dies, honorable kill Rank: Scout (12 Honor Points)" (formats from the client).
local matchRank, matchNoRank, matchKnockout, matchRetreat

function PvP:OnInitialize()
  matchRank = Util.FormatMatcher(COMBATLOG_HONORGAIN)
  matchNoRank = Util.FormatMatcher(COMBATLOG_HONORGAIN_NO_RANK)
  matchKnockout = Util.FormatMatcher(DUEL_WINNER_KNOCKOUT)  -- "%1$s has defeated %2$s in a duel"
  matchRetreat = Util.FormatMatcher(DUEL_WINNER_RETREAT)    -- "%2$s has fled from %1$s in a duel"
end

PvP:RegisterEvent("CHAT_MSG_COMBAT_HONOR_GAIN", function(self, _, msg)
  msg = Util.Plain(msg)
  self:Note("honor_message", type(msg) == "string" and msg:sub(1, 160) or "secret")
  if type(msg) ~= "string" then return end
  local name, rank, honor = matchRank(msg)
  if type(name) ~= "string" then
    name, honor = matchNoRank(msg)
    rank = nil
  end
  if type(name) ~= "string" or name == "" or self:MatchKind() then return end -- "You have been awarded ...": no kill
  local record = self:RecentKill(name)
  if not record then
    local guid = self.byName[baseName(name)]
    record = self:Kill(guid and self:Describe(guid) or { name = name }, nil, nil)
  end
  if record then
    record.data.rank = str(rank) or record.data.rank
    record.data.honor = tonumber(honor) or record.data.honor
  end
end)

-------------------------------------------------------------------------------
-- Deaths by a player's hand
-------------------------------------------------------------------------------

function PvP:NewestDeath()
  local records = FC.Storage:GetStream("events").records
  for i = #records, math.max(1, #records - 50), -1 do
    local r = records[i]
    if type(r) == "table" and r.type == "player_died" then return r end
  end
  return nil
end

-- The killing blow of the newest death recap (the same entry Modules/Progress.lua reads), or nil.
function PvP:RecapBlow()
  local api = C_DeathRecap
  if not (api and type(api.GetRecapEvents) == "function") then return nil end
  local ok, events = pcall(api.GetRecapEvents)
  events = ok and Util.Plain(events)
  if type(events) ~= "table" then return nil end
  local blow, newest
  for _, e in ipairs(events) do
    if type(Util.Plain(e)) == "table" then
      local ts = num(e.timestamp)
      if not blow or (ts and (not newest or ts > newest)) then blow, newest = e, ts end
    end
  end
  if not blow then return nil end
  if newest and newest > 1e9 and math.abs(time() - newest) > 60 then return nil end -- an earlier death's
  if newest and newest == self.lastRecap then return nil end
  return blow, newest
end

function PvP:ReadKiller(death, attempt)
  local blow, stamp = self:RecapBlow()
  if not blow then
    local delay = RECAP_RETRIES[attempt]
    if delay then
      FC:After(delay, function() self:ReadKiller(death, attempt + 1) end)
    else
      self:Note("death_recap", "none")
    end
    return
  end
  self.lastRecap = stamp
  local raw = blow.sourceGUID
  local d = death.data
  self:Note("death_recap", "source=" .. guidKind(raw) .. (d.battleground and (" in " .. d.battleground) or ""))
  local guid = Util.Plain(raw)
  local kind = type(guid) == "string" and guid:match("^(%a+)%-")
  if kind == "Player" then
    local who = self:Describe(guid)
    d.killerType, d.killerGUID = "player", guid
    d.killerClass, d.killerClassName, d.killerRace, d.killerRaceName = who.class, who.className, who.race, who.raceName
    d.killerLevel, d.killerGuild, d.killerFaction, d.killerRealm = who.level, who.guild, who.faction, who.realm
    d.killer = d.killer or who.name
    FC:IncrementStat(d.battleground and "pvp_deaths_matches" or "pvp_deaths")
    FC:ConfirmCapability("pvp_deaths")
    FC:SendMessage("FC_EVENT_UPDATED", death)
  elseif kind == "Pet" then
    d.killerType = "pet"
  end
end

-- Runs after Modules/Progress.lua recorded the death (its file loads first, so its handler comes first).
PvP:RegisterEvent("PLAYER_DEAD", function(self)
  local death = self:NewestDeath()
  if not death or time() - (death.time or 0) > 5 then return end
  death.data.battleground = self:MatchKind()
  self:ReadKiller(death, 1)
end)

-- Inside a match the ghost never runs to the body: the spirit guide brings everyone back (Progress says "corpse").
PvP:RegisterEvent("PLAYER_UNGHOST", function(self)
  if not self:MatchKind() then return end
  local death = self:NewestDeath()
  local d = death and death.data
  if d and d.revive == "corpse" and d.revivedAt and time() - d.revivedAt <= 2 then d.revive = "spirit_healer" end
end)

-------------------------------------------------------------------------------
-- Duels
-------------------------------------------------------------------------------

PvP:RegisterEvent("CHAT_MSG_SYSTEM", function(self, _, msg)
  msg = Util.Plain(msg)
  if type(msg) ~= "string" then return end
  local fled = false
  local winner, loser = matchKnockout(msg)
  if type(winner) ~= "string" then
    winner, loser = matchRetreat(msg)
    fled = true
  end
  if type(winner) ~= "string" or type(loser) ~= "string" then return end
  local me = Util.SafeValues(UnitName, "player")
  local won = baseName(winner) == me
  if not won and baseName(loser) ~= me then return end -- a duel of others nearby
  self:Note("duel", msg:sub(1, 160))
  local opponent = won and loser or winner
  local guid = self.byName[baseName(opponent)]
  local data = guid and self:Describe(guid) or { name = opponent }
  data.won, data.fled = won, fled or nil
  FC:Record("duel", data)
  FC:IncrementStat(won and "duels_won" or "duels_lost")
  FC:ConfirmCapability("duels")
end)

-------------------------------------------------------------------------------
-- Battlegrounds and arenas (the open match is kept in FC.char.pvpMatch, so a /reload or a disconnect keeps it)
-------------------------------------------------------------------------------

function PvP:Match()
  return FC.char and FC.char.pvpMatch
end

-- The player's line of the score board, stored in match.score.
function PvP:ReadScore(match)
  local s
  if type(C_PvP) == "table" and type(C_PvP.GetScoreInfoByPlayerGuid) == "function" then
    local info = Util.SafeValue("table", C_PvP.GetScoreInfoByPlayerGuid, self:MyGUID())
    if info then
      s = { killingBlows = num(info.killingBlows), honorableKills = num(info.honorableKills), deaths = num(info.deaths),
        honor = num(info.honorGained), damage = num(info.damageDone), healing = num(info.healingDone),
        team = num(info.faction) }
    end
  end
  if not s and type(GetNumBattlefieldScores) == "function" then -- the older score board API
    local me = Util.SafeValues(UnitName, "player")
    for i = 1, Util.SafeValue("number", GetNumBattlefieldScores) or 0 do
      local name, kb, hk, deaths, honor, team = Util.SafeValues(GetBattlefieldScore, i)
      if baseName(name) == me then
        s = { killingBlows = num(kb), honorableKills = num(hk), deaths = num(deaths), honor = num(honor), team = num(team) }
        break
      end
    end
  end
  if s then
    if not match.score then self:Note("match_score", string.format("kb=%s hk=%s deaths=%s honor=%s team=%s",
      tostring(s.killingBlows), tostring(s.honorableKills), tostring(s.deaths), tostring(s.honor), tostring(s.team))) end
    match.score = s
  end
end

function PvP:RecordMatch(match, result, opts)
  if match.recorded then return end
  match.recorded = true
  local s = match.score or {}
  local faction = Util.SafeValues(UnitFactionGroup, "player")
  local data = { kind = match.kind, name = match.name, mapID = match.mapID, instanceID = match.instanceID,
    startedAt = match.startedAt, duration = match.duration, result = result, faction = str(faction),
    killingBlows = s.killingBlows, honorableKills = s.honorableKills, deaths = s.deaths, honor = s.honor,
    damage = s.damage, healing = s.healing }
  local record = FC:Record("battleground", data, opts)
  if record and opts and opts.noLocation then record.location = match.location end
  local stat = match.kind == "arena" and "arenas" or "battlegrounds"
  FC:IncrementStat(stat)
  if result == "won" then FC:IncrementStat(stat .. "_won") end
  FC:ConfirmCapability("battlegrounds")
end

-- The match is over: won or lost against the winner the client names (team 0 = Horde, 1 = Alliance in
-- battlegrounds; in arenas the player's own team index).
function PvP:Complete(match, winner, duration)
  if match.recorded then return end
  self:ReadScore(match)
  local team = match.score and match.score.team or Util.SafeValue("number", GetBattlefieldArenaFaction)
    or TEAM[Util.SafeValues(UnitFactionGroup, "player")]
  local result
  if (winner == 0 or winner == 1) and team then result = winner == team and "won" or "lost" end
  match.duration = duration or (time() - match.startedAt)
  self:RecordMatch(match, result)
end

-- Entering or leaving: a match starts when the player is inside one, and ends when they are not any more.
function PvP:CheckMatch()
  if not FC.char then return end
  local kind, match = self:MatchKind(), self:Match()
  local instanceID = FC:CurrentInstanceID()
  if match and (not kind or match.instanceID ~= instanceID or time() - (match.seenAt or match.startedAt) > MATCH_STALE) then
    if not match.recorded then
      match.duration = (match.leftAt or match.seenAt or time()) - match.startedAt
      self:RecordMatch(match, "left", { time = match.leftAt, noLocation = match.location ~= nil })
    end
    FC.char.pvpMatch, match = nil, nil
  end
  if kind and not match then
    local mapID = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
    match = { kind = kind, instanceID = instanceID, mapID = mapID, startedAt = time(), seenAt = time(),
      name = Util.SafeValue("string", GetRealZoneText) }
    FC.char.pvpMatch = match
    self:Note("match_entered", string.format("kind=%s map=%s instance=%s groupSize=%s", kind, tostring(mapID),
      tostring(instanceID), tostring(Util.SafeValue("number", GetNumGroupMembers))))
    FC:After(20, function() -- once the match runs: is the position readable here?
      local now = C_Map and Util.SafeValue("number", C_Map.GetBestMapForUnit, "player")
      self:Note("match_position", string.format("map=%s position=%s", tostring(now), tostring(FC:PlayerMapPosition(now) ~= nil)))
    end)
  end
  if match then match.seenAt = time() end
end

PvP:RegisterEvent("PLAYER_ENTERING_WORLD", function(self) self:CheckMatch() end)
PvP:RegisterEvent("ZONE_CHANGED_NEW_AREA", function(self) self:CheckMatch() end)
-- Before the loading screen out of the match: where it was, for a match left before its end.
PvP:RegisterEvent("PLAYER_LEAVING_WORLD", function(self)
  local match = self:Match()
  if match and self:MatchKind() then
    match.location, match.leftAt = FC:GetLocation(), time()
    self:ReadScore(match)
  end
end)

PvP:RegisterEvent("PVP_MATCH_COMPLETE", function(self, _, winner, duration)
  self:Note("match_complete", string.format("winner=%s duration=%s", tostring(Util.Plain(winner)), tostring(Util.Plain(duration))))
  local match = self:Match()
  if not match then return end
  winner = num(winner) or Util.SafeValue("number", GetBattlefieldWinner)
  self:Complete(match, winner, num(duration))
end)

-- The older way: the score board names the winner once the match is over.
PvP:RegisterEvent("UPDATE_BATTLEFIELD_SCORE", function(self)
  local match = self:Match()
  if not match or match.recorded or not self:MatchKind() then return end
  self:ReadScore(match)
  local winner = Util.SafeValue("number", GetBattlefieldWinner)
  if winner then self:Complete(match, winner, nil) end
end)

function PvP:OnEnable()
  FC:NewTicker(SCORE_EVERY, function()
    local match = self:Match()
    if not match or match.recorded or not self:MatchKind() then return end
    match.seenAt = time()
    if type(RequestBattlefieldScoreData) == "function" then pcall(RequestBattlefieldScoreData) end
    self:ReadScore(match)
  end)
end
