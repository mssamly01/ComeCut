import pytest

import pytest

pytest.importorskip("PySide6")

from comecut_py.core.project import Clip
from comecut_py.gui.main_window import (
    _source_to_timeline_seconds,
    _timeline_to_source_seconds,
)


def test_timeline_to_source_seconds_uses_clip_speed() -> None:
    clip = Clip(source="a.mp4", start=10.0, in_point=2.0, out_point=22.0, speed=2.0)
    assert _timeline_to_source_seconds(clip, 10.0) == pytest.approx(2.0)
    assert _timeline_to_source_seconds(clip, 11.5) == pytest.approx(5.0)


def test_source_to_timeline_seconds_uses_clip_speed() -> None:
    clip = Clip(source="a.mp4", start=3.0, in_point=4.0, out_point=24.0, speed=0.5)
    assert _source_to_timeline_seconds(clip, 4.0) == pytest.approx(3.0)
    assert _source_to_timeline_seconds(clip, 9.0) == pytest.approx(13.0)


def test_speed_mapping_round_trip() -> None:
    clip = Clip(source="a.mp4", start=7.0, in_point=1.25, out_point=31.25, speed=1.7)
    timeline_sec = 13.4
    source_sec = _timeline_to_source_seconds(clip, timeline_sec)
    assert _source_to_timeline_seconds(clip, source_sec) == pytest.approx(timeline_sec)
