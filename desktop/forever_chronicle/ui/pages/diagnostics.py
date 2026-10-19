"""Diagnostics: capability status reported by the addon, data gaps and file locations (spec F-012)."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QLabel, QTableWidgetItem, QVBoxLayout

from ...i18n import format_date, format_datetime, tr
from .. import theme
from ..widgets import Page, muted, table

STATUS_COLORS = {"confirmed": "#1eff00", "present": theme.GOLD, "missing": theme.RED}


class DiagnosticsPage(Page):
    title_key = "tab.diagnostics"
    scrollable = True
    needs_character = False

    def __init__(self, ctx):
        super().__init__(ctx)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.caps_box = QGroupBox()
        cl = QVBoxLayout(self.caps_box)
        self.caps = table(3, 0)
        cl.addWidget(self.caps)
        root.addWidget(self.caps_box, 2)

        self.gaps_box = QGroupBox()
        gl = QVBoxLayout(self.gaps_box)
        self.gaps = QLabel()
        self.gaps.setWordWrap(True)
        gl.addWidget(self.gaps)
        root.addWidget(self.gaps_box)

        self.paths_box = QGroupBox()
        pl = QVBoxLayout(self.paths_box)
        self.paths = muted()
        pl.addWidget(self.paths)
        root.addWidget(self.paths_box)

    def refresh(self) -> None:
        self.caps_box.setTitle(tr("diag.capabilities"))
        self.gaps_box.setTitle(tr("diag.gaps"))
        self.paths_box.setTitle(tr("diag.paths"))

        self.caps.setHorizontalHeaderLabels([tr("diag.col.feature"), tr("diag.col.status"), tr("diag.col.since")])
        caps = self.ctx.repo.capabilities()
        self.caps.setRowCount(len(caps))
        for i, c in enumerate(caps):
            status = QTableWidgetItem(tr(f"diag.cap.{c['status']}"))
            status.setForeground(QColor(STATUS_COLORS.get(c["status"], theme.TEXT)))
            self.caps.setItem(i, 0, QTableWidgetItem(tr(f"cap.{c['capability']}")))
            self.caps.setItem(i, 1, status)
            self.caps.setItem(i, 2, QTableWidgetItem(format_date(c["confirmed_at"]) if c["confirmed_at"] else ""))

        gaps = self.ctx.repo.gaps()
        if gaps:
            self.gaps.setText("\n".join(tr("diag.gap_line", stream=g["stream"], start=g["from_seq"], end=g["to_seq"],
                                           when=format_datetime(g["before_time"])) for g in gaps[:20]))
        else:
            self.gaps.setText(tr("diag.gaps_none"))

        cfg = self.ctx.config
        self.paths.setText(tr("diag.database", path=cfg.database_path) + "\n" + tr("diag.backups", path=cfg.backup_dir))
