from __future__ import annotations

from pathlib import Path

from comecut_py.core.project import Clip, Project, Track
from comecut_py.engine.render import render_project_audio_only
from comecut_py.engine.timeline_audio_proxy import (
    timeline_audio_window_project,
    timeline_audio_window_proxy_path,
    timeline_audio_project,
    timeline_audio_proxy_path,
)


def test_timeline_audio_project_includes_video_track_audio() -> None:
    project = Project(sample_rate=48_000)
    video_track = Track(
        kind="video",
        volume=0.75,
        clips=[
            Clip(source="a.mp4", in_point=0.0, out_point=3.0, start=0.0, volume=0.8),
            Clip(source="b.mp4", in_point=0.0, out_point=3.0, start=3.0, volume=0.9),
        ],
    )
    project.tracks.append(video_track)

    audio_project = timeline_audio_project(project, has_audio=lambda _clip: True)

    assert len(audio_project.tracks) == 1
    assert audio_project.tracks[0].kind == "audio"
    assert audio_project.tracks[0].volume == 0.75
    assert [clip.source for clip in audio_project.tracks[0].clips] == ["a.mp4", "b.mp4"]
    assert audio_project.tracks[0].clips[0] is not video_track.clips[0]


def test_timeline_audio_project_ignores_hidden_muted_tracks() -> None:
    project = Project()
    project.tracks.append(
        Track(
            kind="video",
            hidden=True,
            clips=[Clip(source="hidden.mp4", in_point=0.0, out_point=1.0, start=0.0)],
        )
    )
    project.tracks.append(
        Track(
            kind="audio",
            muted=True,
            clips=[Clip(source="muted.wav", in_point=0.0, out_point=1.0, start=0.0)],
        )
    )

    audio_project = timeline_audio_project(project, has_audio=lambda _clip: True)

    assert audio_project.tracks == []


def test_timeline_audio_project_filters_clips_without_audio() -> None:
    project = Project()
    with_audio = Clip(source="with-audio.mp4", in_point=0.0, out_point=1.0, start=0.0)
    no_audio = Clip(source="silent.mp4", in_point=0.0, out_point=1.0, start=1.0)
    project.tracks.append(Track(kind="video", clips=[with_audio, no_audio]))

    audio_project = timeline_audio_project(
        project,
        has_audio=lambda clip: Path(clip.source).name == "with-audio.mp4",
    )

    assert [clip.source for clip in audio_project.tracks[0].clips] == ["with-audio.mp4"]


def test_rendered_timeline_audio_mix_has_adjacent_video_segments() -> None:
    project = Project()
    source = Track(
        kind="video",
        clips=[
            Clip(source="a.mp4", in_point=0.0, out_point=3.0, start=0.0),
            Clip(source="b.mp4", in_point=0.0, out_point=3.0, start=3.0),
        ],
    )
    project.tracks.append(source)
    audio_project = timeline_audio_project(project, has_audio=lambda _clip: True)

    argv = render_project_audio_only(audio_project, "mix.wav").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]

    assert "a.mp4" in argv
    assert "b.mp4" in argv
    assert "adelay=0|0" in fc
    assert "adelay=3000|3000" in fc
    assert "amix=inputs=2" in fc
    assert "normalize=0" in fc


def test_timeline_audio_proxy_path_changes_when_clip_timing_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "a.mp4"
    source.write_bytes(b"fake")
    project = Project(
        tracks=[
            Track(
                kind="video",
                clips=[Clip(source=str(source), in_point=0.0, out_point=3.0, start=0.0)],
            )
        ]
    )

    first = timeline_audio_proxy_path(project, has_audio=lambda _clip: True)
    project.tracks[0].clips[0].start = 1.0
    second = timeline_audio_proxy_path(project, has_audio=lambda _clip: True)

    assert first != second


def test_timeline_audio_window_project_clips_and_shifts_timing() -> None:
    project = Project()
    project.tracks.append(
        Track(
            kind="audio",
            volume=0.5,
            clips=[
                Clip(source="a.mp3", in_point=10.0, out_point=30.0, start=90.0),
                Clip(source="b.mp3", in_point=0.0, out_point=10.0, start=130.0),
            ],
        )
    )

    window = timeline_audio_window_project(
        project,
        start=100.0,
        duration=40.0,
        has_audio=lambda _clip: True,
    )

    assert len(window.tracks) == 1
    assert window.tracks[0].volume == 0.5
    clips = window.tracks[0].clips
    assert [clip.source for clip in clips] == ["a.mp3", "b.mp3"]
    assert clips[0].start == 0.0
    assert clips[0].in_point == 20.0
    assert clips[0].out_point == 30.0
    assert clips[1].start == 30.0
    assert clips[1].in_point == 0.0
    assert clips[1].out_point == 10.0


def test_timeline_audio_window_proxy_path_changes_when_clip_timing_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "a.mp3"
    source.write_bytes(b"fake")
    project = Project(
        tracks=[
            Track(
                kind="audio",
                clips=[Clip(source=str(source), in_point=0.0, out_point=30.0, start=90.0)],
            )
        ]
    )

    first = timeline_audio_window_proxy_path(
        project,
        start=100.0,
        duration=40.0,
        has_audio=lambda _clip: True,
    )
    project.tracks[0].clips[0].start = 91.0
    second = timeline_audio_window_proxy_path(
        project,
        start=100.0,
        duration=40.0,
        has_audio=lambda _clip: True,
    )

    assert first != second
