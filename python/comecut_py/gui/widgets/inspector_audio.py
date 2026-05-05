"""CapCut-style inspector controls for audio clips."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.project import Clip
from .inspector_video import (
    DB_FLOOR,
    _make_capcut_value_input,
    _make_icon_stepper,
    _make_slider,
    _property_icon,
    _section_label,
    db_to_linear,
    linear_to_db,
)


FADE_MAX_SECONDS = 10.0
_FADE_SLIDER_MAX = int(FADE_MAX_SECONDS * 10)


def _keyframe_diamond_btn() -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("FadeKeyframeDiamond")
    btn.setFixedSize(20, 20)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip("Keyframe control (B.5)")
    icon = _property_icon("icon-editor-properties-keyframe", size=14)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setText("*")
    btn.setStyleSheet(
        """
        QToolButton#FadeKeyframeDiamond {
            background: transparent;
            border: none;
            color: #8a91a0;
            font-size: 14px;
        }
        QToolButton#FadeKeyframeDiamond:hover { color: #cbd0d8; }
        """
    )
    btn.setEnabled(False)
    return btn


class AudioPropertiesBox(QWidget):
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

        outer.addWidget(_section_label("Audio file"))
        self._source_lbl = QLabel("-")
        self._source_lbl.setWordWrap(True)
        self._source_lbl.setStyleSheet("color: #8c93a0; font-size: 11px;")
        outer.addWidget(self._source_lbl)
        outer.addSpacing(12)

        outer.addWidget(self._build_speed_row())
        outer.addSpacing(20)
        outer.addWidget(self._build_volume_row())
        outer.addSpacing(20)
        outer.addWidget(self._build_fade_row("Fade in", which="in"))
        outer.addSpacing(8)
        outer.addWidget(self._build_fade_row("Fade out", which="out"))
        outer.addStretch(1)

        self._wire_signals()
        self.set_clip(None)

    def _build_speed_row(self) -> QWidget:
        row = QWidget()
        vbox = QVBoxLayout(row)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(8)

        header = QHBoxLayout()
        label = QLabel("Speed")
        label.setFixedWidth(80)
        header.addWidget(label)
        header.addStretch(1)

        value_wrap = QWidget()
        value_layout = QHBoxLayout(value_wrap)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(0)
        self._speed_container, self._speed_spin = _make_capcut_value_input(
            75, 0.1, 10.0, "x", 2
        )
        self._speed_spin.setSingleStep(0.1)
        self._speed_stepper, self._speed_inc, self._speed_dec = _make_icon_stepper(
            "AudioSpeed", attached=True
        )
        value_layout.addWidget(self._speed_container)
        value_layout.addWidget(self._speed_stepper)
        header.addWidget(value_wrap)
        vbox.addLayout(header)

        self._speed_slider = _make_slider(10, 1000, 100)
        vbox.addWidget(self._speed_slider)
        return row

    def _build_volume_row(self) -> QWidget:
        row = QWidget()
        vbox = QVBoxLayout(row)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(8)

        header = QHBoxLayout()
        label = QLabel("Volume")
        label.setFixedWidth(80)
        header.addWidget(label)
        header.addStretch(1)

        value_wrap = QWidget()
        value_layout = QHBoxLayout(value_wrap)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(0)
        self._volume_container, self._volume_spin = _make_capcut_value_input(
            80, DB_FLOOR, 20.0, "dB", 1
        )
        self._volume_stepper, self._volume_inc, self._volume_dec = _make_icon_stepper(
            "AudioVolume", attached=True
        )
        value_layout.addWidget(self._volume_container)
        value_layout.addWidget(self._volume_stepper)
        header.addWidget(value_wrap)
        vbox.addLayout(header)

        self._volume_slider = _make_slider(int(DB_FLOOR), 20, 0)
        vbox.addWidget(self._volume_slider)
        return row

    def _build_fade_row(self, label_text: str, *, which: str) -> QWidget:
        row = QWidget()
        vbox = QVBoxLayout(row)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(8)

        header = QHBoxLayout()
        label = QLabel(label_text)
        label.setFixedWidth(80)
        header.addWidget(label)
        header.addStretch(1)

        value_wrap = QWidget()
        value_layout = QHBoxLayout(value_wrap)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(6)
        container, spin = _make_capcut_value_input(70, 0.0, FADE_MAX_SECONDS, "s", 1)
        spin.setSingleStep(0.1)
        diamond = _keyframe_diamond_btn()
        value_layout.addWidget(container)
        value_layout.addWidget(diamond)
        header.addWidget(value_wrap)
        vbox.addLayout(header)

        slider = _make_slider(0, _FADE_SLIDER_MAX, 0)
        vbox.addWidget(slider)

        if which == "in":
            self._fade_in_container = container
            self._fade_in_spin = spin
            self._fade_in_slider = slider
            self._fade_in_diamond = diamond
        else:
            self._fade_out_container = container
            self._fade_out_spin = spin
            self._fade_out_slider = slider
            self._fade_out_diamond = diamond
        return row

    def _wire_signals(self) -> None:
        self._speed_slider.valueChanged.connect(self._on_speed_slider)
        self._speed_spin.valueChanged.connect(self._on_speed_spin)
        self._speed_inc.clicked.connect(self._speed_spin.stepUp)
        self._speed_dec.clicked.connect(self._speed_spin.stepDown)

        self._volume_slider.valueChanged.connect(self._on_volume_slider)
        self._volume_spin.valueChanged.connect(self._on_volume_spin)
        self._volume_inc.clicked.connect(self._volume_spin.stepUp)
        self._volume_dec.clicked.connect(self._volume_spin.stepDown)

        self._fade_in_slider.valueChanged.connect(self._on_fade_in_slider)
        self._fade_in_spin.valueChanged.connect(self._on_fade_in_spin)
        self._fade_out_slider.valueChanged.connect(self._on_fade_out_slider)
        self._fade_out_spin.valueChanged.connect(self._on_fade_out_spin)

    def set_clip(self, clip: Clip | None, *, track_kind: str | None = None) -> None:
        self._binding = True
        try:
            self._clip = clip
            self._track_kind = track_kind
            enabled = clip is not None

            controls = (
                self._speed_slider,
                self._speed_container,
                self._speed_inc,
                self._speed_dec,
                self._volume_slider,
                self._volume_container,
                self._volume_inc,
                self._volume_dec,
                self._fade_in_slider,
                self._fade_in_container,
                self._fade_out_slider,
                self._fade_out_container,
            )
            for widget in controls:
                widget.setEnabled(enabled)

            if clip is None:
                self._source_lbl.setText("-")
                self._speed_slider.setValue(100)
                self._speed_spin.setValue(1.0)
                self._volume_slider.setValue(0)
                self._volume_spin.setValue(0.0)
                self._fade_in_slider.setValue(0)
                self._fade_in_spin.setValue(0.0)
                self._fade_out_slider.setValue(0)
                self._fade_out_spin.setValue(0.0)
                return

            self._source_lbl.setText(str(clip.source) or "-")

            speed = max(0.1, min(10.0, float(clip.speed or 1.0)))
            self._speed_slider.setValue(int(round(speed * 100.0)))
            self._speed_spin.setValue(speed)

            db = max(DB_FLOOR, min(20.0, linear_to_db(float(clip.volume or 0.0))))
            self._volume_slider.setValue(int(round(db)))
            self._volume_spin.setValue(db)

            fade_in = float(getattr(clip.audio_effects, "fade_in", 0.0) or 0.0)
            fade_out = float(getattr(clip.audio_effects, "fade_out", 0.0) or 0.0)
            fade_in = max(0.0, min(FADE_MAX_SECONDS, fade_in))
            fade_out = max(0.0, min(FADE_MAX_SECONDS, fade_out))
            self._fade_in_slider.setValue(int(round(fade_in * 10)))
            self._fade_in_spin.setValue(fade_in)
            self._fade_out_slider.setValue(int(round(fade_out * 10)))
            self._fade_out_spin.setValue(fade_out)
        finally:
            self._binding = False

    def _emit(self, source: str = "") -> None:
        if self._binding:
            return
        self.clip_changed.emit(source)

    def _on_speed_slider(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        speed = max(0.1, min(10.0, value / 100.0))
        self._speed_spin.blockSignals(True)
        self._speed_spin.setValue(speed)
        self._speed_spin.blockSignals(False)
        self._clip.speed = speed
        self._emit("audio_speed")

    def _on_speed_spin(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        speed = max(0.1, min(10.0, value))
        self._speed_slider.blockSignals(True)
        self._speed_slider.setValue(int(round(speed * 100)))
        self._speed_slider.blockSignals(False)
        self._clip.speed = speed
        self._emit("audio_speed")

    def _on_volume_slider(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        db = float(value)
        self._volume_spin.blockSignals(True)
        self._volume_spin.setValue(db)
        self._volume_spin.blockSignals(False)
        self._clip.volume = float(db_to_linear(db))
        self._emit()

    def _on_volume_spin(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        db = max(DB_FLOOR, min(20.0, float(value)))
        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(int(round(db)))
        self._volume_slider.blockSignals(False)
        self._clip.volume = float(db_to_linear(db))
        self._emit()

    def _on_fade_in_slider(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        secs = max(0.0, min(FADE_MAX_SECONDS, value / 10.0))
        self._fade_in_spin.blockSignals(True)
        self._fade_in_spin.setValue(secs)
        self._fade_in_spin.blockSignals(False)
        self._clip.audio_effects.fade_in = secs
        self._emit()

    def _on_fade_in_spin(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        secs = max(0.0, min(FADE_MAX_SECONDS, float(value)))
        self._fade_in_slider.blockSignals(True)
        self._fade_in_slider.setValue(int(round(secs * 10)))
        self._fade_in_slider.blockSignals(False)
        self._clip.audio_effects.fade_in = secs
        self._emit()

    def _on_fade_out_slider(self, value: int) -> None:
        if self._binding or self._clip is None:
            return
        secs = max(0.0, min(FADE_MAX_SECONDS, value / 10.0))
        self._fade_out_spin.blockSignals(True)
        self._fade_out_spin.setValue(secs)
        self._fade_out_spin.blockSignals(False)
        self._clip.audio_effects.fade_out = secs
        self._emit()

    def _on_fade_out_spin(self, value: float) -> None:
        if self._binding or self._clip is None:
            return
        secs = max(0.0, min(FADE_MAX_SECONDS, float(value)))
        self._fade_out_slider.blockSignals(True)
        self._fade_out_slider.setValue(int(round(secs * 10)))
        self._fade_out_slider.blockSignals(False)
        self._clip.audio_effects.fade_out = secs
        self._emit()


__all__ = ["AudioPropertiesBox", "FADE_MAX_SECONDS"]
