"""Cinematic mode: a full-screen replay of the selected time range on the map.

- The route is painted up to the current moment: older parts thin and dim, the last 15 minutes brighter
  towards the marker, the newest minutes glowing; flight paths dashed with moving dashes. Its colours follow
  the map page's choice (by level, by session, one colour), as in the addon (domain/route_colors.py).
- The marker shows the player in the class colour with an arrow in the direction of travel, a gryphon on flight
  paths and a portal inside dungeons. Each event leaves a pin on the map; screenshots leave a small polaroid.
- The camera follows the player calmly and zooms a little on its own: out on flight paths and fast stretches, in
  when a moment is close or the player stands still. On a zone change the new map fades in from black. A trip to
  the other continent (boat, zeppelin) is shown on the world map: the camera pulls back from the old zone, the
  player crosses the sea on a dashed arc, and the camera dives into the new zone.
  A vignette and letterbox bars frame the picture; the top bar names the character, the zone and the moment.
- Events slide in as achievement alerts and flash a burst on the map; level-ups get a large title. At each
  screenshot the replay pauses: the picture flies out from the marker as a polaroid under an achievement
  banner (domain/cinematic.py decides which moments). The visual pieces are in ui/cinematic_fx.py.
- Deaths: the replay slows down before one and holds a moment on a dark red title while the world turns grey
  (the game's spirit world). The body is a headstone; after the release the ghost is a pale wisp and the corpse
  run a pale dotted line. Back at the body the colour returns with rising light.
- Breaks without route points (logouts, long pauses) are skipped. The replay slows down shortly before each
  screenshot and gets back to speed afterwards. Standstills (AFK, waiting) play normally, much faster or are
  skipped (option; the moments inside them are still shown).
- Music: the zone's music from the game (wow/zone_music.py), changing with the zone after a moment there, or
  the music chosen in the settings (option "cine_music").
- Controls (play/pause, speeds, standstills, music, video export, a timeline with marks for events and
  screenshots) appear while the mouse moves and fade out after a moment without movement; the mouse pointer
  hides with them.
- Keys: Space pause/continue (at the end: start again), 1-4 speed, Right: next moment, Left: 5 minutes back,
  S: standstills, M: music on/off, Esc: close.
- Sound (ui/sound.py): music fades in with the window and out when it closes; level-ups play a fanfare (the music
  ducks under it), screenshots a shutter, alerts a chime and deaths a bell.
- The video export (ui/cinematic_export.py) runs the same window off screen, frame by frame.
"""

from __future__ import annotations

import bisect
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel, QPushButton, QToolTip, QWidget)

from ..domain import maps
from ..domain.cinematic import Cue, Death, Levels, build_cues, CUE_EVENT_TYPES, death_spans, still_spans
from ..domain.route import Route, Timeline
from ..domain.route_colors import RouteColors, zone_colors
from ..i18n import format_datetime, format_duration, tr
from ..wow import zone_music
from ..wow.map_art import find_art
from . import icons, theme, world_art
from .world_art import WorldArt
from .cinematic_fx import (FADE_SECONDS, GHOST_COLOR, AchievementToast, CinemaFrame, CinemaView, MarkerItem,
                           PhotoOverlay, Pin, PinsItem, RouteItem, TitleCard, clamp, ease_in_out, load_thumbnail)

W, H = maps.ART_WIDTH, maps.ART_HEIGHT
TICK_MS = 33
BASE_SPEED = 60            # game seconds per real second at 1x (as on the map page)
SPEEDS = (1, 2, 4, 10)
ZOOM = 2.4                 # camera zoom relative to the whole map
FOLLOW_SECONDS = 0.45      # time constant of the camera following the marker
KEEP_INSIDE = 0.3          # the marker stays within this share of the picture's width/height from its centre
ZOOM_OUT_TAXI = 0.86       # dynamic zoom (share of ZOOM): on flight paths ...
ZOOM_OUT_FAST = 0.9        # ... at most this far out while the marker races across the picture ...
ZOOM_IN_CLOSE = 1.07       # ... and a little in when a moment is close, or while standing still or dead
ZOOM_SECONDS = 2.6         # time constant of zoom changes: slow, so the picture stays calm
FAST_FROM, FAST_TO = 0.12, 0.45   # marker speed (picture widths per second) where zooming out begins / is full
CLOSE_SECONDS = 2.5        # real seconds before a moment in which the camera moves in
GAP_SKIP = 30              # breaks without points longer than this are skipped
STILL_MODES = ("normal", "fast", "skip")
STILL_FASTER = 8           # standstills run this many times faster in "fast" mode
STILL_NOTE = 2.4           # seconds a skipped standstill is named
DEATH_SECONDS = 3.2        # the death title
DEATH_HOLD = 1.4           # real seconds the replay holds at a death
GREY_IN, GREY_OUT = 0.9, 1.6   # seconds for the colour to drain at a death and to return on coming back
MUSIC_SETTLE = 2.5         # real seconds in a zone before its music starts (passing through changes nothing)
TOAST_SECONDS = 4.0
LEVEL_SECONDS = 3.6
LEVEL_HOLD = 2.8           # a screenshot right after a level-up waits this long into the level-up title
LEVEL_DUCK = 3.8           # seconds the music stays lowered under the level-up fanfare
PHOTO_SECONDS = 5.5
MAX_TOASTS = 3
CONTROLS_IDLE = 2.5        # seconds without mouse movement before the controls fade out
CONTROLS_HEIGHT = 58
SLOW_SECONDS = 1.5         # real seconds before a screenshot in which the replay slows down
SLOW_MIN = 0.2             # share of the speed right before a screenshot
RAMP_SECONDS = 1.0         # real seconds to get back to speed after a screenshot
ZONE_SECONDS = 2.0         # real seconds a zone stays on screen at least: the replay slows down through short
ZONE_MIN_SPEED = 1         # visits, but never below this speed (×), and not for visits shorter than ZONE_BLIP
ZONE_BLIP = 30             # game seconds; a step into a zone and back is part of the visit around it
ZONE_AHEAD = 0.6           # real seconds of look-ahead, so the replay is slow already when the next zone comes
ZONE_EASE_IN, ZONE_EASE_OUT = 0.25, 0.9   # time constants of slowing down for a short visit / speeding up after
DEATH_COLOR = QColor("#ff3333")
# Trips to the other continent (boat, zeppelin, portal), shown on the world map.
VOYAGE_OUT, VOYAGE_TRAVEL, VOYAGE_IN = 1.0, 1.8, 1.0   # out to the world map, across the sea, into the zone
VOYAGE_GAP = 10 * 60       # a continent change after a longer break fades in from black instead
SHARP, BLURRY = 1.2, 2.2   # a finer map fades in while the one beneath is enlarged from SHARP to BLURRY times
SOFT_EDGE = 0.09           # share of a placed map's width and height that fades out (hides its parchment frame)
CROSS_SECONDS = 0.4        # crossfade from the trip's last picture to the new zone
VOYAGE_LINE = QColor(232, 226, 208, 220)
# The seamless world map (option "cine_map": "world", ui/world_art.py): one picture of every zone.
FRAME_SECONDS = 3.0        # time constant of the view following the size of the zone the player is in
CUT_JUMP = 0.5             # a step longer than this share of the picture's width cuts (crossfade): a teleport


