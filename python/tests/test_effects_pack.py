"""Tests for PR B effect pack:

crop / rotate / flip / chromakey / picture-in-picture (``Clip.scale`` +
``pos_x`` / ``pos_y``) / watermark image overlay / stabilize / freeze-frame /
zoompan Ken Burns.

These are pure filter-graph tests — they assert the constructed ffmpeg argv
contains the expected fragments without actually invoking the binary.
"""

from __future__ import annotations

import pytest

from comecut_py.core.project import (
    ChromaKey,
    Clip,
    ClipEffects,
    CropRect,
    ImageOverlay,
    Project,
    Track,
)
from comecut_py.engine import render_project
from comecut_py.engine.freeze_frame import freeze_frame
from comecut_py.engine.render import _video_effect_chain
from comecut_py.engine.zoompan import zoompan_image

# ---- ClipEffects defaults ------------------------------------------------


def test_new_effects_default_to_noops():
    fx = ClipEffects()
    assert fx.crop is None
    assert fx.rotate == 0.0
    assert fx.hflip is False
    assert fx.vflip is False
    assert fx.chromakey is None


def test_default_effects_chain_is_empty():
    c = Clip(source="a.mp4", in_point=0, out_point=5)
    assert _video_effect_chain(c) == ""


# ---- crop / rotate / flip / chromakey fragments --------------------------


def test_crop_rect_validates_positive_dims():
    with pytest.raises(ValueError):
        CropRect(x=0, y=0, width=0, height=100)
    with pytest.raises(ValueError):
        CropRect(x=-1, y=0, width=10, height=10)


def test_chain_emits_crop_before_color():
    c = Clip(
        source="a.mp4",
        in_point=0,
        out_point=5,
        effects=ClipEffects(
            crop=CropRect(x=10, y=20, width=320, height=240),
            brightness=0.2,
        ),
    )
    chain = _video_effect_chain(c)
    assert "crop=320:240:10:20" in chain
    assert chain.index("crop=") < chain.index("eq=")


def test_chain_emits_hflip_vflip():
    c = Clip(
        source="a.mp4",
        in_point=0,
        out_point=5,
        effects=ClipEffects(hflip=True, vflip=True),
    )
    chain = _video_effect_chain(c)
    parts = chain.split(",")
    assert "hflip" in parts
    assert "vflip" in parts


def test_chain_emits_rotate_radians():
    c = Clip(
        source="a.mp4",
        in_point=0,
        out_point=5,
        effects=ClipEffects(rotate=45.0),
    )
    chain = _video_effect_chain(c)
    assert "rotate=PI*45.0/180" in chain
    # rotate must auto-grow the canvas so corners aren't clipped.
    assert "ow=rotw" in chain and "oh=roth" in chain


def test_chain_emits_chromakey():
    c = Clip(
        source="a.mp4",
        in_point=0,
        out_point=5,
        effects=ClipEffects(
            chromakey=ChromaKey(color="0x00FF00", similarity=0.2, blend=0.05)
        ),
    )
    chain = _video_effect_chain(c)
    assert "chromakey=color=0x00FF00:similarity=0.2:blend=0.05" in chain


# ---- Picture-in-picture via Clip.scale / pos_x / pos_y -------------------


def test_pip_clip_uses_scale_and_explicit_overlay_position():
    p = Project(width=1920, height=1080)
    base = Track(kind="video")
    base.clips.append(Clip(source="bg.mp4", in_point=0, out_point=5, start=0))
    pip = Track(kind="video")
    pip.clips.append(
        Clip(
            source="insert.mp4",
            in_point=0,
            out_point=5,
            start=0,
            scale=0.25,
            pos_x=40,
            pos_y=40,
        )
    )
    p.tracks.extend([base, pip])
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # PiP clip scales to 25 % of the project width (1920 * 0.25 = 480) and is
    # placed at (40, 40) — the base track keeps the legacy full-canvas path.
    assert "scale=480:-2" in fc
    assert "overlay=x=40:y=40" in fc


def test_pip_clip_without_pos_centers_by_default():
    p = Project(width=1280, height=720)
    base = Track(kind="video")
    base.clips.append(Clip(source="bg.mp4", in_point=0, out_point=5, start=0))
    pip = Track(kind="video")
    pip.clips.append(
        Clip(source="insert.mp4", in_point=0, out_point=5, start=0, scale=0.5)
    )
    p.tracks.extend([base, pip])
    fc = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")[
        render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg").index("-filter_complex") + 1
    ]
    assert "overlay=x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2" in fc


# ---- Image overlay / watermark ------------------------------------------


