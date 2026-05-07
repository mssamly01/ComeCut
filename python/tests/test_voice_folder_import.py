from __future__ import annotations

from pathlib import Path

import pytest

from comecut_py.core.project import Clip, Project, Track


class _ProbeInfo:
    def __init__(self, duration: float) -> None:
        self.duration = duration


class _VoiceImportHarness:
    from comecut_py.gui.main_window import MainWindow

    _is_track_hidden = staticmethod(MainWindow._is_track_hidden)
    _is_track_locked = staticmethod(MainWindow._is_track_locked)
    _is_track_muted = staticmethod(MainWindow._is_track_muted)
    _main_video_track = MainWindow._main_video_track
    _get_or_create_track = MainWindow._get_or_create_track
    _voice_target_subtitle_clips = MainWindow._voice_target_subtitle_clips
    _voice_audio_files_from_folder = MainWindow._voice_audio_files_from_folder
    _add_voice_folder_to_timeline = MainWindow._add_voice_folder_to_timeline

    def __init__(self, project: Project) -> None:
        from comecut_py.gui.main_window import MainWindow

        self.project = project
        self._natural_voice_sort_key = MainWindow._natural_voice_sort_key
        self.audio_proxy_started: list[Clip] = []

    def _start_audio_proxy_generation_if_needed(self, clip: Clip) -> None:
        self.audio_proxy_started.append(clip)


def _text_clip(start: float, duration: float, text: str = "line") -> Clip:
    return Clip(
        clip_type="text",
        source="",
        start=start,
        in_point=0.0,
        out_point=duration,
        text_main=text,
    )


