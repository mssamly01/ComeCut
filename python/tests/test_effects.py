"""Tests for per-clip speed, reverse and colour effects in the render pipeline."""

from __future__ import annotations

import pytest

from comecut_py.core.project import Clip, ClipEffects, Project, Track
from comecut_py.engine import render_project
from comecut_py.engine.render import _audio_effect_chain, _video_effect_chain


def test_video_effect_chain_empty_by_default():
    c = Clip(source="a.mp4", in_point=0, out_point=5)
    assert _video_effect_chain(c) == ""


def test_video_effect_chain_speed_only():
    c = Clip(source="a.mp4", in_point=0, out_point=5, speed=2.0)
    assert _video_effect_chain(c) == "setpts=PTS/2.0"


def test_video_effect_chain_reverse_and_blur():
    c = Clip(
        source="a.mp4",
        in_point=0,
        out_point=5,
        reverse=True,
        effects=ClipEffects(blur=4.0),
    )
    chain = _video_effect_chain(c)
    assert chain.startswith("reverse,")
    assert "gblur=sigma=4.0" in chain


def test_video_effect_chain_eq_emitted_only_when_touched():
    c_default = Clip(source="a.mp4", in_point=0, out_point=5, effects=ClipEffects())
    assert "eq=" not in _video_effect_chain(c_default)

    c_touched = Clip(
        source="a.mp4", in_point=0, out_point=5, effects=ClipEffects(brightness=0.2)
    )
    assert "eq=brightness=0.2:contrast=1.0:saturation=1.0" in _video_effect_chain(c_touched)


def test_video_effect_chain_grayscale_uses_hue():
    c = Clip(source="a.mp4", in_point=0, out_point=5, effects=ClipEffects(grayscale=True))
    assert "hue=s=0" in _video_effect_chain(c)


def test_audio_effect_chain_defaults_to_volume_only():
    c = Clip(source="a.mp3", in_point=0, out_point=5)
    assert _audio_effect_chain(c) == "volume=1.0"


def test_audio_effect_chain_reverse_and_double_speed():
    c = Clip(source="a.mp3", in_point=0, out_point=5, reverse=True, speed=2.0)
    chain = _audio_effect_chain(c)
    parts = chain.split(",")
    assert "volume=1.0" in parts
    assert "areverse" in parts
    assert "atempo=2.0" in parts


def test_audio_effect_chain_atempo_decomposition_for_extreme_speed():
    c = Clip(source="a.mp3", in_point=0, out_point=5, speed=4.0)
    chain = _audio_effect_chain(c)
    # atempo max is 2.0 → 4x must be two cascaded atempo=2.0 steps.
    assert chain.count("atempo=2.0") == 2

    c_slow = Clip(source="a.mp3", in_point=0, out_point=5, speed=0.25)
    chain_slow = _audio_effect_chain(c_slow)
    assert chain_slow.count("atempo=0.5") == 2


def test_render_includes_video_effects_on_simple_path():
    p = Project(width=320, height=180)
    v = Track(kind="video")
    v.clips.append(
        Clip(
            source="a.mp4",
            in_point=0,
            out_point=5,
            start=0,
            speed=2.0,
            effects=ClipEffects(blur=3.0, grayscale=True),
        )
    )
    p.tracks.append(v)
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "setpts=PTS/2.0" in fc
    assert "gblur=sigma=3.0" in fc
    assert "hue=s=0" in fc


def test_render_includes_effects_on_transition_chain():
    p = Project(width=320, height=180)
    v = Track(kind="video")
    v.clips.append(
        Clip(source="a.mp4", in_point=0, out_point=5, start=0, reverse=True)
    )
    v.clips.append(Clip(source="b.mp4", in_point=0, out_point=5, start=4))
    from comecut_py.core.project import Transition

    v.transitions.append(Transition(from_index=0, to_index=1, duration=1.0))
    p.tracks.append(v)
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    # reverse must appear *before* the scale/pad so it operates on the raw stream.
    assert "reverse," in fc
    idx_rev = fc.index("reverse,")
    idx_scale = fc.index("scale=320:180", idx_rev)
    assert idx_rev < idx_scale


def test_render_audio_speed_and_reverse_on_simple_path():
    p = Project()
    a = Track(kind="audio")
    a.clips.append(Clip(source="a.mp3", in_point=0, out_point=5, start=0, speed=2.0, reverse=True))
    p.tracks.append(a)
    argv = render_project(p, "out.mp4").build(ffmpeg_bin="ffmpeg")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "areverse" in fc
    assert "atempo=2.0" in fc


def test_effects_roundtrip_json(tmp_path):
    p = Project()
    v = Track(kind="video")
    v.clips.append(
        Clip(
            source="a.mp4",
            in_point=0,
            out_point=5,
            speed=1.5,
            reverse=True,
            effects=ClipEffects(brightness=0.1, contrast=1.2, saturation=0.8, blur=2.0),
        )
    )
    p.tracks.append(v)
    path = tmp_path / "p.json"
    p.to_json(path)
    loaded = Project.from_json(path)
    c = loaded.tracks[0].clips[0]
    assert c.speed == pytest.approx(1.5)
    assert c.reverse is True
    assert c.effects.brightness == pytest.approx(0.1)
    assert c.effects.contrast == pytest.approx(1.2)
    assert c.effects.saturation == pytest.approx(0.8)
    assert c.effects.blur == pytest.approx(2.0)


def test_clip_effects_validation_ranges():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClipEffects(brightness=2.0)  # > 1.0
    with pytest.raises(ValidationError):
        ClipEffects(contrast=-0.5)
    with pytest.raises(ValidationError):
        ClipEffects(blur=-1.0)
