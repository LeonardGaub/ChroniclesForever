"""Phase 0 spike of the cinematic's 3D map (docs/3D_Map_Viewer.md): a dev window that flies the drone camera along
one real session over the baked terrain (tools/build_terrain.py), with the route and the marker.

    desktop\\.venv\\Scripts\\python tools\\terrain_spike.py [--db chronicle.db] [--character Blind] [--session ID]
                                                         [--at 0.3] [--speed 30] [--snap out.png --after 4]

Without --session it takes the character's session with the most points on the baked continent. --snap renders
off screen for --after seconds and saves the window (QWidget.render, as the video export records it) and the
GL framebuffer next to it, then quits.

Keys: Space pause, 1-4 speed, mouse wheel or +/- camera distance, Right/Left 5 minutes on/back, G spirit world,
P save a picture, Esc close. On closing it prints the frame times.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from PySide6.QtCore import QElapsedTimer, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QSurfaceFormat  # noqa: E402
from PySide6.QtOpenGLWidgets import QOpenGLWidget  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.domain import maps  # noqa: E402
from forever_chronicle.domain.route import Route  # noqa: E402
from forever_chronicle.domain.terrain import TerrainPack  # noqa: E402
from forever_chronicle.storage.database import Database  # noqa: E402
from forever_chronicle.storage.repository import Repository  # noqa: E402
from forever_chronicle.ui.stage3d import gl  # noqa: E402
from forever_chronicle.ui.stage3d.camera import DroneCamera  # noqa: E402
from forever_chronicle.ui.stage3d.terrain import TerrainRenderer  # noqa: E402
from forever_chronicle.ui.stage3d.trail import LIFT, SEA_LEVEL, Trail, drape  # noqa: E402
from forever_chronicle.ui.theme import class_color  # noqa: E402

SPEEDS = {Qt.Key.Key_1: 10, Qt.Key.Key_2: 30, Qt.Key.Key_3: 60, Qt.Key.Key_4: 120}   # game seconds per second
TAXI_LIFT = 45.0
SUN = np.array([-0.45, 0.55, 0.70]) / np.linalg.norm([-0.45, 0.55, 0.70])
HORIZON, ZENITH, WATER = (0.80, 0.86, 0.92), (0.32, 0.50, 0.78), (0.10, 0.27, 0.36)


class Journey:
    """One session of the route, placed in the shared 3D world of one continent."""

    def __init__(self, route: Route, pack: TerrainPack, world: int, start: int, end: int):
        self.route, self.pack, self.world = route, pack, world
        self.start, self.end = start, end
        self.timeline = route.timeline(start, end)

    def ground(self, east: float, north: float) -> float:
        return self.pack.height_at(self.world, *self.pack.unshared(self.world, east, north))

    def place(self, map_id, x, y):
        pos = self.pack.world_pos(map_id, x, y) if map_id is not None and x is not None else None
        if pos is None or pos[0] != self.world:
            return None
        return self.pack.shared(*pos)

    def stretches(self) -> list[np.ndarray]:
        """The connected stretches, draped on the ground ((t since start, east, north, z) rows); flights lifted."""
        if hasattr(self, "_stretches"):
            return self._stretches
        out, run, prev = [], [], None

        def close():
            if len(run) > 1:
                s = drape(run, self.ground)
                if prev_taxi:
                    s[:, 3] += TAXI_LIFT
                out.append(s)

        prev_taxi = False
        for p in self.route.points_in(self.start, self.end):
            here = self.place(p.map_id, p.x, p.y)
            joined = prev is not None and here is not None and self.route.connected(prev, p, maps.WORLD)
            if not joined:
                close()
                run = []
            if here is not None:
                run.append((p.time - self.start, *here))
                if p.until and p.until > p.time:
                    run.append((p.until - self.start, *here))
            prev, prev_taxi = p, p.taxi
        close()
        self._stretches = out
        self._spans = [(s[0, 0], s[-1, 0]) for s in out]
        return out

    def marker(self, t: float):
        """Where the marker is at time t: on the draped route itself (so route and marker always meet), else at the
        nearest placed point."""
        rel = t - self.start
        for s, (a, b) in zip(self.stretches(), self._spans):
            if a <= rel <= b:
                i = int(np.clip(np.searchsorted(s[:, 0], rel) - 1, 0, len(s) - 2))
                t0, t1 = s[i, 0], s[i + 1, 0]
                f = 0.0 if t1 <= t0 else (rel - t0) / (t1 - t0)
                return s[i, 1:4] + (s[i + 1, 1:4] - s[i, 1:4]) * f
        p = self.route.point_at(int(t))
        here = self.place(p.map_id, p.x, p.y) if p else None
        if here is None:
            return None
        z = max(self.ground(*here), SEA_LEVEL) + LIFT + (TAXI_LIFT if p.taxi else 0.0)
        return np.array([here[0], here[1], z])


class Stage(QOpenGLWidget):
    def __init__(self, journey: Journey, color: QColor, at: float, speed: int, parent=None):
        super().__init__(parent)
        self.journey = journey
        self.terrain = TerrainRenderer(journey.pack, journey.world)
        self.trail = Trail(color)
        self.camera = DroneCamera()
        self.value = journey.timeline.total * at
        self.speed = speed
        self.paused = False
        self.grey = 0.0
        self.clock = QElapsedTimer()
        self.frame_ms: list[float] = []
        self.update_ms: list[float] = []      # tile streaming per frame (loads queued, uploads, drops)
        self.last_marker = None
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def t(self) -> float:
        return self.journey.timeline.to_time(self.value)

    def initializeGL(self) -> None:
        started = time.perf_counter()
        self.terrain.initialize()
        self.trail.initialize()
        stretches = self.journey.stretches()
        self.trail.set_route(stretches)
        print(f"GL {self.context().format().majorVersion()}.{self.context().format().minorVersion()}, "
              f"set-up {1000 * (time.perf_counter() - started):.0f} ms, "
              f"route {sum(len(s) for s in stretches)} draped points in {len(stretches)} stretches", flush=True)
        f = gl.functions()
        f.glEnable(gl.DEPTH_TEST)
        self.clock.start()

    def paintGL(self) -> None:
        dt = min(0.1, self.clock.restart() / 1000) if self.clock.isValid() else 0.0
        if dt > 0:
            self.frame_ms.append(dt * 1000)
        if not self.paused:
            self.value = min(self.journey.timeline.total, self.value + dt * self.speed)
        marker = self.journey.marker(self.t)
        if marker is None:
            marker = self.last_marker
            if not self.paused:
                self.value = min(self.journey.timeline.total, self.value + dt * self.speed * 10)   # skip unplaced
        if marker is not None:
            if self.last_marker is None or np.linalg.norm(marker[:2] - self.last_marker[:2]) > 1500:
                self.camera.jump(marker)
            self.camera.update(dt, marker, self.journey.ground)
            started = time.perf_counter()
            self.terrain.update(marker[0], marker[1])
            self.update_ms.append(1000 * (time.perf_counter() - started))
        self.last_marker = marker
        f = gl.functions()
        ratio = self.devicePixelRatioF()
        w, h = int(self.width() * ratio), int(self.height() * ratio)
        f.glViewport(0, 0, w, h)
        f.glClearColor(*HORIZON, 1.0)
        f.glClear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT)
        if self.camera.target is None:
            return
        vp, inv_vp, eye = self.camera.matrices(w / max(1, h))
        haze = 1.0 / (self.camera.distance * 10 + 4000)
        self.terrain.draw_sky(inv_vp, HORIZON, ZENITH, self.grey)
        self.terrain.draw(vp, eye, SUN, HORIZON, haze, self.grey, WATER)
        pulse = (time.perf_counter() * 0.8) % 1.0
        self.trail.draw(vp, self.t - self.journey.start, self.camera.distance, marker, (w, h), self.grey, pulse)

    def stats(self) -> str:
        if len(self.frame_ms) < 10:
            return "no frames"
        ms = np.array(self.frame_ms[5:])
        up = np.array(self.update_ms[5:] or [0.0])
        return (f"{len(ms)} frames: mean {ms.mean():.1f} ms ({1000 / ms.mean():.0f} fps), p95 {np.percentile(ms, 95):.1f} ms, "
                f"max {ms.max():.1f} ms, over 33 ms: {(ms > 33.4).sum()}; tile streaming per frame: "
                f"p95 {np.percentile(up, 95):.2f} ms, max {up.max():.1f} ms; tiles seen {self.terrain.uploaded}")


class SpikeWindow(QWidget):
    def __init__(self, journey: Journey, color: QColor, at: float, speed: int, capture_dir: Path):
        super().__init__()
        self.setWindowTitle("Journey Forever: 3D spike")
        self.capture_dir = capture_dir
        self.stage = Stage(journey, color, at, speed, self)
        self.hud = QLabel(self)
        self.hud.setStyleSheet("color: #f4e2b0; background: rgba(10, 8, 4, 150); padding: 6px 10px;"
                               "font: 12px 'Segoe UI'; border-radius: 4px;")
        self.hud.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(15)
        self._fps_frames, self._fps_at, self._fps = 0, time.perf_counter(), 0.0
        self.resize(1600, 900)

    def resizeEvent(self, event) -> None:
        self.stage.setGeometry(self.rect())
        self.hud.move(16, 16)

    def _tick(self) -> None:
        self.stage.update()
        self._fps_frames += 1
        now = time.perf_counter()
        if now - self._fps_at >= 0.5:
            self._fps, self._fps_frames, self._fps_at = self._fps_frames / (now - self._fps_at), 0, now
        s = self.stage
        p = s.journey.route.point_at(int(s.t))
        zone = maps.display_name(p.map_id) if p else "?"
        self.hud.setText(
            f"{datetime.fromtimestamp(s.t):%d.%m. %H:%M:%S}  ·  {zone}{'  ·  Flugroute' if p and p.taxi else ''}\n"
            f"{self._fps:.0f} fps  ·  {len(s.terrain.near)} tiles near, {len(s.terrain.loading)} loading  ·  "
            f"{s.speed}× ·  camera {s.camera.distance:.0f} yd{'  ·  paused' if s.paused else ''}\n"
            "Space pause · 1-4 speed · wheel distance · ←/→ 5 min · G spirit world · P picture · Esc")
        self.hud.adjustSize()

    def capture(self, path: Path) -> None:
        image = QImage(self.size(), QImage.Format.Format_ARGB32)
        self.render(image)
        image.save(str(path))
        self.stage.grabFramebuffer().save(str(path.with_name(path.stem + "_gl" + path.suffix)))
        print(f"saved {path}", flush=True)

    def wheelEvent(self, event) -> None:
        self.stage.camera.wanted_distance = float(np.clip(
            self.stage.camera.wanted_distance * (0.85 if event.angleDelta().y() > 0 else 1 / 0.85), 60, 30000))

    def keyPressEvent(self, event) -> None:
        s, key = self.stage, event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Space:
            s.paused = not s.paused
        elif key in SPEEDS:
            s.speed = SPEEDS[key]
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Minus):
            s.camera.wanted_distance *= 0.8 if key == Qt.Key.Key_Plus else 1.25
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Left):
            s.value = float(np.clip(s.value + (300 if key == Qt.Key.Key_Right else -300), 0, s.journey.timeline.total))
        elif key == Qt.Key.Key_G:
            s.grey = 0.0 if s.grey else 1.0
        elif key == Qt.Key.Key_P:
            self.capture(self.capture_dir / f"spike_{datetime.now():%H%M%S}.png")

    def closeEvent(self, event) -> None:
        print(self.stage.stats(), flush=True)
        self.stage.makeCurrent()
        self.stage.terrain.shutdown()
        super().closeEvent(event)


def pick_session(repo, character_id: str, journey_of) -> tuple[int, int]:
    best, best_n = None, -1
    for s in repo.sessions(character_id):
        start, end = s["started_at"], s["ended_at"] or s["started_at"] + 3600
        j = journey_of(start, end)
        n = sum(1 for p in j.route.points_in(start, end) if j.place(p.map_id, p.x, p.y) is not None)
        if n > best_n:
            best, best_n = (start, end), n
    if best is None:
        raise SystemExit("the character has no session")
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=AppConfig.load().database_path)
    ap.add_argument("--character", default="Blind")
    ap.add_argument("--session")
    ap.add_argument("--world", type=int, default=1, help="1 Kalimdor, 0 Eastern Kingdoms")
    ap.add_argument("--at", type=float, default=0.0, help="start this share into the session")
    ap.add_argument("--speed", type=int, default=30)
    ap.add_argument("--distance", type=float, default=260.0)
    ap.add_argument("--snap", type=Path)
    ap.add_argument("--after", type=float, default=4.0)
    args = ap.parse_args()

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)

    pack = TerrainPack()
    if args.world not in pack.continents:
        raise SystemExit(f"world {args.world} is not baked (tools/build_terrain.py)")
    repo = Repository(Database(args.db).conn)
    char = next((c for c in repo.list_characters() if c.name == args.character), None)
    if char is None:
        raise SystemExit(f"no character {args.character}")
    route = Route.load(repo, char.character_id)
    journey_of = lambda a, b: Journey(route, pack, args.world, a, b)  # noqa: E731
    if args.session:
        s = next(s for s in repo.sessions(char.character_id) if s["session_id"] == args.session)
        start, end = s["started_at"], s["ended_at"]
    else:
        start, end = pick_session(repo, char.character_id, journey_of)
    print(f"{char.name}: {datetime.fromtimestamp(start):%d.%m.%Y %H:%M} - {datetime.fromtimestamp(end):%H:%M}", flush=True)

    window = SpikeWindow(journey_of(start, end), QColor(class_color(char.class_file)), args.at, args.speed,
                         (args.snap.parent if args.snap else Path.cwd()))
    window.stage.camera.wanted_distance = args.distance
    window.stage.camera.distance = args.distance
    if args.snap:
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.show()
        QTimer.singleShot(int(args.after * 1000), lambda: (window.capture(args.snap), window.close(), app.quit()))
    else:
        window.show()
    app.exec()


if __name__ == "__main__":
    main()
