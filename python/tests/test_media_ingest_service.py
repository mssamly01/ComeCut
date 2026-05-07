from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from comecut_py.core.media_cache import CachedMediaInfo
from comecut_py.gui.media_ingest_service import MediaIngestService


def test_video_proxy_threshold_starts_at_thirty_seconds() -> None:
    info = CachedMediaInfo(
        source="clip.mp4",
        duration=29.9,
        has_video=True,
        width=1280,
        height=720,
        video_codec="h264",
    )
    assert not MediaIngestService.should_make_video_proxy(info)

    info.duration = 30.0
    assert MediaIngestService.should_make_video_proxy(info)


def test_audio_only_mp3_gets_proxy_but_wav_short_clip_does_not() -> None:
    mp3 = CachedMediaInfo(
        source="voice.mp3",
        duration=10.0,
        has_audio=True,
        has_video=False,
        audio_codec="mp3",
    )
    wav = CachedMediaInfo(
        source="voice.wav",
        duration=10.0,
        has_audio=True,
        has_video=False,
        audio_codec="pcm_s16le",
    )

    assert MediaIngestService.should_make_audio_proxy(mp3, Path("voice.mp3"))
    assert not MediaIngestService.should_make_audio_proxy(wav, Path("voice.wav"))
