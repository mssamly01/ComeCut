from __future__ import annotations

from pathlib import Path

import pytest

from comecut_py.core.media_cache import CachedMediaInfo
from comecut_py.core.project import Clip, Project, Track


class _VoiceImportHarness:
    from comecut_py.gui.main_window import MainWindow

    _source_key_for_path = staticmethod(MainWindow._source_key_for_path)
    _is_track_hidden = staticmethod(MainWindow._is_track_hidden)
    _is_track_locked = staticmethod(MainWindow._is_track_locked)
    _is_track_muted = staticmethod(MainWindow._is_track_muted)
    _main_video_track = MainWindow._main_video_track
    _get_or_create_track = MainWindow._get_or_create_track
    _cached_media_info_for_path = MainWindow._cached_media_info_for_path
    _duration_for_insert = MainWindow._duration_for_insert
    _register_placeholder_clip = MainWindow._register_placeholder_clip
    _unregister_placeholder_clip = MainWindow._unregister_placeholder_clip
    _clip_overlaps_track = staticmethod(MainWindow._clip_overlaps_track)
    _audio_insert_index_after_last_audio = MainWindow._audio_insert_index_after_last_audio
    _move_audio_clip_to_non_overlapping_track = (
        MainWindow._move_audio_clip_to_non_overlapping_track
    )
    _voice_target_subtitle_clips = MainWindow._voice_target_subtitle_clips
    _voice_audio_files_from_folder = MainWindow._voice_audio_files_from_folder
    _add_voice_folder_to_timeline = MainWindow._add_voice_folder_to_timeline

    class _Cache:
        def __init__(self, durations: dict[str, float] | None = None) -> None:
            self.durations = durations or {}

        def get(self, path: Path | str) -> CachedMediaInfo | None:
            duration = self.durations.get(Path(path).name)
            if duration is None:
                return None
            return CachedMediaInfo(
                source=str(path),
                duration=duration,
                has_audio=True,
                has_video=False,
                audio_codec="mp3",
            )

    class _Ingest:
        def __init__(self, durations: dict[str, float] | None = None) -> None:
            self.cache = _VoiceImportHarness._Cache(durations)
            self.enqueued: list[Path] = []
            self.enqueue_many_calls = 0

        def enqueue(self, path: Path | str) -> None:
            self.enqueued.append(Path(path))

        def enqueue_many(self, paths: list[Path] | tuple[Path, ...]) -> None:
            self.enqueue_many_calls += 1
            for path in paths:
                self.enqueued.append(Path(path))

    def __init__(self, project: Project, durations: dict[str, float] | None = None) -> None:
        from comecut_py.gui.main_window import MainWindow

        self.project = project
        self._natural_voice_sort_key = MainWindow._natural_voice_sort_key
        self._media_ingest = self._Ingest(durations)
        self._duration_placeholder_clip_ids: set[int] = set()
        self._duration_placeholder_by_source_key: dict[str, list[Clip]] = {}
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
) -> None:
    _touch_mp3(tmp_path, "10.mp3")
    _touch_mp3(tmp_path, "1.mp3")
    _touch_mp3(tmp_path, "2.mp3")
    durations = {"1.mp3": 1.0, "2.mp3": 2.5, "10.mp3": 3.0}
    harness = _VoiceImportHarness(Project(tracks=[]), durations=durations)

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert [Path(clip.source).name for clip in created] == ["1.mp3", "2.mp3", "10.mp3"]
    assert [clip.start for clip in created] == [0.0, 1.0, 3.5]
    assert [clip.out_point for clip in created] == [1.0, 2.5, 3.0]
    assert [path.name for path in harness._media_ingest.enqueued] == ["1.mp3", "2.mp3", "10.mp3"]
    assert harness._media_ingest.enqueue_many_calls == 1
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

    harness = _VoiceImportHarness(project, durations=durations)

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert [Path(clip.source).name for clip in created] == ["1.mp3", "2.mp3", "10.mp3"]
    assert [clip.start for clip in created] == [0.5, 3.0, 8.0]
    assert [clip.out_point for clip in created] == [1.1, 2.2, 10.1]
    assert project.library_media == []
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 1
    assert audio_tracks[0].clips == created
    assert harness.audio_proxy_started == []
    assert [path.name for path in harness._media_ingest.enqueued] == ["1.mp3", "2.mp3", "10.mp3"]
    assert harness._media_ingest.enqueue_many_calls == 1


def test_add_voice_folder_falls_back_to_subtitle_duration_when_probe_fails(
    tmp_path: Path,
) -> None:
    _touch_mp3(tmp_path, "1.mp3")
    project = Project(
        tracks=[Track(kind="text", name="Subtitle", clips=[_text_clip(4.0, 2.5, "line")])]
    )
    harness = _VoiceImportHarness(project)

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert len(created) == 1
    assert created[0].start == 4.0
    assert created[0].out_point == 2.5
    assert id(created[0]) in harness._duration_placeholder_clip_ids


def test_add_voice_folder_overlapping_subtitles_auto_split_to_multiple_audio_tracks(
    tmp_path: Path,
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
    harness = _VoiceImportHarness(project, durations={"1.mp3": 2.0, "2.mp3": 2.0})

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
    harness = _VoiceImportHarness(project, durations={"1.mp3": 1.5})

    created = harness._add_voice_folder_to_timeline(tmp_path)

    assert len(created) == 1
    assert created[0].start == 2.0
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 2
    assert len(audio_tracks[0].clips) == 1
    assert len(audio_tracks[1].clips) == 1
    assert audio_tracks[0].clips[0].source == "existing.mp3"
    assert Path(audio_tracks[1].clips[0].source).name == "1.mp3"


def test_voice_placeholder_duration_update_moves_audio_that_would_overlap(
    tmp_path: Path,
) -> None:
    _touch_mp3(tmp_path, "1.mp3")
    _touch_mp3(tmp_path, "2.mp3")
    project = Project(
        tracks=[
            Track(
                kind="text",
                name="Subtitle",
                clips=[
                    _text_clip(0.0, 0.5, "first"),
                    _text_clip(0.75, 0.5, "second"),
                ],
            )
        ]
    )
    harness = _VoiceImportHarness(project)

    created = harness._add_voice_folder_to_timeline(tmp_path)

    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 1
    assert audio_tracks[0].clips == created

    created[0].out_point = 1.0
    moved_to = harness._move_audio_clip_to_non_overlapping_track(
        created[0],
        audio_tracks[0],
    )

    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    assert len(audio_tracks) == 2
    assert moved_to is audio_tracks[1]
    assert created[0] in audio_tracks[1].clips
    assert created[1] in audio_tracks[0].clips
    for track in audio_tracks:
        assert not any(
            a is not b
            and float(a.start) < float(b.start) + float(b.timeline_duration or 0.0)
            and float(a.start) + float(a.timeline_duration or 0.0) > float(b.start)
            for a in track.clips
            for b in track.clips
        )


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
