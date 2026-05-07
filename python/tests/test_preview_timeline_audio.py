from __future__ import annotations

import pytest

from comecut_py.core.audio_mixer import (
    audible_audio_tracks,
    set_track_role,
    set_track_volume,
    track_output_gain,
)
from comecut_py.core.project import Clip, Track
from comecut_py.gui.main_window import MainWindow
from comecut_py.gui.preview_timeline import (
    _ClipIntervalIndex,
    clip_fade_multiplier_at_local_time,
    next_playable_time_after,
    pick_timeline_audio_clip,
)


class _PreviewPickerStub:
    def __init__(self, tracks: list[Track]) -> None:
        self.project = type("ProjectStub", (), {"tracks": tracks})()

    def _pick_video_clip_for_time(self, _seconds: float):  # pragma: no cover - simple stub
        return None

    def _main_video_track(self):
        for track in self.project.tracks:
            if track.kind == "video":
                return track
        return None

    def _pick_preview_clip_for_time(
        self,
        seconds: float,
        *,
        fallback_to_first: bool = False,
    ):
        return MainWindow._pick_preview_clip_for_time(
            self,
            seconds,
            fallback_to_first=fallback_to_first,
        )

    @staticmethod
    def _is_track_hidden(track: Track) -> bool:
        return bool(getattr(track, "hidden", False))


class _PreviewClockStub:
    def __init__(self, position_ms: int, *, playing: bool = True) -> None:
        self.position_ms = position_ms
        self.playing = playing
        self.seek_calls: list[int] = []
        self.rate_calls: list[float] = []
        self.play_calls = 0

    def main_player_position_ms(self) -> int:
        return self.position_ms

    def set_playback_rate(self, rate: float) -> None:
        self.rate_calls.append(rate)

    def force_seek(self, ms: int) -> None:
        self.seek_calls.append(ms)
        self.position_ms = ms

    def main_player_is_playing(self) -> bool:
        return self.playing

    def play(self) -> None:
        self.play_calls += 1
        self.playing = True


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


def test_audio_clip_interval_index_picks_clip_without_linear_scan() -> None:
    clips = [
        Clip(source=f"{idx}.wav", start=float(idx), in_point=0.0, out_point=0.5)
        for idx in range(1000)
    ]
    tracks = [Track(kind="audio", clips=clips)]
    index = _ClipIntervalIndex()
    index.rebuild(audible_audio_tracks(tracks))

    assert pick_timeline_audio_clip(tracks, 125.25, index=index) is clips[125]


def test_audio_clip_interval_index_is_rebuilt_after_track_changes() -> None:
    first = Clip(source="a.wav", start=0.0, in_point=0.0, out_point=1.0)
    second = Clip(source="b.wav", start=2.0, in_point=0.0, out_point=1.0)
    track = Track(kind="audio", clips=[first])
    index = _ClipIntervalIndex()
    index.rebuild(audible_audio_tracks([track]))

    assert index.find(2.5) is None

    track.clips.append(second)
    index.rebuild(audible_audio_tracks([track]))

    assert index.find(2.5) is second


def test_main_window_preview_picker_does_not_fallback_by_default() -> None:
    audio = Clip(source="a.wav", start=3.0, in_point=0.0, out_point=2.0)
    stub = _PreviewPickerStub([Track(kind="audio", clips=[audio])])

    assert MainWindow._pick_preview_clip_for_time(stub, 0.5) is None
    assert MainWindow._pick_preview_clip_for_time(stub, 0.5, fallback_to_first=True) is audio


def test_timeline_play_start_keeps_current_gap_position() -> None:
    audio = Clip(source="a.wav", start=3.0, in_point=0.0, out_point=2.0)
    stub = _PreviewPickerStub([Track(kind="audio", clips=[audio])])

    play_time, clip = MainWindow._resolve_timeline_play_start(stub, 0.5)

    assert play_time == pytest.approx(0.5)
    assert clip is None


def test_timeline_play_start_returns_clip_when_playhead_touches_media() -> None:
    audio = Clip(source="a.wav", start=3.0, in_point=0.0, out_point=2.0)
    stub = _PreviewPickerStub([Track(kind="audio", clips=[audio])])

    play_time, clip = MainWindow._resolve_timeline_play_start(stub, 3.5)

    assert play_time == pytest.approx(3.5)
    assert clip is audio


def test_preview_video_resyncs_when_player_clock_drifts() -> None:
    preview = _PreviewClockStub(position_ms=0, playing=True)
    stub = type("ClockWindowStub", (), {"preview_panel": preview})()

    changed = MainWindow._resync_preview_video_if_clock_drifted(
        stub,
        1_000,
        rate=1.25,
    )

    assert changed is True
    assert preview.seek_calls == [1_000]
    assert preview.rate_calls == [1.25]
    assert preview.play_calls == 0


def test_preview_video_resync_skips_small_clock_drift() -> None:
    preview = _PreviewClockStub(
        position_ms=1_000 - MainWindow._VIDEO_CLOCK_RESYNC_THRESHOLD_MS,
        playing=True,
    )
    stub = type("ClockWindowStub", (), {"preview_panel": preview})()

    changed = MainWindow._resync_preview_video_if_clock_drifted(
        stub,
        1_000,
        rate=1.0,
    )

    assert changed is False
    assert preview.seek_calls == []


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
