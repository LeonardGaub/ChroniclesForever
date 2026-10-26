"""Time of day in the cinematic replay: the light over the map at a recorded moment (option "cine_daylight").

The map is multiplied by a colour per channel (1: unchanged): bright by day, a pink dawn, an orange dusk turning
purple, and a cold blue night. Hours are the recorded moment's local time. Between the keyframes the colour
blends smoothly.
"""

from __future__ import annotations

import datetime

DAY = (1.0, 1.0, 1.0)
NIGHT = (0.5, 0.58, 0.82)
DAWN = (1.0, 0.84, 0.8)
DUSK = (1.0, 0.8, 0.58)
TWILIGHT = (0.74, 0.64, 0.8)
# (local hour, colour), from midnight to midnight.
NIGHT_FROM, NIGHT_UNTIL = 20.5, 6.0
KEYFRAMES = ((0.0, NIGHT), (5.0, NIGHT), (6.0, DAWN), (7.2, DAY), (18.0, DAY), (19.5, DUSK), (20.5, TWILIGHT),
             (21.5, NIGHT), (24.0, NIGHT))


def hour_of(t: float) -> float:
    moment = datetime.datetime.fromtimestamp(t)
    return moment.hour + moment.minute / 60 + moment.second / 3600


def light(hour: float) -> tuple[float, float, float]:
    """The light's colour (r, g, b multipliers, 0..1) at a local hour."""
    hour %= 24.0
    for (h0, c0), (h1, c1) in zip(KEYFRAMES, KEYFRAMES[1:]):
        if h0 <= hour <= h1:
            f = (hour - h0) / (h1 - h0) if h1 > h0 else 0.0
            f = f * f * (3 - 2 * f)                       # smoothstep: no kinks at the keyframes
            return tuple(a + (b - a) * f for a, b in zip(c0, c1))
    return DAY


def light_at(t: float) -> tuple[float, float, float]:
    return light(hour_of(t))


def night(t: float) -> bool:
    """Whether the recorded moment was at night (from the dusk's twilight to dawn): the night's ambience plays."""
    hour = hour_of(t)
    return hour >= NIGHT_FROM or hour < NIGHT_UNTIL
