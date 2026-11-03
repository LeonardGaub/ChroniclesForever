"""The drone camera of the 3D stage: high behind and above the marker, swinging slowly behind the direction of
travel (YAW_SECONDS), looking down steeper the higher it is and turning north-up when it is far out."""

from __future__ import annotations

import math

import numpy as np

from . import gl

YAW_SECONDS = 9.0          # time constant of the swing behind the travel direction
TARGET_SECONDS = 0.6       # the look-at point trails the marker a little
DISTANCE_SECONDS = 1.5
MIN_MOVE = 2.0             # yards a frame's step must have before it counts as a direction
CLEARANCE = 25.0           # the camera stays this high above the ground under it
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

    def pitch(self) -> float:
        """Looking down: 38 degrees at drone height, steeper the further out, nearly straight down far out."""
        k = min(1.0, max(0.0, math.log10(max(self.distance, 1) / 260.0) / math.log10(40)))
        return math.radians(38 + 44 * k)

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

    def eye(self) -> np.ndarray:
        p = self.pitch()
        back = np.array([-math.cos(self.yaw), -math.sin(self.yaw), 0.0])
        eye = self.target + self.distance * (math.cos(p) * back + np.array([0, 0, math.sin(p)]))
        if self.ground is not None:
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