def _touch_mp3(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_bytes(b"mp3")
    return path


def test_add_voice_folder_without_subtitles_adds_sequential_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _touch_mp3(tmp_path, "10.mp3")
    _touch_mp3(tmp_path, "1.mp3")
    _touch_mp3(tmp_path, "2.mp3")
    harness = _VoiceImportHarness(Project(tracks=[]))

    from comecut_py.gui import main_window as main_window_mod

    durations = {"1.mp3": 1.0, "2.mp3": 2.5, "10.mp3": 3.0}
    monkeypatch.setattr(
        main_window_mod,
        "probe",
        lambda path: _ProbeInfo(durations[Path(path).name]),
    )

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert [Path(clip.source).name for clip in created] == ["1.mp3", "2.mp3", "10.mp3"]
    assert [clip.start for clip in created] == [0.0, 1.0, 3.5]
    assert [clip.out_point for clip in created] == [1.0, 2.5, 3.0]
    assert harness.project.library_media == []


def test_add_voice_folder_mismatch_does_not_create_audio(tmp_path: Path) -> None:
    _touch_mp3(tmp_path, "1.mp3")
    project = Project(
        tracks=[
            Track(
                kind="text",
                name="Subtitle",
                clips=[
                    _text_clip(0.0, 1.0, "a"),
                    _text_clip(2.0, 1.0, "b"),
                ],
            )
        ]
    )
    harness = _VoiceImportHarness(project)

    with pytest.raises(ValueError) as exc_info:
        harness._add_voice_folder_to_timeline(tmp_path)

    assert "không khớp" in str(exc_info.value)
    assert not any(track.kind == "audio" for track in project.tracks)
    assert project.library_media == []


def test_add_voice_folder_matches_mp3_to_subtitle_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _touch_mp3(tmp_path, "10.mp3")
    _touch_mp3(tmp_path, "1.mp3")
    _touch_mp3(tmp_path, "2.mp3")
    project = Project(
        tracks=[
            Track(
                kind="text",
                name="Subtitle",
                clips=[
                    _text_clip(0.5, 1.0, "first"),
                    _text_clip(3.0, 1.0, "second"),
                    _text_clip(8.0, 1.0, "third"),
                    _text_clip(12.0, 1.0, ""),
                ],
            ),
            Track(
                kind="text",
                name="Hidden subtitle",
                hidden=True,
                clips=[_text_clip(20.0, 1.0, "hidden")],
            ),
        ]
    )
    durations = {"1.mp3": 1.1, "2.mp3": 2.2, "10.mp3": 10.1}

    from comecut_py.gui import main_window as main_window_mod

    monkeypatch.setattr(
        main_window_mod,
        "probe",
        lambda path: _ProbeInfo(durations[Path(path).name]),
    )
    harness = _VoiceImportHarness(project)

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert [Path(clip.source).name for clip in created] == ["1.mp3", "2.mp3", "10.mp3"]
    assert [clip.start for clip in created] == [0.5, 3.0, 8.0]
    assert [clip.out_point for clip in created] == [1.1, 2.2, 10.1]
    assert project.library_media == []
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 1
    assert audio_tracks[0].clips == created
    assert harness.audio_proxy_started == created


def test_add_voice_folder_falls_back_to_subtitle_duration_when_probe_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _touch_mp3(tmp_path, "1.mp3")
    project = Project(
        tracks=[Track(kind="text", name="Subtitle", clips=[_text_clip(4.0, 2.5, "line")])]
    )
    from comecut_py.gui import main_window as main_window_mod

    def _raise_probe(_path: object) -> _ProbeInfo:
        raise RuntimeError("bad media")

    monkeypatch.setattr(main_window_mod, "probe", _raise_probe)
    harness = _VoiceImportHarness(project)

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert len(created) == 1
    assert created[0].start == 4.0
    assert created[0].out_point == 2.5


def test_add_voice_folder_overlapping_subtitles_auto_split_to_multiple_audio_tracks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _touch_mp3(tmp_path, "1.mp3")
    _touch_mp3(tmp_path, "2.mp3")
    project = Project(
        tracks=[
            Track(
                kind="text",
                name="Subtitle",
                clips=[
                    _text_clip(1.0, 2.0, "first"),
                    _text_clip(1.5, 2.0, "second"),
                ],
            )
        ]
    )
    harness = _VoiceImportHarness(project)

    from comecut_py.gui import main_window as main_window_mod

    monkeypatch.setattr(
        main_window_mod,
        "probe",
        lambda _path: _ProbeInfo(2.0),
    )

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert len(created) == 2
    assert [clip.start for clip in created] == [1.0, 1.5]
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 2
    assert len(audio_tracks[0].clips) == 1
    assert len(audio_tracks[1].clips) == 1
    assert audio_tracks[0].clips[0].start == 1.0
    assert audio_tracks[1].clips[0].start == 1.5


def test_add_voice_folder_uses_new_audio_track_when_existing_track_overlaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _touch_mp3(tmp_path, "1.mp3")
    project = Project(
        tracks=[
            Track(
                kind="audio",
                name="Audio 1",
                clips=[
                    Clip(
                        source="existing.mp3",
                        start=0.0,
                        in_point=0.0,
                        out_point=10.0,
                    )
                ],
            ),
            Track(
                kind="text",
                name="Subtitle",
                clips=[_text_clip(2.0, 1.0, "line")],
            ),
        ]
    )
    harness = _VoiceImportHarness(project)

    from comecut_py.gui import main_window as main_window_mod

    monkeypatch.setattr(
        main_window_mod,
        "probe",
        lambda _path: _ProbeInfo(1.5),
    )

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert len(created) == 1
    assert created[0].start == 2.0
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 2
    assert len(audio_tracks[0].clips) == 1
    assert len(audio_tracks[1].clips) == 1
    assert audio_tracks[0].clips[0].source == "existing.mp3"
    assert Path(audio_tracks[1].clips[0].source).name == "1.mp3"


def test_media_panel_voice_folder_signal_does_not_import_to_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from comecut_py.gui.widgets.media_library import MediaLibraryPanel

    _app = QApplication.instance() or QApplication([])
    panel = MediaLibraryPanel()
    emitted: list[Path] = []
    imported: list[list[Path]] = []
    panel.voice_folder_import_requested.connect(lambda path: emitted.append(Path(path)))
    panel.files_imported.connect(lambda paths: imported.append(paths))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path))

    panel._on_add_voice_folder()

    assert emitted == [tmp_path]
    assert imported == []
    assert panel.list_widget.count() == 0
    panel.deleteLater()
