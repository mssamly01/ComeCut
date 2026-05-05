"""Export Video dialog — mirrors the bundled HTML build's export modal.

Layout (left preview pane + right configuration pane):

* Right column:
    - File name + Save location.
    - **Video** group (toggle): preset / format / resolution.
    - **Audio** group (toggle): format.
    - **Subtitles** group (toggle): format / display track.
* Bottom: Export / Cancel.

The dialog is purely UI — picking ``Export`` returns an :class:`ExportOptions`
dataclass via :meth:`get_options`, leaving ffmpeg/render orchestration to the
host window.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...engine.presets import PRESETS

VIDEO_FORMATS = ["mp4", "webm", "mkv", "mov"]
RESOLUTIONS = ["720P", "1080P", "2K", "4K"]
AUDIO_FORMATS = ["wav", "mp3", "aac"]
SUBTITLE_FORMATS = ["srt", "vtt", "txt", "ass"]


@dataclass
class ExportOptions:
    """User-selected export settings."""

    file_name: str
    save_dir: Path
    preset: str | None  # one of comecut_py.engine.presets.PRESETS keys
    video_enabled: bool
    video_format: str
    resolution: str
    audio_enabled: bool
    audio_format: str
    subs_enabled: bool
    subs_format: str
    subs_display: str  # "main" | "second" | "bilingual"

    def output_path(self) -> Path:
        return self.save_dir / f"{self.file_name}.{self.video_format}"


class ExportDialog(QDialog):
    """Modal export dialog.

    Pass the current project name to seed the file-name field. Resolve
    options via :meth:`get_options` after :meth:`exec` returns
    :class:`QDialog.Accepted`.
    """

    def __init__(self, parent: QWidget | None = None, *, project_name: str = "Untitled") -> None:
        super().__init__(parent)
        self.setWindowTitle("Export your video")
        self.setMinimumSize(720, 480)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)

        # ---- left preview placeholder --------------------------------
        preview = QFrame()
        preview.setObjectName("card")
        preview.setMinimumWidth(280)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pv = QVBoxLayout(preview)
        pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Preview")
        title.setStyleSheet("color: #8c93a0;")
        pv.addWidget(title)
        outer.addWidget(preview, stretch=1)

        # ---- right config column -------------------------------------
        right = QVBoxLayout()
        right.setSpacing(8)
        outer.addLayout(right, stretch=1)

        meta = QFormLayout()
        self._name = QLineEdit(project_name)
        meta.addRow("File name", self._name)

        save_row = QHBoxLayout()
        self._save_dir = QLineEdit(str(Path.home() / "Videos"))
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_dir)
        save_row.addWidget(self._save_dir)
        save_row.addWidget(browse)
        save_w = QWidget()
        save_w.setLayout(save_row)
        meta.addRow("Save location", save_w)
        right.addLayout(meta)

        # ---- video group ---------------------------------------------
        self._video_group = self._toggle_group("Video")
        v_form = QFormLayout()
        self._preset = QComboBox()
        self._preset.addItem("(none)")
        self._preset.addItems(sorted(PRESETS))
        v_form.addRow("Preset", self._preset)

        self._video_format = QComboBox()
        self._video_format.addItems(VIDEO_FORMATS)
        v_form.addRow("Format", self._video_format)

        self._resolution = QComboBox()
        self._resolution.addItems(RESOLUTIONS)
        self._resolution.setCurrentText("1080P")
        v_form.addRow("Resolution", self._resolution)
        self._video_group.body.setLayout(v_form)
        right.addWidget(self._video_group.frame)

        # ---- audio group ---------------------------------------------
        self._audio_group = self._toggle_group("Audio", default=False)
        a_form = QFormLayout()
        self._audio_format = QComboBox()
        self._audio_format.addItems(AUDIO_FORMATS)
        a_form.addRow("Format", self._audio_format)
        self._audio_group.body.setLayout(a_form)
        right.addWidget(self._audio_group.frame)

        # ---- subtitles group -----------------------------------------
        self._subs_group = self._toggle_group("Subtitles", default=False)
        s_form = QFormLayout()
        self._subs_format = QComboBox()
        self._subs_format.addItems(SUBTITLE_FORMATS)
        s_form.addRow("Format", self._subs_format)
        self._subs_display = QComboBox()
        self._subs_display.addItems(["main", "second", "bilingual"])
        s_form.addRow("Display", self._subs_display)
        self._subs_group.body.setLayout(s_form)
        right.addWidget(self._subs_group.frame)

        right.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)

    # ---- helpers -------------------------------------------------------
    @dataclass
    class _Group:
        frame: QFrame
        toggle: QCheckBox
        body: QWidget

    def _toggle_group(self, title: str, *, default: bool = True) -> _Group:
        frame = QFrame()
        frame.setObjectName("card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 8, 12, 12)
        head = QHBoxLayout()
        toggle = QCheckBox(title)
        toggle.setChecked(default)
        toggle.setStyleSheet("font-weight: 600; color: #e6e8ec;")
        head.addWidget(toggle)
        head.addStretch(1)
        v.addLayout(head)
        body = QWidget()
        body.setEnabled(default)
        toggle.toggled.connect(body.setEnabled)
        v.addWidget(body)
        return self._Group(frame=frame, toggle=toggle, body=body)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save location", self._save_dir.text())
        if path:
            self._save_dir.setText(path)

    # ---- output --------------------------------------------------------
    def get_options(self) -> ExportOptions:
        preset = self._preset.currentText()
        return ExportOptions(
            file_name=self._name.text() or "output",
            save_dir=Path(self._save_dir.text() or str(Path.home())),
            preset=None if preset == "(none)" else preset,
            video_enabled=self._video_group.toggle.isChecked(),
            video_format=self._video_format.currentText(),
            resolution=self._resolution.currentText(),
            audio_enabled=self._audio_group.toggle.isChecked(),
            audio_format=self._audio_format.currentText(),
            subs_enabled=self._subs_group.toggle.isChecked(),
            subs_format=self._subs_format.currentText(),
            subs_display=self._subs_display.currentText(),
        )


__all__ = ["ExportDialog", "ExportOptions"]
