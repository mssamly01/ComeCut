from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from comecut_py.core.project import Clip, Project, Track
from comecut_py.integrations.capcut_generator.adapter import (
    prepare_timeline_voice_match_inputs,
)


def test_prepare_timeline_voice_match_inputs_collects_sources_and_exports_srt(tmp_path: Path) -> None:
    video_path = tmp_path / "main.mp4"
    audio_first = tmp_path / "voice_a.mp3"
    audio_second = tmp_path / "voice_b.mp3"
    video_path.write_bytes(b"video")
    audio_first.write_bytes(b"audio-a")
    audio_second.write_bytes(b"audio-b")

    project = Project(
        name="Voice Match Test",
        tracks=[
            Track(
                kind="video",
                name="Main",
                clips=[
                    Clip(source=str(video_path), start=4.0, in_point=0.0, out_point=10.0),
                ],
            ),
            Track(
                kind="audio",
                name="Voice",
                clips=[
                    Clip(source=str(audio_second), start=6.0, in_point=0.0, out_point=2.0),
                    Clip(source=str(audio_first), start=1.0, in_point=0.0, out_point=2.0),
                ],
            ),
            Track(
                kind="text",
                name="Subtitle",
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        start=1.25,
                        in_point=0.0,
                        out_point=2.0,
                        text_main="Xin chào",
                    ),
                    Clip(
                        clip_type="text",
                        source="",
                        start=4.0,
                        in_point=0.0,
                        out_point=1.5,
                        text_main="Dòng chính",
                        text_second="Second line",
                        text_display="bilingual",
                    ),
                ],
            ),
        ],
    )

    inputs = prepare_timeline_voice_match_inputs(project, tmp_path / "work")

    assert inputs.video_path == video_path
    assert inputs.audio_files == [audio_first, audio_second]
    assert inputs.timestamp_screen is None
    exported = inputs.srt_path.read_text(encoding="utf-8")
    assert "00:00:01,250 --> 00:00:03,250" in exported
    assert "Xin chào" in exported
    assert "Dòng chính\nSecond line" in exported


def test_prepare_timeline_voice_match_inputs_skips_hidden_and_muted_tracks(tmp_path: Path) -> None:
    project = Project(
        tracks=[
            Track(
                kind="video",
                name="Main",
                clips=[Clip(source=str(tmp_path / "main.mp4"), out_point=5.0)],
            ),
            Track(
                kind="audio",
                name="Hidden audio",
                hidden=True,
                clips=[Clip(source=str(tmp_path / "hidden.mp3"), out_point=2.0)],
            ),
            Track(
                kind="text",
                name="Muted text",
                muted=True,
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        out_point=2.0,
                        text_main="Không dùng",
                    )
                ],
            ),
        ],
    )

    with pytest.raises(ValueError) as exc_info:
        prepare_timeline_voice_match_inputs(project, tmp_path / "work")

    message = str(exc_info.value)
    assert "Chưa có audio trên timeline" in message
    assert "Chưa có phụ đề/text trên timeline" in message


def test_prepare_timeline_voice_match_inputs_reports_missing_data_in_vietnamese(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as exc_info:
        prepare_timeline_voice_match_inputs(Project(tracks=[]), tmp_path / "work")

    message = str(exc_info.value)
    assert "Track Main chưa có video" in message
    assert "Chưa có audio trên timeline" in message
    assert "Chưa có phụ đề/text trên timeline" in message


def test_voice_match_panel_has_no_source_picker_fields() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from comecut_py.gui.widgets.voice_match_panel import VoiceMatchPanel

    _app = QApplication.instance() or QApplication([])
    panel = VoiceMatchPanel()
    try:
        for attr in (
            "video_edit",
            "audio_folder_edit",
            "srt_edit",
            "timetamp_edit",
            "audio_list",
        ):
            assert not hasattr(panel, attr)
    finally:
        panel.deleteLater()


def test_set_left_tab_voice_match_uses_side_stack_index_2() -> None:
    pytest.importorskip("PySide6")
    from comecut_py.gui.main_window import MainWindow
    from comecut_py.gui.widgets.left_rail import TAB_VOICE_MATCH

    class FakeRail:
        active: str | None = None

        def set_active(self, key: str) -> None:
            self.active = key

    class FakeStack:
        index: int | None = None

        def setCurrentIndex(self, index: int) -> None:
            self.index = index

    fake = SimpleNamespace(
        left_rail=FakeRail(),
        side_stack=FakeStack(),
        sub_nav_stack=FakeStack(),
    )

    MainWindow._set_left_tab(fake, TAB_VOICE_MATCH)

    assert fake.left_rail.active == TAB_VOICE_MATCH
    assert fake.side_stack.index == 2
    assert fake.sub_nav_stack.index == 2