@dataclass
class _Voyage:
    """A trip to the other continent, shown on the world map: out from the old zone until the world is in view,
    the player crossing the sea on an arc, into the new zone. The continent and zone maps lie on the world map
    where they belong, each shown only while the coarser map beneath would look blurry, so every zoom stays
    sharp and the pictures blend into each other."""
    to_view: int
    start: QPointF              # camera centre: where the old zone's view is ...
    over_center: QPointF        # ... both continents ...
    end: QPointF                # ... where the new zone's view will be
    start_scale: float
    over_scale: float
    end_scale: float
    origin: QPointF             # the player before the trip ...
    target: QPointF             # ... and after
    details: list = field(default_factory=list)   # (finer map, scale of the map beneath it: share of the world)
    line: QGraphicsPathItem | None = None
    age: float = 0.0

    @property
    def life(self) -> float:
        return VOYAGE_OUT + VOYAGE_TRAVEL + VOYAGE_IN

    def camera(self) -> tuple[float, QPointF]:
        """(scale, centre) at the current age; scales change geometrically so the zoom feels even."""
        def blend(a: float, b: float, e: float) -> float:
            return math.exp(math.log(a) + (math.log(b) - math.log(a)) * e)

        def between(a: QPointF, b: QPointF, e: float) -> QPointF:
            return QPointF(a.x() + (b.x() - a.x()) * e, a.y() + (b.y() - a.y()) * e)

        # Close to a zone the camera stays on its view (it leaves late and arrives early), so the coarse maps
        # around the zone are only seen from afar.
        if self.age < VOYAGE_OUT:
            f = self.age / VOYAGE_OUT
            return (blend(self.start_scale, self.over_scale, ease_in_out(f)),
                    between(self.start, self.over_center, ease_in_out((f - 0.35) / 0.65)))
        if self.age < VOYAGE_OUT + VOYAGE_TRAVEL:
            return self.over_scale, self.over_center
        f = (self.age - VOYAGE_OUT - VOYAGE_TRAVEL) / VOYAGE_IN
        return (blend(self.over_scale, self.end_scale, ease_in_out(f)),
                between(self.over_center, self.end, ease_in_out(f / 0.65)))

    def travelled(self) -> float:
        return ease_in_out((self.age - VOYAGE_OUT) / VOYAGE_TRAVEL)

    def arc(self, f: float) -> QPointF:
        """A point of the crossing (0: start, 1: arrival), on an arc bulging northwards like a ship's course."""
        a, b = self.origin, self.target
        lift = math.hypot(b.x() - a.x(), b.y() - a.y()) * 0.3
        c = QPointF((a.x() + b.x()) / 2, min(a.y(), b.y()) - lift)
        u = 1 - f
        return QPointF(u * u * a.x() + 2 * u * f * c.x() + f * f * b.x(),
                       u * u * a.y() + 2 * u * f * c.y() + f * f * b.y())

    def marker(self) -> QPointF:
        return self.arc(self.travelled())

    def update_items(self, scale: float) -> None:
        """Fades the finer maps for the view's scale and draws the crossing so far."""
        for item, beneath in self.details:
            enlarged = scale * beneath                      # screen pixels per pixel of the map beneath
            item.setOpacity(clamp(math.log(max(enlarged, 1e-6) / SHARP) / math.log(BLURRY / SHARP)))
        if self.line is not None:
            f = self.travelled()
            path = QPainterPath(self.origin)
            for k in range(1, 41):
                path.lineTo(self.arc(f * k / 40))
            self.line.setPath(path)


class TimelineBar(QWidget):
    """The replay's timeline, as the addon's map slider: a band per zone (dark in dungeons), collapsed breaks
    (dark marks), coloured marks for events and white ones for screenshots; a thin gold line shows the played
    part. Click or drag to jump; hovering names the event, or the zone and moment under the cursor."""

    MARGIN = 10

    def __init__(self, on_seek, zone_name=None):
        super().__init__()
        self.on_seek = on_seek
        self.zone_name = zone_name      # (map_id, instance_id) -> name, for the hover text
        self.timeline: Timeline | None = None
        self.cues: list[Cue] = []
        self.bands: list[tuple[float, float, QColor, int | None, int | None]] = []   # values, colour, zone ids
        self.value = 0.0
        self.setMouseTracking(True)
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, timeline: Timeline, cues: list[Cue], runs=()) -> None:
        self.timeline, self.cues = timeline, cues
        color = zone_colors(runs)
        self.bands = [(timeline.to_value(r.start), timeline.to_value(r.to), QColor(color(r)), r.map_id,
                       r.instance_id) for r in runs]
        self.update()

    def band_at(self, value: float):
        return next((b for b in self.bands if b[0] <= value <= b[1]), None)

    def set_value(self, value: float) -> None:
        if value != self.value:
            self.value = value
            self.update()

    def x_of(self, value: float) -> float:
        total = self.timeline.total if self.timeline else 1.0
        return self.MARGIN + value / total * max(1, self.width() - 2 * self.MARGIN)

    def value_at(self, x: float) -> float:
        total = self.timeline.total if self.timeline else 1.0
        share = (x - self.MARGIN) / max(1, self.width() - 2 * self.MARGIN)
        return max(0.0, min(1.0, share)) * total

    def cue_at(self, x: float) -> Cue | None:
        if not self.timeline:
            return None
        best, best_d = None, 6.0
        for cue in self.cues:
            d = abs(self.x_of(self.timeline.to_value(cue.time)) - x)
            if d <= best_d:
                best, best_d = cue, d
        return best

    def paintEvent(self, event) -> None:
        if not self.timeline:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2 + 5
        left, right = self.x_of(0), self.x_of(self.timeline.total)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 45))
        painter.drawRoundedRect(QRectF(left, mid - 3, right - left, 6), 3, 3)
        for a, b, color, _, _ in self.bands:
            x0, x1 = self.x_of(a), self.x_of(b)
            if x1 - x0 >= 0.5:
                c = QColor(color)
                c.setAlphaF(0.9)
                painter.setBrush(c)
                painter.drawRect(QRectF(x0, mid - 3, x1 - x0, 6))
        x = self.x_of(self.value)
        painter.setBrush(QColor(theme.GOLD))
        painter.drawRect(QRectF(left, mid + 4, max(0.0, x - left), 2))
        painter.setBrush(QColor(0, 0, 0, 230))
        for value in self.timeline.breaks():
            painter.drawRect(QRectF(self.x_of(value) - 1, mid - 5, 2, 10))
        for cue in self.cues:
            cx = self.x_of(self.timeline.to_value(cue.time))
            if cue.kind == "screenshot":
                painter.setBrush(QColor("#ffffff"))
                painter.drawRect(QRectF(cx - 3, mid - 15, 6, 6))
            else:
                painter.setBrush(QColor(cue.color))
                painter.drawRect(QRectF(cx - 1, mid - 14, 2, 9))
        painter.setBrush(QColor(theme.GOLD))
        painter.setPen(QPen(QColor("black"), 1.5))
        painter.drawEllipse(QPointF(x, mid), 7, 7)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.timeline:
            self.on_seek(self.timeline.to_time(self.value_at(event.position().x())))

    def mouseMoveEvent(self, event) -> None:
        if not self.timeline:
            return
        x = event.position().x()
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.on_seek(self.timeline.to_time(self.value_at(x)))
            return
        cue = self.cue_at(x)
        if cue:
            text = f"{cue.glyph or '📷'}  {cue.text}\n{format_datetime(cue.time)}"
        else:
            value = self.value_at(x)
            text = format_datetime(int(self.timeline.to_time(value)))
            band = self.band_at(value)
            zone = self.zone_name(band[3], band[4]) if band and self.zone_name else None
            if zone:
                text = f"{zone}\n{text}"
        QToolTip.showText(event.globalPosition().toPoint(), text, self)




