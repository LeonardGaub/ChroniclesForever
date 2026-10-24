"""Takes the event types' icons (the ones the addon shows) out of the local WoW Forever install and saves them as
PNG in desktop/forever_chronicle/icons/, the icons kept in git (forever_chronicle/wow/game_icons.py).

    desktop\\.venv\\Scripts\\python tools\\extract_icons.py [--out FOLDER] [--install WOW_FOLDER]

Rerun it after adding an event type with a new icon (domain/event_types.py). The icons recorded per event
(achievements, recipes, professions) are not kept in git: the app takes them from the game when needed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forever_chronicle.domain import event_types
from forever_chronicle.wow import game_icons, paths

DEFAULT_INSTALL = Path(r"C:\Program Files (x86)\World of Warcraft")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--out", type=Path, default=game_icons.BUNDLED)
    args = parser.parse_args()
    icons = event_types.all_icons()
    written = set(game_icons.extract(args.install, paths.forever_product(args.install), icons, args.out))
    for icon in icons:
        name = game_icons.name_of(icon)
        print(f"  {name}.png" if name in written else f"  {icon}: not in the game files")
    return 0 if len(written) == len(icons) else 1


if __name__ == "__main__":
    sys.exit(main())
