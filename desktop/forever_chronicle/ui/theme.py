"""Classic-WoW-inspired look: dark stone panels, bronze borders, gold serif headings,
red Classic buttons and tabs at the bottom of the window like the in-game panels."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

GOLD = "#ffd100"
TEXT = "#e8e2d0"
MUTED = "#9d8f75"
BG = "#0f0c09"
PANEL = "#1a1510"
PANEL_ALT = "#15110d"
BORDER = "#5a4630"
SELECT = "#3a2c18"
RED = "#ff4040"

HEADING_FONTS = ["Friz Quadrata TT", "Palatino Linotype", "Book Antiqua", "Georgia", "serif"]

# Classic class colours.
CLASS_COLORS = {
    "DRUID": "#ff7d0a", "HUNTER": "#abd473", "MAGE": "#69ccf0", "PALADIN": "#f58cba", "PRIEST": "#ffffff",
    "ROGUE": "#fff569", "SHAMAN": "#0070de", "WARLOCK": "#9482c9", "WARRIOR": "#c79c6e",
}


def class_color(class_file: str | None) -> str:
    return CLASS_COLORS.get((class_file or "").upper(), TEXT)


def heading_font(size: int = 14, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(HEADING_FONTS)
    font.setPointSize(size)
    font.setBold(bold)
    return font


STYLESHEET = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; }}
QMainWindow::separator {{ background: {BORDER}; width: 1px; }}

QFrame#Panel {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px; }}
QFrame#Panel QLabel, QFrame#Panel QCheckBox {{ background: transparent; }}

QLabel#Heading {{ color: {GOLD}; font-family: {", ".join(f'"{f}"' for f in HEADING_FONTS)}; font-size: 13pt; }}
QLabel#Title {{ font-family: {", ".join(f'"{f}"' for f in HEADING_FONTS)}; font-size: 20pt; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Value {{ color: #ffffff; }}

QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {GOLD};
                    font-family: {", ".join(f'"{f}"' for f in HEADING_FONTS)}; font-size: 11pt; }}
QGroupBox QLabel {{ background: transparent; }}

QPushButton {{ color: {GOLD}; border: 1px solid #c9a24a; border-radius: 3px; padding: 5px 14px;
               background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #9b1c1c, stop:1 #5c0f0f); }}
QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b52424, stop:1 #6e1414); }}
QPushButton:pressed {{ background: #4a0b0b; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; background: #2a2018; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; background: {PANEL}; border-radius: 4px; }}
QTabBar::tab {{ background: #241b12; color: {GOLD}; border: 1px solid {BORDER}; padding: 6px 16px; margin-right: 3px;
                border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; min-width: 70px; }}
QTabBar::tab:selected {{ background: {SELECT}; color: #ffffff; border-color: {GOLD}; }}
QTabBar::tab:hover {{ background: #2e2216; }}

QListWidget, QTableWidget {{ background: {PANEL_ALT}; alternate-background-color: {PANEL}; border: 1px solid {BORDER};
                             selection-background-color: {SELECT}; selection-color: #ffffff; outline: 0; }}
QListWidget::item {{ padding: 2px; border-bottom: 1px solid #241b12; }}
QListWidget::item:selected {{ background: {SELECT}; border-left: 3px solid {GOLD}; }}
QHeaderView::section {{ background: #241b12; color: {GOLD}; border: 0; border-right: 1px solid {BORDER};
                        border-bottom: 1px solid {BORDER}; padding: 4px 6px; }}
QTableWidget {{ gridline-color: #241b12; }}

QLineEdit, QComboBox {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; border-radius: 3px; padding: 4px 6px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {GOLD}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: {SELECT}; border: 1px solid {BORDER}; }}

QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER}; background: {PANEL_ALT}; }}
QCheckBox::indicator:checked {{ background: {GOLD}; }}

QSlider::groove:horizontal {{ height: 6px; background: #241b12; border: 1px solid {BORDER}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: #8a6d3b; border: 1px solid {BORDER}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {GOLD}; border: 1px solid #000000; width: 14px; margin: -6px 0;
                              border-radius: 7px; }}
QSlider::handle:horizontal:disabled {{ background: {MUTED}; }}

QScrollBar:vertical {{ background: {PANEL_ALT}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #4a3a26; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #6b5435; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {SELECT}; color: {GOLD}; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QToolTip {{ background: #090807; color: {TEXT}; border: 1px solid {GOLD}; padding: 4px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(SELECT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
