"""Minimal timeline-driven Voice Match panel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Signal  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class VoiceMatchPanelSettings:
    output_json_path: Path | None
    sync_mode: str
    target_audio_speed: float
    keep_pitch: bool
    video_speed_enabled: bool
    target_video_speed: float
    remove_silence: bool
    waveform_sync: bool
    skip_stretch_shorter: bool
    export_lt8: bool


class VoiceMatchPanel(QWidget):
    """Small control panel; timeline clips are collected only when generating."""

    generate_requested = Signal(object)
    import_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._generated_path: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        title = QLabel("Khớp voice")
        title.setStyleSheet("color: #e6edf6; font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        subtitle = QLabel("Đồng bộ voice theo timeline hiện tại")
        subtitle.setStyleSheet("color: #8c93a0; font-size: 11px;")
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.sync_mode_combo = QComboBox()
        self.sync_mode_combo.addItem("Ưu tiên video", "video_priority")
        self.sync_mode_combo.addItem("Đồng bộ tuyệt đối", "force_sync")
        self.sync_mode_combo.addItem("Audio theo video", "audio_sync")
        self.sync_mode_combo.addItem("Audio theo video - ưu tiên", "audio_sync_priority")
        form.addRow("Sync mode", self.sync_mode_combo)

        self.audio_speed_spin = QDoubleSpinBox()
        self.audio_speed_spin.setRange(0.25, 4.0)
        self.audio_speed_spin.setSingleStep(0.05)
        self.audio_speed_spin.setDecimals(2)
        self.audio_speed_spin.setValue(1.0)
        self.audio_speed_spin.setSuffix("x")
        form.addRow("Audio speed", self.audio_speed_spin)

        self.video_speed_spin = QDoubleSpinBox()
        self.video_speed_spin.setRange(0.25, 4.0)
        self.video_speed_spin.setSingleStep(0.05)
        self.video_speed_spin.setDecimals(2)
        self.video_speed_spin.setValue(1.0)
        self.video_speed_spin.setSuffix("x")
        form.addRow("Video speed", self.video_speed_spin)
        root.addLayout(form)

        self.keep_pitch_check = QCheckBox("Giữ pitch")
        self.keep_pitch_check.setChecked(True)
        root.addWidget(self.keep_pitch_check)

        advanced = QLabel("Nâng cao")
        advanced.setStyleSheet("color: #cfd5df; font-size: 12px; font-weight: 600;")
        root.addWidget(advanced)

        self.remove_silence_check = QCheckBox("Xoá khoảng lặng")
        self.waveform_sync_check = QCheckBox("Waveform sync")
        self.skip_stretch_shorter_check = QCheckBox("Bỏ stretch nếu voice ngắn hơn")
        self.export_lt8_check = QCheckBox("Export LT8")
        for check in (
            self.remove_silence_check,
            self.waveform_sync_check,
            self.skip_stretch_shorter_check,
            self.export_lt8_check,
        ):
            root.addWidget(check)

        output_label = QLabel("Output draft")
        output_label.setStyleSheet("color: #cfd5df; font-size: 12px; font-weight: 600;")
        root.addWidget(output_label)

        output_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Tự động lưu trong project/cache")
        self.output_path_edit.setClearButtonEnabled(True)
        self.output_browse_button = QPushButton("Đổi nơi lưu")
        self.output_browse_button.clicked.connect(self._choose_output_path)
        output_row.addWidget(self.output_path_edit, stretch=1)
        output_row.addWidget(self.output_browse_button)
        root.addLayout(output_row)

        self.generate_button = QPushButton("Tạo draft khớp voice")
        self.generate_button.clicked.connect(self._emit_generate)
        root.addWidget(self.generate_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Log")
        self.log_view.setMaximumBlockCount(300)
        root.addWidget(self.log_view, stretch=1)

        self.import_button = QPushButton("Import vào timeline")
        self.import_button.setEnabled(False)
        self.import_button.setVisible(False)
        self.import_button.clicked.connect(self._emit_import)
        root.addWidget(self.import_button)

        self.setStyleSheet(
            """
            QWidget { background: #16181d; color: #dce6f2; }
            QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit {
                background: #101318;
                border: 1px solid #2a2f38;
                border-radius: 5px;
                color: #dce6f2;
                padding: 5px;
            }
            QPushButton {
                background: #22d3c5;
                border: none;
                border-radius: 5px;
                color: #061115;
                font-weight: 700;
                padding: 7px 10px;
            }
            QPushButton:disabled {
                background: #2a2f38;
                color: #7b8492;
            }
            QCheckBox { color: #cfd5df; }
            QProgressBar {
                background: #101318;
                border: 1px solid #2a2f38;
                border-radius: 4px;
                height: 8px;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #22d3c5;
                border-radius: 4px;
            }
            """
        )

    def _choose_output_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu draft khớp voice",
            "",
            "CapCut Draft JSON (*.json);;JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.output_path_edit.setText(path)

    def settings(self) -> VoiceMatchPanelSettings:
        output_text = self.output_path_edit.text().strip()
        video_speed = float(self.video_speed_spin.value())
        return VoiceMatchPanelSettings(
            output_json_path=Path(output_text) if output_text else None,
            sync_mode=str(self.sync_mode_combo.currentData() or "video_priority"),
            target_audio_speed=float(self.audio_speed_spin.value()),
            keep_pitch=bool(self.keep_pitch_check.isChecked()),
            video_speed_enabled=abs(video_speed - 1.0) > 1e-6,
            target_video_speed=video_speed,
            remove_silence=bool(self.remove_silence_check.isChecked()),
            waveform_sync=bool(self.waveform_sync_check.isChecked()),
            skip_stretch_shorter=bool(self.skip_stretch_shorter_check.isChecked()),
            export_lt8=bool(self.export_lt8_check.isChecked()),
        )

    def _emit_generate(self) -> None:
        self.clear_result()
        self.generate_requested.emit(self.settings())

    def _emit_import(self) -> None:
        if self._generated_path is not None:
            self.import_requested.emit(self._generated_path)

    def set_running(self, running: bool) -> None:
        for widget in (
            self.sync_mode_combo,
            self.audio_speed_spin,
            self.video_speed_spin,
            self.keep_pitch_check,
            self.remove_silence_check,
            self.waveform_sync_check,
            self.skip_stretch_shorter_check,
            self.export_lt8_check,
            self.output_path_edit,
            self.output_browse_button,
            self.generate_button,
        ):
            widget.setEnabled(not running)
        if running:
            self.import_button.setEnabled(False)

    def set_progress(self, percent: int, message: str = "") -> None:
        self.progress_bar.setValue(max(0, min(100, int(percent))))
        if message:
            self.append_log(message)

    def append_log(self, message: str) -> None:
        text = str(message).strip()
        if text:
            self.log_view.appendPlainText(text)

    def clear_result(self) -> None:
        self._generated_path = None
        self.progress_bar.setValue(0)
        self.log_view.clear()
        self.import_button.setEnabled(False)
        self.import_button.setVisible(False)

    def set_generated_path(self, path: Path) -> None:
        self._generated_path = Path(path)
        self.import_button.setEnabled(True)
        self.import_button.setVisible(True)
        self.append_log(f"Đã tạo draft: {self._generated_path}")


__all__ = ["VoiceMatchPanel", "VoiceMatchPanelSettings"]
