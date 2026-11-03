"""The drone camera of the 3D stage: high behind and above the marker, swinging slowly behind the direction of
travel (YAW_SECONDS), looking down steeper the higher it is and turning north-up when it is far out.

In hilly land the camera floats over the ground instead of riding it: the height it looks at follows the ground
slowly (HEIGHT_SECONDS), and the clearance over the ground under the camera, judged over a patch round it, rises
quickly before a ridge (RISE_SECONDS) and sinks slowly after it (SINK_SECONDS)."""

from __future__ import annotations

import math

import numpy as np

from . import gl

YAW_SECONDS = 9.0          # time constant of the swing behind the travel direction
TARGET_SECONDS = 0.6       # the look-at point trails the marker a little
DISTANCE_SECONDS = 1.5
MIN_MOVE = 2.0             # yards a frame's step must have before it counts as a direction
CLEARANCE = 25.0           # the camera stays this high above the ground under it
HEIGHT_SECONDS = 1.1       # the looked-at height following the ground
RISE_SECONDS, SINK_SECONDS = 0.35, 1.8   # the clearance rising before a ridge, sinking after it
PATCH = 0.12               # the ground under the camera counts this share of the distance round it
NORTH_UP_FROM = 2500.0     # from this distance on the camera turns north-up
FOV = math.radians(50)


def smooth(dt: float, tau: float) -> float:
    return 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0


def angle_diff(a: float, b: float) -> float:
    return (b - a + math.pi) % (2 * math.pi) - math.pi


class DroneCamera:
    def __init__(self, distance: float = 260.0):
        self.target: np.ndarray | None = None
        self.yaw = math.pi / 2          # heading the camera looks along (0 = east, pi/2 = north)
        self.distance = distance
        self.wanted_distance = distance
        self._last: np.ndarray | None = None
        self.ground = None              # (east, north) -> ground height
        self._z: float | None = None    # the looked-at height (smoothed)
        self._floor: float | None = None  # the lowest the camera may go (smoothed)
        # Set by the director (director.py) each step: steeper, swung aside, a lag of its own for the swing.
        self.extra_pitch = 0.0
        self.yaw_offset = 0.0
        self.yaw_seconds = YAW_SECONDS

    def pitch(self) -> float:
        """Looking down: 38 degrees at drone height, steeper the further out, nearly straight down far out."""
        k = min(1.0, max(0.0, math.log10(max(self.distance, 1) / 260.0) / math.log10(40)))
        return min(math.radians(84), math.radians(38 + 44 * k) + self.extra_pitch)

    def jump(self, marker: np.ndarray) -> None:
        self.target = np.array(marker, np.float64)
        self._last = self.target.copy()
        self.distance = self.wanted_distance

    def update(self, dt: float, marker: np.ndarray, ground) -> None:
        marker = np.asarray(marker, np.float64)
        if self.target is None:
            self.jump(marker)
        step = marker - self._last
        if math.hypot(step[0], step[1]) > MIN_MOVE:
            heading = math.atan2(step[1], step[0])
            self.yaw += angle_diff(self.yaw, heading) * smooth(dt, YAW_SECONDS)
            self._last = marker.copy()
        if self.distance > NORTH_UP_FROM:
            north_up = min(1.0, (self.distance - NORTH_UP_FROM) / NORTH_UP_FROM)
            self.yaw += angle_diff(self.yaw, math.pi / 2) * north_up * smooth(dt, 1.0)
        self.target += (marker - self.target) * smooth(dt, TARGET_SECONDS)
        self.distance *= (self.wanted_distance / self.distance) ** smooth(dt, DISTANCE_SECONDS)
        self.ground = ground

    def follow(self, dt: float, target: np.ndarray, distance: float, marker: np.ndarray | None, ground,
               jump: bool = False) -> None:
        """Takes the cinematic's camera as it is (its centre and how much it shows, both already smoothed there) and
        only adds the drone's swing behind the marker's direction of travel."""
        target = np.array(target, np.float64)
        if jump or self.target is None:
            self._last = None
            self._z = self._floor = None
        self._z = target[2] if self._z is None else self._z + (target[2] - self._z) * smooth(dt, HEIGHT_SECONDS)
        target[2] = self._z
        self.target = target
        self.distance = self.wanted_distance = distance
        self.ground = ground
        self._follow_floor(dt)
        if marker is not None:
            marker = np.asarray(marker, np.float64)
            if self._last is None:
                self._last = marker.copy()
            step = marker - self._last
            if math.hypot(step[0], step[1]) > MIN_MOVE and not jump:
                self.yaw += angle_diff(self.yaw, math.atan2(step[1], step[0])) * smooth(dt, self.yaw_seconds)
                self._last = marker.copy()
            elif jump:
                self._last = marker.copy()
        if self.distance > NORTH_UP_FROM:
            north_up = min(1.0, (self.distance - NORTH_UP_FROM) / NORTH_UP_FROM)
            self.yaw += angle_diff(self.yaw, math.pi / 2) * north_up * smooth(dt, 1.0)

    def _free_eye(self) -> np.ndarray:
        return self.eye_for(self.yaw_offset, self.extra_pitch)

    def eye_for(self, yaw_offset: float, extra_pitch: float, distance: float | None = None) -> np.ndarray:
        """Where the camera would be with this swing and pitch (and distance), before keeping it off the ground."""
        saved, self.extra_pitch = self.extra_pitch, extra_pitch
        if distance is not None:
            saved_d, self.distance = self.distance, distance
        p = self.pitch()
        self.extra_pitch = saved
        d = self.distance
        if distance is not None:
            self.distance = saved_d
        yaw = self.yaw + yaw_offset
        back = np.array([-math.cos(yaw), -math.sin(yaw), 0.0])
        return self.target + d * (math.cos(p) * back + np.array([0, 0, math.sin(p)]))

    def _follow_floor(self, dt: float) -> None:
        """The lowest the camera may go: CLEARANCE over the highest ground in a patch round it, smoothed."""
        if self.ground is None:
            return
        eye = self._free_eye()
        r = PATCH * self.distance
        high = max(self.ground(eye[0] + dx, eye[1] + dy) for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)))
        wanted = high + CLEARANCE
        if self._floor is None:
            self._floor = wanted
        else:
            tau = RISE_SECONDS if wanted > self._floor else SINK_SECONDS
            self._floor += (wanted - self._floor) * smooth(dt, tau)

    def eye(self) -> np.ndarray:
        eye = self._free_eye()
        if self._floor is not None:
            eye[2] = max(eye[2], self._floor)
        elif self.ground is not None:
            eye[2] = max(eye[2], self.ground(eye[0], eye[1]) + CLEARANCE)
        return eye

    def matrices(self, aspect: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(view-projection, its inverse, eye)."""
        eye = self.eye()
        view = gl.look_at(eye, self.target)
        near = max(1.0, self.distance * 0.02)
        proj = gl.perspective(FOV, aspect, near, self.distance * 40 + 30000)
        vp = proj @ view
        return vp, np.linalg.inv(vp), eye
