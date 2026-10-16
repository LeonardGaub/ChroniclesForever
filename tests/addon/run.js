// Runs the Forever Chronicle addon in a mocked WoW client (fengari Lua VM).
// Each phase is a fresh client start; SavedVariables text is carried over like the real client does.
// Phase 3 output is written to tests/fixtures/ForeverChronicle.lua for the desktop importer tests.
const fs = require('fs');
const path = require('path');
const { lua, lauxlib, lualib, to_luastring } = require('fengari');

const addonsDir = path.join(__dirname, '..', '..', 'addons');
const addonDir = path.join(addonsDir, 'ForeverChronicle');
function tocFiles(addon) {
  const toc = fs.readFileSync(path.join(addonsDir, addon, addon + '.toc'), 'utf8');
  return toc.split(/\r?\n/).map(l => l.trim()).filter(l => l.endsWith('.lua') && !l.startsWith('#'))
    .map(l => l.replace(/\\/g, '/'));
}
// Main addon files by their path inside the addon; the companion's files with its folder in front.
const mainFiles = tocFiles('ForeverChronicle');
const companion = 'ForeverChronicle_Share';
const companionFiles = tocFiles(companion).map(f => companion + '/' + f);
const sourceOf = f => f.startsWith(companion + '/') ? path.join(addonsDir, f) : path.join(addonDir, f);

function runPhase(phase, saved, offset, overrides, mainOnly) {
  const files = mainOnly ? mainFiles : mainFiles.concat(companionFiles);
  const L = lauxlib.luaL_newstate();
  lualib.luaL_openlibs(L);
  const setStr = (name, value) => { lua.lua_pushstring(L, to_luastring(value)); lua.lua_setglobal(L, to_luastring(name)); };
  lua.lua_newtable(L);
  files.forEach((f, i) => { lua.lua_pushstring(L, to_luastring(f)); lua.lua_rawseti(L, -2, i + 1); });
  lua.lua_setglobal(L, to_luastring('ADDON_FILES'));
  lua.lua_newtable(L);
  for (const f of files) {
    const text = overrides && overrides[f] !== undefined ? overrides[f] : fs.readFileSync(sourceOf(f), 'utf8');
    lua.lua_pushstring(L, to_luastring(text));
    lua.lua_setfield(L, -2, to_luastring(f));
  }
  lua.lua_setglobal(L, to_luastring('ADDON_SRC'));
  lua.lua_newtable(L);
  for (const f of files) {
    if (f.startsWith(companion + '/')) {
      lua.lua_pushstring(L, to_luastring(companion));
      lua.lua_setfield(L, -2, to_luastring(f));
    }
  }
  lua.lua_setglobal(L, to_luastring('ADDON_OF'));
  lua.lua_pushinteger(L, phase); lua.lua_setglobal(L, to_luastring('PHASE'));
  lua.lua_pushinteger(L, offset); lua.lua_setglobal(L, to_luastring('PHASE_OFFSET'));
  if (saved) setStr('SAVED', saved);

  for (const script of ['mock_wow.lua', 'scenario.lua']) {
    const src = fs.readFileSync(path.join(__dirname, script), 'utf8');
    if (lauxlib.luaL_loadbuffer(L, to_luastring(src), null, to_luastring(script)) !== lua.LUA_OK ||
        lua.lua_pcall(L, 0, 0, 0) !== lua.LUA_OK) {
      console.error('LUA ERROR in phase ' + phase + ': ' + lua.lua_tojsstring(L, -1));
      process.exit(1);
    }
  }
  lua.lua_getglobal(L, to_luastring('SAVED_OUT'));
  return lua.lua_isstring(L, -1) ? lua.lua_tojsstring(L, -1) : null;
}

// Pure queue logic: load only ScreenshotQueue.lua and run the unit tests against it.
function runQueueTests() {
  const L = lauxlib.luaL_newstate();
  lualib.luaL_openlibs(L);
  const queueSrc = fs.readFileSync(path.join(addonDir, 'Modules', 'ScreenshotQueue.lua'), 'utf8');
  const setup = 'local ns = {}\nlocal chunk = assert(load(QUEUE_SRC, "@ScreenshotQueue.lua"))\nchunk("ForeverChronicle", ns)\nQUEUE = ns.ScreenshotQueue';
  lua.lua_pushstring(L, to_luastring(queueSrc)); lua.lua_setglobal(L, to_luastring('QUEUE_SRC'));
  for (const [name, src] of [['setup', setup], ['queue_tests.lua', fs.readFileSync(path.join(__dirname, 'queue_tests.lua'), 'utf8')]]) {
    if (lauxlib.luaL_loadbuffer(L, to_luastring(src), null, to_luastring(name)) !== lua.LUA_OK ||
        lua.lua_pcall(L, 0, 0, 0) !== lua.LUA_OK) {
      console.error('LUA ERROR in queue tests: ' + lua.lua_tojsstring(L, -1));
      process.exit(1);
    }
  }
}

console.log('screenshot queue');
runQueueTests();
const p1 = runPhase(1, null, 0);
const p2 = runPhase(2, p1, 1000);
const p3 = runPhase(3, p2, 90000);
// The desktop tests read this file; write it right away (phase 12 below needs a file the desktop tests write).
const fixtures = path.join(__dirname, '..', 'fixtures');
fs.mkdirSync(fixtures, { recursive: true });
fs.writeFileSync(path.join(fixtures, 'ForeverChronicle.lua'), p3);
console.log('fixture written: tests/fixtures/ForeverChronicle.lua');
runPhase(4, null, 0);
runPhase(5, null, 0);
runPhase(6, null, 0);
const oldSettings = interval =>
  `ForeverChronicleDB = { schemaVersion = 1, settings = { modules = { Positions = { enabled = true, interval = ${interval} } } } }`;
runPhase(7, oldSettings(10), 0);
runPhase(8, oldSettings(5), 0);
runPhase(9, null, 0);
runPhase(10, null, 0);
runPhase(11, null, 0);
const shareData = runPhase(13, null, 0);
fs.writeFileSync(path.join(fixtures, 'ForeverChronicle_Share.lua'), shareData);
console.log('fixture written: tests/fixtures/ForeverChronicle_Share.lua');
// Friends' characters as written by the sync script (desktop/tests/test_sync.py writes the fixture).
const friendsFixture = path.join(__dirname, '..', 'fixtures', 'FriendsData.lua');
if (fs.existsSync(friendsFixture)) {
  runPhase(12, null, 0, { 'ForeverChronicle_Share/Friends/FriendsData.lua': fs.readFileSync(friendsFixture, 'utf8') });
} else {
  console.log('phase 12 skipped: run the desktop tests first (they write tests/fixtures/FriendsData.lua)');
}

// The main addon alone, as uploaded to CurseForge.
runPhase(14, null, 0, null, true);
runPhase(15, null, 0);
console.log('ALL PHASES PASSED');
