"""Classic map table: uiMapID, artwork name, German/English names and continent.

Forever uses the Classic uiMapIDs (confirmed in Phase 0: 1413 The Barrens, 1414 Kalimdor, 1454 Orgrimmar).
The artwork names match the files in the user's map art archive ("Explored zones/<art>.jpg").
All artwork uses the world map canvas of 1002 x 668 pixels; map coordinates are normalized to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..i18n import language, tr

ART_WIDTH, ART_HEIGHT = 1002, 668
WORLD, KALIMDOR, EASTERN_KINGDOMS = 947, 1414, 1415
CONTINENTS = (KALIMDOR, EASTERN_KINGDOMS)
# Where each continent's map lies on the world map (min_x, max_x, min_y, max_y; may reach past its edges).
# Found by matching the continent map art onto the world map art, so the pictures line up when one fades into
# the other (cinematic mode); the game itself does not tell the addon these.
CONTINENT_ON_WORLD = {KALIMDOR: (-0.1808, 0.6346, 0.0681, 0.8835),
                      EASTERN_KINGDOMS: (0.3937, 1.1399, 0.1184, 0.8646)}


@dataclass(frozen=True)
class MapDef:
    map_id: int
    art: str
    en: str
    de: str
    continent: int | None


_K, _E = KALIMDOR, EASTERN_KINGDOMS
CLASSIC_MAPS = [
    MapDef(947, "world", "Azeroth", "Azeroth", None),
    MapDef(1414, "kalimdor", "Kalimdor", "Kalimdor", None),
    MapDef(1415, "easternkingdoms", "Eastern Kingdoms", "Östliche Königreiche", None),
    MapDef(1411, "durotar", "Durotar", "Durotar", _K),
    MapDef(1412, "mulgore", "Mulgore", "Mulgore", _K),
    MapDef(1413, "barrens", "The Barrens", "Brachland", _K),
    MapDef(1438, "teldrassil", "Teldrassil", "Teldrassil", _K),
    MapDef(1439, "darkshore", "Darkshore", "Dunkelküste", _K),
    MapDef(1440, "ashenvale", "Ashenvale", "Eschental", _K),
    MapDef(1441, "1kneedles", "Thousand Needles", "Tausend Nadeln", _K),
    MapDef(1442, "stonetalon", "Stonetalon Mountains", "Steinkrallengebirge", _K),
    MapDef(1443, "desolace", "Desolace", "Desolace", _K),
    MapDef(1444, "feralas", "Feralas", "Feralas", _K),
    MapDef(1445, "dustwallowmarsh", "Dustwallow Marsh", "Düstermarschen", _K),
    MapDef(1446, "tanaris", "Tanaris", "Tanaris", _K),
    MapDef(1447, "azshara", "Azshara", "Azshara", _K),
    MapDef(1448, "felwood", "Felwood", "Teufelswald", _K),
    MapDef(1449, "ungorocrater", "Un'Goro Crater", "Krater von Un'Goro", _K),
    MapDef(1450, "moonglade", "Moonglade", "Mondlichtung", _K),
    MapDef(1451, "silithus", "Silithus", "Silithus", _K),
    MapDef(1452, "winterspring", "Winterspring", "Winterquell", _K),
    MapDef(1454, "orgrimmar", "Orgrimmar", "Orgrimmar", _K),
    MapDef(1456, "thunderbluff", "Thunder Bluff", "Donnerfels", _K),
    MapDef(1457, "darnassus", "Darnassus", "Darnassus", _K),
    MapDef(1416, "alterac", "Alterac Mountains", "Alteracgebirge", _E),
    MapDef(1417, "arathi", "Arathi Highlands", "Arathihochland", _E),
    MapDef(1418, "badlands", "Badlands", "Ödland", _E),
    MapDef(1419, "blastedlands", "Blasted Lands", "Verwüstete Lande", _E),
    MapDef(1420, "tirisfal", "Tirisfal Glades", "Tirisfal", _E),
    MapDef(1421, "silverpine", "Silverpine Forest", "Silberwald", _E),
    MapDef(1422, "wplaguelands", "Western Plaguelands", "Westliche Pestländer", _E),
    MapDef(1423, "eplaguelands", "Eastern Plaguelands", "Östliche Pestländer", _E),
    MapDef(1424, "hillsbrad", "Hillsbrad Foothills", "Vorgebirge des Hügellands", _E),
    MapDef(1425, "hinterlands", "The Hinterlands", "Hinterland", _E),
    MapDef(1426, "dunmorogh", "Dun Morogh", "Dun Morogh", _E),
    MapDef(1427, "searinggorge", "Searing Gorge", "Sengende Schlucht", _E),
    MapDef(1428, "burningsteppes", "Burning Steppes", "Brennende Steppe", _E),
    MapDef(1429, "elwynn", "Elwynn Forest", "Wald von Elwynn", _E),
    MapDef(1430, "deadwindpass", "Deadwind Pass", "Gebirgspass der Totenwinde", _E),
    MapDef(1431, "duskwood", "Duskwood", "Dämmerwald", _E),
    MapDef(1432, "lochmodan", "Loch Modan", "Loch Modan", _E),
    MapDef(1433, "redridge", "Redridge Mountains", "Rotkammgebirge", _E),
    MapDef(1434, "stranglethorn", "Stranglethorn Vale", "Schlingendorntal", _E),
    MapDef(1435, "swampofsorrows", "Swamp of Sorrows", "Sümpfe des Elends", _E),
    MapDef(1436, "westfall", "Westfall", "Westfall", _E),
    MapDef(1437, "wetlands", "Wetlands", "Sumpfland", _E),
    MapDef(1453, "stormwind", "Stormwind City", "Sturmwind", _E),
    MapDef(1455, "ironforge", "Ironforge", "Eisenschmiede", _E),
    MapDef(1458, "undercity", "Undercity", "Unterstadt", _E),
    MapDef(1459, "alteracvalley", "Alterac Valley", "Alteractal", None),
    MapDef(1460, "warsonggulch", "Warsong Gulch", "Kriegshymnenschlucht", None),
    MapDef(1461, "arathibasin", "Arathi Basin", "Arathibecken", None),
]

BY_ID = {m.map_id: m for m in CLASSIC_MAPS}
BY_ART = {m.art: m for m in CLASSIC_MAPS}


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
