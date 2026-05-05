"""Dark Qt stylesheet matching the look of the bundled HTML editor.

The HTML build uses a near-black canvas with subtle border separators,
mid-gray text, and a teal/cyan accent for primary actions. 

Colour tokens:
* BG           — #1a1d23
* PANEL        — #22262e
* PANEL_ALT    — #2a2f38
* BORDER       — #363b46
* TEXT         — #e6e8ec
* TEXT_MUTED   — #8c93a0
* ACCENT       — #22d3c5
"""

from __future__ import annotations

BG = "#1a1d23"
PANEL = "#22262e"
PANEL_ALT = "#2a2f38"
BORDER = "#363b46"
TEXT = "#e6e8ec"
TEXT_MUTED = "#8c93a0"
ACCENT = "#22d3c5"
ACCENT_HOVER = "#3ee2d4"
DANGER = "#ef4444"
HEADER_TEXT = "#a6acb8"

STYLESHEET = f"""
/* ---- Defaults --------------------------------------------------------- */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
    outline: none;
}}

QMainWindow, QDialog {{
    background: {BG};
}}

/* ---- Panels ----------------------------------------------------------- */
QWidget#panel {{
    background: {PANEL};
    border: none;
}}

QWidget#card {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QLabel#sectionHeader {{
    background: {PANEL};
    color: {HEADER_TEXT};
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.05em;
    padding: 10px 16px;
    border-bottom: 1px solid {BORDER};
}}

/* ---- Buttons ---------------------------------------------------------- */
QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: 600;
}}

QPushButton:hover {{
    border-color: {ACCENT};
}}

QPushButton#primary {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #0a1f1d;
}}

QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
}}

QPushButton#ghost {{
    background: transparent;
    border-color: {BORDER};
}}

QToolButton#iconBtn {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px;
    color: {TEXT_MUTED};
}}

QToolButton#iconBtn:hover {{
    background: {PANEL_ALT};
    color: {TEXT};
}}

QToolButton#iconBtn:checked {{
    color: {ACCENT};
    background: {PANEL_ALT};
}}

/* ---- Inputs ----------------------------------------------------------- */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
}}

QTextEdit, QPlainTextEdit {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {ACCENT};
    selection-color: #0a1f1d;
}}

QLineEdit:focus {{
    border-color: {ACCENT};
}}

QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ---- Tables (subtitle batch list) ------------------------------------- */
QTableWidget {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QTableWidget::item {{
    padding: 8px 10px;
    border-bottom: 1px solid {BORDER};
}}

QHeaderView::section {{
    background: {PANEL};
    color: {TEXT_MUTED};
    border: none;
    padding: 6px 10px;
}}

/* ---- Tabs ------------------------------------------------------------- */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 10px 16px;
    font-weight: 600;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}

/* ---- Dialog button box ------------------------------------------------ */
QDialogButtonBox QPushButton {{
    min-width: 90px;
}}

/* ---- Splitters -------------------------------------------------------- */
QSplitter::handle {{
    background: {BORDER};
}}

/* ---- Menu ------------------------------------------------------------- */
QMenu {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
    color: {TEXT};
}}

QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 4px;
    margin-bottom: 2px;
}}

QMenu::item:selected {{
    background-color: {PANENT_ALT if 'PANENT_ALT' in locals() else PANEL_ALT};
    color: {ACCENT};
}}

QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

/* ---- ScrollBars ------------------------------------------------------- */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 8px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""

def apply_theme(app) -> None:
    app.setStyleSheet(STYLESHEET)

__all__ = ["apply_theme", "BG", "PANEL", "ACCENT"]
