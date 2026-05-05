"""Grid of voice-changer preset cards (CapCut-style)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.voice_presets import PRESETS, VoicePreset


class _PresetCard(QPushButton):
    """A clickable preset card with icon + label."""

    def __init__(self, preset: VoicePreset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.setCheckable(True)
        self.setFixedSize(72, 72)
        self.setToolTip(self._tooltip())
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(self._stylesheet(active=False))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 4)
        layout.setSpacing(2)
        icon = QLabel(preset.icon)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 26px; background: transparent; border: none;")
        label = QLabel(preset.label)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #cbd0d8; font-size: 10px; background: transparent; border: none;")
        layout.addWidget(icon)
        layout.addWidget(label)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, on: bool) -> None:
        self.setStyleSheet(self._stylesheet(active=on))

    def _tooltip(self) -> str:
        if self.preset.id == "none":
            return "Tắt voice changer"
        bits: list[str] = []
        if self.preset.pitch_semitones:
            bits.append(f"Pitch {self.preset.pitch_semitones:+.0f} st")
        if self.preset.formant_shift:
            bits.append(f"Formant {self.preset.formant_shift:+.0f} st")
        if self.preset.chorus_depth:
            bits.append(f"Chorus {int(self.preset.chorus_depth * 100)}%")
        return self.preset.label + ((" — " + ", ".join(bits)) if bits else "")

    @staticmethod
    def _stylesheet(*, active: bool) -> str:
        if active:
            return (
                "QPushButton { background: #1f3b3a; border: 2px solid #22d3c5; "
                "border-radius: 8px; }"
                "QPushButton:hover { background: #234645; }"
            )
        return (
            "QPushButton { background: #1a1d23; border: 1px solid #2a2f38; "
            "border-radius: 8px; }"
            "QPushButton:hover { background: #20242c; border-color: #3a4150; }"
        )


class VoicePresetGrid(QWidget):
    """Grid of preset cards. Emits ``preset_clicked(id)`` on user click."""

    preset_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: dict[str, _PresetCard] = {}
        self._suppress = False
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        cols = 4
        for i, preset in enumerate(PRESETS):
            card = _PresetCard(preset, self)
            # Use a closure or functools.partial to capture preset.id
            card.clicked.connect(lambda _checked, pid=preset.id: self._on_card_clicked(pid))
            row, col = divmod(i, cols)
            layout.addWidget(card, row, col)
            self._cards[preset.id] = card
        
        # Ensure grid is compact
        layout.setColumnStretch(cols, 1)
        layout.setRowStretch(layout.rowCount(), 1)

    def _on_card_clicked(self, preset_id: str) -> None:
        if self._suppress:
            return
        self.set_active(preset_id)
        self.preset_clicked.emit(preset_id)

    def set_active(self, preset_id: str) -> None:
        """Programmatically highlight the matching card; '' clears all."""
        self._suppress = True
        try:
            for pid, card in self._cards.items():
                card.setChecked(pid == preset_id)
        finally:
            self._suppress = False


__all__ = ["VoicePresetGrid"]
