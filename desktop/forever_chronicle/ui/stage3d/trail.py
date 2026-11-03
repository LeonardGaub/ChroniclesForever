"""The route and the ring under the marker on the 3D stage.

The route is a ribbon lying on the ground (its points draped on what the player walked or swam on, a little
lifted), as wide on screen whatever the distance (the width follows the camera distance), with a dark outline so
it reads on bright ground. Each stretch keeps the 2D route's colour (by level, by session or one colour), flight
paths are dashed with moving dashes and fly above the ridges under them, the corpse run is dotted and pale. It
is painted up to the current moment, older parts dimmer, the newest brightest, and drawn a second time faintly
where the ground hides it (the X-ray pass, for valleys behind hills and the underground cities).
Under the marker lies a soft ring of light. The marker itself, the pins and the companions are painted by
their 2D items at screen size (stage.py); the spike's sprite marker is here too.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QRadialGradient

from . import gl
from .terrain import texture

DRAPE_STEP = 6.0     # yards between draped points along the route
LIFT = 1.5           # yards above the ground (or the water: swimming, boats, zeppelins)
FLIGHT_CLEAR = 45.0  # flight paths fly this high above the highest ground near their course
FLIGHT_REACH = 300.0  # yards round each point of a flight that count as "near"
WALK, TAXI, GHOST = 0.0, 1.0, 2.0
TRAIL_SECONDS = 15 * 60
FLOATS = 12          # pos 3, perp 2, side 1, t 1, colour 3, kind 1, distance 1

RIBBON_VS = """
in vec3 a_pos;
in vec2 a_perp;
in float a_side;
in float a_t;
in vec3 a_color;
in float a_kind;
in float a_dist;
uniform mat4 u_vp;
uniform float u_width;
out float v_t;
out float v_side;
out vec3 v_color;
out float v_kind;
out float v_dist;
void main() {
    vec3 p = a_pos + vec3(a_perp * a_side * u_width, 0.0);
    v_t = a_t;
    v_side = a_side;
    v_color = a_color;
    v_kind = a_kind;
    v_dist = a_dist;
    gl_Position = u_vp * vec4(p, 1.0);
}
"""

RIBBON_FS = """
in float v_t;
in float v_side;
in vec3 v_color;
in float v_kind;
in float v_dist;
uniform float u_now;
uniform float u_xray;
uniform float u_grey;
uniform float u_outline;
uniform float u_dash;
uniform float u_phase;
uniform float u_trail;
out vec4 o_color;
void main() {
    if (v_t > u_now) discard;
    int kind = int(v_kind + 0.5);
    if (kind == 1 && fract((v_dist - u_phase) / u_dash) > 0.55) discard;      // flight paths: moving dashes
    if (kind == 2 && fract(v_dist / (u_dash * 0.45)) > 0.5) discard;          // the corpse run: dotted
    float age = u_now - v_t;
    float fresh = clamp(1.0 - age / u_trail, 0.0, 1.0);
    float newest = exp(-age / 120.0);
    float edge = 1.0 - smoothstep(0.6, 1.0, abs(v_side));
    vec3 color = v_color * (0.78 + 0.22 * fresh) + vec3(0.35) * newest;
    float alpha = (0.52 + 0.48 * fresh) * (0.45 + 0.55 * edge);
    if (u_outline > 0.5) {
        color = vec3(0.05, 0.035, 0.02);
        alpha = (0.35 + 0.35 * fresh) * (1.0 - smoothstep(0.75, 1.0, abs(v_side)));
    }
    float lum = dot(color, vec3(0.30, 0.59, 0.11));
    color = mix(color, lum * vec3(0.72, 0.84, 1.0), u_grey);
    o_color = vec4(color, alpha * mix(1.0, 0.28, u_xray));
}
"""

SPRITE_VS = """
in vec2 a_corner;
uniform mat4 u_vp;
uniform vec3 u_pos;
uniform vec2 u_size;
uniform vec2 u_viewport;
out vec2 v_uv;
void main() {
    vec4 clip = u_vp * vec4(u_pos, 1.0);
    clip.xy += a_corner * u_size / u_viewport * 2.0 * clip.w;
    v_uv = vec2(a_corner.x * 0.5 + 0.5, 0.5 - a_corner.y * 0.5);
    gl_Position = clip;
}
"""

SPRITE_FS = """
in vec2 v_uv;
uniform sampler2D u_tex;
out vec4 o_color;
void main() {
    vec4 c = texture(u_tex, v_uv);
    if (c.a < 0.01) discard;
    o_color = c;
}
"""

RING_VS = """
in vec2 a_corner;
uniform mat4 u_vp;
uniform vec3 u_pos;
uniform float u_radius;
out vec2 v_uv;
void main() {
    v_uv = a_corner;
    gl_Position = u_vp * vec4(u_pos + vec3(a_corner * u_radius, 0.0), 1.0);
}
"""

RING_FS = """
in vec2 v_uv;
uniform vec3 u_color;
uniform float u_pulse;
uniform float u_grey;
out vec4 o_color;
void main() {
    float d = length(v_uv);
    if (d > 1.0) discard;
    float ring = smoothstep(1.0, 0.82, d) * smoothstep(0.55 + 0.1 * u_pulse, 0.85, d);
    float glow = (1.0 - d) * 0.35;
    vec3 color = mix(u_color, vec3(1.0), 0.3);
    float lum = dot(color, vec3(0.30, 0.59, 0.11));
    o_color = vec4(mix(color, lum * vec3(0.72, 0.84, 1.0), u_grey), (ring * 0.8 + glow) * 0.9);
}
"""


def drape(points, surface, step: float = DRAPE_STEP) -> np.ndarray:
    """Points of one connected stretch (rows t, east, north[, extra columns: colour, kind ...]) filled in every
    `step` yards and set on what the player stands or swims on (surface: arrays of east, north -> heights). A
    filled-in point takes the extra columns of the point its line runs to. Rows: t, east, north, z, extras."""
    pts = np.asarray(points, np.float64)
    if len(pts) == 0:
        return np.zeros((0, 4), np.float64)
    if len(pts) == 1:
        rows = pts[:, :3]
        extras = pts[:, 3:]
    else:
        seg = np.diff(pts[:, 1:3], axis=0)
        counts = np.maximum(1, (np.hypot(seg[:, 0], seg[:, 1]) / step).astype(np.int64))
        which = np.repeat(np.arange(len(counts)), counts)
        f = (np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)) / counts[which]
        a, b = pts[which], pts[which + 1]
        rows = np.vstack([a[:, :3] + (b[:, :3] - a[:, :3]) * f[:, None], pts[-1:, :3]])
        extras = np.vstack([np.where((f > 0)[:, None], b[:, 3:], a[:, 3:]), pts[-1:, 3:]])
    z = surface(rows[:, 1], rows[:, 2]) + LIFT
    return np.column_stack([rows, z, extras])


def flight_heights(rows: np.ndarray, step: float = DRAPE_STEP) -> np.ndarray:
    """z of a flight path's draped points: FLIGHT_CLEAR over the highest ground within FLIGHT_REACH, smoothed
    so the flight rises and sinks calmly."""
    z = rows[:, 3]
    reach = max(1, int(FLIGHT_REACH / step))
    padded = np.pad(z, reach, mode="edge")
    high = np.lib.stride_tricks.sliding_window_view(padded, 2 * reach + 1).max(axis=1)
    kernel = np.ones(reach) / reach
    smooth = np.convolve(np.pad(high, reach, mode="edge"), kernel, mode="same")[reach:-reach]
    return np.maximum(smooth, high) + FLIGHT_CLEAR


def ribbon(stretches: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (FLOATS each) and triangle indices of the ribbons along the draped stretches (rows t, east, north,
    z[, r, g, b, kind]; without colours white walking)."""
    verts, idx, base = [], [], 0
    for s in stretches:
        if len(s) < 2:
            continue
        d = np.gradient(s[:, 1:3], axis=0)
        length = np.linalg.norm(d, axis=1, keepdims=True)
        d = d / np.maximum(length, 1e-6)
        perp = np.stack([-d[:, 1], d[:, 0]], axis=1)
        steps = np.linalg.norm(np.diff(s[:, 1:3], axis=0), axis=1)
        dist = np.concatenate([[0.0], np.cumsum(steps)])
        extra = s[:, 4:8] if s.shape[1] >= 8 else np.tile([1.0, 1.0, 1.0, WALK], (len(s), 1))
        n = len(s)
        v = np.zeros((n, 2, FLOATS), np.float32)
        for k, side in enumerate((-1.0, 1.0)):
            v[:, k, 0:3] = s[:, 1:4]
            v[:, k, 3:5] = perp
            v[:, k, 5] = side
            v[:, k, 6] = s[:, 0]
            v[:, k, 7:11] = extra
            v[:, k, 11] = dist
        verts.append(v.reshape(-1, FLOATS))
        a = base + 2 * np.arange(n - 1)
        idx.append(np.stack([a, a + 1, a + 2, a + 1, a + 3, a + 2], axis=1).ravel())
        base += 2 * n
    if not verts:
        return np.zeros((0, FLOATS), np.float32), np.zeros(0, np.uint32)
    return np.concatenate(verts), np.concatenate(idx).astype(np.uint32)


