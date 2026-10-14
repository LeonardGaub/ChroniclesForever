-- Forever Chronicle - Screenshot queue (spec F-003)
-- Pure scheduling logic without game API calls, so it can be tested outside the client.
-- Time values are seconds from a monotonic clock supplied by the caller.
--
-- Request fields (set by the caller):
--   trigger, priority (1 = highest), eventIds = {...}, identity (for duplicate merging),
--   delay (wait before the request becomes due), maxAge (how long it may wait once due),
--   bypassCooldown, zoneKey (zone triggers only)
-- Outcomes reported through the onDone(request, outcome) callback:
--   "captured" (by the caller), "stale", "left_zone", "rejected", "replaced", "dropped_on_logout"

local ADDON, FC = ...

local Queue = {}
Queue.__index = Queue
FC.ScreenshotQueue = Queue

-- opts: capacity, cooldown, minGap, coalesceWindow
function Queue.New(opts)
  return setmetatable({
    items = {},
    capacity = opts.capacity or 50,
    cooldown = opts.cooldown or 30,
    minGap = opts.minGap or 2,
    coalesceWindow = opts.coalesceWindow or 2,
    lastShotAt = nil,        -- time of the last capture
    lastShot = nil,          -- last captured request (for late coalescing)
    counter = 0,
  }, Queue)
end

local function mergeInto(target, req)
  for _, id in ipairs(req.eventIds) do table.insert(target.eventIds, id) end
  if req.priority < target.priority then
    target.priority, target.trigger = req.priority, req.trigger
    target.zoneKey = req.zoneKey
  elseif req.trigger ~= "zone" and target.trigger ~= "zone" then
    target.zoneKey = nil
  end
  target.eligibleAt = math.max(target.eligibleAt, req.eligibleAt)
  target.expiresAt = math.max(target.expiresAt, req.expiresAt)
  target.bypassCooldown = target.bypassCooldown or req.bypassCooldown
end

-- Adds a request. Returns "queued", "merged", "linked" (attached to the screenshot just taken),
-- "replaced" (queued after evicting a lower-priority request) or "rejected".
function Queue:Add(req, now, onDone)
  req.createdAt = now
  req.eligibleAt = now + (req.delay or 0)
  req.expiresAt = req.eligibleAt + (req.maxAge or 60)
  self.counter = self.counter + 1
  req.order = self.counter

  -- Same event identity already queued: merge.
  for _, item in ipairs(self.items) do
    if req.identity and item.identity == req.identity then
      mergeInto(item, req)
      return "merged", item
    end
  end
  -- Created within the coalescing window of a queued request: one screenshot for both.
  for _, item in ipairs(self.items) do
    if math.abs(now - item.createdAt) <= self.coalesceWindow then
      mergeInto(item, req)
      return "merged", item
    end
  end
  -- The screenshot for a request from the same moment was already taken: link to it.
  if self.lastShot and now - self.lastShot.createdAt <= self.coalesceWindow then
    for _, id in ipairs(req.eventIds) do table.insert(self.lastShot.eventIds, id) end
    return "linked", self.lastShot
  end

  if #self.items >= self.capacity then
    local worst, worstIndex
    for i, item in ipairs(self.items) do
      if not worst or item.priority > worst.priority or
        (item.priority == worst.priority and item.order > worst.order) then
        worst, worstIndex = item, i
      end
    end
    if worst and req.priority < worst.priority then
      table.remove(self.items, worstIndex)
      if onDone then onDone(worst, "replaced") end
      table.insert(self.items, req)
      return "replaced", req
    end
    if onDone then onDone(req, "rejected") end
    return "rejected", req
  end
  table.insert(self.items, req)
  return "queued", req
end

-- Removes requests that can no longer be captured meaningfully.
-- state: { zoneKey = current zone key }
function Queue:Expire(now, state, onDone)
  for i = #self.items, 1, -1 do
    local item = self.items[i]
    local outcome
    if now > item.expiresAt then
      outcome = "stale"
    elseif item.trigger == "zone" and item.zoneKey and state.zoneKey ~= item.zoneKey then
      outcome = "left_zone"
    end
    if outcome then
      table.remove(self.items, i)
      if onDone then onDone(item, outcome) end
    end
  end
end

-- Returns the request to capture now, or nil.
-- state: { loading = bool, onTaxi = bool }
function Queue:Next(now, state)
  if state.loading then return nil end
  if self.lastShotAt and now < self.lastShotAt + self.minGap then return nil end
  local best, bestIndex
  for i, item in ipairs(self.items) do
    local ready = now >= item.eligibleAt
      and (item.bypassCooldown or not self.lastShotAt or now >= self.lastShotAt + self.cooldown)
      and not (item.trigger == "zone" and state.onTaxi)
    if ready and (not best or item.priority < best.priority or
      (item.priority == best.priority and item.order < best.order)) then
      best, bestIndex = item, i
    end
  end
  if best then table.remove(self.items, bestIndex) end
  return best
end

-- Seconds until the next request can be captured: 0 if one is ready, math.huge if all pending
-- requests are blocked (e.g. zone requests during a flight), nil if the queue is empty or loading.
function Queue:TimeUntilNext(now, state)
  if #self.items == 0 or state.loading then return nil end
  local best = math.huge
  local gapEnd = self.lastShotAt and (self.lastShotAt + self.minGap) or now
  for _, item in ipairs(self.items) do
    if not (item.trigger == "zone" and state.onTaxi) then
      local t = math.max(item.eligibleAt, gapEnd)
      if not item.bypassCooldown and self.lastShotAt then t = math.max(t, self.lastShotAt + self.cooldown) end
      if t < best then best = t end
    end
  end
  if best == math.huge then return best end
  return math.max(0, best - now)
end

function Queue:MarkCaptured(req, now)
  self.lastShotAt = now
  self.lastShot = req
end

-- Empties the queue (logout). Every pending request gets the "dropped_on_logout" outcome.
function Queue:Drain(onDone)
  local items = self.items
  self.items = {}
  for _, item in ipairs(items) do
    if onDone then onDone(item, "dropped_on_logout") end
  end
end

function Queue:Count()
  return #self.items
end
