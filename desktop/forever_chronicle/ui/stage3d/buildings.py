"""The buildings of the 3D stage (WMO from the terrain pack: houses, towers, bridges, city walls, the cities).

Which: those whose box comes within the near ring round the camera, and the big ones (cities, keeps) from further
away; none far out, where they would be specks. Their meshes are decoded by a worker thread and uploaded a few
hundred thousand vertices a frame; meshes not drawn for a while are dropped.
How they look: in the game's own textures, read from the player's install (textures.py), batch by batch, alpha-cut
where the game cuts them (fences, banners, leaves); with the game's baked shade of each vertex and the sun. Until a
texture is there, or without the game files, a batch takes its colours from the minimap pictures under it, as the
ground does: the roofs as the map paints them, the walls in the colour of their foot, darker the steeper they
stand.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from ...domain.terrain import TILE_YARDS, TerrainPack
from . import gl
from .look import Look
from .terrain import COMMON, TerrainRenderer

REACH = (1.5, 2.5, 3.5)    # tiles round the camera's target: close up, wider, high up (terrain.NEAR/WIDE radius)
BIG, BIG_REACH = 250.0, 3.0  # buildings at least this many yards across are drawn this many reaches away
HIDE_FROM = 6000.0         # camera distance from which no buildings are drawn
UPLOAD_VERTICES = 150_000  # per frame
KEEP_FRAMES = 900          # a mesh not drawn this many frames is dropped
ATLAS_UNIT, FAR_UNIT, TEX_UNIT = 5, 6, 0
ALPHA_KEY = 1              # a batch's blend mode: alpha-cut

VS = """
in vec3 a_pos;
in vec3 a_n;
in float a_shade;
in vec2 a_uv;
uniform mat4 u_vp;
uniform mat4 u_model;
out vec3 v_pos;
out vec3 v_n;
out float v_shade;
out vec2 v_uv;
void main() {
    vec4 p = u_model * vec4(a_pos, 1.0);
    v_pos = p.xyz;
    v_n = mat3(u_model) * a_n;
    v_shade = a_shade;
    v_uv = a_uv;
    gl_Position = u_vp * p;
}
"""

FS = COMMON + """
in vec3 v_pos;
in vec3 v_n;
in float v_shade;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform int u_textured;         // 1: the batch's own texture is bound
uniform int u_cutout;           // 1: alpha-cut (fences, banners, leaves)
uniform sampler2D u_atlas;
uniform vec4 u_atlas_rect;      // west, north, size (yards), on
uniform sampler2D u_far_map;
uniform vec4 u_far_rect;        // west, north, width, height (yards)
uniform vec3 u_sun;
uniform float u_light;
uniform vec3 u_cut_from;        // the cut-away (director.py): a cone from the camera to the marker ...
uniform vec3 u_cut_to;
uniform float u_cut_radius;     // ... this wide at the marker; 0: none
uniform vec3 u_ambient;
uniform vec3 u_deep;
out vec4 o_color;
float cut_away(vec3 p) {
    // 1 inside the cone between the camera and the marker (it opens the roofs over a covered marker), with a
    // dithered soft edge.
    if (u_cut_radius <= 0.0) return 0.0;
    vec3 axis = u_cut_to - u_cut_from;
    float t = dot(p - u_cut_from, axis) / dot(axis, axis);
    if (t <= 0.0 || t >= 0.985) return 0.0;
    float r = u_cut_radius * (0.35 + 0.65 * t);
    float off = length(p - (u_cut_from + axis * t));
    return 1.0 - smoothstep(r * 0.75, r, off);
}
float dither(vec2 frag) {
    return fract(52.9829189 * fract(dot(frag, vec2(0.06711056, 0.00583715))));
}
void main() {
    if (cut_away(v_pos) > dither(gl_FragCoord.xy)) discard;
    vec3 n = normalize(v_n);
    if (n.z < 0.0) n = -n;                     // both sides lit alike (roofs seen from below, open walls)
    float steep = 1.0 - abs(n.z);
    vec3 color;
    if (u_textured == 1) {
        vec4 t = texture(u_tex, v_uv);
        if (u_cutout == 1 && t.a < 0.5) discard;
        color = t.rgb * v_shade * 1.15;
    } else {
        vec2 a = vec2(v_pos.x - u_atlas_rect.x, u_atlas_rect.y - v_pos.y) / u_atlas_rect.z;
        vec4 c = vec4(0.0);
        if (u_atlas_rect.w > 0.5 && a.x >= 0.0 && a.y >= 0.0 && a.x <= 1.0 && a.y <= 1.0)
            c = texture(u_atlas, a);
        if (c.a < 0.5) {
            vec2 f = vec2(v_pos.x - u_far_rect.x, u_far_rect.y - v_pos.y) / u_far_rect.zw;
            c = vec4(texture(u_far_map, clamp(f, 0.0, 1.0)).rgb, 1.0);
        }
        color = c.rgb;
        if (dot(color, vec3(1.0)) < 0.09) color = vec3(0.32, 0.3, 0.28);   // over the minimap's black: stone
        color *= v_shade * mix(1.0, 0.72, steep);
    }
    float diffuse = max(dot(n, u_sun), 0.0);
    color *= u_ambient + u_light * 0.55 * diffuse;
    o_color = vec4(finish(color, v_pos), 1.0);
}
"""


def model_matrix(linear: np.ndarray, shift: np.ndarray) -> np.ndarray:
    m = np.identity(4)
    m[:3, :3] = linear
    m[:3, 3] = shift
    return m


class BuildingRenderer:
    def __init__(self, pack: TerrainPack, terrain: TerrainRenderer, textures=None):
        """textures: the game's textures (textures.GameTextures), None to draw everything in the minimap's colours."""
        self.pack, self.terrain, self.textures = pack, terrain, textures
        self.batches: dict[int, np.ndarray] = {}
        self.meshes: dict[int, gl.Mesh] = {}
        self.loading: dict[int, Future] = {}
        self.used: dict[int, int] = {}
        self.frame = 0
        self.visible: list[int] = []
        self.world: int | None = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="buildings")
        self.drawn = 0                      # buildings drawn in the last picture (statistics)

    def initialize(self) -> None:
        self.prog = gl.program(VS, FS)

    @staticmethod
    def _decode(pack: TerrainPack, fdid: int):
        pos, nrm, shade, idx, uv, batches = pack.building_mesh(fdid)
        return np.concatenate([pos, nrm, shade[:, None], uv], axis=1).astype(np.float32), idx, batches

    def update(self, east: float, north: float, distance: float) -> None:
        """Chooses the buildings round (east, north) for the camera at this distance; loads and uploads meshes."""
        self.frame += 1
        layer = self.terrain.active
        if layer is None or distance >= HIDE_FROM:
            self.visible = []
            return
        self.world = layer.world
        b = self.pack.buildings(layer.world)
        if not len(b):
            self.visible = []
            return
        from .terrain import HIGH_FROM, WIDE_FROM
        reach = REACH[2 if distance >= HIGH_FROM else 1 if distance >= WIDE_FROM else 0] * TILE_YARDS
        self.visible = list(b.near(east, north, reach, BIG, reach * BIG_REACH))
        for i in self.visible:
            fdid = int(b.fdids[i])
            if fdid not in self.meshes and fdid not in self.loading:
                self.loading[fdid] = self.pool.submit(self._decode, self.pack, fdid)
        budget = UPLOAD_VERTICES
        for fdid in [f for f, fut in self.loading.items() if fut.done()]:
            if budget <= 0:
                break
            fut = self.loading.pop(fdid)
            try:
                verts, idx, batches = fut.result()
            except (OSError, ValueError):
                continue
            self.meshes[fdid] = gl.Mesh(self.prog, verts, {"a_pos": 3, "a_n": 3, "a_shade": 1, "a_uv": 2},
                                        indices=idx)
            self.batches[fdid] = batches
            self.used[fdid] = self.frame
            budget -= len(verts)
        for fdid in [f for f, last in self.used.items() if self.frame - last > KEEP_FRAMES and f in self.meshes]:
            self.meshes.pop(fdid).destroy()
            self.batches.pop(fdid, None)
            del self.used[fdid]

    def draw(self, vp, eye, look: Look, now: float, cut=None) -> None:
        """cut: (from, to, radius at the marker) of the cut-away, or None."""
        layer = self.terrain.active
        if not self.visible or layer is None or layer.world != self.world:
            self.drawn = 0
            return
        b = self.pack.buildings(self.world)
        p = self.prog
        p.bind()
        gl.uniform(p, "u_vp", gl.qmatrix(vp))
        self.terrain._common(p, eye, look, layer, far=False)
        gl.uniform(p, "u_sun", *[float(v) for v in look.sun])
        if cut is not None and cut[2] > 0:
            gl.uniform(p, "u_cut_from", *[float(v) for v in cut[0]])
            gl.uniform(p, "u_cut_to", *[float(v) for v in cut[1]])
            gl.uniform(p, "u_cut_radius", float(cut[2]))
        else:
            gl.uniform(p, "u_cut_radius", 0.0)
        gl.uniform(p, "u_ambient", *look.ambient)
        gl.uniform(p, "u_deep", *[look.deep * v for v in look.water])
        atlas = self.terrain.atlas(now)
        if atlas is not None:
            tex, e0, n0, size = atlas
            tex.bind(ATLAS_UNIT)
            gl.uniform(p, "u_atlas", ATLAS_UNIT)
            gl.uniform(p, "u_atlas_rect", float(e0), float(n0), float(size), 1.0)
        else:
            gl.uniform(p, "u_atlas_rect", 0.0, 0.0, 1.0, 0.0)
        far, fe, fn, fw, fh = self.terrain.far_picture(layer)
        far.bind(FAR_UNIT)
        gl.uniform(p, "u_far_map", FAR_UNIT)
        gl.uniform(p, "u_far_rect", float(fe), float(fn), float(fw), float(fh))
        gl.uniform(p, "u_tex", TEX_UNIT)
        textures = self.textures
        if textures is not None:
            textures.pump()
        drawn = 0
        for i in self.visible:
            fdid = int(b.fdids[i])
            mesh = self.meshes.get(fdid)
            if mesh is None:
                continue
            self.used[fdid] = self.frame
            gl.uniform(p, "u_model", gl.qmatrix(model_matrix(b.linear[i], b.shift[i])))
            for start, count, tex_id, blend in self.batches[fdid]:
                tex = textures.get(int(tex_id)) if textures is not None else None
                if tex is not None:
                    tex.bind(TEX_UNIT)
                gl.uniform(p, "u_textured", int(tex is not None))
                gl.uniform(p, "u_cutout", int(blend == ALPHA_KEY))
                mesh.draw_range(int(start), int(count))
            drawn += 1
        p.release()
        self.drawn = drawn

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        for mesh in self.meshes.values():
            mesh.destroy()
        self.meshes.clear()
