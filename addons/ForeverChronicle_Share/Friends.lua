-- Journey Forever - friends: adds the friends' characters to the character chooser of the main addon.
-- The sync script writes Friends\FriendsData.lua (ForeverChronicleFriends) from the friends' share files; each
-- friend's characters have the main addon's record shape and are shown read-only.

local FC = ForeverChronicle

local function data()
  local d = rawget(_G, "ForeverChronicleFriends")
  return type(d) == "table" and d or nil
end

FC:RegisterViewSource({
  emptyNoteKey = "VIEW_NO_FRIENDS",
  entries = function()
    local out, d = {}, data()
    for i, friend in ipairs(d and type(d.friends) == "table" and d.friends or {}) do
      if type(friend) == "table" and type(friend.characters) == "table" then
        for _, char in ipairs(friend.characters) do
          if type(char) == "table" and type(char.info) == "table" and char.info.name then
            FC.Storage.UnpackCharacter(char) -- friends' streams arrive packed (Share:Write)
            out[#out + 1] = { key = "friend:" .. i .. ":" .. tostring(char.info.key), char = char,
              owner = tostring(friend.name or "?") }
          end
        end
      end
    end
    return out
  end,
  data = function(kind)
    local d = data()
    return d and type(d[kind]) == "table" and d[kind] or nil
  end,
})
