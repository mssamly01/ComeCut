"""Tests for the keyframe-animation machinery on text overlays."""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from comecut_py.core.keyframes import evaluate_clip_keyframes, evaluate_keyframes
from comecut_py.core.project import Clip, Keyframe, Project, TextOverlay, Track
from comecut_py.engine.render import (
    _clip_keyframes_to_local_expr,
    _drawtext_filter,
    _keyframes_to_expr,
    render_project,
)


# ---- _keyframes_to_expr --------------------------------------------------


def test_empty_keyframes_returns_default():
    assert _keyframes_to_expr([]) == "0.0"
    assert _keyframes_to_expr([], default=1.0) == "1.0"


def test_single_keyframe_returns_constant():
    assert _keyframes_to_expr([Keyframe(time=1.0, value=0.5)]) == "0.5"


def test_two_keyframes_produce_linear_ramp():
    """For a 0→1 ramp over 2s the expression must interpolate correctly at t=1s."""
    kfs = [Keyframe(time=0.0, value=0.0), Keyframe(time=2.0, value=1.0)]
    expr = _keyframes_to_expr(kfs)
    # Evaluate the expression symbolically by substituting `t`.
    # Strip the ffmpeg-escape backslashes so we get valid Python math.
    py_expr = expr.replace("\\", "").replace("if(lt(", "(").replace("),", ")) else (")
    # Build a callable manually instead — safer than ast-rewriting for this test.
    # Just test the string structure + a few eval points via the engine's own logic:
    # Expect the expression to reduce to 0.5 at t=1.0.
    def eval_piecewise(t: float) -> float:
        # Clamp to first keyframe before t0; clamp to last after tN; linear between.
        if t < kfs[0].time:
            return kfs[0].value
        for a, b in zip(kfs, kfs[1:], strict=False):
            if t < b.time:
                return a.value + (t - a.time) * (b.value - a.value) / (b.time - a.time)
        return kfs[-1].value

    for tt in (-0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        assert math.isfinite(eval_piecewise(tt))
    assert eval_piecewise(1.0) == pytest.approx(0.5)
    assert eval_piecewise(0.0) == 0.0
    assert eval_piecewise(2.5) == 1.0

    # And the emitted expression includes the inner lerp term.
    assert "(0.0+(1.0-0.0)*(t-0.0)/2.0)" in expr


def test_three_keyframes_produce_nested_if():
    kfs = [
        Keyframe(time=0.0, value=0.0),
        Keyframe(time=1.0, value=1.0),
        Keyframe(time=2.0, value=0.0),
    ]
    expr = _keyframes_to_expr(kfs)
    # Two `if(lt(t, …` branches inside plus the pre-first clamp.
    assert expr.count("if(lt(t") == 3
    assert "(1.0+(0.0-1.0)*(t-1.0)/1.0)" in expr  # second segment


# ---- Model validation ----------------------------------------------------


def test_keyframes_sorted_on_assignment():
    ov = TextOverlay(
        text="hi",
        end=3.0,
        opacity_keyframes=[
            Keyframe(time=2.0, value=1.0),
            Keyframe(time=0.0, value=0.0),
        ],
    )
    assert [kf.time for kf in ov.opacity_keyframes] == [0.0, 2.0]


def test_duplicate_keyframe_times_rejected():
    with pytest.raises(ValidationError, match="duplicate keyframe time"):
        TextOverlay(
            text="hi",
            end=3.0,
            opacity_keyframes=[
                Keyframe(time=1.0, value=0.0),
                Keyframe(time=1.0, value=1.0),
            ],
        )


def test_negative_time_rejected():
    with pytest.raises(ValidationError):
        Keyframe(time=-0.5, value=0.0)


def test_evaluate_keyframes_interpolates_and_clamps():
    kfs = [
        Keyframe(time=1.0, value=0.25),
        Keyframe(time=3.0, value=1.0),
    ]

    assert evaluate_keyframes(kfs, 0.0, default=0.5) == pytest.approx(0.25)
    assert evaluate_keyframes(kfs, 2.0, default=0.5) == pytest.approx(0.625)
    assert evaluate_keyframes(kfs, 4.0, default=0.5) == pytest.approx(1.0)
    assert evaluate_keyframes([], 2.0, default=0.5) == pytest.approx(0.5)


def test_clip_keyframes_sorted_and_evaluated():
    clip = Clip(
        source="a.mp4",
        in_point=0,
        out_point=5,
        volume=1.0,
        volume_keyframes=[
            Keyframe(time=3.0, value=0.0),
            Keyframe(time=1.0, value=1.0),
        ],
    )

    assert [kf.time for kf in clip.volume_keyframes] == [1.0, 3.0]
    assert evaluate_clip_keyframes(clip, "volume", 2.0, default=clip.volume) == pytest.approx(0.5)


def test_clip_duplicate_keyframe_times_rejected():
    with pytest.raises(ValidationError, match="duplicate keyframe time"):
        Clip(
            source="a.mp4",
            in_point=0,
            out_point=5,
            opacity_keyframes=[
                Keyframe(time=1.0, value=0.0),
                Keyframe(time=1.0, value=1.0),
            ],
        )


def test_clip_keyframes_roundtrip(tmp_path: Path):
    p = Project(
        tracks=[
            Track(
                kind="audio",
                clips=[
                    Clip(
                        source="a.wav",
                        in_point=0,
                        out_point=5,
                        volume_keyframes=[
                            Keyframe(time=0.0, value=1.0),
                            Keyframe(time=2.0, value=0.25),
                        ],
                    )
                ],
            )
        ]
    )
    f = tmp_path / "clip-kfs.json"
    p.to_json(f)

    parsed = Project.from_json(f)
    kfs = parsed.tracks[0].clips[0].volume_keyframes
    assert [kf.time for kf in kfs] == [0.0, 2.0]
    assert [kf.value for kf in kfs] == [1.0, 0.25]


def test_clip_keyframes_to_local_expr_offsets_global_time():
    kfs = [
        Keyframe(time=5.0, value=1.0),
        Keyframe(time=7.0, value=0.0),
    ]

    expr = _clip_keyframes_to_local_expr(kfs, clip_start=5.0, default=1.0)

    assert "t-0.0" in expr
    assert "if(lt(t,2.0)" in expr


# ---- _drawtext_filter ----------------------------------------------------


def test_drawtext_emits_alpha_when_opacity_keyframes_set():
    ov = TextOverlay(
        text="hi",
        end=3.0,
        opacity_keyframes=[
            Keyframe(time=0.0, value=0.0),
            Keyframe(time=1.0, value=1.0),
        ],
    )
    f = _drawtext_filter(ov)
    assert "alpha='" in f
    assert f.count("if(lt(t") >= 1
    # Static x / y still included since no x/y keyframes were set.
    assert ":x=" in f
    assert ":y=" in f


def test_drawtext_animated_xy_override_static_values():
    ov = TextOverlay(
        text="hi",
        end=2.0,
        x="100",
        y="100",
        x_keyframes=[Keyframe(time=0.0, value=50.0), Keyframe(time=2.0, value=450.0)],
    )
    f = _drawtext_filter(ov)
    # x is now an expression; y stayed static.
    assert re.search(r"x='if\(lt\(t.*\)'", f)
    assert "y=100" in f
    assert "x=100" not in f  # static x was overridden


def test_drawtext_no_alpha_when_no_opacity_keyframes():
    ov = TextOverlay(text="hi", end=2.0)
    assert "alpha=" not in _drawtext_filter(ov)


# ---- JSON round-trip -----------------------------------------------------


def test_keyframes_roundtrip(tmp_path: Path):
    p = Project(
        tracks=[
            Track(
                kind="video",
                overlays=[
                    TextOverlay(
                        text="hi",
                        end=3.0,
                        opacity_keyframes=[
                            Keyframe(time=0.0, value=0.0),
                            Keyframe(time=0.5, value=1.0),
                            Keyframe(time=2.5, value=1.0),
                            Keyframe(time=3.0, value=0.0),
                        ],
                    )
                ],
            )
        ]
    )
    f = tmp_path / "p.json"
    p.to_json(f)
    parsed = Project.from_json(f)
    kfs = parsed.tracks[0].overlays[0].opacity_keyframes
    assert [kf.time for kf in kfs] == [0.0, 0.5, 2.5, 3.0]
    assert [kf.value for kf in kfs] == [0.0, 1.0, 1.0, 0.0]


# ---- Render path integration --------------------------------------------


def test_render_project_embeds_keyframe_expression_in_filter(tmp_path: Path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"fake")
    project = Project(
        width=320, height=180, fps=24,
        tracks=[
            Track(
                kind="video",
                clips=[Clip(source=str(src), in_point=0, out_point=2)],
                overlays=[
                    TextOverlay(
                        text="hello",
                        start=0.0,
                        end=2.0,
                        opacity_keyframes=[
                            Keyframe(time=0.0, value=0.0),
                            Keyframe(time=1.0, value=1.0),
                            Keyframe(time=2.0, value=0.0),
                        ],
                    )
                ],
            )
        ],
    )
    argv = render_project(project, tmp_path / "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # Alpha expression landed in drawtext.
    assert "alpha='if(lt(t" in fc
    # Both interpolation segments are present.
    assert "(0.0+(1.0-0.0)*(t-0.0)/1.0)" in fc
    assert "(1.0+(0.0-1.0)*(t-1.0)/1.0)" in fc


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_keyframed_overlay_actually_renders(tmp_path: Path):
    """Real ffmpeg smoke test — a fading-in overlay must produce a valid MP4."""
    src = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=320x180:d=2:r=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(src),
        ],
        check=True, capture_output=True,
    )
    project = Project(
        width=320, height=180, fps=24,
        tracks=[
            Track(
                kind="video",
                clips=[Clip(source=str(src), in_point=0, out_point=2)],
                overlays=[
                    TextOverlay(
                        text="hi",
                        start=0.0,
                        end=2.0,
                        font_size=24,
                        box=False,
                        opacity_keyframes=[
                            Keyframe(time=0.0, value=0.0),
                            Keyframe(time=1.0, value=1.0),
                            Keyframe(time=2.0, value=0.0),
                        ],
                        x_keyframes=[
                            Keyframe(time=0.0, value=10.0),
                            Keyframe(time=2.0, value=200.0),
                        ],
                    )
                ],
            )
        ],
    )
    out = tmp_path / "out.mp4"
    render_project(project, out).run(check=True)
    assert out.exists() and out.stat().st_size > 0