def marker_image(color: QColor, size: int = 64) -> QImage:
    """The spike's marker: a disc in the class colour with a dark rim and a white edge, on a soft glow."""
    img = QImage(size, size, QImage.Format.Format_RGBA8888)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QPointF(size / 2, size / 2)
    glow = QRadialGradient(c, size / 2)
    glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 160))
    glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(c, size / 2, size / 2)
    p.setBrush(color)
    p.setPen(QPen(QColor(20, 14, 8), size * 0.05))
    p.drawEllipse(c, size * 0.2, size * 0.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(255, 255, 255, 220), size * 0.03))
    p.drawEllipse(c, size * 0.245, size * 0.245)
    p.end()
    return img


class Trail:
    def __init__(self, color: QColor, sprite: bool = False):
        self.color = color
        self.sprite_marker = sprite         # the spike draws its own marker; the cinematic paints MarkerItem
        self.mesh: gl.Mesh | None = None
        self.phase = 0.0

    def initialize(self) -> None:
        self.ribbon_prog = gl.program(RIBBON_VS, RIBBON_FS)
        self.ring_prog = gl.program(RING_VS, RING_FS)
        quad = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], np.float32)
        self.ring = gl.Mesh(self.ring_prog, quad, {"a_corner": 2})
        if self.sprite_marker:
            self.sprite_prog = gl.program(SPRITE_VS, SPRITE_FS)
            self.sprite = gl.Mesh(self.sprite_prog, quad, {"a_corner": 2})
            self.marker_tex = texture(marker_image(self.color))

    def set_route(self, stretches: list[np.ndarray]) -> None:
        if self.mesh is not None:
            self.mesh.destroy()
            self.mesh = None
        verts, idx = ribbon(stretches)
        if len(idx):
            self.mesh = gl.Mesh(self.ribbon_prog, verts, {"a_pos": 3, "a_perp": 2, "a_side": 1, "a_t": 1,
                                                          "a_color": 3, "a_kind": 1, "a_dist": 1}, indices=idx)

    def draw(self, vp, now: float, distance: float, marker, viewport, grey: float, pulse: float,
             ring_color: QColor | None = None, dt: float = 0.0) -> None:
        f = gl.functions()
        gl.blend()
        width = float(max(1.2, 0.8 + distance * 0.0045))
        self.phase = (self.phase + dt * width * 4.0) % 1e6
        if self.mesh is not None:
            p = self.ribbon_prog
            p.bind()
            gl.uniform(p, "u_vp", gl.qmatrix(vp))
            gl.uniform(p, "u_now", float(now))
            gl.uniform(p, "u_grey", float(grey))
            gl.uniform(p, "u_dash", width * 7.0)
            gl.uniform(p, "u_phase", float(self.phase))
            gl.uniform(p, "u_trail", float(TRAIL_SECONDS))
            f.glDepthMask(False)
            f.glEnable(gl.POLYGON_OFFSET_FILL)
            f.glPolygonOffset(-2.0, -4.0)
            for xray, depth in ((1.0, gl.GREATER), (0.0, gl.LEQUAL)):
                f.glDepthFunc(depth)
                gl.uniform(p, "u_xray", xray)
                for outline, w in ((1.0, width * 1.5), (0.0, width)):
                    gl.uniform(p, "u_outline", outline)
                    gl.uniform(p, "u_width", w)
                    self.mesh.draw()
            f.glDepthFunc(gl.LESS)
            f.glDisable(gl.POLYGON_OFFSET_FILL)
            f.glDepthMask(True)
            p.release()
        if marker is not None:
            color = ring_color or self.color
            f.glDisable(gl.DEPTH_TEST)
            r = self.ring_prog
            r.bind()
            gl.uniform(r, "u_vp", gl.qmatrix(vp))
            gl.uniform(r, "u_pos", *[float(v) for v in marker])
            gl.uniform(r, "u_radius", float(max(4.0, distance * 0.045)))
            gl.uniform(r, "u_color", color.redF(), color.greenF(), color.blueF())
            gl.uniform(r, "u_pulse", float(pulse))
            gl.uniform(r, "u_grey", float(grey))
            self.ring.draw(gl.TRIANGLE_STRIP)
            r.release()
            if self.sprite_marker:
                s = self.sprite_prog
                s.bind()
                gl.uniform(s, "u_vp", gl.qmatrix(vp))
                gl.uniform(s, "u_pos", float(marker[0]), float(marker[1]), float(marker[2]) + 3.0)
                gl.uniform(s, "u_size", 26.0, 26.0)
                gl.uniform(s, "u_viewport", float(viewport[0]), float(viewport[1]))
                gl.uniform(s, "u_tex", 0)
                self.marker_tex.bind(0)
                self.sprite.draw(gl.TRIANGLE_STRIP)
                s.release()
            f.glEnable(gl.DEPTH_TEST)
        gl.blend(False)
