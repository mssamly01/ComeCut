"""Unit tests for command builders — no actual ffmpeg invocation."""

from __future__ import annotations

from comecut_py.core.ffmpeg_cmd import FFmpegCommand, format_argv, shell_quote
from comecut_py.core.project import Clip, Project, TextOverlay, Track
from comecut_py.engine import (
    adjust_volume,
    burn_subtitles,
    concat,
    cut,
    extract_audio,
    overlay_text,
    render_project,
    trim,
)


def test_builder_smoke():
    cmd = (
        FFmpegCommand()
        .add_input("a.mp4")
        .set_filter_complex("[0:v]scale=1280:720[v]")
        .map("[v]")
        .map("0:a?")
        .out("out.mp4", "-c:v", "libx264")
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    assert "a.mp4" in argv
    assert "out.mp4" in argv
    assert argv[argv.index("-filter_complex") + 1] == "[0:v]scale=1280:720[v]"


def test_builder_requires_output():
    import pytest

    with pytest.raises(ValueError):
        FFmpegCommand().add_input("a.mp4").build(ffmpeg_bin="ffmpeg")


def test_cut_reencode_sets_crf():
    argv = cut("in.mp4", "out.mp4", start="00:00:05", end="00:00:10").build(ffmpeg_bin="ffmpeg")
    assert "-crf" in argv
    assert "-ss" in argv
    # duration must be 5s
    idx = argv.index("-t")
    assert argv[idx + 1] == "00:00:05.000"


def test_cut_copy_mode_no_crf():
    argv = cut("in.mp4", "out.mp4", start=1, end=2, copy=True).build(ffmpeg_bin="ffmpeg")
    assert "-crf" not in argv
    assert "-c" in argv and "copy" in argv


def test_cut_rejects_bad_range():
    import pytest

    with pytest.raises(ValueError):
        cut("a.mp4", "b.mp4", start=10, end=5)


def test_concat_filter_complex():
    argv = concat(["a.mp4", "b.mp4", "c.mp4"], "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "concat=n=3:v=1:a=1" in fc
    assert argv.count("-i") == 3


def test_concat_requires_two():
    import pytest

    with pytest.raises(ValueError):
        concat(["a.mp4"], "out.mp4")


def test_trim_head_only():
    argv = trim("a.mp4", "b.mp4", head="00:00:02").build(ffmpeg_bin="ffmpeg")
    assert "-ss" in argv


def test_trim_tail_requires_duration():
    import pytest

    with pytest.raises(ValueError):
        trim("a.mp4", "b.mp4", tail=1.0)


def test_trim_tail_with_duration():
    argv = trim("a.mp4", "b.mp4", head=1, tail=1, duration=10).build(ffmpeg_bin="ffmpeg")
    assert argv[argv.index("-to") + 1] == "00:00:09.000"


def test_overlay_text_escapes():
    argv = overlay_text("a.mp4", "b.mp4", "Hello: 'world'").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # Colons must be escaped inside the drawtext filter; apostrophes double-escaped.
    assert r"\:" in fc
    assert r"\'" in fc


def test_burn_subtitles_filter():
    argv = burn_subtitles("a.mp4", "subs.srt", "b.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "subtitles=" in fc
    assert "subs.srt" in fc


def test_extract_audio():
    argv = extract_audio("a.mp4", "a.mp3").build(ffmpeg_bin="ffmpeg")
    assert "-vn" in argv
    assert "-c:a" in argv


def test_adjust_volume_rejects_negative():
    import pytest

    with pytest.raises(ValueError):
        adjust_volume("a.mp4", "b.mp4", -0.5)


def test_adjust_volume_filter():
    argv = adjust_volume("a.mp4", "b.mp4", 0.5).build(ffmpeg_bin="ffmpeg")
    idx = argv.index("-filter:a")
    assert argv[idx + 1] == "volume=0.5"


def test_render_project_builds():
    p = Project(width=640, height=360, fps=24)
    v = Track(kind="video")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=3, start=0))
    v.clips.append(Clip(source="b.mp4", in_point=0, out_point=3, start=3))
    v.overlays.append(TextOverlay(text="hi", start=0, end=6))
    p.tracks.append(v)
    a = Track(kind="audio")
    a.clips.append(Clip(source="music.mp3", in_point=0, out_point=6, start=0, volume=0.5))
    p.tracks.append(a)

    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    assert argv.count("-i") == 3
    fc = argv[argv.index("-filter_complex") + 1]
    # Should have a base canvas, two overlays, drawtext, and the audio-track delay.
    assert "color=c=black" in fc
    assert "overlay" in fc
    assert "drawtext" in fc
    assert "adelay" in fc
    # video + audio maps.
    assert argv.count("-map") == 2


def test_render_project_rejects_empty():
    import pytest

    p = Project()
    with pytest.raises(ValueError):
        render_project(p, "out.mp4")


def test_render_project_renders_text_track_clips():
    p = Project(width=640, height=360, fps=24)
    v = Track(kind="video", name="Main")
    v.clips.append(Clip(source="a.mp4", in_point=0, out_point=4, start=0))
    p.tracks.append(v)
    t = Track(kind="text", name="Text 1")
    t.clips.append(
        Clip(
            clip_type="text",
            source="subs.srt",
            in_point=0,
            out_point=2,
            start=0.5,
            text_main="Hello",
            text_second="Xin chao",
            text_display="bilingual",
        )
    )
    p.tracks.append(t)

    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # Text track should burn drawtext layers without adding subtitle files as ffmpeg inputs.
    assert argv.count("-i") == 1
    assert fc.count("drawtext=") >= 2
    assert "Hello" in fc


def test_shell_quote_and_format_argv():
    assert shell_quote("plain") == "plain"
    assert shell_quote("has space") == "'has space'"
    assert shell_quote("it's") == "'it'\\''s'"
    assert format_argv(["ffmpeg", "-i", "a.mp4"]) == "ffmpeg -i a.mp4"
