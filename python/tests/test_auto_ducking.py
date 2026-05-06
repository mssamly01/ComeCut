from __future__ import annotations

import pytest

from comecut_py.core.auto_ducking import (
    AutoDuckingConfig,
    apply_auto_ducking_to_tracks,
    build_ducking_keyframes_for_clip,
    collect_role_intervals,
    merge_ducking_intervals,
)
from comecut_py.core.project import Clip, Keyframe, Track


def _clip(source: str, start: float, duration: float) -> Clip:
    return Clip(source=source, start=start, in_point=0.0, out_point=duration)


def test_collect_role_intervals_uses_audible_voice_tracks_only():
    voice = Track(kind="audio", role="voice", clips=[_clip("voice.wav", 2.0, 3.0)])
    muted_voice = Track(
        kind="audio",
        role="voice",
        muted=True,
        clips=[_clip("muted.wav", 4.0, 2.0)],
    )

    assert collect_role_intervals([voice, muted_voice], ("voice",)) == [(2.0, 5.0)]


def test_merge_ducking_intervals_bridges_release_gap():
    merged = merge_ducking_intervals([(0.0, 1.0), (1.2, 2.0), (3.0, 4.0)], gap=0.25)

    assert merged == [(0.0, 2.0), (3.0, 4.0)]


def test_build_ducking_keyframes_for_music_clip():
    music = _clip("music.wav", 0.0, 10.0)

    keyframes = build_ducking_keyframes_for_clip(
        music,
        [(2.0, 5.0)],
        duck_volume=0.4,
        attack=0.5,
        release=1.0,
    )

    assert [(k.time, k.value) for k in keyframes] == [
        (1.5, 1.0),
        (2.0, 0.4),
        (5.0, 0.4),
        (6.0, 1.0),
    ]


def test_apply_auto_ducking_to_tracks_replaces_music_volume_keyframes():
    voice = Track(kind="audio", role="voice", clips=[_clip("voice.wav", 2.0, 3.0)])
    music_clip = _clip("music.wav", 0.0, 10.0)
    music_clip.volume_keyframes = [Keyframe(time=0.0, value=0.8)]
    music = Track(kind="audio", role="music", clips=[music_clip])

    changed = apply_auto_ducking_to_tracks(
        [voice, music],
        config=AutoDuckingConfig(duck_volume=0.25, attack=0.5, release=0.5),
    )

    assert changed == 1
    assert [(k.time, k.value) for k in music_clip.volume_keyframes] == [
        (1.5, 1.0),
        (2.0, 0.25),
        (5.0, 0.25),
        (5.5, 1.0),
    ]


def test_apply_auto_ducking_can_merge_existing_volume_keyframes():
    voice = Track(kind="audio", role="voice", clips=[_clip("voice.wav", 2.0, 1.0)])
    music_clip = _clip("music.wav", 0.0, 5.0)
    music_clip.volume_keyframes = [Keyframe(time=0.0, value=0.8)]
    music = Track(kind="audio", role="music", clips=[music_clip])

    changed = apply_auto_ducking_to_tracks(
        [voice, music],
        config=AutoDuckingConfig(duck_volume=0.5, attack=0.25, release=0.25),
        replace_existing=False,
    )

    assert changed == 1
    assert music_clip.volume_keyframes[0].time == pytest.approx(0.0)
    assert music_clip.volume_keyframes[0].value == pytest.approx(0.8)
    assert any(k.time == pytest.approx(2.0) and k.value == pytest.approx(0.5) for k in music_clip.volume_keyframes)
