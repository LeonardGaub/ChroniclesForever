"""Overview: statistics from the stat registry, grouped, the equipped gear and the most recent events.

The stats are tiles as in the addon's overview: game icon, name (gold, small) and value (white), two per row, under
each group's heading and description."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
                               QWidget)

from ...domain import event_types, stats
from ...i18n import format_datetime, tr
from .. import icons, theme
from ..widgets import Page, muted

RECENT_EVENTS = 12
TILE_COLUMNS = 2


class StatTile(QWidget):
    """A stat as the addon shows it: the icon in a dark square, the name above the value beside it."""

    def __init__(self, stat: stats.Stat):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setFixedSize(icons.TILE_SIZE, icons.TILE_SIZE)
        picture = icons.tile(stat.icon)
        if picture:
            icon.setPixmap(picture)
        else:  # no icon file: the empty square
            icon.setStyleSheet("background: rgba(0, 0, 0, 178);")
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setContentsMargins(0, 1, 0, 1)
        text.setSpacing(0)
        self.name, self.value = QLabel(), QLabel()
        self.name.setStyleSheet(theme.font_css(9, theme.GOLD))
        self.value.setStyleSheet(theme.font_css(11, "#ffffff"))
        text.addWidget(self.name)
        text.addWidget(self.value)
        layout.addLayout(text, 1)


class OverviewPage(Page):
    title_key = "tab.overview"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left = QVBoxLayout()
        self.groups: dict[str, tuple[QGroupBox, QLabel, QGridLayout]] = {}
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        for stat in stats.STATS:
            if stat.group not in self.groups:
                box = QGroupBox()
                layout = QVBoxLayout(box)
                layout.setSpacing(6)
                desc = muted()
                layout.addWidget(desc)
                grid = QGridLayout()
                grid.setHorizontalSpacing(16)
                grid.setVerticalSpacing(6)
                layout.addLayout(grid)
                self.groups[stat.group] = (box, desc, grid)
                left.addWidget(box)
            grid = self.groups[stat.group][2]
            tile = StatTile(stat)
            n = grid.count()
            grid.addWidget(tile, n // TILE_COLUMNS, n % TILE_COLUMNS)
            self.rows[stat.key] = (tile.name, tile.value)
        left.addStretch(1)
        self.hint = muted()
        left.addWidget(self.hint)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        self.gear_box = QGroupBox()
        gear_layout = QVBoxLayout(self.gear_box)
        self.gear = QListWidget()
        self.gear.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        gear_layout.addWidget(self.gear)
        right.addWidget(self.gear_box, 1)
        self.recent_box = QGroupBox()
        recent_layout = QVBoxLayout(self.recent_box)
        self.recent = QListWidget()
        self.recent.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        recent_layout.addWidget(self.recent)
        right.addWidget(self.recent_box, 1)
        root.addLayout(right, 1)

    def refresh(self) -> None:
        for group, (box, desc, _) in self.groups.items():
            box.setTitle(tr(f"stats.group.{group}"))
            desc.setText(tr(f"stats.group.{group}.desc"))
        self.recent_box.setTitle(tr("overview.recent"))
        self.hint.setText(tr("overview.estimated_hint"))
        values = dict((s.key, (s, v)) for s, v in stats.compute_all(self.ctx.repo, self.character_id)) \
            if self.character_id else {}
        for stat in stats.STATS:
            label, value = self.rows[stat.key]
            label.setText(tr(stat.label_key))
            s, v = values.get(stat.key, (stat, None))
            value.setText(stats.format_value(s, v) if self.character_id else "")

        self.gear_box.setTitle(tr("overview.gear"))
        self.gear.clear()
        self.recent.clear()
        if not self.character_id:
            return
        rows = self.ctx.repo.gear(self.character_id)
        for row in rows:
            name = re.search(r"\[(.+?)\]", row["link"])
            slot = tr(f"gear.slot.{row['slot_name']}") if row["slot_name"] else str(row["slot"])
            item = QListWidgetItem(f"{slot}:  {name.group(1) if name else '?'}")
            item.setForeground(QColor(theme.QUALITY_COLORS.get(row["quality"], theme.TEXT)))
            self.gear.addItem(item)
        if not rows:
            self.gear.addItem(QListWidgetItem(tr("overview.gear_none")))
        for event in self.ctx.repo.events(self.character_id, limit=RECENT_EVENTS):
            icon, text = icons.event_small(event), event_types.describe(event)
            item = QListWidgetItem(text if icon else f"{event_types.get(event.event_type).glyph}  {text}")
            if icon:
                item.setData(Qt.ItemDataRole.DecorationRole, icon)
            item.setToolTip(f"{format_datetime(event.occurred_at)}\n{event_types.location_text(event)}")
            item.setForeground(Qt.GlobalColor.white)
            self.recent.addItem(item)
