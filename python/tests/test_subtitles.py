from __future__ import annotations

import pytest

from comecut_py.core.project import Clip
from comecut_py.subtitles.cue import Cue, CueList
from comecut_py.subtitles.lrc import parse_lrc, write_lrc
from comecut_py.subtitles.srt import parse_srt, write_srt
from comecut_py.subtitles.translate_batch import apply_clip_translations, collect_clip_translate_items
from comecut_py.subtitles.vtt import parse_vtt, write_vtt

SRT_SAMPLE = """\
1
00:00:01,000 --> 00:00:03,500
Hello world
second line

2
00:00:04,000 --> 00:00:06,000
Second cue
"""

VTT_SAMPLE = """\
WEBVTT

00:00:01.000 --> 00:00:03.500
Hello world
second line

00:00:04.000 --> 00:00:06.000
Second cue
"""

LRC_SAMPLE = """\
[ti:Test]
[ar:ComeCut]
[00:01.00]first line
[00:03.50]second line
[00:06.00]third
"""


def test_parse_srt():
    cues = parse_srt(SRT_SAMPLE)
    assert len(cues) == 2
    assert cues.cues[0].start == pytest.approx(1.0)
    assert cues.cues[0].end == pytest.approx(3.5)
    assert cues.cues[0].text == "Hello world\nsecond line"
    assert cues.cues[1].text == "Second cue"


def test_parse_srt_handles_bom_and_crlf():
    text = "\ufeff" + SRT_SAMPLE.replace("\n", "\r\n")
    cues = parse_srt(text)
    assert len(cues) == 2


def test_write_srt_roundtrip():
    cues = parse_srt(SRT_SAMPLE)
    rendered = write_srt(cues)
    reparsed = parse_srt(rendered)
    assert [(c.start, c.end, c.text) for c in reparsed] == [
        (c.start, c.end, c.text) for c in cues
    ]


def test_parse_vtt():
    cues = parse_vtt(VTT_SAMPLE)
    assert len(cues) == 2
    assert cues.cues[0].start == pytest.approx(1.0)
    assert cues.cues[0].text == "Hello world\nsecond line"


def test_write_vtt_has_header():
    cues = parse_vtt(VTT_SAMPLE)
    out = write_vtt(cues)
    assert out.startswith("WEBVTT")


def test_vtt_roundtrip():
    cues = parse_vtt(VTT_SAMPLE)
    out = write_vtt(cues)
    reparsed = parse_vtt(out)
    assert [(c.start, c.end, c.text) for c in reparsed] == [
        (c.start, c.end, c.text) for c in cues
    ]


def test_parse_lrc():
    cues, meta = parse_lrc(LRC_SAMPLE)
    assert meta["ti"] == "Test"
    assert meta["ar"] == "ComeCut"
    assert len(cues) == 3
    assert cues.cues[0].start == pytest.approx(1.0)
    assert cues.cues[0].end == pytest.approx(3.5)
    assert cues.cues[0].text == "first line"
    # Last cue has trailing tail duration (default 3s).
    assert cues.cues[-1].end == pytest.approx(9.0)


def test_write_lrc_roundtrip():
    cues, meta = parse_lrc(LRC_SAMPLE)
    out = write_lrc(cues, metadata=meta)
    reparsed, meta2 = parse_lrc(out)
    assert [(c.start, c.text) for c in reparsed] == [(c.start, c.text) for c in cues]
    assert meta2["ti"] == "Test"


def test_cue_validates():
    with pytest.raises(ValueError):
        Cue(start=5, end=5, text="x")
    with pytest.raises(ValueError):
        Cue(start=-1, end=1, text="x")


def test_cuelist_sorted():
    cues = CueList([Cue(3, 4, "b"), Cue(1, 2, "a")])
    s = cues.sorted()
    assert [c.text for c in s] == ["a", "b"]


def test_convert_srt_to_vtt(tmp_path):
    from comecut_py.subtitles.convert import convert

    src = tmp_path / "in.srt"
    dst = tmp_path / "out.vtt"
    src.write_text(SRT_SAMPLE)
    convert(src, dst)
    content = dst.read_text()
    assert content.startswith("WEBVTT")
    assert "Hello world" in content


def test_convert_vtt_to_srt(tmp_path):
    from comecut_py.subtitles.convert import convert

    src = tmp_path / "in.vtt"
    dst = tmp_path / "out.srt"
    src.write_text(VTT_SAMPLE)
    convert(src, dst)
    out = dst.read_text()
    assert "-->" in out
    assert "," in out  # SRT millisecond separator
    assert "Hello world" in out


def test_detect_format():
    from pathlib import Path

    from comecut_py.subtitles.convert import detect_format

    assert detect_format(Path("x.srt"), "") == "srt"
    assert detect_format(Path("x.vtt"), "") == "vtt"
    assert detect_format(Path("x.lrc"), "") == "lrc"
    # Content-sniff when extension is unknown.
    assert detect_format(Path("x.txt"), "WEBVTT\n\n00:00:01") == "vtt"
    assert detect_format(Path("x.txt"), "[ti:foo]\n[00:01.00]hi") == "lrc"
    assert detect_format(Path("x.txt"), "1\n00:00:01,000 --> 00:00:02,000\nhi") == "srt"

def test_collect_clip_translate_items_prefers_main_and_skips_second_when_requested():
    clips = [
        Clip(clip_type="text", source="a.srt", start=0.0, in_point=0.0, out_point=1.0, text_main="Hello"),
        Clip(clip_type="text", source="a.srt", start=1.1, in_point=0.0, out_point=1.0, text_main="", text_second="Already"),
        Clip(source="a.mp4", start=0.0, in_point=0.0, out_point=1.0),
    ]
    items = collect_clip_translate_items(clips, only_missing_second=True)
    assert len(items) == 1
    assert items[0].item_id == "1"
    assert items[0].source_text == "Hello"

def test_apply_clip_translations_updates_second_and_display_mode():
    clip = Clip(
        clip_type="text",
        source="a.srt",
        start=0.0,
        in_point=0.0,
        out_point=1.0,
        text_main="Hello",
        text_second="",
        text_display="main",
    )
    items = collect_clip_translate_items([clip], only_missing_second=True)
    changed = apply_clip_translations(items, [{"id": "1", "text": "Xin chào"}])
    assert changed == 1
    assert clip.text_second == "Xin chào"
    assert clip.text_display == "bilingual"
