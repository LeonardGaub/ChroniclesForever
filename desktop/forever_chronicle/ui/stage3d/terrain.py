"""The ground of the 3D stage: the worlds of the terrain pack (domain/terrain.py) in one shared world.

Per world (a layer):
- Far view: the whole world as one coarse mesh (17 x 17 vertices per tile) under its overview picture, and its
  liquids (lakes, rivers, the sea along the coast, lava) as a coarse surface.
- Near view: the full tiles (129 x 129 vertices, the 512 px minimap picture, the game's liquid cells) in a ring
  round the camera's target, loaded by a worker thread and uploaded a few per frame. Where a near tile is in, the
  far meshes are left out.
Round them all, the open sea at sea level to the horizon over a dark sea floor, drawn only off the tiles (on the
tiles the game's own liquids are the sea, so ground below sea level inland stays dry). Islands in the sky
(Zephras Isle) float over a sea of clouds instead.
Light: the minimap pictures already hold the artists' shading, so the sun only adds a soft relief on top. Haze
fades the distance into the sky colour (atmosphere, not a fog of war).
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
from PySide6.QtGui import QColor, QImage
from PySide6.QtOpenGL import QOpenGLTexture

from ...domain.terrain import TILE_YARDS, TerrainPack, tile_of, tile_origin
from . import gl
from .look import Look

NEAR_RADIUS = 2           # tiles round the target's tile kept at full detail (5 x 5)
KEEP_RADIUS = 3           # loaded tiles further away are dropped
UPLOADS_PER_FRAME = 2
MAX_NEAR = 49
SEA_FLOOR = -40.0         # far mesh height where the world has no tile
CLOUDS_BELOW = 600.0      # the sea of clouds lies this far under an island in the sky's usual ground (its rocky
                          # underside reaches down into it)
SKY_ZONE = 12000.0        # round an island in the sky there is no sea, only clouds
SEA, FLOOR, CLOUDS = 0, 1, 2

COMMON = """
uniform vec3 u_eye;
uniform vec3 u_sky;
uniform float u_haze;
uniform float u_grey;
uniform int u_far;
uniform vec2 u_offset;
uniform float u_tile;
uniform int u_near_count;
uniform ivec2 u_near[%(max_near)d];
vec3 finish(vec3 color, vec3 pos) {
    float f = 1.0 - exp(-length(pos - u_eye) * u_haze);
    color = mix(color, u_sky, clamp(f, 0.0, 0.9));
    float lum = dot(color, vec3(0.30, 0.59, 0.11));
    return mix(color, lum * vec3(0.72, 0.84, 1.0), u_grey);
}
bool under_near(vec3 pos) {
    if (u_far == 0) return false;
    ivec2 t = ivec2(floor((pos.x - u_offset.x) / u_tile + 32.0), floor(32.0 - (pos.y - u_offset.y) / u_tile));
    for (int i = 0; i < u_near_count; ++i)
        if (u_near[i] == t) return true;
    return false;
}
""" % {"max_near": MAX_NEAR}

GRID_VS = """
uniform mat4 u_vp;
uniform vec2 u_origin;
uniform float u_step;
uniform int u_cols;
vec3 grid_pos(float h) {
    int c = gl_VertexID % u_cols;
    int r = gl_VertexID / u_cols;
    return vec3(u_origin.x + float(c) * u_step, u_origin.y - float(r) * u_step, h);
}
vec2 grid_cr() {
    return vec2(float(gl_VertexID % u_cols), float(gl_VertexID / u_cols));
}
"""

GROUND_VS = GRID_VS + """
in float a_h;
in vec3 a_n;
uniform vec2 u_uv_scale;
out vec2 v_uv;
out vec3 v_n;
out vec3 v_pos;
void main() {
    vec3 p = grid_pos(a_h);
    v_uv = grid_cr() * u_uv_scale;
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
uniform vec3 u_ambient;
uniform vec3 u_deep;
uniform int u_void;
out vec4 o_color;
void main() {
    if (under_near(v_pos)) discard;
    vec3 color = texture(u_tex, v_uv).rgb;
    if (dot(color, vec3(1.0)) < 0.09) {                    // the minimap's black open sea, or no tile here;
        if (u_void == 1) discard;                          // round an island in the sky: nothing (the clouds)
        color = u_deep;
    }
    float diffuse = max(dot(normalize(v_n), u_sun), 0.0);
    color *= u_ambient + u_light * 0.55 * diffuse;
    o_color = vec4(finish(color, v_pos), 1.0);
}
"""

LIQUID_VS = GRID_VS + """
in float a_h;
in float a_kind;
out vec3 v_pos;
out float v_kind;
void main() {
    vec3 p = grid_pos(a_h);
    v_pos = p;
    v_kind = a_kind;
    gl_Position = u_vp * vec4(p, 1.0);
}
"""

LIQUID_FS = COMMON + """
in vec3 v_pos;
in float v_kind;
uniform vec3 u_water;
uniform float u_light;
uniform float u_time;
out vec4 o_color;
void main() {
    if (under_near(v_pos)) discard;
    vec3 view = normalize(u_eye - v_pos);
    float glance = pow(1.0 - max(view.z, 0.0), 3.0);
    int kind = int(v_kind + 0.5);
    vec3 color;
    float alpha;
    if (kind == 3) {            // magma: glows by itself
        float flow = 0.5 + 0.5 * sin(v_pos.x * 0.05 + u_time * 0.7) * sin(v_pos.y * 0.04 - u_time * 0.5);
        color = mix(vec3(0.95, 0.30, 0.05), vec3(1.0, 0.72, 0.25), flow);
        alpha = 1.0;
        o_color = vec4(mix(color, u_sky, clamp(1.0 - exp(-length(v_pos - u_eye) * u_haze), 0.0, 0.6)), alpha);
        return;
    } else if (kind == 4) {     // slime
        color = vec3(0.32, 0.55, 0.12) * (0.4 + 0.6 * u_light);
        alpha = 0.9;
    } else {
        color = mix(u_water * (0.35 + 0.65 * u_light), u_sky, 0.45 * glance);
        alpha = 0.85;
    }
    o_color = vec4(finish(color, v_pos), alpha);
}
"""

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
uniform float u_light;
uniform int u_mode;            // 0 sea, 1 sea floor, 2 clouds under an island in the sky
uniform int u_masks;
uniform sampler2D u_mask0;
uniform sampler2D u_mask1;
uniform sampler2D u_mask2;
uniform vec2 u_mask_offset[3];
uniform vec4 u_sky_zone;       // centre, radius, on
out vec4 o_color;
bool on_tiles(sampler2D mask, vec2 offset) {
    vec2 t = vec2((v_pos.x - offset.x) / u_tile + 32.0, 32.0 - (v_pos.y - offset.y) / u_tile);
    if (t.x < 0.0 || t.y < 0.0 || t.x >= 64.0 || t.y >= 64.0) return false;
    return texture(mask, t / 64.0).r > 0.5;
}
void main() {
    bool in_sky = u_sky_zone.w > 0.5 && distance(v_pos.xy, u_sky_zone.xy) < u_sky_zone.z;
    if (u_mode == 2) {
        if (!in_sky) discard;
        float puff = 0.5 + 0.25 * sin(v_pos.x * 0.004) * sin(v_pos.y * 0.0035) + 0.25 * sin(v_pos.x * 0.011 + v_pos.y * 0.007);
        vec3 color = mix(vec3(0.80, 0.84, 0.90), vec3(1.0), puff) * (0.45 + 0.55 * u_light);
        o_color = vec4(finish(color, v_pos), 1.0);
        return;
    }
    if (in_sky) discard;
    if (u_mode == 0) {
        if (u_masks > 0 && on_tiles(u_mask0, u_mask_offset[0])) discard;
        if (u_masks > 1 && on_tiles(u_mask1, u_mask_offset[1])) discard;
        if (u_masks > 2 && on_tiles(u_mask2, u_mask_offset[2])) discard;
    }
    vec3 view = normalize(u_eye - v_pos);
    float glance = pow(1.0 - max(view.z, 0.0), 3.0) * u_alpha;
    vec3 color = mix(u_water * (0.35 + 0.65 * u_light), u_sky, 0.45 * glance);
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
uniform vec3 u_sun;
uniform vec3 u_sun_color;
uniform float u_stars;
uniform float u_grey;
out vec4 o_color;
float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
void main() {
    vec4 a = u_inv_vp * vec4(v_ndc, -1.0, 1.0);
    vec4 b = u_inv_vp * vec4(v_ndc, 1.0, 1.0);
    vec3 dir = normalize(b.xyz / b.w - a.xyz / a.w);
    vec3 color = mix(u_horizon, u_zenith, smoothstep(-0.02, 0.45, dir.z));
    float sun = max(dot(dir, u_sun), 0.0);
    color += u_sun_color * (pow(sun, 900.0) * 1.5 + pow(sun, 12.0) * 0.25);
    if (u_stars > 0.0 && dir.z > 0.0) {
        vec3 cell = floor(dir * 300.0);
        float s = hash(cell);
        color += vec3(step(0.9975, s) * u_stars * smoothstep(0.0, 0.25, dir.z));
    }
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


def liquid_mesh(heights: np.ndarray, kinds: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Vertices (height, kind) of a liquid grid ((n+1) x (n+1) heights, NaN where dry; n x n kinds per cell) and
    the triangles of its wet cells."""
    rows, cols = kinds.shape
    wet = np.argwhere(kinds > 0)
    if not len(wet):
        return None
    vkind = np.zeros(heights.shape, np.float32)
    for dr in (0, 1):
        for dc in (0, 1):
            vkind[dr:dr + rows, dc:dc + cols] = np.maximum(vkind[dr:dr + rows, dc:dc + cols], kinds)
    verts = np.stack([np.nan_to_num(heights, nan=0.0), vkind], axis=-1).reshape(-1, 2).astype(np.float32)
    stride = cols + 1
    a = wet[:, 0] * stride + wet[:, 1]
    b, d = a + 1, a + stride
    tris = np.stack([a, d, b, b, d, d + 1], axis=1).ravel()
    return verts, tris.astype(np.uint32)


def texture(image: QImage, nearest: bool = False) -> QOpenGLTexture:
    tex = QOpenGLTexture(image.convertToFormat(QImage.Format.Format_RGBA8888),
                         QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps if nearest
                         else QOpenGLTexture.MipMapGeneration.GenerateMipMaps)
    if nearest:
        tex.setMinMagFilters(QOpenGLTexture.Filter.Nearest, QOpenGLTexture.Filter.Nearest)
    else:
        tex.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear, QOpenGLTexture.Filter.Linear)
        tex.setMaximumAnisotropy(8.0)
    tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
    return tex


