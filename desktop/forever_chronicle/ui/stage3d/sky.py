"""The sky of the 3D stage at a recorded moment: the sun's path over the local day, the colours from the 2D
cinematic's light (domain/daylight.py, so both modes agree: a pink dawn, an orange dusk, a cold blue night),
the moon and stars at night. With the time of day switched off it is always early afternoon."""

from __future__ import annotations

import math

import numpy as np

from ...domain import daylight
from .look import Look

SUNRISE, SUNSET = 6.0, 20.0
NOON_ELEVATION = math.radians(62)
DAY_HORIZON, DAY_ZENITH = np.array([0.80, 0.86, 0.92]), np.array([0.32, 0.50, 0.78])
NIGHT_HORIZON, NIGHT_ZENITH = np.array([0.10, 0.13, 0.24]), np.array([0.02, 0.04, 0.11])
WARM_HORIZON = np.array([1.0, 0.62, 0.40])
SUN_DAY, SUN_LOW, MOON = np.array([1.0, 0.95, 0.85]), np.array([1.0, 0.58, 0.32]), np.array([0.55, 0.65, 0.9])
WATER = np.array([0.10, 0.27, 0.36])
AFTERNOON = 14.0


def _body(hour: float, rise: float, length: float) -> np.ndarray:
    """Direction to a body crossing the sky from east (at rise) over the south to west (rise + length hours)."""
    a = ((hour - rise) % 24.0) / length * math.pi
    elevation = math.sin(min(max(a, 0.0), math.pi)) * NOON_ELEVATION
    v = np.array([math.cos(a), -0.45 * math.sin(a), math.tan(max(elevation, math.radians(3)))])
    return v / np.linalg.norm(v)


def look_for(hour: float | None, light: tuple[float, float, float], grey: float, distance: float) -> Look:
    """The look at a local hour (None: the time of day is off) under the 2D light colour."""
    if hour is None:
        hour, light = AFTERNOON, daylight.DAY
    rgb = np.array(light, np.float64)
    lum = float(rgb @ np.array([0.30, 0.59, 0.11]))
    night = min(1.0, max(0.0, (0.86 - lum) / 0.22))
    warm = min(1.0, max(0.0, (rgb[0] - rgb[2]) * 2.4)) * (1 - night)
    day = SUNRISE <= hour % 24 <= SUNSET
    sun = _body(hour, SUNRISE, SUNSET - SUNRISE) if day else _body(hour, SUNSET, 24 - SUNSET + SUNRISE)
    low = 1 - min(1.0, sun[2] / 0.5)
    horizon = (DAY_HORIZON * (1 - warm) + WARM_HORIZON * warm) * (1 - night) + NIGHT_HORIZON * night
    zenith = DAY_ZENITH * (1 - night) + NIGHT_ZENITH * night
    sun_color = MOON if not day else SUN_DAY * (1 - low) + SUN_LOW * low
    sunlight = (1 - night) * (0.55 + 0.45 * (1 - low)) if day else 0.25 * night
    ambient = rgb * (0.62 - 0.18 * night)
    return Look(horizon=tuple(horizon), zenith=tuple(zenith), sun=sun, sun_color=tuple(sun_color),
                light=max(0.2, sunlight), ambient=tuple(ambient), stars=night, haze=1.0 / (distance * 10 + 4000),
                grey=grey, water=tuple(WATER * (0.45 + 0.55 * (1 - night))))
