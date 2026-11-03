"""The ground of the 3D stage: one continent from the terrain pack (domain/terrain.py).

- Far view: the whole continent as one coarse mesh (17 x 17 vertices per tile) under its overview picture.
- Near view: the full tiles (129 x 129 vertices, the 512 px minimap picture) in a ring round the camera's target,
  loaded by a worker thread and uploaded a few per frame. Where a near tile is in, the far mesh is left out.
- The sea: a plane at sea level (z = 0) to the horizon over a dark sea floor (the far mesh's tile-less parts
  take the floor's colour, so the open sea looks alike everywhere); the sky: a gradient from the horizon up.
Light: the minimap pictures already hold the artists' shading, so the sun only adds a soft relief on top. Haze
fades the distance into the sky colour (atmosphere, not a fog of war).
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLTexture

from ...domain.terrain import TILE_YARDS, TerrainPack, tile_of, tile_origin
from . import gl

NEAR_RADIUS = 2           # tiles round the target's tile kept at full detail (5 x 5)
KEEP_RADIUS = 3           # loaded tiles further away are dropped
UPLOADS_PER_FRAME = 2
MAX_NEAR = 49
SEA_FLOOR = -40.0         # far mesh height where the continent has no tile
DEEP = 0.45               # the sea floor's colour: the water's, this much darker

COMMON = """
uniform vec3 u_eye;
uniform vec3 u_sky;
uniform float u_haze;
uniform float u_grey;
vec3 finish(vec3 color, vec3 pos) {
    float f = 1.0 - exp(-length(pos - u_eye) * u_haze);
    color = mix(color, u_sky, clamp(f, 0.0, 0.9));
    float lum = dot(color, vec3(0.30, 0.59, 0.11));
    return mix(color, lum * vec3(0.72, 0.84, 1.0), u_grey);
}
"""

GROUND_VS = """
in float a_h;
in vec3 a_n;
uniform mat4 u_vp;
uniform vec2 u_origin;
uniform float u_step;
uniform int u_cols;
uniform vec2 u_uv_scale;
out vec2 v_uv;
out vec3 v_n;
out vec3 v_pos;
void main() {
    int c = gl_VertexID % u_cols;
    int r = gl_VertexID / u_cols;
    vec3 p = vec3(u_origin.x + float(c) * u_step, u_origin.y - float(r) * u_step, a_h);
    v_uv = vec2(float(c), float(r)) * u_uv_scale;
    v_n = a_n;
    v_pos = p;
    gl_Position = u_vp * vec4(p, 1.0);
}
"""

GROUND_FS = COMMON + """
in vec2 v_uv;
in vec3 v_n;
in vec3 v_pos;
uniform sampler2D u_tex;
uniform vec3 u_sun;
uniform float u_light;
uniform int u_far;
uniform vec2 u_offset;
uniform float u_tile;
uniform int u_near_count;
uniform ivec2 u_near[%(max_near)d];
uniform vec3 u_deep;
out vec4 o_color;
void main() {
    vec3 color = texture(u_tex, v_uv).rgb;
    if (u_far == 1) {
        ivec2 t = ivec2(floor((v_pos.x - u_offset.x) / u_tile + 32.0), floor(32.0 - (v_pos.y - u_offset.y) / u_tile));
        for (int i = 0; i < u_near_count; ++i)
            if (u_near[i] == t) discard;
        if (dot(color, vec3(1.0)) < 0.04) color = u_deep;     // no tile here: open sea
    }
    float diffuse = max(dot(normalize(v_n), u_sun), 0.0);
    color *= u_light * (0.62 + 0.55 * diffuse);
    o_color = vec4(finish(color, v_pos), 1.0);
}
""" % {"max_near": MAX_NEAR}

SEA_VS = """
in vec2 a_xy;
uniform mat4 u_vp;
uniform float u_z;
out vec3 v_pos;
void main() {
    v_pos = vec3(a_xy, u_z);
    gl_Position = u_vp * vec4(v_pos, 1.0);
}
"""

SEA_FS = COMMON + """
in vec3 v_pos;
uniform vec3 u_water;
uniform float u_alpha;
out vec4 o_color;
void main() {
    vec3 view = normalize(u_eye - v_pos);
    float glance = pow(1.0 - max(view.z, 0.0), 3.0) * u_alpha;
    vec3 color = mix(u_water, u_sky, 0.45 * glance);
    o_color = vec4(finish(color, v_pos), u_alpha);
}
"""

SKY_VS = """
in vec2 a_xy;
out vec2 v_ndc;
void main() {
    v_ndc = a_xy;
    gl_Position = vec4(a_xy, 1.0, 1.0);
}
"""

SKY_FS = """
in vec2 v_ndc;
uniform mat4 u_inv_vp;
uniform vec3 u_horizon;
uniform vec3 u_zenith;
uniform float u_grey;
out vec4 o_color;
void main() {
    vec4 a = u_inv_vp * vec4(v_ndc, -1.0, 1.0);
    vec4 b = u_inv_vp * vec4(v_ndc, 1.0, 1.0);
    vec3 dir = normalize(b.xyz / b.w - a.xyz / a.w);
    vec3 color = mix(u_horizon, u_zenith, smoothstep(-0.02, 0.45, dir.z));
    float lum = dot(color, vec3(0.30, 0.59, 0.11));
    o_color = vec4(mix(color, lum * vec3(0.72, 0.84, 1.0), u_grey), 1.0);
}
"""


def normals(h: np.ndarray, step: float) -> np.ndarray:
    """Vertex normals of a height grid (rows north to south, columns west to east)."""
    d_row, d_col = np.gradient(h, step)
    n = np.stack([-d_col, d_row, np.ones_like(h)], axis=-1)       # d/d_north = -d/d_row
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def vertices(h: np.ndarray, step: float) -> np.ndarray:
    return np.concatenate([h[..., None], normals(h, step)], axis=-1).reshape(-1, 4).astype(np.float32)


def texture(image: QImage) -> QOpenGLTexture:
    tex = QOpenGLTexture(image.convertToFormat(QImage.Format.Format_RGBA8888),
                         QOpenGLTexture.MipMapGeneration.GenerateMipMaps)
    tex.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
    tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
    tex.setMaximumAnisotropy(8.0)
    return tex


class _Tile:
    def __init__(self, key, mesh: gl.Mesh, tex: QOpenGLTexture, origin):
        self.key, self.mesh, self.tex, self.origin = key, mesh, tex, origin

    def destroy(self) -> None:
        self.mesh.destroy()
        self.tex.destroy()


class TerrainRenderer:
    def __init__(self, pack: TerrainPack, world: int):
        self.pack = pack
        self.world = world
        self.continent = pack.continents[world]
        self.near: dict[tuple[int, int], _Tile] = {}
        self.loading: dict[tuple[int, int], Future] = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="terrain")
        self.light = 1.0
        self.uploaded = 0             # tiles uploaded so far (the spike's statistics)

    # -- set-up (GL context current) -------------------------------------------------------------------------

    def initialize(self) -> None:
        self.ground = gl.program(GROUND_VS, GROUND_FS)
        self.sea_prog = gl.program(SEA_VS, SEA_FS)
        self.sky_prog = gl.program(SKY_VS, SKY_FS)
        self.tile_indices = gl.IndexOnly(gl.grid_indices(129, 129))
        self._build_far()
        r = 200000.0
        self.sea = gl.Mesh(self.sea_prog, np.array([[-r, -r], [r, -r], [-r, r], [r, r]], np.float32), {"a_xy": 2})
        self.sky = gl.Mesh(self.sky_prog, np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], np.float32), {"a_xy": 2})

    def _build_far(self) -> None:
        heights, picture = self.pack.overview(self.world)
        txs = [tx for tx, _ in self.continent.tiles]
        tys = [ty for _, ty in self.continent.tiles]
        self.far_tx0, self.far_ty0 = min(txs), min(tys)
        ntx, nty = max(txs) - self.far_tx0 + 1, max(tys) - self.far_ty0 + 1
        grid = np.full((nty * 16 + 1, ntx * 16 + 1), np.nan, np.float32)
        for (tx, ty) in self.continent.tiles:
            r, c = (ty - self.far_ty0) * 16, (tx - self.far_tx0) * 16
            block = heights[ty, tx]
            here = grid[r:r + 17, c:c + 17]
            grid[r:r + 17, c:c + 17] = np.where(np.isnan(here), block, here)
        grid = np.where(np.isnan(grid), SEA_FLOOR, grid)
        self.far_cols = grid.shape[1]
        self.far_step = TILE_YARDS / 16
        self.far = gl.Mesh(self.ground, vertices(grid, self.far_step), {"a_h": 1, "a_n": 3},
                           indices=gl.grid_indices(*grid.shape))
        image = QImage(str(picture))
        px = image.width() // 64
        self.far_tex = texture(image.copy(self.far_tx0 * px, self.far_ty0 * px, ntx * px, nty * px))
        self.far_uv = (1 / (ntx * 16), 1 / (nty * 16))

    # -- streaming ------------------------------------------------------------------------------------------

    @staticmethod
    def _load(pack: TerrainPack, world: int, tx: int, ty: int):
        h = pack.heights(world, tx, ty)
        image = QImage(str(pack.tile_path(world, "m", tx, ty)))
        return vertices(h, TILE_YARDS / 128), image.convertToFormat(QImage.Format.Format_RGBA8888)

    def tile_at(self, east: float, north: float) -> tuple[int, int]:
        wx, wy = self.pack.unshared(self.world, east, north)
        tx, ty, _, _ = tile_of(wx, wy)
        return tx, ty

    def update(self, east: float, north: float) -> None:
        """Keeps the near ring round (east, north) loaded; uploads what the worker has finished."""
        cx, cy = self.tile_at(east, north)
        wanted = sorted(((tx, ty) for tx in range(cx - NEAR_RADIUS, cx + NEAR_RADIUS + 1)
                         for ty in range(cy - NEAR_RADIUS, cy + NEAR_RADIUS + 1) if (tx, ty) in self.continent.tiles),
                        key=lambda k: (k[0] - cx) ** 2 + (k[1] - cy) ** 2)
        for key in wanted:
            if key not in self.near and key not in self.loading:
                self.loading[key] = self.pool.submit(self._load, self.pack, self.world, *key)
        uploads = 0
        for key in [k for k, f in self.loading.items() if f.done()]:
            future = self.loading.pop(key)
            if uploads >= UPLOADS_PER_FRAME:
                self.loading[key] = future
                continue
            verts, image = future.result()
            mesh = gl.Mesh(self.ground, verts, {"a_h": 1, "a_n": 3}, shared_indices=self.tile_indices)
            e0, n0 = tile_origin(*key)
            origin = (e0 + self.continent.offset[0], n0 + self.continent.offset[1])
            self.near[key] = _Tile(key, mesh, texture(image), origin)
            uploads += 1
            self.uploaded += 1
        for key in [k for k in self.near if max(abs(k[0] - cx), abs(k[1] - cy)) > KEEP_RADIUS]:
            self.near.pop(key).destroy()

    # -- drawing --------------------------------------------------------------------------------------------

    def _common(self, prog, eye, sky, haze, grey) -> None:
        gl.uniform(prog, "u_eye", *[float(v) for v in eye])
        gl.uniform(prog, "u_sky", *sky)
        gl.uniform(prog, "u_haze", float(haze))
        gl.uniform(prog, "u_grey", float(grey))

    def draw_sky(self, inv_vp, horizon, zenith, grey) -> None:
        f = gl.functions()
        f.glDisable(gl.DEPTH_TEST)
        p = self.sky_prog
        p.bind()
        gl.uniform(p, "u_inv_vp", gl.qmatrix(inv_vp))
        gl.uniform(p, "u_horizon", *horizon)
        gl.uniform(p, "u_zenith", *zenith)
        gl.uniform(p, "u_grey", float(grey))
        self.sky.draw(gl.TRIANGLE_STRIP)
        p.release()
        f.glEnable(gl.DEPTH_TEST)

    def draw(self, vp, eye, sun, sky, haze, grey, water) -> None:
        f = gl.functions()
        p = self.ground
        p.bind()
        gl.uniform(p, "u_vp", gl.qmatrix(vp))
        self._common(p, eye, sky, haze, grey)
        gl.uniform(p, "u_sun", *[float(v) for v in sun])
        gl.uniform(p, "u_light", float(self.light))
        gl.uniform(p, "u_tex", 0)
        gl.uniform(p, "u_tile", float(TILE_YARDS))
        gl.uniform(p, "u_offset", *[float(v) for v in self.continent.offset])
        gl.uniform(p, "u_deep", *[DEEP * v for v in water])
        # near tiles
        gl.uniform(p, "u_far", 0)
        gl.uniform(p, "u_step", float(TILE_YARDS / 128))
        gl.uniform(p, "u_cols", 129)
        gl.uniform(p, "u_uv_scale", 1 / 128, 1 / 128)
        for tile in self.near.values():
            gl.uniform(p, "u_origin", *tile.origin)
            tile.tex.bind(0)
            tile.mesh.draw()
        # far mesh round them
        keys = list(self.near)[:MAX_NEAR]
        gl.uniform(p, "u_far", 1)
        gl.uniform(p, "u_near_count", len(keys))
        for i, (tx, ty) in enumerate(keys):
            gl.uniform(p, f"u_near[{i}]", tx, ty)
        e0, n0 = tile_origin(self.far_tx0, self.far_ty0)
        gl.uniform(p, "u_origin", e0 + self.continent.offset[0], n0 + self.continent.offset[1])
        gl.uniform(p, "u_step", float(self.far_step))
        gl.uniform(p, "u_cols", int(self.far_cols))
        gl.uniform(p, "u_uv_scale", *self.far_uv)
        self.far_tex.bind(0)
        self.far.draw()
        p.release()
        # sea floor, then the sea over it
        s = self.sea_prog
        s.bind()
        gl.uniform(s, "u_vp", gl.qmatrix(vp))
        self._common(s, eye, sky, haze, grey)
        gl.uniform(s, "u_water", *[DEEP * v for v in water])
        gl.uniform(s, "u_z", SEA_FLOOR - 1.0)
        gl.uniform(s, "u_alpha", 1.0)
        self.sea.draw(gl.TRIANGLE_STRIP)
        gl.blend()
        gl.uniform(s, "u_water", *water)
        gl.uniform(s, "u_z", 0.0)
        gl.uniform(s, "u_alpha", 0.78)
        self.sea.draw(gl.TRIANGLE_STRIP)
        s.release()
        gl.blend(False)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        for tile in self.near.values():
            tile.destroy()
        self.near.clear()
