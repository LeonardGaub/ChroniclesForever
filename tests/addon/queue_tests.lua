-- Unit tests for Modules/ScreenshotQueue.lua (pure logic, no WoW API). QUEUE is the module table.

local Queue = QUEUE
local passed = 0

local function test(name, fn)
  fn()
  passed = passed + 1
  print("  ok  " .. name)
end

local function eq(actual, expected, what)
  if actual ~= expected then error(string.format("%s: expected %s, got %s", what, tostring(expected), tostring(actual)), 2) end
end

local function req(trigger, priority, opts)
  opts = opts or {}
  return { trigger = trigger, priority = priority, eventIds = { opts.id or trigger }, identity = opts.identity,
    delay = opts.delay or 0, maxAge = opts.maxAge or 60, bypassCooldown = opts.bypass or false, zoneKey = opts.zoneKey }
end

local function new() return Queue.New({ capacity = 3, cooldown = 30, minGap = 2, coalesceWindow = 2 }) end
local OPEN = { loading = false, onTaxi = false }

test("higher priority is captured first", function()
  local q = new()
  q:Add(req("zone", 4, { zoneKey = "z" }), 0)
  q:Add(req("level", 2), 10)
  eq(q:Next(10, OPEN).trigger, "level", "first")
end)

test("equal priority keeps FIFO order", function()
  local q = Queue.New({ cooldown = 0, minGap = 0, coalesceWindow = 0 })
  q:Add(req("quest", 5, { id = "a" }), 0)
  q:Add(req("quest", 5, { id = "b" }), 1)
  eq(q:Next(5, OPEN).eventIds[1], "a", "first")
  eq(q:Next(5, OPEN).eventIds[1], "b", "second")
end)

test("events within the coalescing window share one screenshot", function()
  local q = new()
  q:Add(req("level", 2, { delay = 5 }), 0)
  local result, item = q:Add(req("achievement", 3, { delay = 5 }), 1.5)
  eq(result, "merged", "result")
  eq(#item.eventIds, 2, "linked events")
  eq(q:Count(), 1, "queue size")
  eq(item.trigger, "level", "highest priority trigger kept")
end)

test("duplicate identity is merged even outside the window", function()
  local q = new()
  q:Add(req("zone", 4, { identity = "zone:1" }), 0)
  eq((q:Add(req("zone", 4, { identity = "zone:1" }), 10)), "merged", "result")
  eq(q:Count(), 1, "queue size")
end)

test("event right after a capture is linked to that screenshot", function()
  local q = new()
  local r = req("level", 2)
  q:Add(r, 0)
  local shot = q:Next(0, OPEN)
  q:MarkCaptured(shot, 0.5)
  local result, target = q:Add(req("achievement", 3), 1)
  eq(result, "linked", "result")
  eq(target, shot, "linked to captured request")
  eq(#shot.eventIds, 2, "events")
end)

test("delay: not due before the delay has passed", function()
  local q = new()
  q:Add(req("level", 2, { delay = 5 }), 0)
  eq(q:Next(4.9, OPEN), nil, "too early")
  eq(q:Next(5, OPEN).trigger, "level", "due")
end)

test("cooldown delays normal requests but does not drop them", function()
  local q = new()
  q:Add(req("zone", 4, { zoneKey = "z" }), 0)
  q:MarkCaptured({ eventIds = {}, createdAt = -10 }, 0)
  eq(q:Next(29, OPEN), nil, "within cooldown")
  q:Expire(29, { zoneKey = "z" })
  eq(q:Count(), 1, "still queued")
  eq(q:Next(30, OPEN).trigger, "zone", "after cooldown")
end)

test("bypass skips the cooldown but respects the minimum gap", function()
  local q = new()
  q:MarkCaptured({ eventIds = {}, createdAt = -10 }, 0)
  q:Add(req("level", 2, { bypass = true }), 0.5)
  eq(q:Next(1, OPEN), nil, "within min gap")
  eq(q:Next(2, OPEN).trigger, "level", "after min gap")
end)

test("requests expire after max age once due", function()
  local q = new()
  local outcomes = {}
  q:Add(req("level", 2, { delay = 5, maxAge = 15 }), 0)
  q:Expire(20, {}, function(_, o) outcomes[#outcomes + 1] = o end)
  eq(q:Count(), 1, "not yet stale at 20")
  q:Expire(20.1, {}, function(_, o) outcomes[#outcomes + 1] = o end)
  eq(outcomes[1], "stale", "outcome")
end)

test("zone request is dropped when the zone was left", function()
  local q = new()
  local outcome
  q:Add(req("zone", 4, { zoneKey = "map:1" }), 0)
  q:Expire(1, { zoneKey = "map:2" }, function(_, o) outcome = o end)
  eq(outcome, "left_zone", "outcome")
end)

test("no zone screenshot on a taxi, none during loading screens", function()
  local q = new()
  q:Add(req("zone", 4, { zoneKey = "z" }), 0)
  eq(q:Next(1, { onTaxi = true }), nil, "taxi")
  eq(q:Next(1, { loading = true }), nil, "loading")
  eq(q:Next(1, OPEN).trigger, "zone", "afterwards")
end)

test("full queue: higher priority replaces the lowest, otherwise rejected", function()
  local q = Queue.New({ capacity = 2, coalesceWindow = 0 })
  local outcomes = {}
  local done = function(r, o) outcomes[#outcomes + 1] = r.trigger .. ":" .. o end
  q:Add(req("death", 6), 0, done)
  q:Add(req("quest", 5), 1, done)
  eq((q:Add(req("death", 6, { id = "d2" }), 2, done)), "rejected", "lower priority rejected")
  eq((q:Add(req("level", 2), 3, done)), "replaced", "higher priority replaces")
  eq(outcomes[1], "death:rejected", "first outcome")
  eq(outcomes[2], "death:replaced", "evicted request")
end)

test("drain on logout reports every pending request", function()
  local q = new()
  local n = 0
  q:Add(req("zone", 4, { zoneKey = "z" }), 0)
  q:Add(req("quest", 5), 10)
  q:Drain(function(_, o) if o == "dropped_on_logout" then n = n + 1 end end)
  eq(n, 2, "dropped")
  eq(q:Count(), 0, "empty")
end)

test("time until next covers delay, cooldown and blocked zone requests", function()
  local q = new()
  eq(q:TimeUntilNext(0, OPEN), nil, "empty queue")
  q:Add(req("level", 2, { delay = 5, bypass = true }), 0)
  eq(q:TimeUntilNext(1, OPEN), 4, "delay remaining")
  q:Next(5, OPEN)
  q:MarkCaptured({ eventIds = {}, createdAt = -10 }, 5)
  q:Add(req("zone", 4, { zoneKey = "z" }), 10)
  eq(q:TimeUntilNext(10, OPEN), 25, "cooldown remaining")
  eq(q:TimeUntilNext(10, { onTaxi = true }), math.huge, "blocked on a taxi")
  eq(q:TimeUntilNext(10, { loading = true }), nil, "hidden during loading")
end)

print(string.format("QUEUE TESTS PASSED (%d)", passed))
