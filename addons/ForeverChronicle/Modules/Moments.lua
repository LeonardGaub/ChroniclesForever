-- Journey Forever - Moments module
-- Moments the player marks themself ("moment"): a screenshot right away and the player's own words for it, shown
-- in the chronicle and on the cinematic's banner.
--   /fj moment <text>  records the moment with its text and takes the screenshot
--   /fj moment, the key binding "Capture a moment" (Bindings.xml): the screenshot first, then a small window asks
--     for the text (left empty or cancelled: the moment stays, without text)
-- The screenshot uses the "moment" trigger (Modules/Screenshots.lua): no delay, never waits for the cooldown.

local ADDON, FC = ...
local L = FC.L

local Moments = FC:NewModule("Moments", { order = 52 })

local ASK_AFTER = 1.5       -- seconds: the text window opens once the screenshot is taken
local MAX_LETTERS = 120

FC:RegisterEventCategory("moments", { labelKey = "CAT_MOMENTS", icon = "Interface\\Icons\\INV_Misc_Spyglass_03", order = 5 })

FC:RegisterEventType("moment", {
  icon = "Interface\\Icons\\INV_Misc_Spyglass_03", category = "moments", highlight = "milestone",
  format = function(r) return r.data.text and string.format(L.EVT_MOMENT_TEXT, r.data.text) or L.EVT_MOMENT end,
})

local function clean(text)
  text = strtrim((tostring(text or ""):gsub("[\r\n]", " "))):sub(1, MAX_LETTERS)
  return text ~= "" and text or nil
end

function Moments:Capture(text)
  text = clean(text)
  local record = FC:Record("moment", { text = text })
  if record and not text then
    FC:After(ASK_AFTER, function() self:Ask(record) end)
  end
  return record
end

function Moments:SetText(record, text)
  record.data.text = clean(text)
  FC:Print(record.data.text and string.format(L.MOMENT_SAVED_TEXT, record.data.text) or L.MOMENT_SAVED)
  FC:SendMessage("FC_EVENT_UPDATED", record)
end

-- The text window: Blizzard's popup with an edit box.
local DIALOG = "JOURNEYFOREVER_MOMENT"

local function editBox(dialog)
  return dialog.GetEditBox and dialog:GetEditBox() or dialog.editBox or dialog.EditBox
end

function Moments:Ask(record)
  if not (StaticPopupDialogs and StaticPopup_Show) then
    self:SetText(record, nil)
    return
  end
  StaticPopupDialogs[DIALOG] = StaticPopupDialogs[DIALOG] or {
    button1 = OKAY, button2 = CANCEL, hasEditBox = true, maxLetters = MAX_LETTERS, editBoxWidth = 320,
    timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
    OnShow = function(dialog) local box = editBox(dialog); if box then box:SetText(""); box:SetFocus() end end,
    OnAccept = function(dialog, data) Moments:SetText(data, editBox(dialog) and editBox(dialog):GetText()) end,
    OnCancel = function(_, data) Moments:SetText(data, nil) end,
    EditBoxOnEnterPressed = function(box)
      local dialog = box:GetParent()
      Moments:SetText(dialog.data, box:GetText())
      dialog:Hide()
    end,
    EditBoxOnEscapePressed = function(box) box:GetParent():Hide() end,
  }
  StaticPopupDialogs[DIALOG].text = L.MOMENT_ASK
  StaticPopup_Show(DIALOG, nil, nil, record)
end

-- Key binding (Bindings.xml) and its names in the key bindings window.
BINDING_HEADER_JOURNEYFOREVER = "Journey Forever"
function ForeverChronicle_CaptureMoment()
  FC:SafeCall(Moments.Capture, Moments)
end

function Moments:OnInitialize()
  BINDING_NAME_JOURNEYFOREVER_MOMENT = L.BINDING_MOMENT
end

FC:RegisterCommand("moment", "CMD_MOMENT", function(arg) Moments:Capture(arg) end, 55)
