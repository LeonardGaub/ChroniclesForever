"""Gallery: the character's screenshots as a grid of pictures, grouped by zone, level, type or session (newest
group first, newest picture first within it), with favourite stars and "only favourites".

A tile shows the picture, what happened (gold) and when; the star in its corner marks a favourite (kept in the
database, Repository.set_favorite). Clicking a tile opens the viewer (ui/screenshots.py): full picture under the
event's banner, stepping through the gallery in its order, and "Wiedergabe ab hier" plays the cinematic mode from
that moment.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ...domain import event_types, maps
from ...domain.cinematic import Levels
from ...domain.route import Route
from ...i18n import format_datetime, tr
from .. import theme
from ..screenshots import ScreenshotViewer, Shot, ThumbnailLoader, file_exists, make_shot
from ..widgets import Page, heading, muted

GROUPS = ("session", "zone", "level", "type")
TILE = QSize(232, 146)          # picture part of a tile
CAPTION_H = 40
GAP = 12
STAR = 30                       # clickable star area in the tile's corner


@dataclass
class Entry:
    shot: Shot
    zone: str
    level: int | None
    kind: str                   # event type label
    session: tuple[int, str]    # (start, label)


class ShotTile(QWidget):
    """A picture with its caption; the star in the top-right corner toggles the favourite."""

    opened = Signal(object)
    starred = Signal(object, bool)

    def __init__(self, entry: Entry, favorite: bool):
        super().__init__()
        self.entry, self.favorite = entry, favorite
        self.pixmap: QPixmap | None = None
        self.hover = False
        self.setFixedSize(TILE.width(), TILE.height() + CAPTION_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip(entry.shot.caption)

    def set_picture(self, icon: QIcon) -> None:
        self.pixmap = icon.pixmap(icon.availableSizes()[0]) if icon.availableSizes() else icon.pixmap(TILE * 2)
        self.update()

    def star_rect(self) -> QRect:
        return QRect(TILE.width() - STAR - 4, 4, STAR, STAR)

    def enterEvent(self, event) -> None:
        self.hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.rect().contains(event.position().toPoint()):
            return
        if self.star_rect().contains(event.position().toPoint()):
            self.favorite = not self.favorite
            self.update()
            self.starred.emit(self, self.favorite)
        else:
            self.opened.emit(self)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        picture = QRectF(0, 0, TILE.width(), TILE.height())
        painter.fillRect(self.rect(), QColor(theme.PANEL_ALT))
        if self.pixmap is not None and not self.pixmap.isNull():
            # Cropped to fill the tile, from the middle.
            pw, ph = self.pixmap.width(), self.pixmap.height()
            scale = max(picture.width() / pw, picture.height() / ph)
            cw, ch = picture.width() / scale, picture.height() / scale
            painter.drawPixmap(picture, self.pixmap, QRectF((pw - cw) / 2, (ph - ch) / 2, cw, ch))
        else:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(picture, Qt.AlignmentFlag.AlignCenter, tr("screenshot.loading"))
        cue = self.entry.shot.cue
        title = (cue.title or cue.text) if cue else self.entry.shot.caption
        caption = QRectF(0, TILE.height(), TILE.width(), CAPTION_H)
        painter.fillRect(caption, QColor(theme.PANEL))
        font = theme.heading_font(10)
        painter.setFont(font)
        painter.setPen(QColor(theme.GOLD))
        painter.drawText(caption.adjusted(8, 3, -8, -CAPTION_H / 2), Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(font).elidedText(title, Qt.TextElideMode.ElideRight, TILE.width() - 16))
        small = painter.font()
        small.setPointSize(8)
        painter.setFont(small)
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(caption.adjusted(8, CAPTION_H / 2, -8, -3), Qt.AlignmentFlag.AlignVCenter,
                         "  ·  ".join(p for p in ((cue.heading if cue else ""), format_datetime(cue.time) if cue else "")
                                      if p))
        if self.favorite or self.hover:
            self._star(painter, QRectF(self.star_rect()))
        painter.setPen(QPen(QColor(theme.GOLD if self.hover else theme.BORDER), 2 if self.hover else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()

    def _star(self, painter: QPainter, r: QRectF) -> None:
        import math
        path = QPainterPath()
        c, outer, inner = r.center(), r.width() / 2 - 2, r.width() / 5
        for i in range(10):
            radius = outer if i % 2 == 0 else inner
            a = math.radians(-90 + i * 36)
            p = QPointF(c.x() + radius * math.cos(a), c.y() + radius * math.sin(a))
            path.moveTo(p) if i == 0 else path.lineTo(p)
        path.closeSubpath()
        painter.setPen(QPen(QColor(0, 0, 0, 220), 1.5))
        painter.setBrush(QColor(theme.GOLD) if self.favorite else QColor(255, 255, 255, 90))
        painter.drawPath(path)


class TileGrid(QWidget):
    """Tiles in as many columns as fit; laid out again when the width changes."""

    def __init__(self, tiles: list[ShotTile]):
        super().__init__()
        self.tiles = tiles
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GAP)
        self.columns = 0
        self._place(4)

    def _place(self, columns: int) -> None:
        if columns == self.columns:
            return
        self.columns = columns
        for tile in self.tiles:
            self.grid.removeWidget(tile)
        for i, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, i // columns, i % columns)
        self.grid.setColumnStretch(columns, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place(max(1, (self.width() + GAP) // (TILE.width() + GAP)))


class GalleryPage(Page):
    title_key = "tab.gallery"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        bar = QHBoxLayout()
        self.heading = heading()
        self.group_by = QComboBox()
        self.group_by.currentIndexChanged.connect(self._group_changed)
        self.only_favorites = QPushButton()
        self.only_favorites.setCheckable(True)
        self.only_favorites.toggled.connect(lambda _: self._fill())
        self.count = muted()
        self.count.setWordWrap(False)
        self.open_folder = QPushButton()
        self.open_folder.clicked.connect(self._open_folder)
        bar.addWidget(self.heading)
        bar.addSpacing(12)
        bar.addWidget(self.group_by)
        bar.addWidget(self.only_favorites)
        bar.addStretch(1)
        bar.addWidget(self.count)
        bar.addWidget(self.open_folder)
        root.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll, 1)
        self.empty = muted()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty)

        self.thumbnails = ThumbnailLoader(self, TILE * 2)
        self.entries: list[Entry] = []
        self.favorites: set[str] = set()
        self.tiles: list[ShotTile] = []
        self.shown: list[Shot] = []           # in display order (the viewer steps through them)
        self.sections: list[tuple[str, list[Entry]]] = []

    # -- data ------------------------------------------------------------------------------

    def refresh(self) -> None:
        self.heading.setText(tr("tab.gallery"))
        self.only_favorites.setText(tr("gallery.only_favorites"))
        self.open_folder.setText(tr("screenshot.open_folder"))
        client = self.ctx.client()
        self.open_folder.setEnabled(bool(client and client.screenshots_dir.is_dir()))
        mode = self.ctx.config.extra.get("gallery_group", "session")
        self.group_by.blockSignals(True)
        self.group_by.clear()
        for key in GROUPS:
            self.group_by.addItem(tr(f"gallery.by.{key}"), key)
        self.group_by.setCurrentIndex(max(0, self.group_by.findData(mode)))
        self.group_by.blockSignals(False)
        self.entries = self._load() if self.character_id else []
        self.favorites = self.ctx.repo.favorite_screenshots(self.character_id) if self.character_id else set()
        self._fill()

    def _load(self) -> list[Entry]:
        repo, cid = self.ctx.repo, self.character_id
        rows = [r for r in repo.screenshots(cid, only_files=True) if file_exists(r["file_path"])]
        if not rows:
            return []
        events = {e.event_id: e for e in repo.events(cid, limit=1_000_000)}
        char = next((c for c in repo.list_characters() if c.character_id == cid), None)
        levels = Levels(events.values(), char.level if char else None)
        route = Route(repo.positions(cid), repo.map_infos())
        sessions = sorted((s["started_at"] for s in repo.sessions(cid)), reverse=True)
        entries = []
        for row in rows:
            event = events.get(row["first_event_id"])
            shot = make_shot(row, event)
            t = shot.time or 0
            zone = event.zone_name if event is not None and event.zone_name else None
            if zone is None:
                point = route.point_at(int(t))
                view = route.view_for(point) if point else None
                info = route.map_infos.get(view) if view is not None else None
                zone = maps.display_name(view, info["name"] if info is not None else None) if view else None
            kind = (tr(event_types.get(event.event_type).label_key) if event is not None
                    else tr(f"trigger.{row['trigger_type']}"))
            start = next((s for s in sessions if s <= t), None)
            session = (start or 0, format_datetime(start) if start else tr("common.unknown"))
            entries.append(Entry(shot, zone or tr("gallery.no_zone"), levels.at(t), kind, session))
        return entries

    def _group_changed(self) -> None:
        self.ctx.config.extra["gallery_group"] = self.group_by.currentData()
        self.ctx.config.save()
        self._fill()

    def _sections(self, entries: list[Entry]) -> list[tuple[str, list[Entry]]]:
        """(heading, entries) per group: groups newest first (levels highest first), pictures newest first."""
        mode = self.group_by.currentData() or "session"
        key = {"zone": lambda e: e.zone, "level": lambda e: e.level or 0, "type": lambda e: e.kind,
               "session": lambda e: e.session}[mode]
        groups: dict = {}
        for e in sorted(entries, key=lambda e: e.shot.time or 0, reverse=True):
            groups.setdefault(key(e), []).append(e)
        order = sorted(groups, key=lambda k: k if mode == "level" else max(e.shot.time or 0 for e in groups[k]),
                       reverse=True)
        def title(k) -> str:
            if mode == "level":
                return tr("cine.level", level=k) if k else tr("common.unknown")
            if mode == "session":
                return tr("gallery.session", when=k[1])
            return str(k)
        return [(title(k), groups[k]) for k in order]

    def _fill(self) -> None:
        self.thumbnails.clear()
        entries = [e for e in self.entries
                   if not self.only_favorites.isChecked() or e.shot.screenshot_id in self.favorites]
        self.sections = self._sections(entries)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)
        self.tiles, self.shown = [], []
        for title, group in self.sections:
            label = QLabel(f"{title}   <span style='color:{theme.MUTED}; font-size:9pt'>"
                           f"{tr('gallery.picture_one') if len(group) == 1 else tr('gallery.pictures', n=len(group))}</span>")
            label.setStyleSheet(theme.font_css(13, theme.GOLD))
            layout.addWidget(label)
            tiles = []
            for entry in group:
                tile = ShotTile(entry, entry.shot.screenshot_id in self.favorites)
                tile.setProperty("index", len(self.shown))
                tile.opened.connect(self._open_tile)
                tile.starred.connect(self._star_tile)
                self.thumbnails.request(entry.shot.path, tile.set_picture)
                tiles.append(tile)
                self.shown.append(entry.shot)
            self.tiles.extend(tiles)
            layout.addWidget(TileGrid(tiles))
        layout.addStretch(1)
        self.scroll.setWidget(content)
        n_fav = sum(1 for e in self.entries if e.shot.screenshot_id in self.favorites)
        self.count.setText(tr("gallery.count", n=len(self.entries), fav=n_fav) if self.entries else "")
        self.empty.setVisible(not entries)
        self.empty.setText(tr("gallery.empty_favorites") if self.entries else tr("gallery.empty"))

    # -- actions ---------------------------------------------------------------------------

    def open_viewer(self, index: int) -> ScreenshotViewer | None:
        if not 0 <= index < len(self.shown):
            return None
        viewer = ScreenshotViewer(self.shown, index, self, self.ctx)
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        viewer.favorite_changed.connect(self._favorite_changed)
        viewer.showFullScreen()
        return viewer

    def _open_tile(self, tile: ShotTile) -> None:
        self.open_viewer(tile.property("index"))

    def _star_tile(self, tile: ShotTile, on: bool) -> None:
        shot = tile.entry.shot
        self.ctx.repo.set_favorite(shot.character_id, shot.screenshot_id, on)
        self._favorite_changed(shot.screenshot_id, on)

    def _favorite_changed(self, screenshot_id: str, on: bool) -> None:
        (self.favorites.add if on else self.favorites.discard)(screenshot_id)
        for tile in self.tiles:
            if tile.entry.shot.screenshot_id == screenshot_id and tile.favorite != on:
                tile.favorite = on
                tile.update()
        n_fav = sum(1 for e in self.entries if e.shot.screenshot_id in self.favorites)
        self.count.setText(tr("gallery.count", n=len(self.entries), fav=n_fav))

    def _open_folder(self) -> None:
        client = self.ctx.client()
        if client:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(client.screenshots_dir)))
