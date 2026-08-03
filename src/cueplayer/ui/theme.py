"""Cursor-inspired dark theme for the whole app.

Applied once in ``app.py`` via ``QApplication.setStyle("Fusion")`` +
``QApplication.setStyleSheet(build_stylesheet())``. Per-widget stylesheets
should only add accents that the global sheet cannot express (mark colors,
NOW cards, timeline painting) — see AGENTS.md / theme rollout notes.
"""

from __future__ import annotations

import base64

from PySide6.QtGui import QColor, QPalette

# Core palette -----------------------------------------------------------
# Cursor-like: near-black chrome, slightly lifted side panels.
BG_APP = "#09090b"
BG_SIDEBAR = "#141416"
BG_PANEL = "#111113"
BG_RAISED = "#18181b"
BG_INPUT = "#0c0c0e"
BG_HOVER = "#1c1c1f"
BG_SELECTED = "#1a3a5c"

BORDER = "#27272a"
BORDER_STRONG = "#3f3f46"

TEXT = "#e4e4e7"
TEXT_MUTED = "#a1a1aa"
TEXT_DISABLED = "#52525b"

ACCENT = "#4a9eff"
ACCENT_HOVER = "#79b8ff"
ACCENT_PRESSED = "#3a82d6"
ACCENT_TEXT = "#09090b"

DANGER = "#e5534b"
WARNING = "#d29922"

# Shared QSlider look (used by Master Volume + LTC Gain, and any other
# horizontal slider that wants the same groove/handle/accent styling).
# QSlider isn't covered by the global stylesheet below because a few
# sliders need per-instance sizing, so we share this snippet instead of
# duplicating the QSS.
SLIDER_QSS = f"""
QSlider::groove:horizontal {{
    height: 6px; background: {BORDER}; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 14px; margin: -5px 0; border-radius: 7px;
    background: {TEXT};
}}
QSlider::sub-page:horizontal {{
    background: {TEXT}; border-radius: 3px;
}}
"""


# White tick on accent fill — Qt stylesheets need an image for a visible checkmark.
_CHECK_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='15' height='15' viewBox='0 0 15 15'>"
    "<path d='M3.2 7.6 L6.2 10.6 L11.8 4.4' fill='none' stroke='#ffffff' "
    "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/>"
    "</svg>"
)
_CHECK_ICON = "data:image/svg+xml;base64," + base64.b64encode(_CHECK_SVG.encode("utf-8")).decode("ascii")


# Selection-styling helpers ------------------------------------------------
# Shared so any hand-painted "this is selected / this is a drop target"
# overlay (setlist drag indicator, timeline box-select, custom-colored rows,
# etc.) reads as the same accent-blue family as the rest of the app instead
# of a one-off, mismatched color.


def with_alpha(hex_color: str, alpha: int) -> QColor:
    """Return ``hex_color`` as a QColor with the given alpha (0-255)."""
    color = QColor(hex_color)
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


def contrast_text_color(hex_color: str) -> str:
    """Pick readable near-black / near-white text for an arbitrary background."""
    color = QColor(hex_color)
    if not color.isValid():
        return TEXT
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#0b0b0d" if luminance > 150 else "#f4f4f5"


def build_stylesheet() -> str:
    check_icon = _CHECK_ICON
    return f"""
QWidget {{
    background-color: {BG_APP};
    color: {TEXT};
    selection-background-color: {BG_SELECTED};
    selection-color: {TEXT};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {BG_APP};
}}

QToolTip {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* --- Menus --------------------------------------------------------- */
QMenuBar {{
    background-color: {BG_APP};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
    padding: 2px 4px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background: {BG_HOVER};
}}
QMenu {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {BG_SELECTED};
    color: {TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}

/* --- Buttons --------------------------------------------------------- */
QPushButton {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 12px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
    border-color: {BORDER_STRONG};
}}
QPushButton:pressed {{
    background-color: {BG_APP};
}}
QPushButton:checked {{
    background-color: {BG_SELECTED};
    border-color: {ACCENT};
    color: #ffffff;
}}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
    border-color: {BORDER};
    background-color: {BG_PANEL};
}}
QPushButton:default {{
    border-color: {ACCENT};
}}

/* --- Setlist sidebar (slightly lighter than app chrome) ---------------- */
#setlistPanel {{
    background-color: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}
#setlistPanel QLabel {{
    background: transparent;
    color: {TEXT};
}}
#setlistPanel QTableWidget {{
    background-color: {BG_SIDEBAR};
    alternate-background-color: #19191c;
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#setlistPanel QHeaderView::section {{
    background-color: #1a1a1d;
    color: {TEXT_MUTED};
}}
#setlistPanel QPushButton {{
    background-color: {BG_RAISED};
}}

/* --- Inputs ------------------------------------------------------------ */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
    selection-background-color: {BG_SELECTED};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled {{
    color: {TEXT_DISABLED};
    background-color: {BG_PANEL};
}}

QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 8px;
}}
QComboBox:hover {{
    border-color: {BORDER_STRONG};
}}
QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {BG_SELECTED};
    outline: none;
}}

QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}

/* --- Checkboxes / radios ------------------------------------------------ */
QCheckBox, QRadioButton {{
    color: {TEXT};
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER_STRONG};
    background: {BG_INPUT};
}}
QCheckBox::indicator {{
    border-radius: 3px;
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url({check_icon});
}}
QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {{
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {ACCENT_HOVER};
}}

/* --- Group boxes --------------------------------------------------------- */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 12px;
    color: {TEXT};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {TEXT_MUTED};
}}

/* --- Tables / lists -------------------------------------------------- */
QTableWidget, QTableView, QListWidget, QTreeWidget {{
    background-color: {BG_PANEL};
    alternate-background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    outline: none;
}}
QTableWidget::item, QListWidget::item {{
    padding: 4px 6px;
}}
QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {BG_SELECTED};
    color: #ffffff;
}}
QHeaderView::section {{
    background-color: {BG_RAISED};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 6px 8px;
}}
QTableCornerButton::section {{
    background-color: {BG_RAISED};
    border: none;
}}

/* --- Scrollbars ------------------------------------------------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* --- Misc ------------------------------------------------------------- */
QSplitter::handle {{
    background: {BORDER};
}}
QSplitter::handle:hover {{
    background: {ACCENT};
}}
QStatusBar {{
    background-color: {BG_APP};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
}}
QScrollArea {{
    border: none;
}}
QDialogButtonBox QPushButton {{
    min-width: 72px;
}}
"""


def apply_dark_palette(app) -> None:  # noqa: ANN001
    """Set a matching QPalette so native widgets (dialogs, color picker) fit in."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_APP))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_RAISED))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_RAISED))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_RAISED))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(DANGER))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(BG_SELECTED))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_DISABLED))
    app.setPalette(palette)