def _faded(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    return effect


class CinematicWindow(QWidget):
    def __init__(self, ctx, character_id: str, start: int, end: int, speed: int = 4, colors: str = "level",
                 sound=None, exporting: bool = False, still: str | None = None):
        """sound: what plays the music and effects (default ctx.sound; the video export passes its recorder).
        exporting: driven frame by frame off screen, without controls or a timer of its own.
        still: how standstills play (STILL_MODES; default: the choice kept in the settings)."""
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(tr("cine.title"))
        self.setStyleSheet(f"background: black; color: {theme.TEXT};")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.ctx = ctx
        self.character_id = character_id
        self.exporting = exporting
        repo = ctx.repo
        self.sound = sound or ctx.sound
        self.route = Route(repo.positions(character_id), repo.map_infos(), repo.instance_names(), repo.entrances())
        # Quests are no cues, but a quest screenshot names its quest.
        events = repo.events(character_id, types=CUE_EVENT_TYPES + ("quest_completed",), limit=1_000_000)
        self.cues: list[Cue] = build_cues(events, repo.screenshots(character_id, only_files=True), start, end)
        self.cue_times = [c.time for c in self.cues]
        self.deaths: list[Death] = [d for d in death_spans(events, self.route) if d.revived >= start and d.time <= end]
        self.ghost_spans = [(d.released, d.revived) for d in self.deaths if d.released is not None]
        char = next((c for c in repo.list_characters() if c.character_id == character_id), None)
        self.char_name = char.name if char else ""
        self.char_color = theme.class_color(char.class_file if char else None)
        self.levels = Levels(events, char.level if char else None)
        self.color_mode = colors
        self.colors = RouteColors(colors, self.levels, [s["started_at"] for s in repo.sessions(character_id)])
        self.start, self.end = start, max(end, start + 1)
        self.speed = speed if speed in SPEEDS else 4
        self.still_spans = still_spans(self.route, self.start, self.end)
        self.still_starts = [a for a, _ in self.still_spans]
        mode = still or ctx.config.extra.get("cine_still")
        self.still_mode = mode if mode in STILL_MODES else "fast"
        self.t = float(self.route.next_time_after(start - 1) or start)
        self.cue_index = bisect.bisect_left(self.cue_times, self.t)
        self.zone_visits = self._zone_visits()
        self.zone_visit_starts = [a for a, _, _ in self.zone_visits]
        self.zone_share = 1.0               # share of the chosen speed short zone visits allow (smoothed)
        self._update_zone_share(0.0, now=True)
        self.paused = False
        self.ended = False
        self.view_map: int | None = None
        # Seamless: the whole world is one scene (view_map WORLD); the zone the player is in only sets the
        # caption, the music and how much the view shows (frame_size: the zone's size in world units, followed
        # slowly so crossing into a bigger or smaller zone zooms calmly).
        self.seamless = ctx.config.extra.get("cine_map", "world") == "world" and world_art.available()
        self.world: WorldArt | None = None
        self.zone_now: int | None = None
        self.frame_size: tuple[float, float] | None = None
        self.route_item: RouteItem | None = None
        self.pins: PinsItem | None = None
        self.camera: QPointF | None = None
        self.last_head: QPointF | None = None
        self.zoom = 1.0                     # dynamic zoom, a share of ZOOM
        self.screen_speed = 0.0             # how fast the marker crosses the picture (widths per second, smoothed)
        self.frame_dt = 0.0                 # real time of the current step (camera smoothing)
        self.hold = 0.0                     # real seconds the replay waits (at a death)
        self._art: dict[int, QPixmap] = {}
        self._soft: dict[int, QPixmap | None] = {}
        self._thumbs: dict[str, QPixmap | None] = {}

        # Zone music: the files of every place in the range come out of the game in the background (the export
        # takes them first); until a zone's files are there, the music playing goes on.
        self.zone_music = ctx.config.extra.get("cine_music", "zone") == "zone"
        self.music_now: tuple[Path, ...] | None = None
        self.music_next: tuple[Path, ...] | None = None
        self.music_wait = 0.0
        music_files = zone_music.all_file_ids(
            (r.map_id if r.map_id is not None else self.route.view_for(self.route.point_at(int(r.start))),
             r.instance_id) for r in self.route.zone_runs(self.start, self.end)) if self.zone_music else []
        if zone_music.missing(music_files) and ctx.client():
            if exporting:
                zone_music.extract_missing(ctx.client(), music_files)
            else:
                threading.Thread(target=zone_music.extract_missing, args=(ctx.client(), music_files),
                                 daemon=True).start()

        self.view = CinemaView(self)
        self.view.setScene(QGraphicsScene(self.view))
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setInteractive(False)
        self.view.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.view.setBackgroundBrush(QColor("black"))
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.marker = MarkerItem()
        self.marker.color = QColor(self.char_color)

        # The last picture of the old map, fading out over the new one (crossfade).
        self.snapshot = QLabel(self)
        self.snapshot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.snapshot_effect = _faded(self.snapshot)
        self.snapshot_age = CROSS_SECONDS
        self.snapshot.hide()
        self.voyage: _Voyage | None = None

        # Black cover for map changes (fades out), then the vignette and letterbox bars.
        self.cover = QWidget(self)
        self.cover.setStyleSheet("background: black;")
        self.cover_effect = _faded(self.cover)
        self.cover_age = FADE_SECONDS * 2
        self.frame = CinemaFrame(self)

        # In the top bar: the character on the left, zone and moment on the right.
        fonts = ", ".join(f'"{f}"' for f in theme.HEADING_FONTS)
        self.caption = QLabel(self)
        self.caption.setStyleSheet(f"background: transparent; font-family: {fonts}; font-size: 16pt;")
        self.place = QLabel(self)
        self.place.setStyleSheet(f"background: transparent; font-family: {fonts}; font-size: 14pt;")
        self.place.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for label in (self.caption, self.place):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption_effects = [_faded(self.caption), _faded(self.place)]

        self.toasts: list[AchievementToast] = []
        self.title = TitleCard(self)
        # Under the top bar: "fast-forward" while a standstill runs faster, or the standstill just skipped.
        self.still_label = QLabel(self)
        self.still_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.still_label.setStyleSheet(
            f"background: rgba(0,0,0,150); color: {theme.MUTED}; border: 1px solid rgba(201,162,74,90);"
            f"border-radius: 3px; padding: 3px 10px; font-family: {fonts}; font-size: 11pt;")
        self.still_effect = _faded(self.still_label)
        self.still_note = 0.0               # seconds left showing a skipped standstill
        self.still_label.hide()
        self.photo = PhotoOverlay(self, PHOTO_SECONDS)
        self.photo_on = False
        self.pending_photo: Cue | None = None
        self._build_controls()

        self.ramp = RAMP_SECONDS
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        # Mouse movement anywhere shows the controls.
        for widget in (self, self.view, self.view.viewport(), self.controls):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        self._sync_controls()
        self._render()

    def _build_controls(self) -> None:
        self.controls = QWidget(self)
        self.controls.setObjectName("controls")
        self.controls.setStyleSheet(
            f"#controls {{ background: rgba(0,0,0,200); border-top: 1px solid {theme.BORDER}; }}"
            f"QPushButton {{ background: rgba(255,255,255,18); color: {theme.TEXT}; border: 1px solid {theme.BORDER};"
            "border-radius: 3px; padding: 4px 10px; font-size: 11pt; }"
            f"QPushButton:checked {{ color: {theme.GOLD}; border-color: {theme.GOLD}; }}"
            f"QLabel {{ background: transparent; color: {theme.MUTED}; font-size: 10pt; }}")
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(6)
        self.play_button = QPushButton()
        self.play_button.setFixedWidth(44)
        self.play_button.clicked.connect(self.toggle_pause)
        row.addWidget(self.play_button)
        self.speed_buttons = []
        for speed in SPEEDS:
            button = QPushButton(f"{speed}×")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, s=speed: self.set_speed(s))
            row.addWidget(button)
            self.speed_buttons.append((speed, button))
        self.still_button = QPushButton()
        self.still_button.clicked.connect(self.cycle_still)
        row.addWidget(self.still_button)
        self.music_button = QPushButton("♪")
        self.music_button.setCheckable(True)
        self.music_button.setFixedWidth(40)
        self.music_button.clicked.connect(self.toggle_music)
        row.addWidget(self.music_button)
        self.export_button = QPushButton(tr("cine.export"))
        self.export_button.setToolTip(tr("cine.export_tip"))
        self.export_button.clicked.connect(self.export_video)
        row.addWidget(self.export_button)
        row.addSpacing(10)
        self.bar = TimelineBar(self._seek_from_bar, self._zone_name)
        self.bar.set_data(self.route.timeline(self.start, self.end, GAP_SKIP), self.cues,
                          self.route.zone_runs(self.start, self.end))
        row.addWidget(self.bar, 1)
        self.clock_label = QLabel()
        self.clock_label.setMinimumWidth(130)
        row.addWidget(self.clock_label)
        self.keys_label = QLabel(tr("cine.hint"))
        self.keys_label.setToolTip(tr("cine.keys_tip"))
        self.keys_label.setMaximumWidth(220)
        row.addWidget(self.keys_label)
        for widget in [self.play_button, self.still_button, self.music_button, self.export_button] + [
                b for _, b in self.speed_buttons]:
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # Space stays with the window
        self.controls_effect = _faded(self.controls)
        self.controls_idle = CONTROLS_IDLE + FADE_SECONDS   # hidden until the mouse moves
        self.controls.hide()

    # -- lifecycle -----------------------------------------------------------------------

    def start_playback(self) -> None:
        self.clock.start()
        self.timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._layout()
        self._apply_zoom()
        if not self.timer.isActive() and not self.clock.isValid():
            if not self.exporting:
                self.start_playback()
            self.music_now = self._wanted_music()
            self.sound.music.start(tracks=list(self.music_now) if self.music_now else None)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.sound.music.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout()
        self._apply_zoom()

    def _layout(self) -> None:
        r = self.rect()
        for widget in (self.view, self.snapshot, self.cover, self.frame, self.title, self.photo):
            widget.setGeometry(r)
        self.title.setGeometry(0, int(r.height() * 0.5 - r.height() * 0.2), r.width(), int(r.height() * 0.3))
        self.controls.setGeometry(0, r.height() - CONTROLS_HEIGHT, r.width(), CONTROLS_HEIGHT)
        self._layout_bars()
        self._layout_toasts()
        self._layout_still()

    def _layout_still(self) -> None:
        self.still_label.adjustSize()
        self.still_label.move((self.width() - self.still_label.width()) // 2,
                              CinemaFrame.target_bar(self.width(), self.height()) + 14)

    def _layout_bars(self) -> None:
        """The top bar's texts, fading in with the bar. They stay inside the window: a child reaching past its
        edge keeps Windows from showing the window over the whole screen."""
        r = self.rect()
        full = CinemaFrame.target_bar(r.width(), r.height())
        for label in (self.caption, self.place):
            label.adjustSize()
        self.caption.move(32, max(4, (full - self.caption.height()) // 2))
        self.place.move(max(0, r.width() - 32 - self.place.width()), max(4, (full - self.place.height()) // 2))
        for effect in self.caption_effects:
            effect.setOpacity(self.frame.progress ** 2)

    def _layout_toasts(self) -> None:
        r = self.rect()
        w = int(min(470, max(340, r.width() * 0.3)))
        h = int(max(80, min(100, r.height() * 0.095)))
        y = CinemaFrame.target_bar(r.width(), r.height()) + 18
        for toast in self.toasts:
            toast.resize(w, h)
            toast.place_at(r.width() - 24, y)
            y += h + 6

    def picture_area(self) -> QRectF:
        """The window between the letterbox bars."""
        bar = CinemaFrame.target_bar(self.width(), self.height())
        return QRectF(0, bar, self.width(), self.height() - 2 * bar)

    # -- keys ------------------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        self.wake_controls()
        if key == Qt.Key.Key_Space:
            self.toggle_pause()
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_4:
            self.set_speed(SPEEDS[key - Qt.Key.Key_1])
        elif key == Qt.Key.Key_M:
            self.toggle_music()
        elif key == Qt.Key.Key_S:
            self.cycle_still()
        elif key == Qt.Key.Key_Right:
            if self.cue_index < len(self.cues):
                self.seek(self.cues[self.cue_index].time - 1)
        elif key == Qt.Key.Key_Left:
            self.seek(max(self.start, self.t - 300))
        else:
            super().keyPressEvent(event)

    def seek(self, t: float) -> None:
        self.t = float(max(self.start, min(self.end, t)))
        self.cue_index = bisect.bisect_left(self.cue_times, self.t)
        self.ended = False
        self.ramp = RAMP_SECONDS
        self.hold = 0.0
        self._update_zone_share(0.0, now=True)
        self.view.set_grey(1.0 if self._death_at(self.t) else 0.0)
        self.still_note = 0.0
        self.title.hide()
        self._hide_photo()
        self.pending_photo = None
        if self.voyage is not None and self.view_map == maps.WORLD and self.voyage.line is not None:
            self.view.scene().removeItem(self.voyage.line)
        self.voyage = None
        self.snapshot.hide()
        for toast in self.toasts:            # they belong to another moment
            toast.deleteLater()
        self.toasts.clear()
        if self.pins:
            self.pins.clear_bursts()
        self._render(jump=True)
        self._update_music(0.0, now=True)

    def _seek_from_bar(self, t: float) -> None:
        self.wake_controls()
        self.seek(t)

    def toggle_pause(self) -> None:
        if self.ended:
            self.paused = False
            self.seek(self.start)
        else:
            self.paused = not self.paused
        self._sync_controls()

    def set_speed(self, speed: int) -> None:
        self.speed = speed
        self._update_zone_share(0.0, now=True)
        self._sync_controls()

    def toggle_music(self) -> None:
        """Music on/off; the choice is kept in the settings."""
        config = self.sound.config
        config.music = not config.music
        config.save()
        if config.music:
            self.music_now = self._wanted_music()
            self.sound.music.start(tracks=list(self.music_now) if self.music_now else None)
        else:
            self.sound.music.stop()
        self._sync_controls()

    def cycle_still(self) -> None:
        """Standstills: normal, faster, skipped; the choice is kept in the settings."""
        self.still_mode = STILL_MODES[(STILL_MODES.index(self.still_mode) + 1) % len(STILL_MODES)]
        self.ctx.config.extra["cine_still"] = self.still_mode
        self.ctx.config.save()
        self._sync_controls()

    def export_video(self) -> None:
        """Pauses and offers to save the replay as a video (ui/cinematic_export.py)."""
        from .cinematic_export import ExportDialog
        if not self.ended:
            self.paused = True
        self._sync_controls()
        ExportDialog(self, self.ctx, self.character_id, self.start, self.end, self.speed, self.color_mode).exec()

    def _sync_controls(self) -> None:
        self.still_button.setText(tr(f"cine.still.{self.still_mode}"))
        self.still_button.setToolTip(tr("cine.still_tip"))
        self.music_button.setChecked(self.sound.config.music)
        self.music_button.setToolTip(tr("cine.music_off") if self.sound.config.music else tr("cine.music_on"))
        playing = not self.paused and not self.ended
        self.play_button.setText("❚❚" if playing else "▶")
        self.play_button.setToolTip(tr("map.pause") if playing else tr("map.play"))
        for speed, button in self.speed_buttons:
            button.setChecked(speed == self.speed)

    # -- controls visibility -------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            self.wake_controls()
        return False

    def wake_controls(self) -> None:
        """Shows the controls (and the mouse pointer) again; they fade out after CONTROLS_IDLE seconds."""
        self.controls_idle = 0.0
        if not self.controls.isVisible():
            self.controls.show()
            self.controls.raise_()
            self.unsetCursor()
            self.view.viewport().unsetCursor()

    def _age_controls(self, dt: float) -> None:
        if self.controls.isVisible() and self.controls.underMouse():
            self.controls_idle = 0.0        # stays while the pointer is on it
        self.controls_idle += dt
        if not self.controls.isVisible():
            return
        if self.controls_idle < CONTROLS_IDLE:
            opacity = min(1.0, self.controls_effect.opacity() + dt / FADE_SECONDS * 2)
        else:
            opacity = max(0.0, 1 - (self.controls_idle - CONTROLS_IDLE) / FADE_SECONDS)
        self.controls_effect.setOpacity(opacity)
        if opacity <= 0.0:
            self.controls.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.view.viewport().setCursor(Qt.CursorShape.BlankCursor)

    # -- playback --------------------------------------------------------------------------

    def _tick(self) -> None:
        dt = min(0.1, self.clock.restart() / 1000) if self.clock.isValid() else TICK_MS / 1000
        self.advance(dt)

    def advance(self, dt: float) -> None:
        """One step of real time dt (seconds): animations and overlays, then the replay unless a picture is
        shown or the replay holds (at a death)."""
        self.frame_dt = dt
        self._age_overlays(dt)
        self._update_grey(dt)
        self._update_music(dt)
        if self.photo_on:
            if not self.photo.advance(dt):
                self._hide_photo()
            return
        if self.pending_photo is not None:
            if not self._title_busy():
                cue, self.pending_photo = self.pending_photo, None
                self._show_photo(cue)
            return                          # held at the screenshot's moment meanwhile
        if self.voyage is not None:
            self._travel(dt)
            return
        if self.hold > 0:
            self.hold = max(0.0, self.hold - dt)
            self._render()                  # the camera settles meanwhile
            return
        if self.paused or self.ended:
            return
        self.ramp += dt
        self._update_zone_share(dt)
        before = self.t
        t = self.t + self.speed * BASE_SPEED * dt * self.pace()
        t = self._skip_gap(t)
        t = self._skip_still(t)
        while self.cue_index < len(self.cues) and self.cues[self.cue_index].time <= t:
            cue = self.cues[self.cue_index]
            self.cue_index += 1
            if cue.kind == "screenshot":
                t = cue.time               # stop exactly there while the picture is shown
                self.t = t
                self._render()
                if self._title_busy():
                    self.pending_photo = cue   # the level-up title first, then its picture
                else:
                    self._show_photo(cue)
                break
            self._show_cue(cue)
            if cue.event_type == "player_died":
                t = max(self.t, cue.time)  # hold right there
                break
        if t >= self.end:
            t, self.ended = self.end, True
            # Playing time in the range, breaks left out (as the level-up title's time since the level before).
            played = self.route.timeline(self.start, self.end, GAP_SKIP).total
            self._show_title(tr("cine.end"), life=10**9,
                             subtitle=tr("cine.end_played", time=format_duration(played)))
            self._sync_controls()
        self.t = t
        self._crossings(before, t)
        self._render()

    def pace(self) -> float:
        """Share of the chosen speed: slower shortly before a screenshot or a death, back to full speed after
        one; slower through short zone visits; much faster through a standstill ("fast" mode)."""
        factor = min(1.0, SLOW_MIN + (1 - SLOW_MIN) * self.ramp / RAMP_SECONDS, self.zone_share)
        if self.still_mode == "fast" and self._still_at(self.t) is not None:
            factor *= STILL_FASTER
        upcoming = next((c for c in self.cues[self.cue_index:]
                         if c.kind == "screenshot" or c.event_type == "player_died"), None)
        if upcoming is not None:
            window = self.speed * BASE_SPEED * SLOW_SECONDS   # game time covered in SLOW_SECONDS at full speed
            distance = upcoming.time - self.t
            if distance < window:
                factor = min(factor, SLOW_MIN + (1 - SLOW_MIN) * max(0.0, distance) / window)
        return factor

    # -- zone visits -------------------------------------------------------------------------

    def _zone_visits(self) -> list[tuple[float, float, float]]:
        """Stretches of the range in one place as the caption names it (a zone, or a dungeon): (start, end,
        game seconds per real second at most there, so the place stays on screen for ZONE_SECONDS). Steps into
        a zone and straight back (shorter than ZONE_BLIP) belong to the visit around them."""
        route = self.route
        continents = {info["continent_id"] for info in route.map_infos.values()}
        entrance_views: dict[int, int | None] = {}
        visits: list[list] = []             # [place, start, end]
        for p in route.points[max(0, bisect.bisect_right(route.times, self.start) - 1):]:
            if p.time > self.end:
                break
            if p.end < self.start:
                continue
            if p.instance_id is not None:
                if p.instance_id not in entrance_views:
                    entrance_views[p.instance_id] = route.view_for(p)
                place = (entrance_views[p.instance_id], p.instance_id)
            elif p.map_id in continents or p.x is None:      # only these need the search for their zone
                place = (route.view_for(p), None)
            else:
                place = (p.map_id, None)
            if place == (None, None):
                continue
            if visits and visits[-1][0] == place:
                continue
            begin = max(float(p.time), float(self.start))
            if visits:
                visits[-1][2] = begin
            visits.append([place, begin, float(self.end)])
        timeline = route.timeline(self.start, self.end, GAP_SKIP)
        played = lambda v: timeline.to_value(v[2]) - timeline.to_value(v[1])  # noqa: E731  (breaks left out)
        merged: list[list] = []
        for visit in visits:
            if len(merged) >= 2 and played(merged[-1]) < ZONE_BLIP and merged[-2][0] == visit[0]:
                merged.pop()
                merged[-1][2] = visit[2]
            else:
                merged.append(visit)
        if len(merged) < 2:
            return []
        floor = ZONE_MIN_SPEED * BASE_SPEED
        return [(v[1], v[2], math.inf if played(v) < ZONE_BLIP else max(floor, played(v) / ZONE_SECONDS))
                for v in merged]

    def _update_zone_share(self, dt: float, now: bool = False) -> None:
        """Lets the share of the chosen speed drift towards what the visits now and just ahead allow: down
        quickly before a short visit, back up gently after it (at once after a jump or a new speed)."""
        rate = self.speed * BASE_SPEED
        horizon = self.t + rate * ZONE_AHEAD
        cap = math.inf
        i = max(0, bisect.bisect_right(self.zone_visit_starts, self.t) - 1)
        while i < len(self.zone_visits) and self.zone_visits[i][0] <= horizon:
            if self.zone_visits[i][1] > self.t:
                cap = min(cap, self.zone_visits[i][2])
            i += 1
        target = min(1.0, cap / rate)
        if now:
            self.zone_share = target
            return
        tau = ZONE_EASE_IN if target < self.zone_share else ZONE_EASE_OUT
        self.zone_share += (target - self.zone_share) * (1 - math.exp(-dt / tau))

    # -- standstills -------------------------------------------------------------------------

    def _still_at(self, t: float) -> tuple[float, float] | None:
        i = bisect.bisect_right(self.still_starts, t) - 1
        if i >= 0 and t < self.still_spans[i][1]:
            return self.still_spans[i]
        return None

    def _skip_still(self, t: float) -> float:
        """In "skip" mode a standstill is jumped over, up to its end or the next moment inside it."""
        if self.still_mode != "skip":
            return t
        span = self._still_at(t)
        if span is None:
            return t
        target = span[1]
        if self.cue_index < len(self.cues):
            target = min(target, max(t, self.cues[self.cue_index].time - 1))
        if target > t:
            self.still_note = STILL_NOTE
            self.still_label.setText(tr("cine.still_skipped", time=format_duration(int(span[1] - span[0]))))
            self._layout_still()
        return max(t, target)

    def _update_still(self, dt: float) -> None:
        """The note under the top bar: fast-forward through a standstill, or the standstill just skipped."""
        self.still_note = max(0.0, self.still_note - dt)
        span = self._still_at(self.t) if self.still_mode == "fast" and not self.ended else None
        show = self.still_note > 0 or span is not None
        if span is not None and self.still_note <= 0:
            text = tr("cine.still_fast", factor=STILL_FASTER, time=format_duration(int(span[1] - span[0])))
            if text != self.still_label.text():
                self.still_label.setText(text)
                self._layout_still()
        opacity = self.still_effect.opacity()
        opacity = min(1.0, opacity + dt / FADE_SECONDS) if show else max(0.0, opacity - dt / FADE_SECONDS)
        self.still_effect.setOpacity(opacity)
        self.still_label.setVisible(opacity > 0)

    # -- deaths ------------------------------------------------------------------------------

    def _death_at(self, t: float) -> Death | None:
        return next((d for d in self.deaths if d.dead(t)), None)

    def _crossings(self, before: float, t: float) -> None:
        """Light where the ghost appears at the graveyard, and where the player comes back to life."""
        if not self.pins or not self.marker.isVisible():
            return
        for d in self.deaths:
            if d.released is not None and before < d.released <= t:
                self.pins.burst(self.marker.pos(), GHOST_COLOR, "spirit")
            if before < d.revived <= t:
                self.pins.burst(self.marker.pos(), QColor(theme.GOLD), "revive")
                self.sound.play("event")

    def _update_grey(self, dt: float) -> None:
        dead = self._death_at(self.t) is not None
        grey = self.view.grey
        grey = min(1.0, grey + dt / GREY_IN) if dead else max(0.0, grey - dt / GREY_OUT)
        self.view.set_grey(grey)

    # -- music -------------------------------------------------------------------------------

    def _wanted_music(self) -> tuple[Path, ...] | None:
        """The zone's music at the current moment (None: the music chosen in the settings). Where a place has
        none of its own, or its files are not there yet, the music playing goes on."""
        if not self.zone_music:
            return None
        point = self.route.point_at(int(self.t))
        if point is None:
            return self.music_now
        files = zone_music.file_ids(self.route.view_for(point), point.instance_id, self.t)
        found = tuple(zone_music.paths(files))
        return found or self.music_now

    def _update_music(self, dt: float, now: bool = False) -> None:
        """Changes to the zone's music once the replay has been there for MUSIC_SETTLE seconds (at once after a
        jump), so passing through a zone changes nothing."""
        if not self.zone_music or not self.sound.music.active:
            return
        wanted = self._wanted_music()
        if wanted == self.music_now:
            self.music_next, self.music_wait = None, 0.0
            return
        if wanted != self.music_next:
            self.music_next, self.music_wait = wanted, 0.0
        self.music_wait += dt
        if now or self.music_wait >= MUSIC_SETTLE:
            self.music_now, self.music_next = wanted, None
            self.sound.music.play(list(wanted) if wanted else None)

    def _skip_gap(self, t: float) -> float:
        """Time without points (logout, a long break) is skipped."""
        times = self.route.times
        i = bisect.bisect_right(times, self.t) - 1
        if 0 <= i < len(times) - 1:
            a, b = self.route.points[i], self.route.points[i + 1]
            if t > a.end and b.time - a.end > GAP_SKIP:
                return max(t, float(b.time)) if t < b.time else t
        return t

    # -- scene -----------------------------------------------------------------------------

    def _render(self, jump: bool = False) -> None:
        point = self.route.point_at(int(self.t))
        if point is None:
            return
        zone = self.route.view_for(point)
        # Places the world map does not show (Forever's own islands) keep their own map.
        if self.seamless and maps.world_rect(zone, self.route.map_infos) is not None:
            if self.view_map != maps.WORLD:
                self._show_world()
                jump = True
            if zone is not None and zone != self.zone_now:
                if not jump and self.zone_now is not None and self._start_world_voyage(self.zone_now, zone, point):
                    return
                self.zone_now = zone
            spot = self.route.glide(self.t, maps.WORLD)
        else:
            if zone is not None and zone != self.view_map:
                if not jump and self.view_map is not None and self._start_voyage(self.view_map, zone, point):
                    return
                self._switch_map(zone)
                jump = True
            spot = self.route.glide(self.t)
        xy = self.route.project(*spot, self.view_map) if spot and self.view_map is not None else None
        head = QPointF(xy[0] * W, xy[1] * H) if xy else None
        if (self.view_map == maps.WORLD and head is not None and self.last_head is not None and not jump
                and math.hypot(head.x() - self.last_head.x(), head.y() - self.last_head.y()) * self._scale()
                > CUT_JUMP * self.view.viewport().width()):
            self._take_snapshot()           # a teleport: cut to the new place under a crossfade
            jump = True
        if self.route_item:
            self.route_item.set_time(self.t, head if point.instance_id is None else None)
        if self.pins:
            self.pins.set_time(self.t, animate=not jump)
        death = self._death_at(self.t)
        self.marker.set_mode("dungeon" if point.instance_id is not None else "taxi" if point.taxi
                             else ("ghost" if death.ghost(self.t) else "dead") if death else "walk")
        if head is not None:
            moved = 0.0
            if self.last_head is not None and not jump:
                self.marker.aim(head.x() - self.last_head.x(), head.y() - self.last_head.y())
                moved = math.hypot(head.x() - self.last_head.x(), head.y() - self.last_head.y())
            self.last_head = head
            self.marker.setPos(head)
            self.marker.show()
            self._follow(head, moved, point.taxi, death is not None, jump)
        else:
            self.last_head = None
            self.marker.hide()
        self._set_caption(zone, self.route.instance_name(point))
        self.bar.set_value(self.bar.timeline.to_value(self.t))
        self.clock_label.setText(format_datetime(int(self.t)))

    # -- camera ------------------------------------------------------------------------------

    def _scale(self) -> float:
        """View scale (screen pixels per map pixel) at the current zoom."""
        vw, vh = self.view.viewport().width(), self.view.viewport().height()
        if self.view_map == maps.WORLD and self.frame_size is not None:
            fw, fh = self.frame_size
            return min(vw / fw, vh / fh) * ZOOM * self.zoom
        return min(vw / W, vh / H) * ZOOM * self.zoom

    def _zone_frame(self, zone: int | None) -> tuple[float, float] | None:
        """A zone's size on the seamless world map (world units)."""
        rect = maps.world_rect(zone, self.route.map_infos)
        return ((rect[2] - rect[0]) * W, (rect[3] - rect[1]) * H) if rect else None

    def _follow_frame(self, jump: bool) -> None:
        """The seamless view's frame drifts towards the size of the zone the player is in (in log space, so
        growing and shrinking feel alike)."""
        target = self._zone_frame(self.zone_now)
        if target is None:
            return
        if jump or self.frame_size is None:
            self.frame_size = target
            return
        k = 1 - math.exp(-self.frame_dt / FRAME_SECONDS)
        self.frame_size = tuple(math.exp(math.log(a) + (math.log(b) - math.log(a)) * k)
                                for a, b in zip(self.frame_size, target))

    def _follow(self, head: QPointF, moved: float, taxi: bool, dead: bool, jump: bool) -> None:
        """Moves the camera calmly after the marker, keeping it near the middle, and lets the zoom drift towards
        what is happening: out on flight paths and fast stretches, in when a moment is close or the player
        stands still or lies dead. Both change slowly (time constants), so the picture stays calm."""
        dt = self.frame_dt
        if self.view_map == maps.WORLD:
            self._follow_frame(jump or self.camera is None)
        scale = self._scale()
        if dt > 0 and not jump:
            width = max(1, self.view.viewport().width())
            speed = moved * scale / width / dt            # picture widths per second
            self.screen_speed += (speed - self.screen_speed) * (1 - math.exp(-dt / 1.0))
        if taxi:
            target = ZOOM_OUT_TAXI
        elif self.screen_speed > FAST_FROM:
            target = 1 - (1 - ZOOM_OUT_FAST) * clamp((self.screen_speed - FAST_FROM) / (FAST_TO - FAST_FROM))
        elif dead or self._still_at(self.t) is not None or self._moment_close():
            target = ZOOM_IN_CLOSE
        else:
            target = 1.0
        if jump or self.camera is None:
            self.camera = QPointF(head)
        else:
            self.zoom += (target - self.zoom) * (1 - math.exp(-dt / ZOOM_SECONDS))
            follow = 1 - math.exp(-dt / FOLLOW_SECONDS)
            self.camera = QPointF(self.camera.x() + (head.x() - self.camera.x()) * follow,
                                  self.camera.y() + (head.y() - self.camera.y()) * follow)
            # Never let the marker drift out of the middle of the picture.
            scale = self._scale()
            area = self.picture_area()
            max_dx, max_dy = KEEP_INSIDE * area.width() / scale, KEEP_INSIDE * area.height() / scale
            self.camera = QPointF(min(max(self.camera.x(), head.x() - max_dx), head.x() + max_dx),
                                  min(max(self.camera.y(), head.y() - max_dy), head.y() + max_dy))
        self._apply_zoom()

    def _moment_close(self) -> bool:
        """True when the next moment comes within CLOSE_SECONDS of real time at the current pace."""
        if self.cue_index >= len(self.cues):
            return False
        return self.cues[self.cue_index].time - self.t < self.speed * BASE_SPEED * CLOSE_SECONDS

    def _switch_map(self, view: int, fade: str | None = "black") -> None:
        """Shows another map. fade: "black" (from black), "cross" (over the old picture) or None."""
        if fade == "cross":
            self._take_snapshot()
        scene = self.view.scene()
        if self.marker.scene() is scene:
            scene.removeItem(self.marker)   # kept across maps; clear() would delete it
        scene.clear()
        self.view_map = view
        scene.setSceneRect(QRectF(0, 0, W, H))
        pixmap = self._pixmap(view)
        if pixmap is not None:
            scene.addPixmap(pixmap)
        else:
            scene.addRect(QRectF(0, 0, W, H), QPen(QColor(theme.BORDER)), QBrush(QColor(theme.PANEL)))
        self.route_item = RouteItem(self.route.segments(view, self.start, self.end), self.colors, self.ghost_spans)
        scene.addItem(self.route_item)
        self.pins = PinsItem(self._pins_for(view))
        scene.addItem(self.pins)
        scene.addItem(self.marker)
        self.camera = None
        self.last_head = None
        self._apply_zoom()
        if fade == "black":
            self.cover_age = 0.0
            self.cover_effect.setOpacity(1.0)

    def _show_world(self) -> None:
        """Shows the seamless world map: every zone at once, the route and pins of the whole range on it."""
        scene = self.view.scene()
        if self.marker.scene() is scene:
            scene.removeItem(self.marker)
        scene.clear()
        self.view_map = maps.WORLD
        self.zone_now = None
        self.frame_size = None
        scene.setSceneRect(QRectF(-W, -H, 3 * W, 3 * H))       # room to centre anywhere
        self.world = WorldArt(scene)
        cities = {r.map_id for r in self.route.zone_runs(self.start, self.end) if r.map_id in maps.CITIES}
        for city in sorted(cities):
            rect = maps.world_rect(city, self.route.map_infos)
            pixmap = self._soft_pixmap(city)
            if rect is not None and pixmap is not None:
                self.world.add_city(city, pixmap, QRectF(rect[0] * W, rect[1] * H, (rect[2] - rect[0]) * W,
                                                   (rect[3] - rect[1]) * H))
        self.route_item = RouteItem(self.route.segments(maps.WORLD, self.start, self.end), self.colors,
                                    self.ghost_spans)
        scene.addItem(self.route_item)
        self.pins = PinsItem(self._pins_for(maps.WORLD))
        scene.addItem(self.pins)
        scene.addItem(self.marker)
        self.camera = None
        self.last_head = None
        self._apply_zoom()
        self.cover_age = 0.0
        self.cover_effect.setOpacity(1.0)

    def _start_world_voyage(self, old: int, new: int, point) -> bool:
        """A trip to the other continent on the seamless map: the camera pulls back until the world is in view,
        the player crosses the sea on an arc, and the camera dives in again. False if it is none."""
        ca, cb = self._continent(old), self._continent(new)
        if ca == cb or ca not in maps.CONTINENT_IN_WORLD or cb not in maps.CONTINENT_IN_WORLD:
            return False
        j = bisect.bisect_right(self.route.times, point.time) - 1
        if j <= 0 or point.time - self.route.points[j - 1].end > VOYAGE_GAP:
            return False
        spot = self.route.glide(self.t, maps.WORLD)
        xy = self.route.project(*spot, maps.WORLD) if spot else None
        frame = self._zone_frame(new)
        if xy is None or frame is None or self.last_head is None or self.camera is None:
            return False
        target = QPointF(xy[0] * W, xy[1] * H)
        vw, vh = self.view.viewport().width(), self.view.viewport().height()
        area = self.picture_area()
        start = self._scale()
        end = min(vw / frame[0], vh / frame[1]) * ZOOM * self.zoom
        over = min(area.width() / (W * 0.96), area.height() / (H * 0.96), start, end)
        pen = QPen(VOYAGE_LINE, 3)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line = self.view.scene().addPath(QPainterPath(), pen)
        line.setZValue(3)
        self.marker.set_mode("walk")
        self.voyage = _Voyage(new, QPointF(self.camera), QRectF(0, 0, W, H).center(), target, start, over, end,
                              QPointF(self.last_head), target, [], line)
        self._travel(0.0)
        return True

    # -- zone changes ----------------------------------------------------------------------

    def _take_snapshot(self) -> None:
        self.snapshot.setPixmap(self.view.viewport().grab())
        self.snapshot.setGeometry(self.view.geometry())
        self.snapshot_age = 0.0
        self.snapshot_effect.setOpacity(1.0)
        self.snapshot.show()

    def _continent(self, view: int | None) -> int | None:
        if view in (maps.KALIMDOR, maps.EASTERN_KINGDOMS):
            return view
        return maps.continent_of(view, self.route.map_infos) if view is not None else None

    def _zone_rect(self, view: int) -> QRectF | None:
        """Where a zone lies on its continent's map (in scene units of the continent map); a continent covers
        its whole map."""
        if view in (maps.KALIMDOR, maps.EASTERN_KINGDOMS):
            return QRectF(0, 0, W, H)
        info = self.route.map_infos.get(view)
        if info is None or info["min_x"] is None or info["max_x"] <= info["min_x"] or info["max_y"] <= info["min_y"]:
            return None
        return QRectF(info["min_x"] * W, info["min_y"] * H, (info["max_x"] - info["min_x"]) * W,
                      (info["max_y"] - info["min_y"]) * H)

    def _zone_camera(self, head: QPointF) -> QPointF:
        """Where a zone view centred on head really centres: the view stops at the map's edges."""
        scale = self._scale()
        half_w, half_h = self.view.viewport().width() / scale / 2, self.view.viewport().height() / scale / 2
        x = min(max(head.x(), half_w), W - half_w) if W > 2 * half_w else W / 2
        y = min(max(head.y(), half_h), H - half_h) if H > 2 * half_h else H / 2
        return QPointF(x, y)

    @staticmethod
    def _on_continent(rect: QRectF, p: QPointF) -> QPointF:
        """A point of a zone map on its continent's map (rect: the zone on the continent)."""
        return QPointF(rect.left() + p.x() / W * rect.width(), rect.top() + p.y() / H * rect.height())

    def _start_voyage(self, old: int, new: int, point) -> bool:
        """Shows a trip to the other continent on the world map; False if it is none or cannot be shown (no maps,
        no geometry, a long break before it)."""
        ca, cb = self._continent(old), self._continent(new)
        if ca == cb or ca not in maps.CONTINENT_ON_WORLD or cb not in maps.CONTINENT_ON_WORLD:
            return False
        j = bisect.bisect_right(self.route.times, point.time) - 1
        if j <= 0 or point.time - self.route.points[j - 1].end > VOYAGE_GAP:
            return False
        a, b = self._zone_rect(old), self._zone_rect(new)
        spot = self.route.glide(self.t)
        new_xy = self.route.project(*spot, new) if spot else None
        if (a is None or b is None or new_xy is None or self.last_head is None
                or any(self._pixmap(m) is None for m in (maps.WORLD, ca, cb))):
            return False
        on_world = {c: self._world_rect(c) for c in (ca, cb)}
        a, b = self._inside(on_world[ca], a), self._inside(on_world[cb], b)    # the zones on the world map
        viewport = self.view.viewport().rect()
        old_center = self.view.mapToScene(viewport.center())          # the old zone's view as it is now
        new_head = QPointF(new_xy[0] * W, new_xy[1] * H)
        world = QRectF(0, 0, W, H)
        area = self.picture_area()
        base = self._scale()
        start, end = base * W / a.width(), base * W / b.width()
        over = min(area.width() / (world.width() * 0.96), area.height() / (world.height() * 0.96), start, end)

        scene = self.view.scene()
        if self.marker.scene() is scene:
            scene.removeItem(self.marker)
        scene.clear()
        scene.setSceneRect(world.adjusted(-W, -H, W, H))     # room to centre anywhere
        scene.addPixmap(self._pixmap(maps.WORLD))
        details = []
        for continent in (ca, cb):
            rect = on_world[continent]
            details.append((self._placed_art(continent, rect, 0.5), 1.0))
            zone, zone_rect = (old, a) if continent == ca else (new, b)
            if zone != continent:
                details.append((self._placed_art(zone, zone_rect, 1), rect.width() / W))
            route = RouteItem(self.route.segments(continent, self.start, self.end), self.colors, self.ghost_spans)
            pins = PinsItem(self._pins_for(continent))
            for item in (route, pins):
                item.setPos(rect.topLeft())
                item.setScale(rect.width() / W)
                scene.addItem(item)
            route.setZValue(2)
            route.set_time(self.t, None)
            pins.set_time(self.t, animate=False)
            if continent == ca:
                self.route_item, self.pins = route, pins
        pen = QPen(VOYAGE_LINE, 3)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line = scene.addPath(QPainterPath(), pen)
        line.setZValue(3)
        origin = self._on_continent(a, self.last_head)
        scene.addItem(self.marker)
        self.marker.set_mode("walk")
        self.marker.setPos(origin)
        self.marker.show()
        self.view_map = None                      # no single map until the new zone is shown
        self.camera = self.last_head = None
        self.voyage = _Voyage(new, self._on_continent(a, old_center), world.center(),
                              self._on_continent(b, self._zone_camera(new_head)), start, over, end, origin,
                              self._on_continent(b, new_head), [d for d in details if d[0] is not None], line)
        self._travel(0.0)
        return True

    @staticmethod
    def _world_rect(continent: int) -> QRectF:
        x0, x1, y0, y1 = maps.CONTINENT_ON_WORLD[continent]
        return QRectF(x0 * W, y0 * H, (x1 - x0) * W, (y1 - y0) * H)

    @staticmethod
    def _inside(outer: QRectF, inner: QRectF) -> QRectF:
        """inner (in the scene units of a map) placed on that map lying at outer."""
        k = outer.width() / W
        return QRectF(outer.left() + inner.left() * k, outer.top() + inner.top() * k, inner.width() * k,
                      inner.height() * k)

    def _placed_art(self, view: int, rect: QRectF, z: float) -> QGraphicsPixmapItem | None:
        """A map's art lying at rect of the current scene."""
        pixmap = self._soft_pixmap(view)
        if pixmap is None:
            return None
        item = self.view.scene().addPixmap(pixmap)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setPos(rect.topLeft())
        item.setScale(rect.width() / W)
        item.setZValue(z)
        return item

    def _travel(self, dt: float) -> None:
        voyage = self.voyage
        voyage.age += dt
        if voyage.age >= voyage.life:
            self.voyage = None
            if self.view_map == maps.WORLD:         # seamless: already there, on the same map
                if voyage.line is not None:
                    self.view.scene().removeItem(voyage.line)
                self.zone_now = voyage.to_view
                self.frame_size = None
                self.camera = None
            else:
                self._switch_map(voyage.to_view, "cross")
            self._render(jump=True)
            return
        scale, center = voyage.camera()
        voyage.update_items(scale)
        before = self.marker.pos()
        self.marker.setPos(voyage.marker())
        self.marker.aim(self.marker.x() - before.x(), self.marker.y() - before.y())
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.view.centerOn(center)
        self._update_world(scale)

    def _pins_for(self, view: int) -> list[Pin]:
        """A pin for each cue that happened on this map (inside a dungeon: at its entrance)."""
        pins = []
        for cue in self.cues:
            spot = self.route.glide(cue.time)
            xy = self.route.project(*spot, view) if spot else None
            if xy is None:
                continue
            thumb = self._thumb(cue.path) if cue.kind == "screenshot" else None
            if cue.kind == "screenshot" and thumb is None:
                continue
            tilt = ((cue.time * 2654435761) & 0xFF) / 255 * 16 - 8
            pins.append(Pin(cue.time, QPointF(xy[0] * W, xy[1] * H), cue.glyph or "•", QColor(cue.color), thumb,
                            tilt, icons.of_event(cue.icon, cue.event_type) if thumb is None else None))
        return pins

    def _thumb(self, path: str | None) -> QPixmap | None:
        if path not in self._thumbs:
            self._thumbs[path] = load_thumbnail(path)
        return self._thumbs[path]

    def _soft_pixmap(self, view: int) -> QPixmap | None:
        """A map's art fading out towards its edges, to lie on a coarser map without showing its frame."""
        if view not in self._soft:
            pixmap = self._pixmap(view)
            soft = None
            if pixmap is not None:
                soft = QPixmap(pixmap.size())
                soft.fill(Qt.GlobalColor.transparent)
                painter = QPainter(soft)
                painter.drawPixmap(0, 0, pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                for horizontal in (True, False):
                    size = pixmap.width() if horizontal else pixmap.height()
                    edge = QLinearGradient(0, 0, size, 0) if horizontal else QLinearGradient(0, 0, 0, size)
                    for at, alpha in ((0, 0), (SOFT_EDGE * 0.35, 0), (SOFT_EDGE, 255), (1 - SOFT_EDGE, 255),
                                      (1 - SOFT_EDGE * 0.35, 0), (1, 0)):
                        edge.setColorAt(at, QColor(0, 0, 0, alpha))
                    painter.fillRect(soft.rect(), edge)
                painter.end()
            self._soft[view] = soft
        return self._soft[view]

    def _pixmap(self, view: int) -> QPixmap | None:
        if view not in self._art:
            art = find_art(view)
            pixmap = QPixmap(str(art)) if art else QPixmap()
            if not pixmap.isNull() and (pixmap.width() != W or pixmap.height() != H):
                pixmap = pixmap.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            self._art[view] = pixmap
        pixmap = self._art[view]
        return None if pixmap.isNull() else pixmap

    def _apply_zoom(self) -> None:
        vw, vh = self.view.viewport().width(), self.view.viewport().height()
        if vw <= 0 or vh <= 0 or self.voyage is not None:
            return
        scale = self._scale()
        self.view.resetTransform()
        self.view.scale(scale, scale)
        if self.camera is not None:
            self.view.centerOn(self.camera)
        self._update_world(scale)

    def _update_world(self, scale: float) -> None:
        """The seamless map's detail for the view as it is now."""
        if self.world is not None and self.view_map == maps.WORLD:
            self.world.update(self.view.mapToScene(self.view.viewport().rect()).boundingRect(), scale,
                              self.zone_now, self.frame_dt)

    def _zone_name(self, map_id: int | None, instance_id: int | None) -> str | None:
        if instance_id is not None:
            return self.route.instance_names.get(instance_id) or f"#{instance_id}"
        if map_id is None:
            return None
        info = self.route.map_infos.get(map_id)
        return maps.display_name(map_id, info["name"] if info is not None else None)

    def _set_caption(self, zone: int | None, dungeon: str | None) -> None:
        zone_name = self._zone_name(zone, None) or ""
        level = self.levels.at(self.t)
        left = f"<span style='color:{self.char_color}; font-weight:bold'>{self.char_name}</span>"
        if level:
            left += f"<br><span style='color:{theme.MUTED}; font-size:11pt'>{tr('cine.level', level=level)}</span>"
        where = (f"<span style='color:{theme.GOLD}'>{dungeon}</span><span style='color:{theme.MUTED}'>  ·  "
                 f"{zone_name}</span>") if dungeon else f"<span style='color:#e6c77a'>{zone_name}</span>"
        right = f"{where}<br><span style='color:{theme.MUTED}; font-size:11pt'>{format_datetime(int(self.t))}</span>"
        changed = False
        for label, text in ((self.caption, left), (self.place, right)):
            if text != label.text():
                label.setText(text)
                changed = True
        if changed:
            self._layout_bars()

    # -- overlays --------------------------------------------------------------------------

    def _show_cue(self, cue: Cue) -> None:
        if self.pins and self.marker.isVisible():
            kind = "level" if cue.kind == "level" else "death" if cue.event_type == "player_died" else "event"
            color = QColor(theme.GOLD) if kind == "level" else DEATH_COLOR if kind == "death" else QColor(cue.color)
            self.pins.burst(self.marker.pos(), color, kind)
        if cue.kind == "level" and cue.level is not None:
            self._show_title(tr("cine.level", level=cue.level), LEVEL_SECONDS, heading=tr("cine.banner.level_up"),
                             subtitle=self._level_subtitle(cue))
            if self.sound.play("level_up"):
                self.sound.music.duck(LEVEL_DUCK)
            return
        if cue.event_type == "player_died":
            # A moment of silence: the replay holds on a dark red title while the colour drains away.
            self._show_title(self.char_name or tr("cine.banner.player_died"), DEATH_SECONDS,
                             heading=tr("cine.banner.player_died"),
                             subtitle="  ·  ".join(p for p in (cue.cause, cue.place) if p), tone="death")
            self.hold = DEATH_HOLD
            self.ramp = 0.0
            if self.sound.play("death"):
                self.sound.music.duck(DEATH_HOLD + 1.5)
            return
        self.sound.play("event")
        if cue.has_screenshot:
            return                          # its picture follows, under a banner that says the same
        toast = AchievementToast(self, cue, TOAST_SECONDS)
        self.toasts.append(toast)
        while len(self.toasts) > MAX_TOASTS:
            self.toasts.pop(0).deleteLater()
        self._layout_toasts()
        toast.show()
        for widget in (self.title, self.photo, self.controls):
            if widget.isVisible():
                widget.raise_()

    def _level_subtitle(self, cue: Cue) -> str:
        """Where, and the playing time since the level before (breaks left out)."""
        parts = [cue.place] if cue.place else []
        i = bisect.bisect_left(self.levels.times, cue.time)
        if i > 0:
            took = self.route.timeline(self.levels.times[i - 1], cue.time, GAP_SKIP).total
            if took >= 60:
                parts.append(tr("cine.level_took", time=format_duration(took), level=self.levels.levels[i - 1]))
        return "  ·  ".join(parts)

    def _show_title(self, text: str, life: float, heading: str = "", subtitle: str = "", tone: str = "gold") -> None:
        self.title.show_text(text, life, heading, subtitle, tone)

    def _title_busy(self) -> bool:
        """True while a level-up or death title has not been shown for LEVEL_HOLD seconds yet."""
        return self.title.isVisible() and self.title.age < LEVEL_HOLD and self.title.life <= LEVEL_SECONDS

    def _show_photo(self, cue: Cue) -> None:
        pixmap = QPixmap(cue.path)
        if pixmap.isNull():
            return
        if self.title.isVisible() and self.title.life <= LEVEL_SECONDS:
            self.title.life = min(self.title.life, self.title.age + FADE_SECONDS)   # makes way for the picture
        area = self.picture_area()
        # Big enough for the polaroid at its largest, small enough to draw quickly at every frame.
        pixmap = pixmap.scaled(int(area.width() * 0.75), int(area.height() * 0.95), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        origin = (QPointF(self.view.mapFromScene(self.marker.pos())) if self.marker.isVisible()
                  else area.center())
        self.photo.show_cue(cue, pixmap, origin, area)
        self.photo_on = True
        self.sound.play("screenshot")
        self.controls.raise_()

    def _hide_photo(self) -> None:
        if self.photo_on:
            self.ramp = 0.0                 # get back to speed gently
        self.photo_on = False
        self.photo.hide()

    def _age_overlays(self, dt: float) -> None:
        for toast in list(self.toasts):
            if not toast.advance(dt):
                self.toasts.remove(toast)
                toast.deleteLater()
                self._layout_toasts()
        self.title.advance(dt)
        self._update_still(dt)
        if self.frame.advance(dt):
            self._layout_bars()
            self._layout_still()
        self.marker.tick(dt)
        if self.route_item:
            self.route_item.advance_phase(dt)
        if self.pins:
            self.pins.tick(dt)
        if self.snapshot.isVisible():
            self.snapshot_age += dt
            self.snapshot_effect.setOpacity(max(0.0, 1 - self.snapshot_age / CROSS_SECONDS))
            if self.snapshot_age >= CROSS_SECONDS:
                self.snapshot.hide()
        if self.cover_age < FADE_SECONDS * 2:
            self.cover_age += dt
            self.cover_effect.setOpacity(max(0.0, 1 - self.cover_age / FADE_SECONDS))
        self._age_controls(dt)
