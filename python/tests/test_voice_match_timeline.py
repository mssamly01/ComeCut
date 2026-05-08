from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from comecut_py.core.project import Clip, Keyframe, Project, Track
from comecut_py.integrations.capcut_generator.adapter import (
    TimelineVoiceMatchOptions,
    build_direct_main_voice_match_project,
    generate_voice_match_from_timeline,
    generate_voice_match_project_from_timeline,
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


def test_generate_voice_match_uses_comecut_media_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from comecut_py.integrations.capcut_generator import adapter as adapter_mod

    video_path = tmp_path / "main.mp4"
    audio_path = tmp_path / "voice.mp3"
    video_path.write_bytes(b"video")
    audio_path.write_bytes(b"audio")
    output_path = tmp_path / "matched.json"
    calls: list[tuple[str, str]] = []

    def _fake_probe(path: Path) -> SimpleNamespace:
        calls.append(("probe", Path(path).name))
        if Path(path).suffix.lower() == ".mp4":
            return SimpleNamespace(duration=4.0, width=1280, height=720)
        return SimpleNamespace(duration=1.25, width=None, height=None)

    class FakeGenerator:
        def __init__(self, fps: float, canvas_width: int, canvas_height: int) -> None:
            self.fps = fps
            self.canvas_width = canvas_width
            self.canvas_height = canvas_height

        def generate_single_json(self, _progress, video, audio_files, _srt, output, *_args):
            assert self.get_media_duration(video) == 4_000_000
            assert self.get_media_duration(audio_files[0]) == 1_250_000
            assert self.get_video_dimensions(video) == (1280, 720)
            Path(output).write_text("{}", encoding="utf-8")
            return output

    monkeypatch.setattr(adapter_mod, "probe_media", _fake_probe)
    monkeypatch.setattr(adapter_mod, "_load_capcut_generator_class", lambda: FakeGenerator)

    project = Project(
        tracks=[
            Track(kind="video", name="Main", clips=[Clip(source=str(video_path), out_point=4.0)]),
            Track(kind="audio", name="Voice", clips=[Clip(source=str(audio_path), out_point=1.25)]),
            Track(
                kind="text",
                name="Text",
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        start=0.0,
                        in_point=0.0,
                        out_point=1.0,
                        text_main="line",
                    )
                ],
            ),
        ]
    )
    options = TimelineVoiceMatchOptions(
        project=project,
        output_json_path=output_path,
        work_dir=tmp_path / "work",
    )

    result = generate_voice_match_from_timeline(options)

    assert result == output_path
    assert output_path.exists()
    assert ("probe", "main.mp4") in calls
    assert ("probe", "voice.mp3") in calls


def test_generate_voice_match_project_from_timeline_imports_and_integrates_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from comecut_py.integrations.capcut_generator import adapter as adapter_mod

    output_path = tmp_path / "matched.json"
    original = Project(
        tracks=[
            Track(
                kind="video",
                name="Main",
                clips=[Clip(source="main.mp4", start=0.0, in_point=0.0, out_point=5.0, volume=0.4)],
            ),
            Track(kind="audio", name="Old Voice", clips=[Clip(source="old.mp3", out_point=1.0)]),
            Track(
                kind="text",
                name="Old Text",
                clips=[Clip(clip_type="text", source="", out_point=1.0, text_main="old")],
            ),
        ],
    )
    matched = Project(
        tracks=[
            Track(
                kind="video",
                name="Matched Video",
                clips=[Clip(source="main.mp4", start=1.0, in_point=2.0, out_point=3.0, speed=1.1)],
            ),
            Track(
                kind="audio",
                name="Matched Voice",
                clips=[Clip(source="voice.mp3", start=1.25, in_point=0.0, out_point=0.75)],
            ),
            Track(
                kind="text",
                name="Matched Text",
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        start=1.25,
                        in_point=0.0,
                        out_point=0.75,
                        text_main="matched",
                    )
                ],
            ),
        ],
    )

    def _fake_generate(options: TimelineVoiceMatchOptions, progress_callback=None) -> Path:
        assert options.output_json_path == output_path
        return output_path

    monkeypatch.setattr(adapter_mod, "generate_voice_match_from_timeline", _fake_generate)
    monkeypatch.setattr(adapter_mod, "import_capcut_draft", lambda path: matched)

    result = generate_voice_match_project_from_timeline(
        TimelineVoiceMatchOptions(
            project=original,
            output_json_path=output_path,
            work_dir=tmp_path / "work",
        )
    )

    main = next(track for track in result.project.tracks if track.kind == "video" and track.name == "Main")
    voice = next(track for track in result.project.tracks if track.kind == "audio")
    text = next(track for track in result.project.tracks if track.kind == "text")

    assert result.output_json_path == output_path
    assert [track.name for track in result.project.tracks] == ["Main", "Matched Voice", "Matched Text"]
    assert main.clips[0].source == "main.mp4"
    assert main.clips[0].speed == 1.1
    assert main.clips[0].volume == 0.4
    assert voice.clips[0].linked_parent_id == main.clips[0].clip_id
    assert text.clips[0].linked_parent_id == main.clips[0].clip_id
    assert voice.clips[0].linked_offset == pytest.approx(0.25)
    assert text.clips[0].text_main == "matched"


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


