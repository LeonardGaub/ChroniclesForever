// Runs a FriendsData.lua file in a Lua VM (fengari) and prints ForeverChronicleFriends as JSON, plus the names
// of any other globals the file created. Used by the desktop tests to prove the generated file is plain data.
// Usage: node dump_friends.js <path to FriendsData.lua>
const fs = require('fs');
const { lua, lauxlib, lualib, to_luastring } = require('fengari');

const L = lauxlib.luaL_newstate();
lualib.luaL_openlibs(L);
const src = fs.readFileSync(process.argv[2]);
const dump = `
local before = {}
for k in pairs(_G) do before[k] = true end
local chunk = assert(load(FILE_SRC, "=FriendsData.lua"))
chunk()
local extra = {}
for k in pairs(_G) do if not before[k] and k ~= "ForeverChronicleFriends" then extra[#extra + 1] = tostring(k) end end
local function enc(v)
  local t = type(v)
  if t == "string" then
    return '"' .. v:gsub('[%c"\\\\\\128-\\255]', function(c) return string.format("\\\\u%04x", c:byte()) end) .. '"'
  elseif t == "number" then
    if v == math.floor(v) and math.abs(v) < 2^53 then return string.format("%d", v) end
    return string.format("%.17g", v)
  elseif t == "boolean" then return tostring(v)
  elseif t == "table" then
    local n = #v
    local isArray = n > 0 or next(v) == nil
    for k in pairs(v) do if type(k) ~= "number" or k < 1 or k > n or k % 1 ~= 0 then isArray = false end end
    local out = {}
    if isArray then
      for i = 1, n do out[i] = enc(v[i]) end
      return "[" .. table.concat(out, ",") .. "]"
    end
    for k, val in pairs(v) do out[#out + 1] = enc(tostring(k)) .. ":" .. enc(val) end
    return "{" .. table.concat(out, ",") .. "}"
  end
  return "null"
end
return enc({ data = ForeverChronicleFriends, extraGlobals = extra })
`;
lua.lua_pushstring(L, src);
lua.lua_setglobal(L, to_luastring('FILE_SRC'));
if (lauxlib.luaL_loadstring(L, to_luastring(dump)) !== lua.LUA_OK || lua.lua_pcall(L, 0, 1, 0) !== lua.LUA_OK) {
  console.error('LUA ERROR: ' + lua.lua_tojsstring(L, -1));
  process.exit(1);
}
process.stdout.write(lua.lua_tojsstring(L, -1));
