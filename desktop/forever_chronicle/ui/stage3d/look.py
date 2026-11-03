"""How the 3D stage looks at a moment: sky, sun, light, haze, water and the spirit world's grey. The cinematic sets
it from the recorded local time (sky.py); the default is a clear midday."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _unit(v) -> np.ndarray:
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


@dataclass
class Look:
    horizon: tuple[float, float, float] = (0.80, 0.86, 0.92)
    zenith: tuple[float, float, float] = (0.32, 0.50, 0.78)
    sun: np.ndarray = field(default_factory=lambda: _unit([-0.45, 0.55, 0.70]))
    sun_color: tuple[float, float, float] = (1.0, 0.95, 0.85)
    light: float = 1.0                                   # sunlight (0 at night)
    ambient: tuple[float, float, float] = (0.62, 0.62, 0.62)
    stars: float = 0.0
    haze: float = 1 / 6600                               # per yard
    grey: float = 0.0                                    # the spirit world (0..1)
    water: tuple[float, float, float] = (0.10, 0.27, 0.36)
    deep: float = 0.45                                   # the sea floor: the water's colour, this much darker
