"""Takes the event types' and stat tiles' icons (the ones the addon shows) out of the local WoW Forever install and
saves them as PNG in desktop/forever_chronicle/icons/, the icons kept in git (forever_chronicle/wow/game_icons.py).

    desktop\\.venv\\Scripts\\python tools\\extract_icons.py [--out FOLDER] [--install WOW_FOLDER]

Rerun it after adding an event type or a stat with a new icon (domain/event_types.py, domain/stats.py). The icons
recorded per event (achievements, professions, mounts) are not kept in git: the app takes them from the game when
needed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "tools")]
from db2 import find_install  # noqa: E402
from forever_chronicle.domain import event_types, stats  # noqa: E402
from forever_chronicle.wow import game_icons, paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--install", type=Path, help="the World of Warcraft folder (default: found automatically)")
    parser.add_argument("--out", type=Path, default=game_icons.BUNDLED)
    args = parser.parse_args()
    install = find_install(args.install)
    icons = list({game_icons.name_of(i): i for i in event_types.all_icons() + stats.all_icons()}.values())
    written = set(game_icons.extract(install, paths.forever_product(install), icons, args.out))
    for icon in icons:
        name = game_icons.name_of(icon)
        print(f"  {name}.png" if name in written else f"  {icon}: not in the game files")
    return 0 if len(written) == len(icons) else 1


if __name__ == "__main__":
    sys.exit(main())
