"""Classic map table: uiMapID, German/English names and continent.

Forever uses the Classic uiMapIDs (confirmed in Phase 0: 1413 The Barrens, 1414 Kalimdor, 1454 Orgrimmar).
All map images (wow/map_art.py) use the world map canvas of 1002 x 668 pixels; map coordinates are normalized to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..i18n import language, tr

ART_WIDTH, ART_HEIGHT = 1002, 668
WORLD, KALIMDOR, EASTERN_KINGDOMS = 947, 1414, 1415
# Where each continent's map lies on the world map (min_x, max_x, min_y, max_y; may reach past its edges).
# Found by matching the continent map art onto the world map art, so the pictures line up when one fades into
# the other (cinematic mode); the game itself does not tell the addon these.
CONTINENT_ON_WORLD = {KALIMDOR: (-0.1808, 0.6346, 0.0681, 0.8835),
                      EASTERN_KINGDOMS: (0.3937, 1.1399, 0.1184, 0.8646)}


@dataclass(frozen=True)
class MapDef:
    map_id: int
    en: str
    de: str
    continent: int | None


_K, _E = KALIMDOR, EASTERN_KINGDOMS
CLASSIC_MAPS = [
    MapDef(947, "Azeroth", "Azeroth", None),
    MapDef(1414, "Kalimdor", "Kalimdor", None),
    MapDef(1415, "Eastern Kingdoms", "Östliche Königreiche", None),
    MapDef(1411, "Durotar", "Durotar", _K),
    MapDef(1412, "Mulgore", "Mulgore", _K),
    MapDef(1413, "The Barrens", "Brachland", _K),
    MapDef(1438, "Teldrassil", "Teldrassil", _K),
    MapDef(1439, "Darkshore", "Dunkelküste", _K),
    MapDef(1440, "Ashenvale", "Eschental", _K),
    MapDef(1441, "Thousand Needles", "Tausend Nadeln", _K),
    MapDef(1442, "Stonetalon Mountains", "Steinkrallengebirge", _K),
    MapDef(1443, "Desolace", "Desolace", _K),
    MapDef(1444, "Feralas", "Feralas", _K),
    MapDef(1445, "Dustwallow Marsh", "Düstermarschen", _K),
    MapDef(1446, "Tanaris", "Tanaris", _K),
    MapDef(1447, "Azshara", "Azshara", _K),
    MapDef(1448, "Felwood", "Teufelswald", _K),
    MapDef(1449, "Un'Goro Crater", "Krater von Un'Goro", _K),
    MapDef(1450, "Moonglade", "Mondlichtung", _K),
    MapDef(1451, "Silithus", "Silithus", _K),
    MapDef(1452, "Winterspring", "Winterquell", _K),
    MapDef(1454, "Orgrimmar", "Orgrimmar", _K),
    MapDef(1456, "Thunder Bluff", "Donnerfels", _K),
    MapDef(1457, "Darnassus", "Darnassus", _K),
    MapDef(1416, "Alterac Mountains", "Alteracgebirge", _E),
    MapDef(1417, "Arathi Highlands", "Arathihochland", _E),
    MapDef(1418, "Badlands", "Ödland", _E),
    MapDef(1419, "Blasted Lands", "Verwüstete Lande", _E),
    MapDef(1420, "Tirisfal Glades", "Tirisfal", _E),
    MapDef(1421, "Silverpine Forest", "Silberwald", _E),
    MapDef(1422, "Western Plaguelands", "Westliche Pestländer", _E),
    MapDef(1423, "Eastern Plaguelands", "Östliche Pestländer", _E),
    MapDef(1424, "Hillsbrad Foothills", "Vorgebirge des Hügellands", _E),
    MapDef(1425, "The Hinterlands", "Hinterland", _E),
    MapDef(1426, "Dun Morogh", "Dun Morogh", _E),
    MapDef(1427, "Searing Gorge", "Sengende Schlucht", _E),
    MapDef(1428, "Burning Steppes", "Brennende Steppe", _E),
    MapDef(1429, "Elwynn Forest", "Wald von Elwynn", _E),
    MapDef(1430, "Deadwind Pass", "Gebirgspass der Totenwinde", _E),
    MapDef(1431, "Duskwood", "Dämmerwald", _E),
    MapDef(1432, "Loch Modan", "Loch Modan", _E),
    MapDef(1433, "Redridge Mountains", "Rotkammgebirge", _E),
    MapDef(1434, "Stranglethorn Vale", "Schlingendorntal", _E),
    MapDef(1435, "Swamp of Sorrows", "Sümpfe des Elends", _E),
    MapDef(1436, "Westfall", "Westfall", _E),
    MapDef(1437, "Wetlands", "Sumpfland", _E),
    MapDef(1453, "Stormwind City", "Sturmwind", _E),
    MapDef(1455, "Ironforge", "Eisenschmiede", _E),
    MapDef(1458, "Undercity", "Unterstadt", _E),
    MapDef(1459, "Alterac Valley", "Alteractal", None),
    MapDef(1460, "Warsong Gulch", "Kriegshymnenschlucht", None),
    MapDef(1461, "Arathi Basin", "Arathibecken", None),
]

BY_ID = {m.map_id: m for m in CLASSIC_MAPS}


def display_name(map_id: int | None, client_name: str | None = None) -> str:
    known = BY_ID.get(map_id) if map_id is not None else None
    if known:
        return known.de if language() == "de" else known.en
    return client_name or tr("map.unknown_map", id=map_id)


def continent_of(map_id: int, map_infos: dict | None = None) -> int | None:
    """Continent from the addon's recorded geometry, falling back to the table."""
    info = (map_infos or {}).get(map_id)
    if info is not None and info["continent_id"]:
        return info["continent_id"]
    known = BY_ID.get(map_id)
    return known.continent if known else None
