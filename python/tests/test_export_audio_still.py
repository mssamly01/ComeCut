from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, Project, Track, Transition
from comecut_py.engine.render import render_project_audio_only, render_project_still_frame


def _audio_clip(source: str, start: float = 0.0, duration: float = 3.0) -> Clip:
    return Clip(source=source, in_point=0.0, out_point=duration, start=start)


def _output_arg_pair(argv: list[str], flag: str) -> list[str]:
    start = argv.index("-map")
    for idx in range(start, len(argv) - 1):
        if argv[idx] == flag:
            return argv[idx : idx + 2]
    raise AssertionError(f"{flag!r} not found after output map")


def test_render_project_audio_only_builds_limited_mix():
    project = Project(sample_rate=44_100)
    voice = Track(kind="audio", name="Voice", volume=0.5, clips=[_audio_clip("voice.wav")])
    music = Track(
        kind="audio",
        name="Music",
        clips=[_audio_clip("music.wav", start=1.25, duration=4.0)],
    )
    project.tracks.extend([voice, music])

    argv = render_project_audio_only(project, "mix.mp3", audio_format="mp3").build(
        ffmpeg_bin="ffmpeg"
    )
    fc = argv[argv.index("-filter_complex") + 1]

    assert "-vn" in argv
    assert ["-c:a", "libmp3lame"] == argv[argv.index("-c:a") : argv.index("-c:a") + 2]
    assert ["-ar", "44100"] == argv[argv.index("-ar") : argv.index("-ar") + 2]
    assert "volume=0.5" in fc
    assert "adelay=1250|1250" in fc
    assert "amix=inputs=2" in fc
    assert "alimiter=limit=0.95[amaster]" in fc
    assert argv[argv.index("-map") + 1] == "[amaster]"


def test_render_project_audio_only_supports_audio_transitions():
    project = Project()
    track = Track(
        kind="audio",
        clips=[
            _audio_clip("a.wav", start=0.0, duration=3.0),
            _audio_clip("b.wav", start=2.5, duration=3.0),
        ],
        transitions=[Transition(from_index=0, to_index=1, duration=0.5)],
    )
    project.tracks.append(track)

    argv = render_project_audio_only(project, "mix.wav").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]

    assert "acrossfade=d=0.5" in fc
    assert "-c:a" in argv
    assert argv[argv.index("-c:a") + 1] == "pcm_s16le"


def test_render_project_audio_only_rejects_empty_or_muted_audio():
    project = Project(tracks=[Track(kind="audio", muted=True, clips=[_audio_clip("a.wav")])])

    with pytest.raises(ValueError, match="audible audio"):
        render_project_audio_only(project, "mix.m4a")


def test_render_project_still_frame_uses_video_only_single_frame_export():
    project = Project(width=640, height=360, fps=25.0)
    project.tracks.append(
        Track(kind="video", clips=[Clip(source="video.mp4", in_point=0.0, out_point=5.0, start=0.0)])
    )
    project.tracks.append(Track(kind="audio", clips=[_audio_clip("audio.wav")]))

    argv = render_project_still_frame(project, "frame.png", at_seconds=2.0).build(
        ffmpeg_bin="ffmpeg"
    )
    fc = argv[argv.index("-filter_complex") + 1]

    assert argv.count("-map") == 1
    assert "-an" in argv
    assert ["-c:v", "png"] == argv[argv.index("-c:v") : argv.index("-c:v") + 2]
    assert ["-frames:v", "1"] == argv[argv.index("-frames:v") : argv.index("-frames:v") + 2]
    assert ["-ss", "2.0"] == _output_arg_pair(argv, "-ss")
    assert "audio.wav" not in argv
    assert "a0" not in fc


def test_render_project_still_frame_clamps_to_project_duration():
    project = Project(width=320, height=180, fps=10.0)
    project.tracks.append(
        Track(kind="video", clips=[Clip(source="video.mp4", in_point=0.0, out_point=1.0, start=0.0)])
    )

    argv = render_project_still_frame(project, "frame.jpg", at_seconds=99.0).build(
        ffmpeg_bin="ffmpeg"
    )

    assert ["-c:v", "mjpeg"] == argv[argv.index("-c:v") : argv.index("-c:v") + 2]
    assert ["-q:v", "2"] == argv[argv.index("-q:v") : argv.index("-q:v") + 2]
    assert ["-ss", "0.9"] == _output_arg_pair(argv, "-ss")
