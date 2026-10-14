"""Overview: statistics from the stat registry, grouped, plus the most recent events."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from ...domain import event_types, stats
from ...i18n import format_datetime, tr
from ..widgets import Page, muted, value_label

RECENT_EVENTS = 12


class OverviewPage(Page):
    title_key = "tab.overview"

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left = QVBoxLayout()
        self.groups: dict[str, tuple[QGroupBox, QFormLayout]] = {}
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        for stat in stats.STATS:
            if stat.group not in self.groups:
                box = QGroupBox()
                form = QFormLayout(box)
                form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
                form.setHorizontalSpacing(24)
                form.setVerticalSpacing(6)
                self.groups[stat.group] = (box, form)
                left.addWidget(box)
            label, value = QLabel(), value_label()
            self.groups[stat.group][1].addRow(label, value)
            self.rows[stat.key] = (label, value)
        left.addStretch(1)
        self.hint = muted()
        left.addWidget(self.hint)
        root.addLayout(left, 1)

        self.recent_box = QGroupBox()
        recent_layout = QVBoxLayout(self.recent_box)
        self.recent = QListWidget()
        self.recent.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        recent_layout.addWidget(self.recent)
        root.addWidget(self.recent_box, 1)

    def refresh(self) -> None:
        for group, (box, _) in self.groups.items():
            box.setTitle(tr(f"stats.group.{group}"))
        self.recent_box.setTitle(tr("overview.recent"))
        self.hint.setText(tr("overview.estimated_hint"))
        values = dict((s.key, (s, v)) for s, v in stats.compute_all(self.ctx.repo, self.character_id)) \
            if self.character_id else {}
        for stat in stats.STATS:
            label, value = self.rows[stat.key]
            label.setText(tr(stat.label_key))
            s, v = values.get(stat.key, (stat, None))
            value.setText(stats.format_value(s, v) if self.character_id else "")

        self.recent.clear()
        if not self.character_id:
            return
        for event in self.ctx.repo.events(self.character_id, limit=RECENT_EVENTS):
            et = event_types.get(event.event_type)
            item = QListWidgetItem(f"{et.glyph}  {event_types.describe(event)}")
            item.setToolTip(f"{format_datetime(event.occurred_at)}\n{event_types.location_text(event)}")
            item.setForeground(Qt.GlobalColor.white)
            self.recent.addItem(item)
