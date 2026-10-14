-- Journey Forever - Commands
-- /fj router plus the core commands. Modules add their own with FC:RegisterCommand.

local ADDON, FC = ...
local L = FC.L

FC:RegisterCommand("help", "CMD_HELP", function()
  local list = {}
  for _, cmd in pairs(FC.commands) do list[#list + 1] = cmd end
  table.sort(list, function(a, b)
    if a.order ~= b.order then return a.order < b.order end
    return a.name < b.name
  end)
  FC:Print(L.CMD_HELP_HEADER)
  FC:Print("  /fj - " .. L.CMD_TOGGLE)
  for _, cmd in ipairs(list) do FC:Print("  /fj " .. cmd.name .. " - " .. L[cmd.helpKey]) end
end, 1)

FC:RegisterCommand("status", "CMD_STATUS", function()
  local info = FC.char and FC.char.info or {}
  FC:Print(string.format(L.STATUS_LINE, FC.VERSION, info.name or "?", info.level or "?",
    FC.sessionStartedAt and FC.Util.FormatDuration(time() - FC.sessionStartedAt) or L.UNKNOWN))
  for _, u in ipairs(FC.Storage:GetUsage()) do
    FC:Print(string.format("  %s: %d / %d", u.name, u.count, u.cap))
  end
end, 10)

FC:RegisterCommand("diag", "CMD_DIAG", function(arg)
  if arg == "on" or arg == "off" then
    FC.db.settings.debug = (arg == "on")
  end
  FC:Print(FC.db.settings.debug and L.DIAG_ON or L.DIAG_OFF)
end, 20)

FC:RegisterCommand("lang", "CMD_LANG", function(arg)
  local map = { de = "deDE", en = "enUS" }
  if map[arg] and FC:SetLanguage(map[arg]) then
    FC:Print(L.LANG_CHANGED)
  else
    FC:Print(L.LANG_USAGE)
  end
end, 30)

FC:RegisterCommand("save", "CMD_SAVE", function()
  FC:Print(L.SAVE_HINT)
end, 40)

SLASH_FOREVERCHRONICLE1 = "/fj"
SLASH_FOREVERCHRONICLE2 = "/chronicle"
SlashCmdList.FOREVERCHRONICLE = function(msg)
  msg = strtrim(msg or "")
  local name, arg = msg:match("^(%S*)%s*(.-)$")
  name = (name or ""):lower()
  if name == "" then
    if FC.UI then FC.UI:Toggle() end
    return
  end
  local cmd = FC.commands[name]
  if cmd then
    FC:SafeCall(cmd.fn, arg)
  else
    FC:Print(L.CMD_UNKNOWN)
  end
end
