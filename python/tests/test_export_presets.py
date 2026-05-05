"""Unit tests for the export-preset pack (PR D).

Covers:
* :data:`PRESETS` — the built-in named presets and the shape of their
  :class:`ExportPreset` records.
* ``render_project(preset=...)`` — codec/bitrate/resolution swapping and
  the scale+pad stage appended to the filter graph.
* ``render_project(export_range=...)`` — ``-ss``/``-to`` injection and
  validation.
* ``render_project_twopass(...)`` — two commands, one with ``-pass 1 -f
  null``, one with ``-pass 2`` writing the real output, sharing a
  ``-passlogfile`` prefix.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from comecut_py.core.project import Clip, Project, Track
from comecut_py.engine import (
    PRESETS,
    ExportPreset,
    preset_output_args,
    render_project,
    render_project_twopass,
)


def _single_clip_project() -> Project:
    p = Project(width=1920, height=1080, fps=30)
    p.tracks.append(
        Track(kind="video", clips=[
            Clip(source="in.mp4", in_point=0, out_point=5),
        ])
    )
    p.tracks.append(
        Track(kind="audio", clips=[
            Clip(source="in.mp4", in_point=0, out_point=5),
        ])
    )
    return p


# ---- PRESETS registry -------------------------------------------------------


def test_preset_registry_covers_requested_targets():
    # The 7 presets the feature brief enumerated must all be present.
    for name in ["youtube-1080p", "youtube-4k", "reels", "tiktok",
                 "twitter", "gif", "webm"]:
        assert name in PRESETS, name
        assert isinstance(PRESETS[name], ExportPreset)


def test_reels_and_tiktok_are_vertical_9_16():
    for name in ["reels", "tiktok"]:
        p = PRESETS[name]
        assert p.width == 1080
        assert p.height == 1920
        # 9:16 — verify the aspect ratio explicitly, not just the
        # dimensions.
        assert p.width / p.height == pytest.approx(9 / 16, rel=1e-3)


def test_youtube_4k_is_3840x2160():
    p = PRESETS["youtube-4k"]
    assert p.width == 3840
    assert p.height == 2160


def test_gif_preset_has_no_audio():
    p = PRESETS["gif"]
    assert p.vcodec == "gif"
    assert p.acodec is None
    assert p.container == "gif"


def test_webm_uses_vp9_and_opus():
    p = PRESETS["webm"]
    assert p.vcodec == "libvpx-vp9"
    assert p.acodec == "libopus"
    assert p.container == "webm"


# ---- preset_output_args -----------------------------------------------------


def test_preset_output_args_crf_only():
    args = preset_output_args(PRESETS["youtube-1080p"])
    assert "-c:v" in args
    assert "libx264" in args
    assert "-crf" in args
    # YouTube 1080p preset uses CRF 18 (not the default 20).
    crf_idx = args.index("-crf")
    assert args[crf_idx + 1] == "18"
    assert "-b:v" not in args  # CRF-only by default
    assert "-c:a" in args
    assert "aac" in args


def test_preset_output_args_gif_strips_audio():
    args = preset_output_args(PRESETS["gif"])
    assert "-an" in args
    # GIF has no audio codec at all.
    assert "-c:a" not in args


def test_preset_output_args_two_pass_requires_bitrate():
    preset = replace(PRESETS["youtube-1080p"], video_bitrate="8M")
    pass1 = preset_output_args(preset, pass_number=1, pass_log_prefix="/tmp/foo")
    assert "-pass" in pass1 and pass1[pass1.index("-pass") + 1] == "1"
    assert "-b:v" in pass1 and pass1[pass1.index("-b:v") + 1] == "8M"
    assert "-passlogfile" in pass1
    # CRF is dropped in bitrate-targeted pass-1 because it would be
    # ignored anyway and ffmpeg warns about mutually-exclusive options.
    assert "-crf" not in pass1


# ---- render_project(preset=...) --------------------------------------------


def test_render_project_default_keeps_old_behaviour():
    argv = render_project(_single_clip_project(), "out.mp4").build(ffmpeg_bin="ffmpeg")
    # No preset → original libx264 CRF 20 AAC faststart output.
    assert "libx264" in argv
    assert "-crf" in argv and argv[argv.index("-crf") + 1] == "20"
    assert "+faststart" in argv


def test_render_project_with_preset_uses_preset_codec():
    argv = render_project(
        _single_clip_project(), "out.webm", preset="webm",
    ).build(ffmpeg_bin="ffmpeg")
    assert "libvpx-vp9" in argv
    assert "libopus" in argv


def test_render_project_with_preset_adds_scale_pad_when_sizes_differ():
    # Project is 1920x1080 but we render to reels 1080x1920. The graph
    # must scale the composition down and pad it to 1080x1920.
    argv = render_project(
        _single_clip_project(), "out.mp4", preset="reels",
    ).build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=decrease" in fc
    assert "pad=1080:1920" in fc


def test_render_project_with_gif_preset_drops_audio_map():
    argv = render_project(
        _single_clip_project(), "out.gif", preset="gif",
    ).build(ffmpeg_bin="ffmpeg")
    # No ``-map [aout]`` / ``-map [a*]`` — audio is stripped entirely so
    # the gif muxer doesn't complain.
    map_indices = [i for i, a in enumerate(argv) if a == "-map"]
    map_values = [argv[i + 1] for i in map_indices]
    for m in map_values:
        # Audio labels in our render are ``[aout]``, ``[a0]``, ``[a1]``,
        # ``[a_v0_...]``, etc. None of those should appear.
        assert "aout" not in m
        assert not m.startswith("[a")


def test_render_project_with_unknown_preset_raises():
    with pytest.raises(ValueError, match="Unknown preset"):
        render_project(_single_clip_project(), "out.mp4", preset="not-a-preset")


# ---- export_range -----------------------------------------------------------


def test_render_project_with_export_range_emits_ss_to():
    argv = render_project(
        _single_clip_project(), "out.mp4", export_range=(1.5, 4.0),
    ).build(ffmpeg_bin="ffmpeg")
    # ``-ss`` and ``-to`` must appear after all the inputs and before
    # the output path. We assert their presence and ordering.
    assert "-ss" in argv
    assert "-to" in argv
    # Both should appear in the OUTPUT options, not the input options,
    # so they come after ``-filter_complex``.
    fc_idx = argv.index("-filter_complex")
    for flag, val in [("-ss", "1.5"), ("-to", "4.0")]:
        idxs = [i for i, a in enumerate(argv) if a == flag]
        # The last -ss and -to should be after -filter_complex.
        assert any(i > fc_idx for i in idxs)
        # And their value should match.
        last = max(i for i in idxs if i > fc_idx)
        assert argv[last + 1] == val


def test_render_project_with_invalid_export_range_raises():
    with pytest.raises(ValueError, match="export_range end"):
        render_project(
            _single_clip_project(), "out.mp4", export_range=(4.0, 1.5),
        )


# ---- two-pass ---------------------------------------------------------------


def test_render_project_twopass_emits_two_commands():
    preset = replace(PRESETS["youtube-1080p"], video_bitrate="8M")
    pass1, pass2 = render_project_twopass(
        _single_clip_project(), "out.mp4",
        preset=preset,
        pass_log_prefix="/tmp/twopass",
    )
    a1 = pass1.build(ffmpeg_bin="ffmpeg")
    a2 = pass2.build(ffmpeg_bin="ffmpeg")

    # Pass 1: -pass 1 and -f null, writes to /dev/null.
    assert "-pass" in a1 and a1[a1.index("-pass") + 1] == "1"
    assert "-f" in a1 and a1[a1.index("-f") + 1] == "null"
    assert a1[-1] == "/dev/null"

    # Pass 2: -pass 2, writes to out.mp4.
    assert "-pass" in a2 and a2[a2.index("-pass") + 1] == "2"
    assert a2[-1] == "out.mp4"

    # Both share the same -passlogfile so the stats file generated in
    # pass 1 is read in pass 2.
    log1 = a1[a1.index("-passlogfile") + 1]
    log2 = a2[a2.index("-passlogfile") + 1]
    assert log1 == log2 == "/tmp/twopass"


def test_render_project_twopass_rejects_crf_only_preset():
    with pytest.raises(ValueError, match="video_bitrate"):
        render_project_twopass(
            _single_clip_project(), "out.mp4",
            preset="youtube-1080p",  # CRF-only in the default registry
        )
