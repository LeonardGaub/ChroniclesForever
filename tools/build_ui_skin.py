"""Builds the desktop app's Classic skin from the game's own UI textures, read from the local WoW Forever install,
into desktop/forever_chronicle/ui/assets/skin/ (kept in git, as the event icons and maps; ui/theme.py uses them).

    desktop\\.venv\\Scripts\\python tools\\build_ui_skin.py [--install WOW_FOLDER] [--out FOLDER]

The game draws its frames from pieces (a backdrop's edge file is a strip of eight 32 px cells: left, right, top,
bottom edge, then the four corners; buttons and tabs are three slices). Qt style sheets want one picture per
look that they cut into nine slices (border-image), so the pieces are put together here:

- panel.png:      the dialog box (UI-DialogBox-Border) round dark marble (UI-Background-Marble), 512 x 512, slices 32
- card.png / card_hover.png / card_selected.png: the tooltip border (silver; gold for hover and selected) round a dark
  stone fill, 256 x 256, slices 16
- tooltip.png:    the tooltip border round near-black, slices 16 (tooltips, menus, group boxes)
- button_*.png:   UI-Panel-Button Up / Down / Highlight (added onto Up) / Disabled, the 80 x 22 part, slices 0 12;
                  button_selected.png: the highlight with a gold border (checkable buttons that are on)
- tab_*.png:      UI-Character-InActiveTab / ActiveTab (the character frame's tabs hanging below it) / highlight
- input.png:      Common-Input-Border (its top 20 px), slices 3 8 (line edits, drop-downs)
- check_*.png:    UI-CheckBox Up, with Check, with Highlight, both; Disabled greyed
- slider_handle.png, rock.png (the window's background, 512 px tile)
- xp_frame.png:   the experience bar's frame with its twenty bubbles (UI-MainMenuBar-Dwarf: four 256 px pieces,
                  as MainMenuXPBarTexture0-3 place them), 1024 x 15; xp_fill.png: UI-StatusBar in the bar's purple
                  (0.58, 0, 0.55) (the cinematic's XP bar, ui/cinematic_hud.py)
- levelup_*.png:  pieces of the game's level-up display (Interface\\LevelUp\\LevelUpTex): its gold line and
                  golden glow (the cinematic's level-up, ui/cinematic_fx.py); its dark backdrop overlaps other
                  pieces there, so the title keeps its own soft band

Rerun after a client patch if the textures change. Needs numpy and Pillow (as tools/extract_icons.py).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "tools")]
from db2 import find_install  # noqa: E402
from forever_chronicle.wow import game_icons, paths  # noqa: E402

OUT = ROOT / "desktop" / "forever_chronicle" / "ui" / "assets" / "skin"
TEXTURES = {
    "dialog": r"Interface\DialogFrame\UI-DialogBox-Border",
    "gold": r"Interface\DialogFrame\UI-DialogBox-Gold-Border",
    "tooltip": r"Interface\Tooltips\UI-Tooltip-Border",
    "marble": r"Interface\FrameGeneral\UI-Background-Marble",
    "rock": r"Interface\FrameGeneral\UI-Background-Rock",
    "button_up": r"Interface\Buttons\UI-Panel-Button-Up",
    "button_down": r"Interface\Buttons\UI-Panel-Button-Down",
    "button_highlight": r"Interface\Buttons\UI-Panel-Button-Highlight",
    "button_disabled": r"Interface\Buttons\UI-Panel-Button-Disabled",
    "tab": r"Interface\PaperDollInfoFrame\UI-Character-InActiveTab",
    "tab_active": r"Interface\PaperDollInfoFrame\UI-Character-ActiveTab",
    "tab_highlight": r"Interface\PaperDollInfoFrame\UI-Character-Tab-Highlight",
    "input": r"Interface\Common\Common-Input-Border",
    "check_up": r"Interface\Buttons\UI-CheckBox-Up",
    "check_check": r"Interface\Buttons\UI-CheckBox-Check",
    "check_highlight": r"Interface\Buttons\UI-CheckBox-Highlight",
    "check_disabled": r"Interface\Buttons\UI-CheckBox-Check-Disabled",
    "slider_handle": r"Interface\Buttons\UI-SliderBar-Button-Horizontal",
    "menubar": r"Interface\MainMenuBar\UI-MainMenuBar-Dwarf",
    "statusbar": r"Interface\TargetingFrame\UI-StatusBar",
    "levelup": r"Interface\LevelUp\LevelUpTex",
}
XP_PIECES = (192, 128, 64, 0)      # rows of the four frame pieces in UI-MainMenuBar-Dwarf, left to right
XP_ROWS = (8, 23)                  # the frame's rows within each 64 px block (its shadow included)
XP_COLOR = (148, 0, 140)           # the game's experience colour (0.58, 0, 0.55)
# Pieces of LevelUpTex (512 x 512), measured by their alpha: (left, top, right, bottom).
LEVELUP_PIECES = {"levelup_line.png": (11, 14, 408, 20), "levelup_glow.png": (284, 119, 502, 240)}


def load(folder: Path, key: str) -> Image.Image:
    return Image.open(folder / f"{game_icons.name_of(TEXTURES[key])}.png").convert("RGBA")


def add(base: Image.Image, light: Image.Image) -> Image.Image:
    """Additive blend (the game draws highlights with blend mode ADD: black adds nothing); the base keeps its
    shape (the highlight textures are opaque black round the glow)."""
    glow = Image.composite(light, Image.new("RGBA", light.size), light).convert("RGB")
    out = ImageChops.add(base.convert("RGB"), glow).convert("RGBA")
    out.putalpha(base.getchannel("A"))
    return out


def backdrop(edge: Image.Image, size: int, fill: Image.Image | None, inset: int, cell: int | None = None) -> Image.Image:
    """A frame from a backdrop edge strip (eight cells: left, right, top, bottom, TL, TR, BL, BR) round fill."""
    cell = cell or edge.height
    cells = [edge.crop((i * cell, 0, (i + 1) * cell, cell)) for i in range(8)]
    out = Image.new("RGBA", (size, size))
    if fill is not None:
        out.alpha_composite(fill.resize((size - 2 * inset, size - 2 * inset), Image.LANCZOS), (inset, inset))
    left, right, top, bottom, tl, tr, bl, br = cells
    top = top.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)   # the strip keeps horizontal edges upright
    bottom = bottom.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
    for y in range(cell, size - cell, cell):
        out.alpha_composite(left, (0, y))
        out.alpha_composite(right, (size - cell, y))
    for x in range(cell, size - cell, cell):
        out.alpha_composite(top, (x, 0))
        out.alpha_composite(bottom, (x, size - cell))
    out.alpha_composite(tl, (0, 0))
    out.alpha_composite(tr, (size - cell, 0))
    out.alpha_composite(bl, (0, size - cell))
    out.alpha_composite(br, (size - cell, size - cell))
    return out


def stone(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """A vertical gradient (the cards' fill)."""
    img = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        f = y / max(1, size - 1)
        draw.line([(0, y), (size, y)], fill=tuple(int(a + (b - a) * f) for a, b in zip(top, bottom)) + (255,))
    return img


def tint(img: Image.Image, color: tuple) -> Image.Image:
    """The game tints grey borders with a vertex colour (the tooltip border in gold)."""
    r, g, b, a = img.split()
    grey = img.convert("L")
    out = Image.merge("RGB", [grey.point(lambda v, c=c: v * c // 255) for c in color]).convert("RGBA")
    out.putalpha(a)
    return out


def build(src: Path, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    made = []

    def save(img: Image.Image, name: str) -> None:
        img.save(out / name)
        made.append(name)

    marble = load(src, "marble")
    save(backdrop(load(src, "dialog"), 512, ImageEnhance.Brightness(marble).enhance(1.25), 11), "panel.png")
    card_fill = stone(256, (36, 27, 18), (22, 17, 12))
    tooltip = load(src, "tooltip")
    save(backdrop(tooltip, 256, card_fill, 4), "card.png")
    gold = tint(tooltip, (255, 209, 0))
    save(backdrop(gold, 256, card_fill, 4), "card_hover.png")
    save(backdrop(gold, 256, stone(256, (58, 44, 24), (29, 22, 14)), 4), "card_selected.png")
    save(backdrop(tooltip, 128, stone(128, (9, 8, 7), (9, 8, 7)), 4), "tooltip.png")
    save(backdrop(tint(tooltip, (180, 140, 80)), 128, stone(128, (26, 21, 16), (26, 21, 16)), 4), "group.png")

    for state in ("up", "down", "disabled"):
        save(load(src, f"button_{state}").crop((0, 0, 80, 22)), f"button_{state}.png")
    hover = add(load(src, "button_up"), load(src, "button_highlight")).crop((0, 0, 80, 22))
    save(hover, "button_hover.png")
    selected = hover.copy()                      # a chosen option: gold border and glow (the user's preference)
    draw = ImageDraw.Draw(selected)
    draw.rounded_rectangle((1, 1, 78, 20), radius=4, outline=(255, 209, 0, 255), width=2)
    draw.rounded_rectangle((3, 3, 76, 18), radius=3, outline=(255, 230, 140, 110), width=1)
    save(selected, "button_selected.png")

    tab = load(src, "tab")                       # 128 x 32
    active = load(src, "tab_active").crop((0, 0, 128, 35))
    save(tab, "tab.png")
    save(active, "tab_active.png")
    save(add(tab, load(src, "tab_highlight")), "tab_hover.png")

    save(load(src, "input").crop((0, 0, 128, 20)), "input.png")    # the game uses the top 20 px (texcoords 0..0.625)
    up, check, light = load(src, "check_up"), load(src, "check_check"), load(src, "check_highlight")
    checked = up.copy()
    checked.alpha_composite(check)
    save(ImageEnhance.Brightness(up).enhance(1.7), "check.png")      # brighter, to show on the dark panels
    save(checked, "check_checked.png")
    save(add(up, light), "check_hover.png")
    save(add(checked, light), "check_checked_hover.png")
    save(ImageEnhance.Brightness(ImageEnhance.Color(checked).enhance(0)).enhance(0.6), "check_disabled.png")
    save(load(src, "slider_handle"), "slider_handle.png")
    save(load(src, "rock").resize((512, 512), Image.LANCZOS), "rock.png")
    menubar = load(src, "menubar")
    frame = Image.new("RGBA", (1024, XP_ROWS[1] - XP_ROWS[0]))
    for i, top in enumerate(XP_PIECES):
        frame.alpha_composite(menubar.crop((0, top + XP_ROWS[0], 256, top + XP_ROWS[1])), (i * 256, 0))
    save(frame, "xp_frame.png")
    save(tint(load(src, "statusbar"), XP_COLOR), "xp_fill.png")
    levelup = load(src, "levelup")
    for name, box in LEVELUP_PIECES.items():
        save(levelup.crop(box), name)
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, help="the World of Warcraft folder (default: found automatically)")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    install = find_install(args.install)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        got = set(game_icons.extract(install, paths.forever_product(install), list(TEXTURES.values()), src))
        missing = [t for t in TEXTURES.values() if game_icons.name_of(t) not in got and "Disabled" not in t]
        if missing:
            print("not in the game files:", *missing, sep="\n  ")
            return 1
        for name in build(src, args.out):
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
