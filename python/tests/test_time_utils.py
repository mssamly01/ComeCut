from __future__ import annotations

import pytest

from comecut_py.core.time_utils import format_timecode, parse_timecode


@pytest.mark.parametrize(
    "input_,expected",
    [
        (0, 0.0),
        (5, 5.0),
        (5.25, 5.25),
        ("5", 5.0),
        ("5.25", 5.25),
        ("5,25", 5.25),
        ("01:30", 90.0),
        ("1:30.500", 90.5),
        ("01:02:03", 3723.0),
        ("01:02:03.250", 3723.25),
        ("01:02:03,250", 3723.25),
    ],
)
def test_parse_timecode_valid(input_, expected):
    assert parse_timecode(input_) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", " ", "abc", "1:2:3:4", "-5", ":30", "01::02"])
def test_parse_timecode_invalid(bad):
    with pytest.raises(ValueError):
        parse_timecode(bad)


def test_parse_timecode_negative_number():
    with pytest.raises(ValueError):
        parse_timecode(-1)


def test_parse_timecode_rejects_bool():
    with pytest.raises(ValueError):
        parse_timecode(True)


@pytest.mark.parametrize(
    "seconds,srt,millis,expected",
    [
        (0.0, False, True, "00:00:00.000"),
        (90.5, False, True, "00:01:30.500"),
        (3723.25, False, True, "01:02:03.250"),
        (3723.25, True, True, "01:02:03,250"),
        (3723.25, False, False, "01:02:03"),
    ],
)
def test_format_timecode(seconds, srt, millis, expected):
    assert format_timecode(seconds, srt=srt, millis=millis) == expected


def test_format_timecode_rejects_negative():
    with pytest.raises(ValueError):
        format_timecode(-1.0)


def test_roundtrip():
    for s in [0.0, 1.234, 60.0, 3600.5, 3723.999]:
        assert parse_timecode(format_timecode(s)) == pytest.approx(s, abs=1e-3)
