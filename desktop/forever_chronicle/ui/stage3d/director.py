"""The 3D stage's camera director: how the drone films what the cinematic is doing, on top of following it.

- In cities the drone stays higher and looks down steeper (CITY_*): the streets, Orgrimmar's canyon and the
  mesas of Thunder Bluff are seen from above, not through their walls.
- A clear view: each step the line of sight to the marker is tested against the ground and the buildings' roofs
  (TerrainPack.obstacles_many). When it is blocked, the drone takes the smallest change that clears it (a swing
  to the side, then steeper), eases into it and holds it a moment, so it does not flicker.
- Shots: entering a zone or city for the first time in the replay, the drone pulls back and turns slowly round
  the place (REVEAL_*); at a level-up, a screenshot or a death it orbits slowly while the moment holds
  (ORBIT_SPEED); on a flight path it flies low behind the flyer, swinging after it quickly (a chase camera).
- Covered: where the marker is under a roof (a hall, an upper walkway, an overhang: in Orgrimmar most of the time)
  no view is clear, so the buildings open a cone from the camera to the marker (buildings.py cut_away; CUT_*).
- During the opening, trips across the world, cloud trips and the credits it does nothing: the cinematic's own
  camera moves are the shot there.
"""

from __future__ import annotations

import math

import numpy as np

from ...domain import maps
from .camera import smooth

CITY_FARTHER, CITY_MIN = 1.8, 320.0      # in cities: this much farther, at least this many yards
CITY_PITCH = math.radians(14)
CHASE_CLOSER, CHASE_PITCH, CHASE_SWING = 0.7, math.radians(-10), 2.2   # flight paths: closer, lower, faster swing
REVEAL_SECONDS, REVEAL_PULL, REVEAL_TURN = 5.0, 1.5, math.radians(55)  # a first visit: pull back, turn round
ORBIT_SPEED, ORBIT_CLOSER = math.radians(9), 0.9                        # per second, while a moment holds
SWINGS = [math.radians(a) for a in (30, -30, 60, -60, 100, -100)]
LIFTS = [math.radians(a) for a in (10, 20, 30)]
AVOID_SECONDS, AVOID_HOLD = 0.8, 2.5
SIGHT_SAMPLES = 28
SETTLE_SECONDS = 1.5                      # the city's and the flight's distance and pitch ease in and out
CUT_RADIUS, CUT_SECONDS, COVER_ABOVE = 0.16, 0.5, 3.0   # the cut-away: share of the distance wide at the marker;
                                          # opening and closing; a roof this high over the marker covers it


def bump(f: float) -> float:
    """0 -> 1 -> 0 over f in 0..1, smooth at both ends."""
    f = min(1.0, max(0.0, f))
    return math.sin(math.pi * f) ** 2


