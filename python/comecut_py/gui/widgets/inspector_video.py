"""CapCut-style inspector controls for video clips."""

from __future__ import annotations

import math
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, Signal, QPointF  # type: ignore
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTransform, QColor, QPen  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QDial,
)

from ...core.effect_presets import (
    apply_effect_preset,
    list_effect_presets,
    save_effect_preset,
)
from ...core.project import Clip, ClipEffects

try:
    from PySide6.QtSvg import QSvgRenderer  # type: ignore
except Exception:  # pragma: no cover - optional dependency on some runtimes
    QSvgRenderer = None


DB_FLOOR = -60.0
_ICON_COLOR = "#a6acb8"
_SYMBOL_RE = re.compile(
    r'<symbol\s+id="(?P<id>[^"]+)"(?P<attrs>[^>]*)>(?P<body>.*?)</symbol>',
    re.DOTALL,
)
_PROPERTIES_SYMBOL_CACHE: dict[str, tuple[str, str]] | None = None


def linear_to_db(linear: float) -> float:
    if linear <= 1e-6:
        return DB_FLOOR
    return 20.0 * math.log10(linear)


def db_to_linear(db: float) -> float:
    if db <= DB_FLOOR:
        return 0.0
    return 10.0 ** (db / 20.0)


def scale_to_percent(scale: float | None) -> int:
    if scale is None:
        return 100
    return int(round(max(0.0, min(5.0, float(scale))) * 100.0))


def percent_to_scale(percent: int) -> float | None:
    if percent == 100:
        return None
    return max(0.01, min(5.0, percent / 100.0))


def percent_to_scale_value(percent: int) -> float:
    return max(0.01, min(5.0, percent / 100.0))


def _clamp_scale_value(scale: float | None, *, default: float = 1.0) -> float:
    if scale is None:
        scale = default
    return max(0.01, min(5.0, float(scale)))


def clip_visible_duration(clip) -> float:
    """Return the clip's visible duration on the timeline, in seconds.

    Mirrors ``Clip.timeline_duration`` ``(out_point - in_point) / speed``
    but always returns a finite float (``0.0`` when the clip is open-ended)
    so callers can safely format it for UI display.
    """
    if clip is None:
        return 0.0
    d = getattr(clip, "timeline_duration", None)
    if d is None:
        return 0.0
    try:
        return max(0.0, float(d))
    except (TypeError, ValueError):
        return 0.0


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        "color: #d0d5de; font-size: 12px; margin-top: 4px; margin-bottom: 2px;"
    )
    return label


def _make_reset_button(text: str = "Reset") -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(26)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        """
        QPushButton {
            background: #1c1f24;
            color: #a6acb8;
            border: 1px solid #2a2f38;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        }
        QPushButton:hover {
            color: #ffffff;
            border-color: #22d3c5;
        }
        QPushButton:disabled {
            color: #555b66;
            border-color: #252932;
        }
        """
    )
    return btn


def _sep() -> QFrame:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.HLine)
    frame.setFixedHeight(1)
    frame.setStyleSheet("background: #2b2f36; color: #2b2f36;")
    return frame


def _load_property_symbols() -> dict[str, tuple[str, str]]:
    global _PROPERTIES_SYMBOL_CACHE
    if _PROPERTIES_SYMBOL_CACHE is not None:
        return _PROPERTIES_SYMBOL_CACHE
    symbols: dict[str, tuple[str, str]] = {}
    icon_sheet = Path(__file__).resolve().parents[4] / "index.html"
    try:
        raw = icon_sheet.read_text(encoding="utf-8")
    except OSError:
        _PROPERTIES_SYMBOL_CACHE = symbols
        return symbols
    for match in _SYMBOL_RE.finditer(raw):
        symbol_id = match.group("id")
        if symbol_id.startswith("icon-editor-properties-"):
            symbols[symbol_id] = (match.group("attrs"), match.group("body"))
    _PROPERTIES_SYMBOL_CACHE = symbols
    return symbols


