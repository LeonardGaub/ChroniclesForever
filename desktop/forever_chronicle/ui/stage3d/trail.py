"""The route and the marker on the 3D stage.

The route is a ribbon lying on the ground (its points draped on the terrain, a little lifted), as wide on screen
whatever the distance (the width follows the camera distance). It is painted up to the current moment, older
parts dimmer, the newest brightest, and drawn a second time faintly where the ground hides it (the X-ray pass,
for valleys behind hills and the underground cities). The marker is a camera-facing picture painted with
QPainter, standing over a soft ring of light on the ground; it is never hidden.
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

RIBBON_VS = """
in vec3 a_pos;
in vec2 a_perp;
in float a_side;
in float a_t;
uniform mat4 u_vp;
uniform float u_width;
out float v_t;
out float v_side;
void main() {
    vec3 p = a_pos + vec3(a_perp * a_side * u_width, 0.0);
    v_t = a_t;
    v_side = a_side;
    gl_Position = u_vp * vec4(p, 1.0);
}
"""

RIBBON_FS = """
in float v_t;
in float v_side;
uniform float u_now;
uniform vec3 u_color;
uniform float u_xray;
uniform float u_grey;
out vec4 o_color;
void main() {
    if (v_t > u_now) discard;
    float age = u_now - v_t;
    float fresh = exp(-age / 900.0);
    float edge = 1.0 - smoothstep(0.55, 1.0, abs(v_side));
    vec3 color = mix(u_color * 0.75, mix(u_color, vec3(1.0), 0.35), fresh);
    float lum = dot(color, vec3(0.30, 0.59, 0.11));
    color = mix(color, lum * vec3(0.72, 0.84, 1.0), u_grey);
    float alpha = (0.55 + 0.45 * fresh) * (0.35 + 0.65 * edge);
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
out vec4 o_color;
void main() {
    float d = length(v_uv);
    if (d > 1.0) discard;
    float ring = smoothstep(1.0, 0.82, d) * smoothstep(0.55 + 0.1 * u_pulse, 0.85, d);
    float glow = (1.0 - d) * 0.35;
    o_color = vec4(mix(u_color, vec3(1.0), 0.3), (ring * 0.8 + glow) * 0.9);
}
"""


def drape(points: list[tuple[float, float, float]], surface, step: float = DRAPE_STEP):
    """(t, east, north) points of one connected stretch, filled in every `step` yards and set on what the player
    stands or swims on (surface: (east, north) -> height): (t, east, north, z) rows."""
    rows = []
    for (t0, e0, n0), (t1, e1, n1) in zip(points, points[1:]):
        n = max(1, int(math.hypot(e1 - e0, n1 - n0) / step))
        for i in range(n):
            f = i / n
            e, nn = e0 + (e1 - e0) * f, n0 + (n1 - n0) * f
            rows.append((t0 + (t1 - t0) * f, e, nn, surface(e, nn) + LIFT))
    if points:
        t, e, n = points[-1]
        rows.append((t, e, n, surface(e, n) + LIFT))
    return np.array(rows, np.float64)


def ribbon(stretches: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Vertices (pos 3, perp 2, side 1, t 1) and triangle indices of the ribbons along the draped stretches."""
    verts, idx, base = [], [], 0
    for s in stretches:
        if len(s) < 2:
            continue
        d = np.gradient(s[:, 1:3], axis=0)
        length = np.linalg.norm(d, axis=1, keepdims=True)
        d = d / np.maximum(length, 1e-6)
        perp = np.stack([-d[:, 1], d[:, 0]], axis=1)
        n = len(s)
        v = np.zeros((n, 2, 7), np.float32)
        for k, side in enumerate((-1.0, 1.0)):
            v[:, k, 0:3] = s[:, 1:4]
            v[:, k, 3:5] = perp
            v[:, k, 5] = side
            v[:, k, 6] = s[:, 0]
        verts.append(v.reshape(-1, 7))
        a = base + 2 * np.arange(n - 1)
        idx.append(np.stack([a, a + 1, a + 2, a + 1, a + 3, a + 2], axis=1).ravel())
        base += 2 * n
    if not verts:
        return np.zeros((0, 7), np.float32), np.zeros(0, np.uint32)
    return np.concatenate(verts), np.concatenate(idx).astype(np.uint32)


def marker_image(color: QColor, size: int = 64) -> QImage:
    """The marker: a disc in the class colour with a dark rim and a white edge, on a soft glow."""
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
    def __init__(self, color: QColor):
        self.color = color
        self.mesh: gl.Mesh | None = None

    def initialize(self) -> None:
        self.ribbon_prog = gl.program(RIBBON_VS, RIBBON_FS)
        self.sprite_prog = gl.program(SPRITE_VS, SPRITE_FS)
        self.ring_prog = gl.program(RING_VS, RING_FS)
        quad = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], np.float32)
        self.sprite = gl.Mesh(self.sprite_prog, quad, {"a_corner": 2})
        self.ring = gl.Mesh(self.ring_prog, quad, {"a_corner": 2})
        self.marker_tex = texture(marker_image(self.color))

    def set_route(self, stretches: list[np.ndarray]) -> None:
        if self.mesh is not None:
            self.mesh.destroy()
            self.mesh = None
        verts, idx = ribbon(stretches)
        if len(idx):
            self.mesh = gl.Mesh(self.ribbon_prog, verts, {"a_pos": 3, "a_perp": 2, "a_side": 1, "a_t": 1}, indices=idx)

    def draw(self, vp, now: float, distance: float, marker, viewport, grey: float, pulse: float) -> None:
        f = gl.functions()
        rgb = (self.color.redF(), self.color.greenF(), self.color.blueF())
        gl.blend()
        if self.mesh is not None:
            p = self.ribbon_prog
            p.bind()
            gl.uniform(p, "u_vp", gl.qmatrix(vp))
            gl.uniform(p, "u_width", float(max(1.2, distance * 0.0075)))
            gl.uniform(p, "u_now", float(now))
            gl.uniform(p, "u_color", *rgb)
            gl.uniform(p, "u_grey", float(grey))
            f.glDepthMask(False)
            f.glEnable(gl.POLYGON_OFFSET_FILL)
            f.glPolygonOffset(-2.0, -4.0)
            for xray, depth in ((1.0, gl.GREATER), (0.0, gl.LEQUAL)):
                f.glDepthFunc(depth)
                gl.uniform(p, "u_xray", xray)
                self.mesh.draw()
            f.glDepthFunc(gl.LESS)
            f.glDisable(gl.POLYGON_OFFSET_FILL)
            f.glDepthMask(True)
            p.release()
        if marker is not None:
            f.glDisable(gl.DEPTH_TEST)
            r = self.ring_prog
            r.bind()
            gl.uniform(r, "u_vp", gl.qmatrix(vp))
            gl.uniform(r, "u_pos", *[float(v) for v in marker])
            gl.uniform(r, "u_radius", float(max(4.0, distance * 0.045)))
            gl.uniform(r, "u_color", *rgb)
            gl.uniform(r, "u_pulse", float(pulse))
            self.ring.draw(gl.TRIANGLE_STRIP)
            r.release()
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
