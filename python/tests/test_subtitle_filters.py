from __future__ import annotations

import pytest

from comecut_py.core.project import Clip
from comecut_py.engine.subtitle_filters import (
    filter_adjacent_duplicate_clips,
    filter_interjection_clips,
    filter_ocr_error_clips,
    filter_reading_speed_issue_clips,
    is_interjection,
    is_ocr_error_text,
    reading_speed_cps,
)


def _text_clip(
    text: str,
    *,
    start: float = 0.0,
    in_point: float = 0.0,
    out_point: float = 2.0,
) -> Clip:
    return Clip(
        source="test.srt",
        clip_type="text",
        text_main=text,
        start=start,
        in_point=in_point,
        out_point=out_point,
    )


def test_is_interjection_basic() -> None:
    assert is_interjection("啊啊")
    assert is_interjection("哎呀")
    assert not is_interjection("你好")
    assert not is_interjection("Hello")
    assert not is_interjection("")


def test_is_ocr_error_text() -> None:
    assert is_ocr_error_text("")
    assert is_ocr_error_text("123 456")
    assert is_ocr_error_text(",,,")
    assert is_ocr_error_text("abc$%^")
    assert not is_ocr_error_text("你好")
    assert not is_ocr_error_text("Hello world")


def test_reading_speed_cps() -> None:
    clip = _text_clip("abc", out_point=1.0)
    assert reading_speed_cps(clip) == pytest.approx(3.0)
    assert reading_speed_cps(_text_clip("", out_point=1.0)) == 0.0
    assert reading_speed_cps(_text_clip("abc", out_point=0.0)) == 0.0


def test_filter_functions() -> None:
    clips = [
        _text_clip("啊啊", start=0.0, out_point=1.0),
        _text_clip("123", start=1.0, out_point=3.0),
        _text_clip("Hello", start=3.0, out_point=8.0),
        _text_clip("Hello", start=8.0, out_point=9.0),
        _text_clip("你好世界", start=9.0, out_point=9.7),
    ]
    assert len(filter_interjection_clips(clips)) == 1
    assert len(filter_ocr_error_clips(clips)) == 1
    assert len(filter_reading_speed_issue_clips(clips, min_cps=3.0)) >= 1
    duplicates = filter_adjacent_duplicate_clips(clips)
    assert len(duplicates) == 1
    assert duplicates[0].text_main == "Hello"
