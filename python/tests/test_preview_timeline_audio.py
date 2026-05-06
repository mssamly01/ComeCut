from __future__ import annotations

import pytest

from comecut_py.core.audio_mixer import (
    audible_audio_tracks,
    set_track_role,
    set_track_volume,
    track_output_gain,
)
from comecut_py.core.project import Clip, Track
from comecut_py.gui.preview_timeline import (
    clip_fade_multiplier_at_local_time,
    next_playable_time_after,
    pick_timeline_audio_clip,
)


def test_audio_clip_can_be_picked_without_selection() -> None:
    audio = Clip(source="a.wav", start=5.0, in_point=0.0, out_point=10.0)
    tracks = [Track(kind="audio", clips=[audio])]
    assert pick_timeline_audio_clip(tracks, 6.0) is audio


def test_muted_audio_track_is_ignored() -> None:
    audio = Clip(source="a.wav", start=0.0, in_point=0.0, out_point=10.0)
    tracks = [Track(kind="audio", muted=True, clips=[audio])]
    assert pick_timeline_audio_clip(tracks, 2.0) is None


def test_hidden_audio_track_is_ignored() -> None:
    audio = Clip(source="a.wav", start=0.0, in_point=0.0, out_point=10.0)
    tracks = [Track(kind="audio", hidden=True, clips=[audio])]
    assert pick_timeline_audio_clip(tracks, 2.0) is None


def test_zero_volume_audio_track_is_ignored_by_preview_picker() -> None:
    audio = Clip(source="a.wav", start=0.0, in_point=0.0, out_point=10.0)
    tracks = [Track(kind="audio", volume=0.0, clips=[audio])]
    assert pick_timeline_audio_clip(tracks, 2.0) is None


def test_audio_mixer_helpers_clamp_volume_and_role() -> None:
    track = Track(kind="audio", clips=[Clip(source="a.wav", out_point=1.0)])

    assert set_track_volume(track, "-2") == 0.0
    assert track_output_gain(track) == 0.0
    assert audible_audio_tracks([track]) == []

    assert set_track_volume(track, "1.5") == pytest.approx(1.5)
    assert track_output_gain(track) == pytest.approx(1.5)
    assert set_track_role(track, "voice") == "voice"
    assert set_track_role(track, "unknown") == "other"


def test_fallback_to_first_audio_clip() -> None:
    audio = Clip(source="a.wav", start=3.0, in_point=0.0, out_point=2.0)
    tracks = [Track(kind="audio", clips=[audio])]
    assert pick_timeline_audio_clip(tracks, 0.5, fallback_to_first=True) is audio


def test_next_playable_time_skips_to_later_audio_clip() -> None:
    clip1 = Clip(source="a.wav", start=0.0, in_point=0.0, out_point=1.0)
    clip2 = Clip(source="b.wav", start=3.0, in_point=0.0, out_point=2.0)
    tracks = [Track(kind="audio", clips=[clip1, clip2])]
    assert next_playable_time_after(tracks, 1.0) == 3.0


def test_fade_multiplier_clamps_overlapping_fades_to_half_duration() -> None:
    clip = Clip(source="a.wav", start=0.0, in_point=0.0, out_point=2.0, speed=2.0)
    clip.audio_effects.fade_in = 3.0
    clip.audio_effects.fade_out = 3.0

    assert clip_fade_multiplier_at_local_time(clip, 0.25) == pytest.approx(0.5)
    assert clip_fade_multiplier_at_local_time(clip, 0.5) == pytest.approx(1.0)
    assert clip_fade_multiplier_at_local_time(clip, 0.75) == pytest.approx(0.5)