class _Tile:
    def __init__(self, key, mesh: gl.Mesh, tex: QOpenGLTexture, origin, water: gl.Mesh | None):
        self.key, self.mesh, self.tex, self.origin, self.water = key, mesh, tex, origin, water

    def destroy(self) -> None:
        self.mesh.destroy()
        self.tex.destroy()
        if self.water is not None:
            self.water.destroy()


class _Layer:
    """One world of the pack: far meshes, near tiles, its tile mask for the sea."""

    def __init__(self, pack: TerrainPack, world: int):
        self.pack, self.world = pack, world
        self.continent = pack.continents[world]
        self.near: dict[tuple[int, int], _Tile] = {}
        self.loading: dict[tuple[int, int], Future] = {}
        self.sky_island = pack.sky_island(world)

    def initialize(self, ground: gl.QOpenGLShaderProgram, liquid: gl.QOpenGLShaderProgram) -> None:
        heights, picture = self.pack.overview(self.world)
        w_heights, w_kinds = self.pack.overview_liquids(self.world)
        txs = [tx for tx, _ in self.continent.tiles]
        tys = [ty for _, ty in self.continent.tiles]
        self.tx0, self.ty0 = min(txs), min(tys)
        ntx, nty = max(txs) - self.tx0 + 1, max(tys) - self.ty0 + 1
        grid = np.full((nty * 16 + 1, ntx * 16 + 1), np.nan, np.float32)
        water = np.full(grid.shape, np.nan, np.float32)
        kinds = np.zeros((nty * 16, ntx * 16), np.uint8)
        for (tx, ty) in self.continent.tiles:
            r, c = (ty - self.ty0) * 16, (tx - self.tx0) * 16
            for target, block in ((grid, heights[ty, tx]), (water, w_heights[ty, tx])):
                here = target[r:r + 17, c:c + 17]
                target[r:r + 17, c:c + 17] = np.where(np.isnan(here), block, here)
            kinds[r:r + 16, c:c + 16] = w_kinds[ty, tx]
        missing = np.isnan(grid)
        grid = np.where(missing, SEA_FLOOR, grid)
        self.cols = grid.shape[1]
        self.step = TILE_YARDS / 16
        indices = gl.grid_indices(*grid.shape)
        if self.sky_island:             # it floats: no ground where it has no tiles
            hole = missing.ravel()
            indices = indices.reshape(-1, 3)[~hole[indices.reshape(-1, 3)].any(axis=1)].ravel()
        self.far = gl.Mesh(ground, vertices(grid, self.step), {"a_h": 1, "a_n": 3}, indices=indices)
        liquids = liquid_mesh(water, kinds)
        self.far_water = None if liquids is None else gl.Mesh(liquid, liquids[0], {"a_h": 1, "a_kind": 1},
                                                              indices=liquids[1])
        image = QImage(str(picture))
        px = image.width() // 64
        self.far_tex = texture(image.copy(self.tx0 * px, self.ty0 * px, ntx * px, nty * px))
        self.far_uv = (1 / (ntx * 16), 1 / (nty * 16))
        mask = QImage(64, 64, QImage.Format.Format_Grayscale8)
        mask.fill(0)
        for (tx, ty) in self.continent.tiles:
            mask.setPixelColor(tx, ty, QColor(255, 255, 255))
        self.mask = texture(mask, nearest=True)
        e0, n0 = tile_origin(self.tx0, self.ty0)
        self.far_origin = (e0 + self.continent.offset[0], n0 + self.continent.offset[1])
        if self.sky_island:
            lows = sorted(lo for lo, _ in self.continent.tiles.values())
            low = lows[len(lows) // 2]
            e1, n1 = tile_origin(max(txs) + 1, max(tys) + 1)
            self.centre = ((self.far_origin[0] + e1 + self.continent.offset[0]) / 2,
                           (self.far_origin[1] + n1 + self.continent.offset[1]) / 2)
            self.clouds_z = low - CLOUDS_BELOW

    def origin(self, key) -> tuple[float, float]:
        e0, n0 = tile_origin(*key)
        return e0 + self.continent.offset[0], n0 + self.continent.offset[1]

    def contains(self, east: float, north: float) -> bool:
        wx, wy = self.pack.unshared(self.world, east, north)
        tx, ty, _, _ = tile_of(wx, wy)
        return (tx, ty) in self.continent.tiles

    def destroy(self) -> None:
        for tile in self.near.values():
            tile.destroy()
        self.near.clear()


class TerrainRenderer:
    def __init__(self, pack: TerrainPack, worlds: list[int] | None = None):
        self.pack = pack
        self.layers = [_Layer(pack, w) for w in (worlds if worlds is not None else list(pack.continents))]
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="terrain")
        self.uploaded = 0             # tiles uploaded so far (statistics)
        self.active: _Layer | None = None

    @property
    def near(self) -> dict:
        return self.active.near if self.active else {}

    @property
    def loading(self) -> dict:
        return self.active.loading if self.active else {}

    # -- set-up (GL context current) -------------------------------------------------------------------------

    def initialize(self) -> None:
        self.ground = gl.program(GROUND_VS, GROUND_FS)
        self.liquid = gl.program(LIQUID_VS, LIQUID_FS)
        self.sea_prog = gl.program(SEA_VS, SEA_FS)
        self.sky_prog = gl.program(SKY_VS, SKY_FS)
        self.tile_indices = gl.IndexOnly(gl.grid_indices(129, 129))
        for layer in self.layers:
            layer.initialize(self.ground, self.liquid)
        r = 400000.0
        self.sea = gl.Mesh(self.sea_prog, np.array([[-r, -r], [r, -r], [-r, r], [r, r]], np.float32), {"a_xy": 2})
        self.sky = gl.Mesh(self.sky_prog, np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], np.float32), {"a_xy": 2})

    # -- streaming ------------------------------------------------------------------------------------------

    @staticmethod
    def _load(pack: TerrainPack, world: int, tx: int, ty: int):
        h = pack.heights(world, tx, ty)
        image = QImage(str(pack.tile_path(world, "m", tx, ty)))
        liquids = pack.liquids(world, tx, ty)
        water = liquid_mesh(*liquids) if liquids is not None else None
        return vertices(h, TILE_YARDS / 128), image.convertToFormat(QImage.Format.Format_RGBA8888), water

    def layer_at(self, east: float, north: float) -> _Layer | None:
        return next((layer for layer in self.layers if layer.contains(east, north)), None)

    def update(self, east: float, north: float) -> None:
        """Keeps the near ring round (east, north) loaded (in the world there); uploads what the worker has
        finished; drops what is out of reach."""
        layer = self.layer_at(east, north) or self.active
        if layer is not self.active and self.active is not None:
            self.active.destroy()
            for f in self.active.loading.values():
                f.cancel()
            self.active.loading.clear()
        self.active = layer
        if layer is None:
            return
        wx, wy = self.pack.unshared(layer.world, east, north)
        cx, cy, _, _ = tile_of(wx, wy)
        wanted = sorted(((tx, ty) for tx in range(cx - NEAR_RADIUS, cx + NEAR_RADIUS + 1)
                         for ty in range(cy - NEAR_RADIUS, cy + NEAR_RADIUS + 1) if (tx, ty) in layer.continent.tiles),
                        key=lambda k: (k[0] - cx) ** 2 + (k[1] - cy) ** 2)
        for key in wanted:
            if key not in layer.near and key not in layer.loading:
                layer.loading[key] = self.pool.submit(self._load, self.pack, layer.world, *key)
        uploads = 0
        for key in [k for k, f in layer.loading.items() if f.done()]:
            if uploads >= UPLOADS_PER_FRAME:
                break
            future = layer.loading.pop(key)
            if future.cancelled():
                continue
            verts, image, water = future.result()
            mesh = gl.Mesh(self.ground, verts, {"a_h": 1, "a_n": 3}, shared_indices=self.tile_indices)
            wmesh = None if water is None else gl.Mesh(self.liquid, water[0], {"a_h": 1, "a_kind": 1}, indices=water[1])
            layer.near[key] = _Tile(key, mesh, texture(image), layer.origin(key), wmesh)
            uploads += 1
            self.uploaded += 1
        for key in [k for k in layer.near if max(abs(k[0] - cx), abs(k[1] - cy)) > KEEP_RADIUS]:
            layer.near.pop(key).destroy()

    # -- drawing --------------------------------------------------------------------------------------------

    def _common(self, prog, eye, look: Look, layer: _Layer | None, far: bool) -> None:
        gl.uniform(prog, "u_eye", *[float(v) for v in eye])
        gl.uniform(prog, "u_sky", *look.horizon)
        gl.uniform(prog, "u_haze", float(look.haze))
        gl.uniform(prog, "u_grey", float(look.grey))
        gl.uniform(prog, "u_tile", float(TILE_YARDS))
        gl.uniform(prog, "u_light", float(look.light))
        keys = list(layer.near)[:MAX_NEAR] if (far and layer is self.active and layer is not None) else []
        gl.uniform(prog, "u_far", int(bool(keys)))
        gl.uniform(prog, "u_near_count", len(keys))
        for i, (tx, ty) in enumerate(keys):
            gl.uniform(prog, f"u_near[{i}]", tx, ty)
        if layer is not None:
            gl.uniform(prog, "u_offset", *[float(v) for v in layer.continent.offset])
        gl.uniform(prog, "u_void", int(layer is not None and layer.sky_island))

    def draw_sky(self, inv_vp, look: Look) -> None:
        f = gl.functions()
        f.glDisable(gl.DEPTH_TEST)
        p = self.sky_prog
        p.bind()
        gl.uniform(p, "u_inv_vp", gl.qmatrix(inv_vp))
        gl.uniform(p, "u_horizon", *look.horizon)
        gl.uniform(p, "u_zenith", *look.zenith)
        gl.uniform(p, "u_sun", *[float(v) for v in look.sun])
        gl.uniform(p, "u_sun_color", *look.sun_color)
        gl.uniform(p, "u_stars", float(look.stars))
        gl.uniform(p, "u_grey", float(look.grey))
        self.sky.draw(gl.TRIANGLE_STRIP)
        p.release()
        f.glEnable(gl.DEPTH_TEST)

    def draw(self, vp, eye, look: Look, time: float = 0.0) -> None:
        f = gl.functions()
        qvp = gl.qmatrix(vp)
        deep = [look.deep * v for v in look.water]
        # ground: near tiles, then every layer's far mesh round them
        p = self.ground
        p.bind()
        gl.uniform(p, "u_vp", qvp)
        gl.uniform(p, "u_sun", *[float(v) for v in look.sun])
        gl.uniform(p, "u_ambient", *look.ambient)
        gl.uniform(p, "u_deep", *deep)
        gl.uniform(p, "u_tex", 0)
        if self.active is not None:
            self._common(p, eye, look, self.active, far=False)
            gl.uniform(p, "u_step", float(TILE_YARDS / 128))
            gl.uniform(p, "u_cols", 129)
            gl.uniform(p, "u_uv_scale", 1 / 128, 1 / 128)
            for tile in self.active.near.values():
                gl.uniform(p, "u_origin", *tile.origin)
                tile.tex.bind(0)
                tile.mesh.draw()
        for layer in self.layers:
            self._common(p, eye, look, layer, far=True)
            gl.uniform(p, "u_origin", *layer.far_origin)
            gl.uniform(p, "u_step", float(layer.step))
            gl.uniform(p, "u_cols", int(layer.cols))
            gl.uniform(p, "u_uv_scale", *layer.far_uv)
            layer.far_tex.bind(0)
            layer.far.draw()
        p.release()
        # sea floor and clouds (opaque), then liquids and the open sea (blended)
        s = self.sea_prog
        s.bind()
        gl.uniform(s, "u_vp", qvp)
        self._common(s, eye, look, None, far=False)
        for i, layer in enumerate(self.layers[:3]):
            gl.uniform(s, f"u_mask_offset[{i}]", *[float(v) for v in layer.continent.offset])
            layer.mask.bind(1 + i)
            gl.uniform(s, f"u_mask{i}", 1 + i)
        gl.uniform(s, "u_masks", min(3, len(self.layers)))
        island = next((layer for layer in self.layers if layer.sky_island), None)
        if island is not None:
            gl.uniform(s, "u_sky_zone", *island.centre, SKY_ZONE, 1.0)
        else:
            gl.uniform(s, "u_sky_zone", 0.0, 0.0, 0.0, 0.0)
        gl.uniform(s, "u_water", *deep)
        gl.uniform(s, "u_alpha", 1.0)
        gl.uniform(s, "u_mode", FLOOR)
        gl.uniform(s, "u_z", SEA_FLOOR - 1.0)
        self.sea.draw(gl.TRIANGLE_STRIP)
        if island is not None:
            gl.uniform(s, "u_mode", CLOUDS)
            gl.uniform(s, "u_z", float(island.clouds_z))
            self.sea.draw(gl.TRIANGLE_STRIP)
        s.release()
        gl.blend()
        f.glDepthMask(False)
        q = self.liquid
        q.bind()
        gl.uniform(q, "u_vp", qvp)
        gl.uniform(q, "u_water", *look.water)
        gl.uniform(q, "u_time", float(time))
        if self.active is not None:
            self._common(q, eye, look, self.active, far=False)
            gl.uniform(q, "u_step", float(TILE_YARDS / 128))
            gl.uniform(q, "u_cols", 129)
            for tile in self.active.near.values():
                if tile.water is not None:
                    gl.uniform(q, "u_origin", *tile.origin)
                    tile.water.draw()
        for layer in self.layers:
            if layer.far_water is None:
                continue
            self._common(q, eye, look, layer, far=True)
            gl.uniform(q, "u_origin", *layer.far_origin)
            gl.uniform(q, "u_step", float(layer.step))
            gl.uniform(q, "u_cols", int(layer.cols))
            layer.far_water.draw()
        q.release()
        s.bind()
        gl.uniform(s, "u_water", *look.water)
        gl.uniform(s, "u_alpha", 0.85)
        gl.uniform(s, "u_mode", SEA)
        gl.uniform(s, "u_z", 0.0)
        self.sea.draw(gl.TRIANGLE_STRIP)
        s.release()
        f.glDepthMask(True)
        gl.blend(False)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        for layer in self.layers:
            layer.destroy()
