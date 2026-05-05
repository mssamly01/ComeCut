"""Horizontal navigation rail for the left panel area, following CapCut's layout style.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize  # type: ignore
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor  # type: ignore
from PySide6.QtSvg import QSvgRenderer  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QToolButton,
    QWidget,
)

TAB_MEDIA = "media"
TAB_TEXT = "text"

# Use fill="currentColor" to allow dynamic color replacement
_SVG_ICONS = {
    TAB_MEDIA: """<svg viewBox="0 0 50 50" xmlns="http://www.w3.org/2000/svg"><path d="M50 12.5V9.498A2 2 0 0 0 48.002 7.5H2.002A2 2 0 0 0 0 9.498V12.5h5v5H0v5h5v5H0v5h5v5H0v2.998A2 2 0 0 0 2.002 42.5h46a2 2 0 0 0 1.998 -2.002V37.5h-5v-5h5v-5h-5V22.5h5V17.5h-5V12.5zM20 32.5V17.5l12.5 7.5z" fill="currentColor"/></svg>""",
    TAB_TEXT: """<svg viewBox="0 -1 20 20" xmlns="http://www.w3.org/2000/svg"><g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M19 9V7h-8v2"/><path data-name="primary" d="M1 3V1h10v2m4 4v10m-2 0h4M6 1v16m-2 0h4"/></g></svg>""",
}

_LABELS = {
    TAB_MEDIA: "Media",
    TAB_TEXT: "Text",
}

# Colors matching the CSS
COLOR_NORMAL = "#8c93a0"
COLOR_HOVER = "#e6e8ec"
COLOR_ACTIVE = "#22d3c5"

class LeftRail(QFrame):
    tab_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("leftRail")
        self.setFixedHeight(48)
        self.setStyleSheet(
            f"QFrame#leftRail {{ background: #1a1d23; border-bottom: 1px solid #363b46; }}"
        )
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}

        for key in (TAB_MEDIA, TAB_TEXT):
            btn = self._make_btn(_SVG_ICONS[key], _LABELS[key])
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, k=key: self.tab_selected.emit(k))
            layout.addWidget(btn)
            self._group.addButton(btn)
            self._buttons[key] = btn

        self._buttons[TAB_MEDIA].setChecked(True)

    def _render_svg(self, svg_str: str, color_hex: str) -> QPixmap:
        # Replace currentColor with the target hex color
        colored_svg = svg_str.replace("currentColor", color_hex)
        renderer = QSvgRenderer(colored_svg.encode("utf-8"))
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    def _make_btn(self, svg_str: str, label: str) -> QToolButton:
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setText(label)
        btn.setFixedSize(54, 40)
        
        # Create a dynamic icon with different states
        icon = QIcon()
        
        # Normal state (Unchecked, Not Hovered)
        icon.addPixmap(self._render_svg(svg_str, COLOR_NORMAL), QIcon.Mode.Normal, QIcon.State.Off)
        # Hover state (Unchecked) - Note: QIcon doesn't have a specific "Hover" state, 
        # but Active Mode is often used for it in some widgets.
        icon.addPixmap(self._render_svg(svg_str, COLOR_HOVER), QIcon.Mode.Active, QIcon.State.Off)
        # Checked state (Active)
        icon.addPixmap(self._render_svg(svg_str, COLOR_ACTIVE), QIcon.Mode.Normal, QIcon.State.On)
        icon.addPixmap(self._render_svg(svg_str, COLOR_ACTIVE), QIcon.Mode.Active, QIcon.State.On)

        btn.setIcon(icon)
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btn.setStyleSheet(
            f"""
            QToolButton {{
                background: transparent;
                border: none;
                color: {COLOR_NORMAL};
                font-weight: bold;
                font-size: 10px;
                padding: 0;
            }}
            QToolButton:hover {{
                color: {COLOR_HOVER};
            }}
            QToolButton:checked {{
                color: {COLOR_ACTIVE};
            }}
            """
        )
        return btn

    def set_active(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)


__all__ = ["TAB_MEDIA", "TAB_TEXT", "LeftRail"]