def test_image_overlay_builds_loop_scale_alpha_chain(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)  # placeholder

    p = Project(width=1280, height=720)
    v = Track(kind="video")
    v.clips.append(Clip(source="bg.mp4", in_point=0, out_point=10, start=0))
    v.image_overlays.append(
        ImageOverlay(source=str(logo), start=1.0, end=5.0, x=20, y=30, scale=0.5, opacity=0.7)
    )
    p.tracks.append(v)
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "loop=loop=-1:size=1:start=0" in fc
    assert "scale=iw*0.5:-2" in fc
    assert "colorchannelmixer=aa=0.7" in fc
    # Overlay stream is trimmed to its end time so it never outlives the
    # project timeline — critical when ``loop=-1`` would otherwise keep
    # emitting frames forever.
    assert "trim=duration=5.0" in fc
    assert "overlay=x=20:y=30:enable='between(t,1.0,5.0)'" in fc
    # Image is registered as a distinct ffmpeg input.
    assert str(logo) in argv


def test_image_overlay_extends_project_duration():
    p = Project()
    v = Track(kind="video")
    v.clips.append(Clip(source="bg.mp4", in_point=0, out_point=3, start=0))
    v.image_overlays.append(
        ImageOverlay(source="logo.png", start=0.0, end=7.5)
    )
    p.tracks.append(v)
    assert p.duration == pytest.approx(7.5)


# ---- Standalone engine commands -----------------------------------------


def test_freeze_frame_builds_concat_filter():
    # Pass explicit probe values so the test doesn't shell out to ffprobe.
    cmd = freeze_frame(
        "in.mp4", "out.mp4", at=2.0, hold=1.5,
        has_audio=True, sample_rate=48000, channels=2,
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # A + B + C segments + concat n=3.
    assert "trim=start=0:end=2.0" in fc
    assert "trim=duration=1.5" in fc
    assert "concat=n=3:v=1:a=1" in fc


def test_freeze_frame_audio_uses_probed_sample_rate_and_layout():
    cmd = freeze_frame(
        "in.mp4", "out.mp4", at=1.0, hold=0.5,
        has_audio=True, sample_rate=44100, channels=1,
    )
    fc = cmd.build(ffmpeg_bin="ffmpeg")[cmd.build(ffmpeg_bin="ffmpeg").index("-filter_complex") + 1]
    # anullsrc must inherit the probed params, not hardcoded 48 kHz stereo.
    assert "anullsrc=channel_layout=mono:sample_rate=44100" in fc
    # Every audio segment is normalised via ``aformat`` so concat sees
    # matching streams.
    assert fc.count("aformat=sample_rates=44100:channel_layouts=mono") >= 3


def test_freeze_frame_video_only_source_skips_audio_graph():
    cmd = freeze_frame(
        "screencast.mp4", "out.mp4", at=1.0, hold=0.5, has_audio=False,
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # No ``[0:a]``, no ``anullsrc``, no ``aformat`` — only video segments
    # and a video-only concat.
    assert "[0:a]" not in fc
    assert "anullsrc" not in fc
    assert "aformat" not in fc
    assert "concat=n=3:v=1:a=0" in fc
    # Map list contains only the video output.
    map_args = [argv[i + 1] for i, a in enumerate(argv) if a == "-map"]
    assert map_args == ["[vo]"]


def test_freeze_frame_rejects_non_positive_values():
    with pytest.raises(ValueError):
        freeze_frame("in.mp4", "out.mp4", at=0, hold=1.0, has_audio=True)
    with pytest.raises(ValueError):
        freeze_frame("in.mp4", "out.mp4", at=1, hold=-1.0, has_audio=True)


def test_zoompan_image_builds_linear_interpolation():
    cmd = zoompan_image(
        "pic.jpg", "out.mp4", duration=2.0,
        start_zoom=1.0, end_zoom=1.5, width=640, height=360, fps=30,
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # nframes = round(2.0 * 30) = 60 → interpolation over 59 intervals.
    assert "1.0+(1.5-1.0)*on/59" in fc
    assert "s=640x360" in fc
    assert "fps=30" in fc
    # Output duration is clipped by the output-side -t so -loop 1 on the
    # still image doesn't produce an endless stream.
    assert "-t" in argv and argv[argv.index("-t") + 1] == "2.0"


def test_zoompan_image_single_frame_static_zoom():
    cmd = zoompan_image(
        "pic.jpg", "out.mp4", duration=0.01,
        start_zoom=1.2, end_zoom=1.5, fps=30,
    )
    argv = cmd.build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # round(0.01*30) = 0 → nframes clamped to 1 → static start_zoom expr.
    assert "z='1.2'" in fc
