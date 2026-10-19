-- Journey Forever - Locale
-- Language tables are registered by Locales/*.lua. FC.L resolves keys against the active
-- language, then English, then returns the key itself so a missing string is visible but harmless.

local ADDON, FC = ...

FC.locales = {}
FC.DEFAULT_LANGUAGE = "deDE"

local active = {}

function FC:RegisterLocale(lang, strings)
  self.locales[lang] = self.locales[lang] or {}
  for k, v in pairs(strings) do self.locales[lang][k] = v end
end

FC.L = setmetatable({}, {
  __index = function(_, key)
    local v = active[key]
    if v == nil and FC.locales.enUS then v = FC.locales.enUS[key] end
    return v or key
  end,
})

function FC:GetLanguage()
  local lang = self.db and self.db.settings.language
  if lang and self.locales[lang] then return lang end
  return self.DEFAULT_LANGUAGE
end

function FC:ApplyLanguage()
  active = self.locales[self:GetLanguage()] or {}
end

function FC:SetLanguage(lang)
  if not self.locales[lang] then return false end
  self.db.settings.language = lang
  self:ApplyLanguage()
  self:SendMessage("FC_LANGUAGE_CHANGED", lang)
  return true
end