class CameraDirector:
    def __init__(self):
        self.seen: set[int] = set()
        self.zone: int | None = None
        self.reveal: float | None = None      # age of the shot when entering a new place
        self.swing = 0.0                      # the swing aside for a clear view (smoothed) ...
        self.lift = 0.0                       # ... and the extra pitch for it
        self.wanted = (0.0, 0.0)
        self.hold = 0.0
        self.blocked = False                  # the last test (statistics)
        self.factor = 1.0                     # distance and pitch for the place (city, flight), smoothed
        self.pitch = 0.0
        self.cut = 0.0                        # how open the cut-away is (0..1)
        self.centre = 0.0                     # how much the drone centres on the marker (0..1): chases, moments
        self.covered = False

    def neutral(self, w) -> bool:
        return (w.intro is not None or w.voyage is not None or w.sky_trip is not None or w.credits is not None
                or w.ended)

    def direct(self, dt: float, w, camera, pack, marker, distance: float) -> float:
        """Sets the camera's extra pitch, swing and swing lag for the cinematic's state now; returns the distance
        to film from."""
        camera.yaw_seconds = 9.0
        covered = False
        if marker is not None:
            top = float(pack.obstacles_many(np.array([marker[0]]), np.array([marker[1]]))[0])
            covered = top > marker[2] + COVER_ABOVE
        self.covered = covered
        self.cut += ((1.0 if covered and not self.neutral(w) else 0.0) - self.cut) * smooth(dt, CUT_SECONDS)
        centred = (not self.neutral(w) and marker is not None
                   and (w.marker.mode == "taxi" or covered or w.photo_on or w.hold > 0 or w.title.isVisible()))
        self.centre += ((1.0 if centred else 0.0) - self.centre) * smooth(dt, SETTLE_SECONDS)
        if self.neutral(w) or marker is None:
            self._ease(dt, (0.0, 0.0))
            camera.extra_pitch, camera.yaw_offset = self.lift, self.swing
            self.reveal = None
            return distance
        zone = w.zone_now if w.view_map == maps.WORLD else w.view_map
        factor, pitch = 1.0, 0.0
        if zone in maps.CITIES:
            factor, pitch = max(CITY_FARTHER, CITY_MIN / max(distance, 1.0)), CITY_PITCH
        if w.marker.mode == "taxi":
            factor, pitch = factor * CHASE_CLOSER, pitch + CHASE_PITCH
            camera.yaw_seconds = CHASE_SWING
        k = smooth(dt, SETTLE_SECONDS)
        self.factor += (factor - self.factor) * k
        self.pitch += (pitch - self.pitch) * k
        distance *= self.factor
        pitch = self.pitch
        # a first visit
        if zone is not None and zone != self.zone:
            self.zone = zone
            if zone not in self.seen and w.marker.mode != "taxi":
                self.reveal = 0.0
            self.seen.add(zone)
        if self.reveal is not None:
            self.reveal += dt
            f = self.reveal / REVEAL_SECONDS
            if f >= 1:
                self.reveal = None
            else:
                distance *= 1 + (REVEAL_PULL - 1) * bump(f)
                camera.yaw += REVEAL_TURN / REVEAL_SECONDS * dt * math.sin(math.pi * f) * 2
        # a moment holds
        if w.photo_on or w.hold > 0 or w.title.isVisible():
            distance *= ORBIT_CLOSER
            camera.yaw += ORBIT_SPEED * dt
        camera.distance = distance
        if covered:                            # nothing clears it: keep the view, the cut-away opens it
            self._ease(dt, self.wanted)
        else:
            self._avoid(dt, camera, pack, np.asarray(marker, np.float64), pitch)
        camera.extra_pitch = pitch + self.lift
        camera.yaw_offset = self.swing
        return distance

    def cut_away(self, eye, marker, distance: float):
        """(from, to, radius) of the cut-away for the buildings, or None while it is closed."""
        if self.cut < 0.01 or marker is None:
            return None
        return eye, marker, CUT_RADIUS * distance * self.cut

    def _ease(self, dt: float, wanted) -> None:
        k = smooth(dt, AVOID_SECONDS)
        self.swing += (wanted[0] - self.swing) * k
        self.lift += (wanted[1] - self.lift) * k

    def _clear(self, pack, eyes: list[np.ndarray], marker: np.ndarray) -> list[bool]:
        """For each eye: True when nothing stands between it and the marker (its last yards left out)."""
        f = np.linspace(0.04, 1.0, SIGHT_SAMPLES)
        pts = []
        for eye in eyes:
            length = max(1.0, float(np.linalg.norm(marker - eye)))
            g = f * (1 - 12.0 / length)
            pts.append(eye[None] + (marker - eye)[None] * g[:, None])
        pts = np.concatenate(pts)
        high = pack.obstacles_many(pts[:, 0], pts[:, 1]).reshape(len(eyes), SIGHT_SAMPLES)
        return list((pts[:, 2].reshape(len(eyes), SIGHT_SAMPLES) > high - 2.0).all(axis=1))

    def _avoid(self, dt: float, camera, pack, marker: np.ndarray, pitch: float) -> None:
        options = [(0.0, 0.0)] + [(s, 0.0) for s in SWINGS] + [(s, lift) for lift in LIFTS for s in [0.0] + SWINGS]
        current = self.wanted
        eyes = [camera.eye_for(s, pitch + lift) for s, lift in [current] + options]
        clear = self._clear(pack, eyes, marker)
        self.blocked = not clear[1]
        self.hold = max(0.0, self.hold - dt)
        if clear[0] and (self.hold > 0 or not clear[1]):
            pass                                   # the chosen view is still clear: keep it
        elif clear[1]:
            self.wanted = (0.0, 0.0)               # the plain view is clear again
        else:
            costs = [abs(s) / math.radians(30) + lift / math.radians(10) for s, lift in options]
            best = min((c, i) for i, (c, ok) in enumerate(zip(costs, clear[1:])) if ok) if any(clear[1:]) else None
            self.wanted = options[best[1]] if best else (0.0, LIFTS[-1])
            self.hold = AVOID_HOLD
        self._ease(dt, self.wanted)