def test_direct_main_voice_match_replaces_main_without_compare_track() -> None:
    original = Project(
        tracks=[
            Track(
                kind="video",
                name="Main",
                clips=[
                    Clip(
                        source="original.mp4",
                        start=0.0,
                        in_point=0.0,
                        out_point=8.0,
                        volume=0.75,
                    )
                ],
            ),
            Track(
                kind="audio",
                name="Voice",
                clips=[Clip(source="voice.mp3", start=0.5, in_point=0.0, out_point=2.0)],
            ),
            Track(
                kind="text",
                name="Subtitle",
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        start=0.5,
                        in_point=0.0,
                        out_point=2.0,
                        text_main="old subtitle",
                    )
                ],
            ),
        ],
    )
    matched = Project(
        tracks=[
            Track(
                kind="video",
                name="Khớp voice - Video",
                clips=[
                    Clip(
                        source="original.mp4",
                        start=0.0,
                        in_point=0.0,
                        out_point=2.0,
                        speed=0.9,
                        volume_keyframes=[Keyframe(time=0.0, value=0.0)],
                    ),
                    Clip(
                        source="original.mp4",
                        start=2.0,
                        in_point=2.0,
                        out_point=4.5,
                        speed=1.25,
                    ),
                ],
            ),
            Track(
                kind="text",
                name="Matched Text",
                clips=[
                    Clip(
                        clip_type="text",
                        source="",
                        start=2.25,
                        in_point=0.0,
                        out_point=1.0,
                        text_main="matched subtitle",
                    )
                ],
            ),
            Track(
                kind="audio",
                name="Matched Voice",
                clips=[Clip(source="voice.mp3", start=2.25, in_point=0.0, out_point=1.0)],
            ),
        ],
    )

    result = build_direct_main_voice_match_project(original, matched)
    result_main = next(
        (track for track in result.tracks if track.kind == "video" and track.name == "Main"),
        None,
    )
    result_text = next(track for track in result.tracks if track.kind == "text")
    result_audio = next(track for track in result.tracks if track.kind == "audio")

    assert result_main is not None
    assert result_main.name == "Main"
    assert [clip.speed for clip in result_main.clips] == [0.9, 1.25]
    assert [clip.volume for clip in result_main.clips] == [0.75, 0.75]
    assert result_main.clips[0].volume_keyframes == []
    assert result_main.clips[0].audio_effects.fade_in == 0.0
    assert result_main.clips[0].audio_effects.fade_out == 0.0
    assert [track.name for track in result.tracks] == ["Main", "Matched Voice", "Matched Text"]
    assert result_text.clips[0].start == 2.25
    assert result_text.clips[0].text_main == "matched subtitle"
    assert result_audio.clips[0].start == 2.25
    parent = result_main.clips[1]
    assert result_text.clips[0].linked_parent_id == parent.clip_id
    assert result_audio.clips[0].linked_parent_id == parent.clip_id
    assert result_text.clips[0].link_group_id == parent.link_group_id
    assert result_audio.clips[0].link_group_id == parent.link_group_id
    assert result_text.clips[0].linked_offset == pytest.approx(0.25)
    assert result_audio.clips[0].linked_offset == pytest.approx(0.25)
    assert original.tracks[0].clips[0].source == "original.mp4"
    assert len(original.tracks[0].clips) == 1


def test_voice_match_snapshot_toggle_restores_original_and_matched() -> None:
    pytest.importorskip("PySide6")
    from comecut_py.gui.main_window import MainWindow

    original = Project(
        tracks=[
            Track(
                kind="video",
                name="Main",
                clips=[Clip(source="original.mp4", out_point=8.0)],
            )
        ],
    )
    matched = Project(
        tracks=[
            Track(
                kind="video",
                name="Main",
                clips=[
                    Clip(source="original.mp4", start=0.0, in_point=0.0, out_point=2.0, speed=0.8),
                    Clip(source="original.mp4", start=2.0, in_point=2.0, out_point=4.0, speed=1.2),
                ],
            )
        ],
    )

    class FakePanel:
        state: str | None = None

        def set_compare_state(self, state: str | None, **_kwargs) -> None:
            self.state = state

    class FakeWindow:
        def __init__(self) -> None:
            self._voice_match_original_project = original
            self._voice_match_matched_project = matched
            self._voice_match_view_state = None
            self.voice_match_panel = FakePanel()
            self.project = Project()

        def _apply_voice_match_project_snapshot(self, snapshot: Project, view_state: str) -> None:
            self.project = snapshot.model_copy(deep=True)
            self._voice_match_view_state = view_state

    fake = FakeWindow()

    MainWindow._on_voice_match_show_matched(fake)
    assert fake._voice_match_view_state == "matched"
    assert fake.voice_match_panel.state == "matched"
    assert len(fake.project.tracks[0].clips) == 2
    assert fake.project.tracks[0].clips[1].speed == 1.2

    MainWindow._on_voice_match_show_original(fake)
    assert fake._voice_match_view_state == "original"
    assert fake.voice_match_panel.state == "original"
    assert len(fake.project.tracks[0].clips) == 1
    assert fake.project.tracks[0].clips[0].source == "original.mp4"


def test_voice_match_panel_compare_buttons_state() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from comecut_py.gui.widgets.voice_match_panel import VoiceMatchPanel

    _app = QApplication.instance() or QApplication([])
    panel = VoiceMatchPanel()
    try:
        panel.set_compare_state("matched", has_original=True, has_matched=True)
        assert panel.show_original_button.isEnabled()
        assert not panel.show_matched_button.isEnabled()

        panel.set_compare_state("original", has_original=True, has_matched=True)
        assert not panel.show_original_button.isEnabled()
        assert panel.show_matched_button.isEnabled()

        panel.set_compare_state(None, has_original=False, has_matched=False)
        assert not panel.show_original_button.isEnabled()
        assert not panel.show_matched_button.isEnabled()
    finally:
        panel.deleteLater()