def _property_icon(symbol_id: str, color: str = _ICON_COLOR, size: int = 10) -> QIcon:
    if QSvgRenderer is None:
        return QIcon()
    symbol = _load_property_symbols().get(symbol_id)
    if symbol is None:
        return QIcon()
    attrs, body = symbol
    svg = f'<svg xmlns="http://www.w3.org/2000/svg"{attrs}>{body}</svg>'.replace(
        "currentColor", color
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def _rotate_icon(icon: QIcon, degrees: float, size: int = 10) -> QIcon:
    if icon.isNull():
        return QIcon()
    pix = icon.pixmap(size, size)
    rot = pix.transformed(QTransform().rotate(degrees), Qt.TransformationMode.SmoothTransformation)
    return QIcon(rot)


def _make_slider(minimum: int, maximum: int, value: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(minimum, maximum)
    slider.setValue(value)
    slider.setStyleSheet(
        """
        QSlider::groove:horizontal {
            height: 4px;
            background: #2b2f36;
            border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #22d3c5;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 10px;
            height: 16px;
            margin: -6px 0;
            border-radius: 3px;
            background: #22d3c5;
            border: none;
        }
        """
    )
    return slider


def _make_capcut_value_input(width: int = 64, minimum: float = 0, maximum: float = 100, suffix: str = "", decimals: int = 2) -> tuple[QWidget, QDoubleSpinBox]:
    container = QFrame()
    container.setFixedWidth(width)
    container.setFixedHeight(30)
    container.setStyleSheet("""
        QFrame {
            background: #1c1f24;
            border: 1px solid #2a2f38;
            border-top-left-radius: 4px;
            border-bottom-left-radius: 4px;
            border-right: none;
        }
    """)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addStretch(1)

    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    # Estimate width based on decimals - even tighter for seamless look
    spin_width = 35 if decimals == 1 else 42
    spin.setFixedWidth(spin_width)
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    spin.setStyleSheet("background: transparent; color: #ffffff; border: none; font-size: 12px; font-weight: 500; padding: 0px;")
    layout.addWidget(spin)

    if suffix:
        suffix_lbl = QLabel(suffix)
        suffix_lbl.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 500; border: none; background: transparent; padding: 0px;")
        layout.addWidget(suffix_lbl)

    layout.addStretch(1)
    return container, spin


def _make_spin(minimum: int = -100000, maximum: int = 100000) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedHeight(28)
    spin.setStyleSheet(
        "QSpinBox { background: #1c1f24; color: #e6e8ec; border: 1px solid #3f444d;"
        " border-radius: 4px; padding: 2px 6px; }"
    )
    return spin


def _make_capcut_axis_input(axis: str, minimum: int = -100000, maximum: int = 100000) -> tuple[QWidget, QSpinBox, QToolButton, QToolButton]:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # Input part
    input_box = QFrame()
    input_box.setFixedHeight(30)
    input_box.setFixedWidth(70)
    input_box.setStyleSheet("""
        QFrame {
            background: #1c1f24;
            border: 1px solid #2a2f38;
            border-top-left-radius: 4px;
            border-bottom-left-radius: 4px;
            border-right: none;
        }
    """)
    box_layout = QHBoxLayout(input_box)
    box_layout.setContentsMargins(8, 0, 4, 0)
    box_layout.setSpacing(2)

    axis_lbl = QLabel(axis)
    axis_lbl.setStyleSheet("color: #22d3c5; font-weight: bold; font-size: 11px; border: none; background: transparent;") 
    box_layout.addWidget(axis_lbl)

    spin = QSpinBox()
    spin.setRange(-100000, 100000)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setStyleSheet("background: transparent; color: #ffffff; border: none; font-size: 12px; font-weight: 500;")
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    box_layout.addWidget(spin, 1)

    layout.addWidget(input_box)

    # Stepper part
    stepper_container, up_btn, down_btn = _make_icon_stepper(f"{axis}Pos", attached=True)
    stepper_container.setFixedSize(18, 30)
    layout.addWidget(stepper_container)

    return container, spin, up_btn, down_btn


class _RotateDial(QDial):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setRange(-180, 180)
        self.setWrapping(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        center = QPointF(rect.center())
        radius = rect.width() / 2.0
        
        # Background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111318"))  
        painter.drawEllipse(rect)
        
        # Border
        painter.setPen(QPen(QColor("#2a2f38"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
        
        val = self.value()
        # Capcut 0 degree is pointing right (3 o'clock)
        angle = math.radians(val)
        
        line_radius = radius - 4.0
        end_x = center.x() + line_radius * math.cos(angle)
        end_y = center.y() + line_radius * math.sin(angle)
        
        # Draw line from center
        pen = QPen(QColor("#e6e8ec"), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(center, QPointF(end_x, end_y))
        
        # Draw cyan dot at the end
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#22d3c5"))
        painter.drawEllipse(QPointF(end_x, end_y), 1.5, 1.5)


def _make_capcut_rotate_input() -> tuple[QWidget, QDoubleSpinBox, QToolButton, QToolButton, _RotateDial]:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    # Input part (SpinBox + Stepper)
    input_group = QWidget()
    input_layout = QHBoxLayout(input_group)
    input_layout.setContentsMargins(0, 0, 0, 0)
    input_layout.setSpacing(0)

    # Inner frame to hold spin + non-selectable degree label
    inner_frame = QFrame()
    inner_frame.setFixedHeight(30)
    inner_frame.setFixedWidth(80)
    inner_frame.setStyleSheet("""
        QFrame {
            background: #1c1f24;
            border: 1px solid #2a2f38;
            border-top-left-radius: 4px;
            border-bottom-left-radius: 4px;
            border-right: none;
        }
    """)
    inner_layout = QHBoxLayout(inner_frame)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    inner_layout.setSpacing(0)

    inner_layout.addStretch(1)

    spin = QDoubleSpinBox()
    spin.setRange(-360.0, 360.0)
    spin.setDecimals(2)
    spin.setSuffix("") 
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedWidth(40) # Even tighter
    spin.setStyleSheet("background: transparent; color: #ffffff; border: none; font-size: 12px; font-weight: 500; padding: 0px;")
    spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    inner_layout.addWidget(spin)

    deg_lbl = QLabel("°")
    deg_lbl.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 500; border: none; background: transparent; padding: 0px; padding-bottom: 2px;") 
    inner_layout.addWidget(deg_lbl)


    inner_layout.addStretch(1)
    
    input_layout.addWidget(inner_frame)

    stepper_container, up_btn, down_btn = _make_icon_stepper("RotatePos", attached=True)
    stepper_container.setFixedSize(18, 30)
    input_layout.addWidget(stepper_container)
    
    layout.addWidget(input_group)

    # Dial part
    dial = _RotateDial()
    layout.addWidget(dial)

    return container, spin, up_btn, down_btn, dial


def _make_percent_input(width: int = 70, value: int = 100) -> tuple[QWidget, QDoubleSpinBox]:
    # Use generic value input with 0 decimals for integer percentage
    container, spin = _make_capcut_value_input(width, 0, 500, "%", 0)
    spin.setValue(value)
    return container, spin


def _make_icon_stepper(prefix: str, *, attached: bool) -> tuple[QWidget, QToolButton, QToolButton]:
    base_icon = _property_icon("icon-editor-properties-collaps2", size=9)
    up_icon = base_icon
    down_icon = _rotate_icon(base_icon, 180.0, size=9)

    stepper = QWidget()
    stepper.setFixedSize(18, 28)
    layout = QVBoxLayout(stepper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    top_rule = (
        f"QToolButton#{prefix}Up {{ border-top-right-radius: 4px; border-bottom-width: 0px; }}"
        if attached
        else f"QToolButton#{prefix}Up {{ border-top-left-radius: 4px; border-top-right-radius: 4px; border-bottom-width: 0px; }}"
    )
    bottom_rule = (
        f"QToolButton#{prefix}Down {{ border-bottom-right-radius: 4px; }}"
        if attached
        else f"QToolButton#{prefix}Down {{ border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; }}"
    )
    border_left_rule = "border-left-width: 0px;" if attached else ""

    def make_button(name: str, icon: QIcon, fallback: str) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName(name)
        btn.setFixedSize(18, 14)
        btn.setAutoRepeat(True)
        btn.setIcon(icon)
        btn.setIconSize(QSize(8, 8))
        if icon.isNull():
            btn.setText(fallback)
        btn.setStyleSheet(
            """
            QToolButton {
                background: #2b2f36;
                color: #d0d5de;
                border: 1px solid #3f444d;
                %s
                padding: 0px;
            }
            QToolButton:hover {
                background: #34394a;
                color: #ffffff;
            }
            %s
            %s
            """
            % (border_left_rule, top_rule, bottom_rule)
        )
        return btn

    up_btn = make_button(f"{prefix}Up", up_icon, "^")
    down_btn = make_button(f"{prefix}Down", down_icon, "v")
    layout.addWidget(up_btn)
    layout.addWidget(down_btn)
    return stepper, up_btn, down_btn


def _make_percent_stepper() -> tuple[QWidget, QToolButton, QToolButton]:
    return _make_icon_stepper("ScalePercent", attached=True)


def _make_dspin(minimum: float = 0.0, maximum: float = 100000.0, *, step: float = 0.1) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(3)
    spin.setSingleStep(step)
    spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedHeight(28)
    spin.setStyleSheet(
        "QDoubleSpinBox { background: #1c1f24; color: #e6e8ec; border: 1px solid #3f444d;"
        " border-radius: 4px; padding: 2px 6px; }"
    )
    return spin


class _CapCutSwitch(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(36, 20) # Larger size as requested
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect().adjusted(1, 1, -1, -1)
        checked = self.isChecked()
        
        # Draw track
        painter.setPen(Qt.PenStyle.NoPen)
        track_color = QColor("#22d3c5") if checked else QColor("#3f444d")
        painter.setBrush(track_color)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        
        # Draw thumb
        thumb_diameter = rect.height() - 6 # Slightly larger gap for cleaner look
        thumb_color = QColor("white") if checked else QColor("#a6acb8")
        painter.setBrush(thumb_color)
        
        # Calculate vertical center
        y = rect.top() + (rect.height() - thumb_diameter) / 2
        
        if checked:
            # Thumb on the right
            x = rect.right() - thumb_diameter - 3
        else:
            # Thumb on the left
            x = rect.left() + 3
            
        painter.drawEllipse(x, y, thumb_diameter, thumb_diameter)

def _make_toggle() -> _CapCutSwitch:
    return _CapCutSwitch()


class VideoPropertiesBox(QWidget):
    clip_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._clip: Clip | None = None
        self._track_kind: str | None = None
        self._binding = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._btn_basic = QPushButton("Basic")
        self._btn_voice = QPushButton("Voice changer")
        for index, btn in enumerate((self._btn_basic, self._btn_voice)):
            btn.setCheckable(True)
            btn.setProperty("seg_left", index == 0)
            btn.setProperty("seg_right", index == 1)
            btn.setStyleSheet(
                """
                QPushButton {
                    background: #101215;
                    color: #8c93a0;
                    border: 1px solid #2f3440;
                    border-left-width: 0px;
                    border-radius: 0px;
                    padding: 8px 14px;
                    font-weight: 600;
                }
                QPushButton[seg_left="true"] {
                    border-left-width: 1px;
                    border-top-left-radius: 4px;
                    border-bottom-left-radius: 4px;
                }
                QPushButton[seg_right="true"] {
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QPushButton:checked {
                    background: #0f6f84;
                    color: #ffffff;
                    border-color: #0aa0bf;
                }
                """
            )
            self._tab_group.addButton(btn, index)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)
        tab_row.addWidget(self._btn_basic, 1)
        tab_row.addWidget(self._btn_voice, 1)
        outer.addLayout(tab_row)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._build_basic_page()
        self._build_voice_page()

        self._btn_basic.toggled.connect(
            lambda checked: checked and self._stack.setCurrentWidget(self._basic_page)
        )
        self._btn_voice.toggled.connect(
            lambda checked: checked and self._stack.setCurrentWidget(self._voice_page)
        )
        self._btn_basic.setChecked(True)

        self.set_clip(None)

    def _build_basic_page(self) -> None:
        self._basic_page = QWidget()
        outer = QVBoxLayout(self._basic_page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)
        self._stack.addWidget(self._basic_page)



        self._scale_row = QWidget()
        scale_vbox = QVBoxLayout(self._scale_row)
        scale_vbox.setContentsMargins(0, 0, 0, 0)
        scale_vbox.setSpacing(8)

        scale_header = QHBoxLayout()
        scale_lbl = QLabel("Tỷ lệ")
        scale_lbl.setFixedWidth(80)
        scale_header.addWidget(scale_lbl)
        scale_header.addStretch(1)
        
        scale_value = QWidget()
        scale_value_layout = QHBoxLayout(scale_value)
        scale_value_layout.setContentsMargins(0, 0, 0, 0)
        scale_value_layout.setSpacing(0)
        self._scale_container, self._scale_spin = _make_percent_input(75, 100)
        # Tests and external callers refer to the boxed value-input as the
        # "scale chip" (CapCut UI term). Keep an alias so both names work.
        self._scale_chip = self._scale_spin
        self._scale_stepper, self._scale_inc, self._scale_dec = _make_percent_stepper()
        scale_value_layout.addWidget(self._scale_container)
        scale_value_layout.addWidget(self._scale_stepper)
        scale_header.addWidget(scale_value)
        scale_vbox.addLayout(scale_header)

        self._scale_slider = _make_slider(0, 500, 100)
        scale_vbox.addWidget(self._scale_slider)
        outer.addWidget(self._scale_row)

        # Ngang (Scale X)
        self._scale_x_row = QWidget()
        scale_x_vbox = QVBoxLayout(self._scale_x_row)
        scale_x_vbox.setContentsMargins(0, 0, 0, 0)
        scale_x_vbox.setSpacing(8)
        scale_x_header = QHBoxLayout()
        scale_x_lbl = QLabel("Ngang")
        scale_x_lbl.setFixedWidth(80)
        scale_x_header.addWidget(scale_x_lbl)
        scale_x_header.addStretch(1)
        scale_x_value = QWidget()
        scale_x_value_layout = QHBoxLayout(scale_x_value)
        scale_x_value_layout.setContentsMargins(0, 0, 0, 0)
        scale_x_value_layout.setSpacing(0)
        self._scale_x_container, self._scale_x_spin = _make_percent_input(75, 100)
        self._scale_x_stepper, self._scale_x_inc, self._scale_x_dec = _make_percent_stepper()
        scale_x_value_layout.addWidget(self._scale_x_container)
        scale_x_value_layout.addWidget(self._scale_x_stepper)
        scale_x_header.addWidget(scale_x_value)
        scale_x_vbox.addLayout(scale_x_header)
        self._scale_x_slider = _make_slider(0, 500, 100)
        scale_x_vbox.addWidget(self._scale_x_slider)
        outer.addWidget(self._scale_x_row)

        # Dọc (Scale Y)
        self._scale_y_row = QWidget()
        scale_y_vbox = QVBoxLayout(self._scale_y_row)
        scale_y_vbox.setContentsMargins(0, 0, 0, 0)
        scale_y_vbox.setSpacing(8)
        scale_y_header = QHBoxLayout()
        scale_y_lbl = QLabel("Dọc")
        scale_y_lbl.setFixedWidth(80)
        scale_y_header.addWidget(scale_y_lbl)
        scale_y_header.addStretch(1)
        scale_y_value = QWidget()
        scale_y_value_layout = QHBoxLayout(scale_y_value)
        scale_y_value_layout.setContentsMargins(0, 0, 0, 0)
        scale_y_value_layout.setSpacing(0)
        self._scale_y_container, self._scale_y_spin = _make_percent_input(75, 100)
        self._scale_y_stepper, self._scale_y_inc, self._scale_y_dec = _make_percent_stepper()
        scale_y_value_layout.addWidget(self._scale_y_container)
        scale_y_value_layout.addWidget(self._scale_y_stepper)
        scale_y_header.addWidget(scale_y_value)
        scale_y_vbox.addLayout(scale_y_header)
        self._scale_y_slider = _make_slider(0, 500, 100)
        scale_y_vbox.addWidget(self._scale_y_slider)
        outer.addWidget(self._scale_y_row)

        uniform_row = QHBoxLayout()
        uniform_row.addWidget(QLabel("Thu phóng đồng nhất"))
        uniform_row.addStretch(1)
        self._uniform_cb = _make_toggle()
        self._uniform_cb.setChecked(True)
        uniform_row.addWidget(self._uniform_cb)
        outer.addLayout(uniform_row)

        # Gap after Scale cluster
        outer.addSpacing(20)

        xy_row = QHBoxLayout()
        xy_row.setSpacing(12)
        pos_lbl = QLabel("Vị trí")
        pos_lbl.setFixedWidth(80)
        xy_row.addWidget(pos_lbl)
        
        self._x_container, self._x_spin, self._x_inc, self._x_dec = _make_capcut_axis_input("X")
        xy_row.addWidget(self._x_container)
        
        self._y_container, self._y_spin, self._y_inc, self._y_dec = _make_capcut_axis_input("Y")
        xy_row.addWidget(self._y_container)
        
        xy_row.addStretch(1)
        outer.addLayout(xy_row)

        # Gap after Position
        outer.addSpacing(20)

        rotate_row = QHBoxLayout()
        rotate_row.setSpacing(12)
        
        rotate_lbl = QLabel("Xoay")
        rotate_lbl.setFixedWidth(80)
        rotate_row.addWidget(rotate_lbl)
        # rotate_row.addStretch(1) # Removed stretch to bring it closer as requested
        
        self._rotate_container, self._rotate_spin, self._rotate_inc, self._rotate_dec, self._rotate_dial = _make_capcut_rotate_input()
        rotate_row.addWidget(self._rotate_container)
        rotate_row.addStretch(1)
        
        outer.addLayout(rotate_row)

        reset_transform_row = QHBoxLayout()
        reset_transform_row.setContentsMargins(0, 0, 0, 0)
        reset_transform_row.addStretch(1)
        self._reset_transform_btn = _make_reset_button("Reset transform")
        reset_transform_row.addWidget(self._reset_transform_btn)
        outer.addLayout(reset_transform_row)

        # Gap after Rotate to Effects
        outer.addSpacing(20)

        effect_header = QHBoxLayout()
        effect_header.setContentsMargins(0, 0, 0, 0)
        effect_header.addWidget(_section_label("Effects"))
        effect_header.addStretch(1)
        self._reset_effects_btn = _make_reset_button("Reset filters")
        effect_header.addWidget(self._reset_effects_btn)
        outer.addLayout(effect_header)

        effect_preset_row = QHBoxLayout()
        effect_preset_row.setContentsMargins(0, 0, 0, 0)
        effect_preset_row.setSpacing(6)
        self._effect_preset_combo = QComboBox()
        self._effect_preset_combo.setMinimumContentsLength(12)
        self._btn_apply_effect_preset = QPushButton("Apply")
        self._btn_save_effect_preset = QPushButton("Save")
        effect_preset_row.addWidget(self._effect_preset_combo, 1)
        effect_preset_row.addWidget(self._btn_apply_effect_preset)
        effect_preset_row.addWidget(self._btn_save_effect_preset)
        outer.addLayout(effect_preset_row)

        effect_knobs = QWidget()
        effect_knob_layout = QVBoxLayout(effect_knobs)
        effect_knob_layout.setContentsMargins(0, 0, 0, 0)
        effect_knob_layout.setSpacing(6)

        def add_effect_spin(label: str, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(QLabel(label))
            spin = _make_dspin(minimum, maximum, step=step)
            spin.setDecimals(2)
            row.addWidget(spin, 1)
            effect_knob_layout.addLayout(row)
            return spin

        self._effect_brightness_spin = add_effect_spin("Brightness", -1.0, 1.0, 0.05)
        self._effect_contrast_spin = add_effect_spin("Contrast", 0.0, 4.0, 0.05)
        self._effect_saturation_spin = add_effect_spin("Saturation", 0.0, 3.0, 0.05)
        self._effect_blur_spin = add_effect_spin("Blur", 0.0, 20.0, 0.5)

        effect_toggle_row = QHBoxLayout()
        effect_toggle_row.setContentsMargins(0, 0, 0, 0)
        effect_toggle_row.setSpacing(10)
        self._effect_grayscale_cb = QCheckBox("Grayscale")
        self._effect_hflip_cb = QCheckBox("Flip H")
        self._effect_vflip_cb = QCheckBox("Flip V")
        effect_toggle_row.addWidget(self._effect_grayscale_cb)
        effect_toggle_row.addWidget(self._effect_hflip_cb)
        effect_toggle_row.addWidget(self._effect_vflip_cb)
        effect_toggle_row.addStretch(1)
        effect_knob_layout.addLayout(effect_toggle_row)
        outer.addWidget(effect_knobs)

        # Gap after Rotate to Speed
        outer.addSpacing(20)
        self._speed_row_container = QWidget()
        speed_vbox = QVBoxLayout(self._speed_row_container)
        speed_vbox.setContentsMargins(0, 0, 0, 0)
        speed_vbox.setSpacing(8)

        speed_header = QHBoxLayout()
        speed_lbl = QLabel("Tốc độ")
        speed_lbl.setFixedWidth(80)
        speed_header.addWidget(speed_lbl)
        speed_header.addStretch(1)
        self._reset_speed_btn = _make_reset_button("Reset")
        speed_header.addWidget(self._reset_speed_btn)

        speed_value = QWidget()
        speed_value_layout = QHBoxLayout(speed_value)
        speed_value_layout.setContentsMargins(0, 0, 0, 0)
        speed_value_layout.setSpacing(0)
        self._speed_container, self._speed_spin = _make_capcut_value_input(75, 0.1, 10.0, "x", 2)
        # Speed steps by 0.1x per click on the inc/dec stepper.
        self._speed_spin.setSingleStep(0.1)
        self._speed_stepper, self._speed_inc, self._speed_dec = _make_icon_stepper(
            "Speed", attached=True
        )
        speed_value_layout.addWidget(self._speed_container)
        speed_value_layout.addWidget(self._speed_stepper)
        speed_header.addWidget(speed_value)
        speed_vbox.addLayout(speed_header)

        self._speed_slider = _make_slider(10, 1000, 100)
        speed_vbox.addWidget(self._speed_slider)
        outer.addWidget(self._speed_row_container)

        # Gap after Speed
        outer.addSpacing(20)

        # Âm lượng row
        self._vol_row_container = QWidget()
        vol_vbox = QVBoxLayout(self._vol_row_container)
        vol_vbox.setContentsMargins(0, 0, 0, 0)
        vol_vbox.setSpacing(8)

        vol_header = QHBoxLayout()
        vol_lbl = QLabel("Âm lượng")
        vol_lbl.setFixedWidth(80)
        vol_header.addWidget(vol_lbl)
        vol_header.addStretch(1)
        self._reset_volume_btn = _make_reset_button("Reset")
        vol_header.addWidget(self._reset_volume_btn)

        vol_value = QWidget()
        vol_value_layout = QHBoxLayout(vol_value)
        vol_value_layout.setContentsMargins(0, 0, 0, 0)
        vol_value_layout.setSpacing(0)
        self._volume_container, self._volume_spin = _make_capcut_value_input(80, DB_FLOOR, 20, "dB", 1)
        self._volume_stepper, self._volume_inc, self._volume_dec = _make_icon_stepper("Volume", attached=True)
        vol_value_layout.addWidget(self._volume_container)
        vol_value_layout.addWidget(self._volume_stepper)
        vol_header.addWidget(vol_value)
        vol_vbox.addLayout(vol_header)

        self._volume_slider = _make_slider(int(DB_FLOOR), 20, 0)
        vol_vbox.addWidget(self._volume_slider)
        outer.addWidget(self._vol_row_container)

        outer.addStretch(1)
        
        self._scale_slider.valueChanged.connect(self._on_scale_changed)
        self._scale_spin.valueChanged.connect(self._on_scale_spin_changed)
        self._scale_inc.clicked.connect(self._scale_spin.stepUp)
        self._scale_dec.clicked.connect(self._scale_spin.stepDown)
        self._uniform_cb.toggled.connect(self._on_uniform_toggled)
        self._scale_x_slider.valueChanged.connect(self._on_scale_x_changed)
        self._scale_x_spin.valueChanged.connect(self._on_scale_x_spin_changed)
        self._scale_x_inc.clicked.connect(self._scale_x_spin.stepUp)
        self._scale_x_dec.clicked.connect(self._scale_x_spin.stepDown)
        self._scale_y_slider.valueChanged.connect(self._on_scale_y_changed)
        self._scale_y_spin.valueChanged.connect(self._on_scale_y_spin_changed)
        self._scale_y_inc.clicked.connect(self._scale_y_spin.stepUp)
        self._scale_y_dec.clicked.connect(self._scale_y_spin.stepDown)
        self._x_spin.valueChanged.connect(self._on_x_changed)
        self._x_inc.clicked.connect(self._x_spin.stepUp)
        self._x_dec.clicked.connect(self._x_spin.stepDown)
        self._y_spin.valueChanged.connect(self._on_y_changed)
        self._y_inc.clicked.connect(self._y_spin.stepUp)
        self._y_dec.clicked.connect(self._y_spin.stepDown)
        self._rotate_dial.valueChanged.connect(self._on_rotate_dial_changed)
        self._rotate_spin.valueChanged.connect(self._on_rotate_spin_changed)
        self._rotate_inc.clicked.connect(self._rotate_spin.stepUp)
        self._rotate_dec.clicked.connect(self._rotate_spin.stepDown)
        self._reset_transform_btn.clicked.connect(self._reset_transform_group)
        self._effect_preset_combo.currentIndexChanged.connect(
            self._update_effect_preset_button_state
        )
        self._btn_apply_effect_preset.clicked.connect(self._apply_selected_effect_preset)
        self._btn_save_effect_preset.clicked.connect(self._save_current_effect_preset)
        self._reset_effects_btn.clicked.connect(self._reset_effects_group)
        self._effect_brightness_spin.valueChanged.connect(self._on_effect_brightness_changed)
        self._effect_contrast_spin.valueChanged.connect(self._on_effect_contrast_changed)
        self._effect_saturation_spin.valueChanged.connect(self._on_effect_saturation_changed)
        self._effect_blur_spin.valueChanged.connect(self._on_effect_blur_changed)
        self._effect_grayscale_cb.toggled.connect(self._on_effect_grayscale_toggled)
        self._effect_hflip_cb.toggled.connect(self._on_effect_hflip_toggled)
        self._effect_vflip_cb.toggled.connect(self._on_effect_vflip_toggled)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        self._speed_spin.valueChanged.connect(self._on_speed_spin_changed)
        self._speed_dec.clicked.connect(self._speed_spin.stepDown)
        self._speed_inc.clicked.connect(self._speed_spin.stepUp)
        self._reset_speed_btn.clicked.connect(self._reset_speed_group)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        self._volume_spin.valueChanged.connect(self._on_volume_spin_changed)
        self._volume_dec.clicked.connect(self._volume_spin.stepDown)
        self._volume_inc.clicked.connect(self._volume_spin.stepUp)
        self._reset_volume_btn.clicked.connect(self._reset_volume_group)
        self._sync_uniform_scale_ui()
        self._refresh_effect_preset_combo()

    def _build_voice_page(self) -> None:
        from .voice_preset_grid import VoicePresetGrid

        self._voice_page = QWidget()
        layout = QVBoxLayout(self._voice_page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)
        self._stack.addWidget(self._voice_page)

        layout.addWidget(_section_label("Voice changer"))
        self._voice_grid = VoicePresetGrid()
        self._voice_grid.preset_clicked.connect(self._on_voice_preset_clicked)
        layout.addWidget(self._voice_grid)

        layout.addWidget(_section_label("Tinh chỉnh thủ công"))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Pitch"))
        self._pitch_spin = _make_dspin(-24.0, 24.0, step=0.5)
        self._pitch_spin.setDecimals(1)
        row.addWidget(self._pitch_spin, 1)
        layout.addLayout(row)
        layout.addStretch(1)

        self._pitch_spin.valueChanged.connect(self._on_pitch_changed)

    def _on_voice_preset_clicked(self, preset_id: str) -> None:
        if self._binding or self._clip is None:
            return
        from ...core.voice_presets import apply_preset
        apply_preset(self._clip.audio_effects, preset_id)
        # Sync pitch spinner display so user sees the resulting value
        self._binding = True
        try:
            self._pitch_spin.setValue(self._clip.audio_effects.pitch_semitones)
        finally:
            self._binding = False
        self._emit()

    def current_clip(self) -> Clip | None:
        return self._clip

    def _sync_uniform_scale_ui(self) -> None:
        uniform = bool(self._uniform_cb.isChecked())
        self._scale_row.setVisible(uniform)
        self._scale_x_row.setVisible(not uniform)
        self._scale_y_row.setVisible(not uniform)

    @staticmethod
    def _clip_scale_axes(clip: Clip) -> tuple[float, float]:
        base = _clamp_scale_value(clip.scale, default=1.0)
        sx = clip.scale_x
        sy = clip.scale_y
        if sx is None and sy is None:
            return base, base
        if sx is None:
            sx = sy if sy is not None else base
        if sy is None:
            sy = sx if sx is not None else base
        return _clamp_scale_value(sx), _clamp_scale_value(sy)

    def _apply_uniform_scale(self, percent: int) -> None:
        if self._clip is None:
            return
        self._clip.scale = percent_to_scale(int(percent))
        self._clip.scale_x = None
        self._clip.scale_y = None

    def _apply_non_uniform_scale(self, x_percent: int, y_percent: int) -> None:
        if self._clip is None:
            return
        self._clip.scale = None
        self._clip.scale_x = percent_to_scale_value(int(x_percent))
        self._clip.scale_y = percent_to_scale_value(int(y_percent))

    def set_clip(self, clip: Clip | None, *, track_kind: str | None = None) -> None:
        self._binding = True
        try:
            self._clip = clip
            self._track_kind = track_kind
            enabled = clip is not None

            controls = (
                self._scale_slider,
                self._scale_container,
                self._scale_inc,
                self._scale_dec,
                self._uniform_cb,
                self._scale_x_slider,
                self._scale_x_container,
                self._scale_x_inc,
                self._scale_x_dec,
                self._scale_y_slider,
                self._scale_y_container,
                self._scale_y_inc,
                self._scale_y_dec,
                self._x_spin,
                self._x_inc,
                self._x_dec,
                self._y_spin,
                self._y_inc,
                self._y_dec,
                self._rotate_dial,
                self._rotate_spin,
                self._rotate_inc,
                self._rotate_dec,
                self._reset_transform_btn,
                self._effect_preset_combo,
                self._btn_apply_effect_preset,
                self._btn_save_effect_preset,
                self._reset_effects_btn,
                self._effect_brightness_spin,
                self._effect_contrast_spin,
                self._effect_saturation_spin,
                self._effect_blur_spin,
                self._effect_grayscale_cb,
                self._effect_hflip_cb,
                self._effect_vflip_cb,
                self._speed_slider,
                self._speed_container,
                self._speed_inc,
                self._speed_dec,
                self._reset_speed_btn,
                self._volume_slider,
                self._volume_container,
                self._volume_inc,
                self._volume_dec,
                self._reset_volume_btn,
                self._pitch_spin,
            )
            for widget in controls:
                widget.setEnabled(enabled)

            if clip is None:
                self._scale_slider.setValue(100)
                self._scale_spin.setValue(100)
                self._scale_x_slider.setValue(100)
                self._scale_x_spin.setValue(100)
                self._scale_y_slider.setValue(100)
                self._scale_y_spin.setValue(100)
                self._uniform_cb.setChecked(True)
                self._sync_uniform_scale_ui()
                self._x_spin.setValue(0)
                self._y_spin.setValue(0)
                self._speed_slider.setValue(100)
                self._speed_spin.setValue(1.0)
                self._volume_slider.setValue(0)
                self._volume_spin.setValue(0.0)
                self._rotate_spin.setValue(0.0)
                self._rotate_dial.setValue(0)
                self._effect_brightness_spin.setValue(0.0)
                self._effect_contrast_spin.setValue(1.0)
                self._effect_saturation_spin.setValue(1.0)
                self._effect_blur_spin.setValue(0.0)
                self._effect_grayscale_cb.setChecked(False)
                self._effect_hflip_cb.setChecked(False)
                self._effect_vflip_cb.setChecked(False)
                self._pitch_spin.setValue(0.0)
                if hasattr(self, "_voice_grid"):
                    self._voice_grid.set_active("none")
                self._update_effect_preset_button_state()
                return

            uniform = clip.scale_x is None and clip.scale_y is None
            percent = scale_to_percent(clip.scale)
            sx, sy = self._clip_scale_axes(clip)
            self._uniform_cb.setChecked(uniform)
            self._sync_uniform_scale_ui()
            self._scale_slider.setValue(percent)
            self._scale_spin.setValue(percent)
            self._scale_x_slider.setValue(scale_to_percent(sx))
            self._scale_x_spin.setValue(scale_to_percent(sx))
            self._scale_y_slider.setValue(scale_to_percent(sy))
            self._scale_y_spin.setValue(scale_to_percent(sy))
            self._x_spin.setValue(int(clip.pos_x if clip.pos_x is not None else 0))
            self._y_spin.setValue(int(clip.pos_y if clip.pos_y is not None else 0))

            rot = float(clip.effects.rotate or 0.0)
            self._rotate_spin.setValue(rot)
            # Sync dial, adjusting for -180 to 180 wrap
            dial_val = int(round(rot)) % 360
            if dial_val > 180:
                dial_val -= 360
            elif dial_val < -180:
                dial_val += 360
            self._rotate_dial.setValue(dial_val)

            self._effect_brightness_spin.setValue(float(clip.effects.brightness))
            self._effect_contrast_spin.setValue(float(clip.effects.contrast))
            self._effect_saturation_spin.setValue(float(clip.effects.saturation))
            self._effect_blur_spin.setValue(float(clip.effects.blur))
            self._effect_grayscale_cb.setChecked(bool(clip.effects.grayscale))
            self._effect_hflip_cb.setChecked(bool(clip.effects.hflip))
            self._effect_vflip_cb.setChecked(bool(clip.effects.vflip))

            speed_val = float(clip.speed or 1.0)
            self._speed_slider.setValue(int(round(speed_val * 100.0)))
            self._speed_spin.setValue(speed_val)

            db = max(DB_FLOOR, min(20.0, linear_to_db(float(clip.volume or 0.0))))
            self._volume_slider.setValue(int(round(db)))
            self._volume_spin.setValue(db)

            self._pitch_spin.setValue(
                float(getattr(clip.audio_effects, "pitch_semitones", 0.0) or 0.0)
            )
            if hasattr(self, "_voice_grid"):
                from ...core.voice_presets import detect_preset_id
                self._voice_grid.set_active(detect_preset_id(self._clip.audio_effects))
        finally:
            self._binding = False
        self._update_effect_preset_button_state()

    def _emit(self) -> None:
        if self._binding:
            return
        self.clip_changed.emit("")

    def _refresh_effect_preset_combo(self, select_name: str | None = None) -> None:
        if not hasattr(self, "_effect_preset_combo"):
            return
        current = select_name or str(self._effect_preset_combo.currentData() or "")
        self._effect_preset_combo.blockSignals(True)
        self._effect_preset_combo.clear()
        presets = list_effect_presets()
        if not presets:
            self._effect_preset_combo.addItem("No presets yet", None)
        else:
            for preset in presets:
                self._effect_preset_combo.addItem(preset.name, preset.name)
        if current:
            index = self._effect_preset_combo.findData(current)
            if index >= 0:
                self._effect_preset_combo.setCurrentIndex(index)
        self._effect_preset_combo.blockSignals(False)
        self._update_effect_preset_button_state()

    def _update_effect_preset_button_state(self, *_args) -> None:
        if not hasattr(self, "_btn_apply_effect_preset"):
            return
        has_clip = self._clip is not None
        has_preset = bool(self._effect_preset_combo.currentData())
        self._effect_preset_combo.setEnabled(has_clip)
        self._btn_save_effect_preset.setEnabled(has_clip)
        self._btn_apply_effect_preset.setEnabled(has_clip and has_preset)

    def _save_current_effect_preset(self) -> None:
        if self._binding or self._clip is None:
            return
        default_name = Path(self._clip.source or "Effect").stem.strip() or "Effect"
        name, accepted = QInputDialog.getText(
            self,
            "Save effect preset",
            "Preset name:",
            text=f"{default_name} Effects",
        )
        name = name.strip()
        if not accepted or not name:
            return
        try:
            save_effect_preset(name, self._clip)
        except Exception as exc:  # pragma: no cover - defensive UI path
            QMessageBox.warning(self, "Save preset failed", str(exc))
            return
        self._refresh_effect_preset_combo(select_name=name)

    def _apply_selected_effect_preset(self) -> None:
        if self._binding or self._clip is None:
            return
        name = str(self._effect_preset_combo.currentData() or "")
        if not name:
            return
        try:
            apply_effect_preset(self._clip, name)
        except Exception as exc:  # pragma: no cover - defensive UI path
            QMessageBox.warning(self, "Apply preset failed", str(exc))
            return
        self.set_clip(self._clip, track_kind=self._track_kind)
        self._emit()

    def _reset_transform_group(self) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.scale = None
        self._clip.scale_x = None
        self._clip.scale_y = None
        self._clip.pos_x = None
        self._clip.pos_y = None
        self._clip.effects.rotate = 0.0
        self.set_clip(self._clip, track_kind=self._track_kind)
        self._emit()

    def _reset_effects_group(self) -> None:
        if self._binding or self._clip is None:
            return
        rotate = self._clip.effects.rotate
        self._clip.effects = ClipEffects(rotate=rotate)
        self.set_clip(self._clip, track_kind=self._track_kind)
        self._emit()

    def _reset_speed_group(self) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.speed = 1.0
        self.set_clip(self._clip, track_kind=self._track_kind)
        self.clip_changed.emit("video_speed")

    def _reset_volume_group(self) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.volume = 1.0
        self.set_clip(self._clip, track_kind=self._track_kind)
        self._emit()

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        super().mousePressEvent(event)

    def _on_scale_changed(self, value: int) -> None:
        self._scale_spin.blockSignals(True)
        self._scale_spin.setValue(float(value))
        self._scale_spin.blockSignals(False)
        if self._uniform_cb.isChecked():
            self._scale_x_slider.blockSignals(True)
            self._scale_x_slider.setValue(value)
            self._scale_x_slider.blockSignals(False)
            self._scale_x_spin.blockSignals(True)
            self._scale_x_spin.setValue(float(value))
            self._scale_x_spin.blockSignals(False)
            self._scale_y_slider.blockSignals(True)
            self._scale_y_slider.setValue(value)
            self._scale_y_slider.blockSignals(False)
            self._scale_y_spin.blockSignals(True)
            self._scale_y_spin.setValue(float(value))
            self._scale_y_spin.blockSignals(False)
        if self._binding or self._clip is None or not self._uniform_cb.isChecked():
            return
        self._apply_uniform_scale(int(value))
        self._emit()

    def _on_scale_spin_changed(self, value: float) -> None:
        self._scale_slider.setValue(int(value))

    def _on_scale_x_changed(self, value: int) -> None:
        self._scale_x_spin.blockSignals(True)
        self._scale_x_spin.setValue(float(value))
        self._scale_x_spin.blockSignals(False)
        if self._binding or self._clip is None or self._uniform_cb.isChecked():
            return
        self._apply_non_uniform_scale(int(value), self._scale_y_slider.value())
        self._emit()

    def _on_scale_x_spin_changed(self, value: float) -> None:
        self._scale_x_slider.setValue(int(value))

    def _on_scale_y_changed(self, value: int) -> None:
        self._scale_y_spin.blockSignals(True)
        self._scale_y_spin.setValue(float(value))
        self._scale_y_spin.blockSignals(False)
        if self._binding or self._clip is None or self._uniform_cb.isChecked():
            return
        self._apply_non_uniform_scale(self._scale_x_slider.value(), int(value))
        self._emit()

    def _on_scale_y_spin_changed(self, value: float) -> None:
        self._scale_y_slider.setValue(int(value))

    def _on_uniform_toggled(self, checked: bool) -> None:
        self._sync_uniform_scale_ui()
        if self._binding or self._clip is None:
            return
        if checked:
            percent = int(self._scale_x_slider.value())
            self._scale_slider.blockSignals(True)
            self._scale_slider.setValue(percent)
            self._scale_slider.blockSignals(False)
            self._scale_spin.blockSignals(True)
            self._scale_spin.setValue(float(percent))
            self._scale_spin.blockSignals(False)
            self._apply_uniform_scale(percent)
        else:
            self._apply_non_uniform_scale(
                int(self._scale_x_slider.value()),
                int(self._scale_y_slider.value()),
            )
        self._emit()

    def _on_scale_x_changed(self, value: int) -> None:
        self._scale_x_spin.blockSignals(True)
        self._scale_x_spin.setValue(float(value))
        self._scale_x_spin.blockSignals(False)
        if self._binding or self._clip is None or self._uniform_cb.isChecked():
            return
        self._apply_non_uniform_scale(value, int(self._scale_y_slider.value()))
        self._emit()

    def _on_scale_x_spin_changed(self, value: float) -> None:
        self._scale_x_slider.setValue(value)

    def _on_scale_y_changed(self, value: int) -> None:
        self._scale_y_spin.blockSignals(True)
        self._scale_y_spin.setValue(float(value))
        self._scale_y_spin.blockSignals(False)
        if self._binding or self._clip is None or self._uniform_cb.isChecked():
            return
        self._apply_non_uniform_scale(int(self._scale_x_slider.value()), value)
        self._emit()

    def _on_scale_y_spin_changed(self, value: float) -> None:
        self._scale_y_slider.setValue(value)

    def _on_x_changed(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.pos_x = None if int(value) == 0 else int(value)
        self._emit()

    def _on_y_changed(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.pos_y = None if int(value) == 0 else int(value)
        self._emit()

    def _on_rotate_dial_changed(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        
        # When dial changes, we want to update the spinbox but allow multiple rotations
        # Capcut logic: moving dial updates the current rotation to nearest matching angle
        current_spin = self._rotate_spin.value()
        
        base_rot = round(current_spin / 360.0) * 360.0
        new_rot = base_rot + value
        
        # Prevent jumping back and forth if we cross 180/-180 boundary
        if new_rot - current_spin > 180:
            new_rot -= 360
        elif new_rot - current_spin < -180:
            new_rot += 360
            
        self._clip.effects.rotate = float(new_rot)
        self._rotate_spin.blockSignals(True)
        self._rotate_spin.setValue(new_rot)
        self._rotate_spin.blockSignals(False)
        self._emit()

    def _on_rotate_spin_changed(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.rotate = float(value)
        
        self._rotate_dial.blockSignals(True)
        dial_val = int(round(value)) % 360
        if dial_val > 180:
            dial_val -= 360
        elif dial_val < -180:
            dial_val += 360
        self._rotate_dial.setValue(dial_val)
        self._rotate_dial.blockSignals(False)
        
        self._emit()

    def _on_effect_brightness_changed(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.brightness = max(-1.0, min(1.0, float(value)))
        self._emit()

    def _on_effect_contrast_changed(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.contrast = max(0.0, min(4.0, float(value)))
        self._emit()

    def _on_effect_saturation_changed(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.saturation = max(0.0, min(3.0, float(value)))
        self._emit()

    def _on_effect_blur_changed(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.blur = max(0.0, min(20.0, float(value)))
        self._emit()

    def _on_effect_grayscale_toggled(self, checked: bool) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.grayscale = bool(checked)
        self._emit()

    def _on_effect_hflip_toggled(self, checked: bool) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.hflip = bool(checked)
        self._emit()

    def _on_effect_vflip_toggled(self, checked: bool) -> None:
        if self._binding or self._clip is None:
            return
        self._clip.effects.vflip = bool(checked)
        self._emit()

    def _on_speed_changed(self, value: int) -> None:
        val_float = value / 100.0
        self._speed_spin.blockSignals(True)
        self._speed_spin.setValue(val_float)
        self._speed_spin.blockSignals(False)
        if self._binding or self._clip is None:
            return
        self._clip.speed = max(0.1, min(10.0, val_float))
        self.clip_changed.emit("video_speed")

    def _on_speed_spin_changed(self, value: float) -> None:
        self._speed_slider.blockSignals(True)
        self._speed_slider.setValue(int(value * 100))
        self._speed_slider.blockSignals(False)
        if self._binding or self._clip is None:
            return
        self._clip.speed = max(0.1, min(10.0, value))
        self.clip_changed.emit("video_speed")

    def _on_volume_changed(self, value: int) -> None:
        val_float = float(value)
        self._volume_spin.blockSignals(True)
        self._volume_spin.setValue(val_float)
        self._volume_spin.blockSignals(False)
        if self._binding or self._clip is None:
            return
        self._clip.volume = db_to_linear(val_float)
        self._emit()

    def _on_volume_spin_changed(self, value: float) -> None:
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(int(value))
        self._volume_slider.blockSignals(False)
        if self._binding or self._clip is None:
            return
        self._clip.volume = db_to_linear(value)
        self._emit()

    def _on_pitch_changed(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        afx = self._clip.audio_effects
        afx.pitch_semitones = max(-24.0, min(24.0, float(value)))
        # Manual override -> drop preset id (will show no card highlighted)
        if afx.voice_preset_id:
            from ...core.voice_presets import PRESETS_BY_ID
            preset = PRESETS_BY_ID.get(afx.voice_preset_id)
            if preset and abs(afx.pitch_semitones - preset.pitch_semitones) > 0.01:
                afx.voice_preset_id = ""
                if hasattr(self, "_voice_grid"):
                    self._voice_grid.set_active("")
        self._emit()


__all__ = [
    "DB_FLOOR",
    "VideoPropertiesBox",
    "clip_visible_duration",
    "db_to_linear",
    "linear_to_db",
    "percent_to_scale",
    "scale_to_percent",
]
