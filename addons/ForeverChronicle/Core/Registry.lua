-- Forever Chronicle - Registry
-- Declarative registries that modules use to plug into recording, the UI and commands.

local ADDON, FC = ...

-------------------------------------------------------------------------------
-- Event types: how a recorded event is shown in the in-game chronicle.
--   def = { labelKey, icon, format = function(record) -> text, order }
-------------------------------------------------------------------------------

FC.eventTypes = {}

function FC:RegisterEventType(eventType, def)
  def.type = eventType
  self.eventTypes[eventType] = def
end

local FALLBACK_ICON = "Interface\\Icons\\INV_Misc_QuestionMark"

-- Text and icon for a recorded event. Unknown types (e.g. from newer versions) show their type name.
function FC:DescribeEvent(record)
  local def = self.eventTypes[record.type]
  local icon = def and def.icon or FALLBACK_ICON
  if def and def.getIcon then
    local ok, custom = pcall(def.getIcon, record)
    if ok and custom then icon = custom end
  end
  if def and def.format then
    local ok, text = pcall(def.format, record)
    if ok and text then return text, icon end
  end
  return record.type, icon
end

-------------------------------------------------------------------------------
-- Stats: per-character counters/values shown in the overview.
--   def = { labelKey, icon, order, format = "number" | "duration" | function(value),
--           compute = function() -> value,    -- optional; otherwise the stored counter is used
--           fromRecord = function(char) -> value }  -- optional; for other characters (alts, friends), whose
--                                                   -- live state is unknown; otherwise their stored counter
-------------------------------------------------------------------------------

FC.statDefs = {}
FC.statGroups = {}

-- Groups are shown as sections on the overview: heading (labelKey) and a short description (descKey).
function FC:RegisterStatGroup(key, labelKey, descKey, order)
  table.insert(self.statGroups, { key = key, labelKey = labelKey, descKey = descKey, order = order or 100 })
  table.sort(self.statGroups, function(a, b) return a.order < b.order end)
end

FC:RegisterStatGroup("session", "STATGROUP_SESSION", "STATGROUP_SESSION_DESC", 10)
FC:RegisterStatGroup("time", "STATGROUP_TIME", "STATGROUP_TIME_DESC", 20)
FC:RegisterStatGroup("progress", "STATGROUP_PROGRESS", "STATGROUP_PROGRESS_DESC", 30)

-- def.group: key of a stat group (default "progress").
function FC:RegisterStat(key, def)
  def.key = key
  def.order = def.order or 100
  def.group = def.group or "progress"
  table.insert(self.statDefs, def)
  table.sort(self.statDefs, function(a, b) return a.order < b.order end)
end

-------------------------------------------------------------------------------
-- Graphs: line graphs under the character on the overview, switchable; they show the last 2 hours of played time.
--   def = { labelKey, order, color = { r, g, b }, series = function(since) -> { { time, value }, ... } (ascending),
--           relative = true (show the change since the window start), step = true (changes at exact times),
--           format = function(value) -> text }
-------------------------------------------------------------------------------

FC.graphDefs = {}

function FC:RegisterGraph(key, def)
  def.key = key
  def.order = def.order or 100
  table.insert(self.graphDefs, def)
  table.sort(self.graphDefs, function(a, b) return a.order < b.order end)
end

function FC:GetStatsInGroup(group)
  local out = {}
  for _, def in ipairs(self.statDefs) do
    if def.group == group then out[#out + 1] = def end
  end
  return out
end

function FC:IncrementStat(key, amount)
  local stats = self.char.stats
  stats[key] = (stats[key] or 0) + (amount or 1)
end

function FC:SetStat(key, value)
  self.char.stats[key] = value
end

function FC:GetStatValue(def)
  if not self:IsViewingPlayed() then
    local char = self:ViewChar()
    if def.fromRecord then
      local ok, value = pcall(def.fromRecord, char)
      return ok and value or nil
    end
    return type(char.stats) == "table" and char.stats[def.key] or nil
  end
  if def.compute then
    local ok, value = pcall(def.compute)
    return ok and value or nil
  end
  return self.char and self.char.stats[def.key]
end

function FC:FormatStat(def, value)
  if value == nil then return self.L.UNKNOWN end
  if type(def.format) == "function" then return def.format(value) end
  if def.format == "duration" then return self.Util.FormatDuration(value) end
  return tostring(value)
end

-------------------------------------------------------------------------------
-- Options: settings shown on the settings tab, grouped in sections.
--   def = { section, module, key, type = "toggle" | "choice", labelKey, tooltipKey, column = 1 | 2,
--           choices = { { value, labelKey | text } }, order, get, set, onChange = function(value) }
-- section defaults to "general". Modules add their own sections with FC:RegisterOptionSection.
-------------------------------------------------------------------------------

FC.optionDefs = {}
FC.optionSections = {}

function FC:RegisterOptionSection(key, labelKey, order, icon)
  table.insert(self.optionSections, { key = key, labelKey = labelKey, order = order or 100, icon = icon })
  table.sort(self.optionSections, function(a, b) return a.order < b.order end)
end

FC:RegisterOptionSection("general", "SECTION_GENERAL", 1, "Interface\\Icons\\INV_Misc_Gear_01")

function FC:RegisterOption(def)
  def.order = def.order or 100
  table.insert(self.optionDefs, def)
  table.sort(self.optionDefs, function(a, b) return a.order < b.order end)
end

function FC:GetOptionValue(def)
  if def.get then return def.get() end
  return self.db.settings.modules[def.module][def.key]
end

function FC:SetOptionValue(def, value)
  if def.set then
    def.set(value)
  else
    self.db.settings.modules[def.module][def.key] = value
  end
  if def.onChange then self:SafeCall(def.onChange, value) end
  self:SendMessage("FC_OPTION_CHANGED", def)
end

-------------------------------------------------------------------------------
-- Slash commands: /fc <name> <args>
-------------------------------------------------------------------------------

FC.commands = {}

function FC:RegisterCommand(name, helpKey, fn, order)
  self.commands[name] = { name = name, helpKey = helpKey, fn = fn, order = order or 100 }
end
