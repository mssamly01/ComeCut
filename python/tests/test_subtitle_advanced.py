"""Tests for the advanced subtitle pack (PR F).

Covers four feature groups:

* :class:`SubtitleStyle` — libass ``force_style`` rendering, colour
  conversion from CSS hex to ``&HAABBGGRR``, and end-to-end wiring
  through :func:`burn_subtitles`.
* :mod:`subtitles.ass` — ASS/SSA parser + writer + SRT↔ASS round-trip
  through :func:`convert`.
* :mod:`subtitles.processing` — ``wrap_text_by_chars``,
  ``split_long_cues``, ``cap_cue_duration``.
* :mod:`subtitles.realign` — fuzzy matching cues against ASR word
  timestamps, including graceful degradation when the match is poor.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import pytest

from comecut_py.engine import burn_subtitles
from comecut_py.subtitles import (
    ASRWord,
    Cue,
    CueList,
    SubtitleStyle,
    cap_cue_duration,
    convert,
    parse_ass,
    parse_srt,
    realign_cues,
    split_long_cues,
    wrap_text_by_chars,
    write_ass,
    write_srt,
)
from comecut_py.subtitles.style import _css_or_hex_to_libass

# ---- SubtitleStyle ----------------------------------------------------------


def test_subtitle_style_empty_is_noop():
    assert SubtitleStyle().to_force_style() == ""


def test_subtitle_style_renders_full_set():
    s = SubtitleStyle(
        font_name="Arial", font_size=32,
        primary_colour="#FFFFFF", outline_colour="#000000",
        bold=True, italic=False,
        outline=1.5, shadow=0.0,
        border_style=1, alignment="bottom-center",
        margin_l=20, margin_r=20, margin_v=40,
    )
    out = s.to_force_style()
    # Order-independent presence checks.
    for expected in [
        "FontName=Arial", "Fontsize=32",
        "PrimaryColour=&H00FFFFFF", "OutlineColour=&H00000000",
        "Bold=1", "Italic=0",
        "Outline=1.5", "Shadow=0.0",
        "BorderStyle=1", "Alignment=2",
        "MarginL=20", "MarginR=20", "MarginV=40",
    ]:
        assert expected in out


def test_subtitle_style_alignment_accepts_integer():
    assert "Alignment=8" in SubtitleStyle(alignment=8).to_force_style()


def test_subtitle_style_rejects_unknown_alignment():
    with pytest.raises(ValueError, match="alignment"):
        SubtitleStyle(alignment="centre-ish").to_force_style()


def test_css_hex_to_libass_rgb():
    # Red = RR=FF, GG=00, BB=00 → libass little-endian with alpha 00 →
    # &H000000FF
    assert _css_or_hex_to_libass("#FF0000") == "&H000000FF"
    # Green = 00FF00 → &H0000FF00
    assert _css_or_hex_to_libass("#00FF00") == "&H0000FF00"
    # White → &H00FFFFFF
    assert _css_or_hex_to_libass("#FFFFFF") == "&H00FFFFFF"


def test_css_hex_to_libass_with_alpha_inverts_to_libass_transparency():
    # CSS #FF000080 = red at 50% alpha. libass alpha byte is INVERTED:
    # CSS 0x80 (128) → libass 0xFF - 0x80 = 0x7F.
    assert _css_or_hex_to_libass("#FF000080") == "&H7F0000FF"


def test_css_hex_to_libass_passes_native_through():
    assert _css_or_hex_to_libass("&H00ABCDEF") == "&H00ABCDEF"


def test_burn_subtitles_accepts_subtitle_style(tmp_path: Path):
    subs = tmp_path / "subs.srt"
    subs.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8",
    )
    style = SubtitleStyle(font_size=32, primary_colour="#FFFF00")
    cmd = burn_subtitles(
        "in.mp4", subs, "out.mp4", force_style=style,
    )
    fc = cmd.filter_complex or ""
    assert "Fontsize=32" in fc
    assert "PrimaryColour=&H0000FFFF" in fc


# ---- ASS parser / writer / round-trip --------------------------------------


_SAMPLE_ASS = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H00000000,&H00000000,0,0,1,2,0,2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,Hello, world!
Dialogue: 0,0:00:04.00,0:00:06.20,Default,,0,0,0,,{\\b1}Bold{\\b0} and line one\\Nline two
"""


def test_parse_ass_parses_dialogue_lines():
    cues = list(parse_ass(_SAMPLE_ASS))
    assert len(cues) == 2
    assert cues[0].start == 1.0
    assert cues[0].end == 3.5
    assert cues[0].text == "Hello, world!"


def test_parse_ass_strips_override_codes_and_converts_newlines():
    cues = list(parse_ass(_SAMPLE_ASS))
    assert "{" not in cues[1].text
    assert "}" not in cues[1].text
    # Two-line dialogue with ``\N`` → real newline in the parsed text.
    assert cues[1].text == "Bold and line one\nline two"


def test_parse_ass_skips_malformed_lines():
    # Reverse timing and missing time field both skipped, not raised.
    bad = """\
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:05.00,0:00:03.00,Default,,0,0,0,,Reversed
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,OK
"""
    cues = list(parse_ass(bad))
    assert len(cues) == 1
    assert cues[0].text == "OK"


def test_write_ass_round_trip_preserves_timings_and_text():
    cues = CueList([
        Cue(start=1.23, end=4.56, text="Line one"),
        Cue(start=5.00, end=7.12, text="Line two\nwrapped"),
    ])
    ass_text = write_ass(cues)
    assert "Dialogue:" in ass_text
    reparsed = list(parse_ass(ass_text))
    assert len(reparsed) == 2
    assert reparsed[0].start == pytest.approx(1.23, abs=0.01)
    assert reparsed[0].end == pytest.approx(4.56, abs=0.01)
    # Writer escapes \n → \N; reader un-escapes.
    assert reparsed[1].text == "Line two\nwrapped"


def test_convert_srt_to_ass_and_back(tmp_path: Path):
    srt = tmp_path / "in.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nHello, ASS world\n",
        encoding="utf-8",
    )
    ass_path = tmp_path / "mid.ass"
    convert(srt, ass_path)
    assert "[Events]" in ass_path.read_text()
    srt2 = tmp_path / "out.srt"
    convert(ass_path, srt2)
    cues = list(parse_srt(srt2.read_text()))
    assert len(cues) == 1
    assert cues[0].text == "Hello, ASS world"


# ---- processing -------------------------------------------------------------


def test_wrap_text_by_chars_hard_wraps_at_boundary():
    wrapped = wrap_text_by_chars(
        "The quick brown fox jumps over the lazy dog",
        max_chars_per_line=20,
    )
    assert all(len(line) <= 20 for line in wrapped.split("\n"))
    # Original words must be preserved in order.
    assert wrapped.replace("\n", " ").split() == [
        "The", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog",
    ]


def test_wrap_text_by_chars_handles_empty_input():
    assert wrap_text_by_chars("") == ""
    assert wrap_text_by_chars("   ") == ""


def test_split_long_cues_splits_when_too_many_lines():
    cues = CueList([
        Cue(start=0.0, end=10.0, text=" ".join(["word"] * 20)),
    ])
    out = list(split_long_cues(cues, max_chars_per_line=20, max_lines=1))
    # 20 words of 4 chars + space = ~100 chars split at ≤20 chars/line.
    # With max_lines=1 the cue must have been split into multiple cues.
    assert len(out) > 1
    # Cues should be contiguous and monotone in time.
    for a, b in pairwise(out):
        assert b.start >= a.start
        assert a.end <= b.start + 1e-6


def test_split_long_cues_bisects_on_max_duration():
    cues = CueList([Cue(start=0.0, end=10.0, text="short text")])
    out = list(split_long_cues(
        cues, max_chars_per_line=80, max_lines=2, max_duration=4.0,
    ))
    assert len(out) >= 2
    for c in out:
        assert (c.end - c.start) <= 4.0 + 1e-6
    # Regression: duration-bisection of a single-line cue must NOT
    # produce empty-text cues — every resulting cue must keep the
    # (full or wrapped) text intact.
    for c in out:
        assert c.text.strip() != ""


def test_split_long_cues_single_line_duration_split_preserves_text():
    """A 10 s single-line cue split at max_duration=4 s should appear on
    screen the whole 10 s, not flicker to blank during the 2nd/3rd sub-cue."""
    cues = CueList([Cue(start=0.0, end=10.0, text="hello world")])
    out = list(split_long_cues(
        cues, max_chars_per_line=80, max_lines=2, max_duration=4.0,
    ))
    assert all(c.text == "hello world" for c in out)
    # Time coverage should reach from 0 to ~10 s with no gaps.
    assert out[0].start == pytest.approx(0.0)
    assert out[-1].end == pytest.approx(10.0)


def test_cap_cue_duration_clamps_end_only():
    cues = CueList([Cue(start=10.0, end=20.0, text="x")])
    out = list(cap_cue_duration(cues, max_duration=3.0))
    assert out[0].start == 10.0
    assert out[0].end == 13.0


def test_cap_cue_duration_leaves_short_cues_alone():
    cues = CueList([Cue(start=10.0, end=11.5, text="x")])
    out = list(cap_cue_duration(cues, max_duration=3.0))
    assert out[0].end == 11.5


# ---- realign ---------------------------------------------------------------


def test_realign_cues_uses_asr_word_times():
    cues = CueList([
        Cue(start=99.0, end=100.0, text="hello world"),
        Cue(start=101.0, end=102.0, text="goodbye friend"),
    ])
    words = [
        ASRWord("Hello", 0.20, 0.50),
        ASRWord("world.", 0.55, 0.90),
        ASRWord("Goodbye,", 2.10, 2.55),
        ASRWord("friend!", 2.60, 3.00),
    ]
    out = list(realign_cues(cues, words))
    assert out[0].start == pytest.approx(0.20)
    assert out[0].end == pytest.approx(0.90)
    assert out[1].start == pytest.approx(2.10)
    assert out[1].end == pytest.approx(3.00)
    # Cue text is preserved.
    assert out[0].text == "hello world"
    assert out[1].text == "goodbye friend"


def test_realign_cues_falls_back_on_poor_match():
    # No words overlap with the cue text, so the fuzzy match ratio is
    # below min_confidence and the original timing is preserved.
    cues = CueList([Cue(start=5.0, end=6.0, text="unrelated captions")])
    words = [ASRWord("lalala", 0.1, 0.3), ASRWord("bababa", 0.35, 0.7)]
    out = list(realign_cues(cues, words, min_confidence=0.5))
    assert out[0].start == 5.0
    assert out[0].end == 6.0


def test_realign_cues_handles_empty_asr_transcript():
    cues = CueList([Cue(start=5.0, end=6.0, text="anything")])
    out = list(realign_cues(cues, []))
    assert out[0].start == 5.0
    assert out[0].end == 6.0


def test_realign_cues_respects_tuple_input():
    # Accept ``(word, start, end)`` tuples instead of ASRWord objects.
    cues = CueList([Cue(start=99.0, end=100.0, text="good day")])
    out = list(realign_cues(cues, [("good", 1.0, 1.3), ("day", 1.4, 1.8)]))
    assert out[0].start == pytest.approx(1.0)
    assert out[0].end == pytest.approx(1.8)


def test_write_srt_after_realign_is_parseable(tmp_path: Path):
    cues = CueList([Cue(start=99.0, end=100.0, text="hello world")])
    words = [ASRWord("hello", 0.1, 0.4), ASRWord("world", 0.5, 0.9)]
    out = realign_cues(cues, words)
    text = write_srt(out)
    reparsed = list(parse_srt(text))
    assert reparsed[0].start == pytest.approx(0.1, abs=0.01)
    assert reparsed[0].end == pytest.approx(0.9, abs=0.01)


# ---- CLI integration -------------------------------------------------------


def test_translate_subs_cli_parses_ass_and_writes_ass(tmp_path: Path, monkeypatch):
    """Regression: `translate-subs` must branch on src_fmt == "ass" instead
    of falling through to parse_lrc (which would produce garbage cues)."""
    from typer.testing import CliRunner

    from comecut_py.cli import app

    cues = CueList([Cue(start=1.0, end=2.5, text="hello world")])
    src = tmp_path / "in.ass"
    src.write_text(write_ass(cues), encoding="utf-8")
    dst = tmp_path / "out.ass"

    # Stub translator so no network call happens.
    class _Fake:
        def translate_cues(self, cues, *, target, source=None):
            return CueList([
                Cue(start=c.start, end=c.end, text=f"[{target}] {c.text}", index=c.index)
                for c in cues
            ])

        def translate_items(self, items, *, target, source=None):
            return [{"id": x["id"], "text": f"[{target}] {x['text']}"} for x in items]

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch("comecut_py.ai.openai_translate.OpenAITranslate", return_value=_Fake()):
        result = CliRunner().invoke(
            app, ["translate-subs", str(src), str(dst), "--to", "Vietnamese"],
        )
    assert result.exit_code == 0, result.output
    # Output must be a valid ASS file preserving our stub's translation.
    written = dst.read_text(encoding="utf-8")
    assert "[Script Info]" in written
    reparsed = list(parse_ass(written))
    assert len(reparsed) == 1
    assert reparsed[0].text == "[Vietnamese] hello world"
    assert reparsed[0].start == pytest.approx(1.0, abs=0.02)
    assert reparsed[0].end == pytest.approx(2.5, abs=0.02)

def test_translate_subs_cli_batch_size_uses_translate_items(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from comecut_py.cli import app

    src = tmp_path / "in.srt"
    src.write_text(
        (
            "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:02,100 --> 00:00:03,000\nWorld\n\n"
            "3\n00:00:03,100 --> 00:00:04,000\nAgain\n"
        ),
        encoding="utf-8",
    )
    dst = tmp_path / "out.srt"

    class _Fake:
        def __init__(self):
            self.calls: list[list[dict[str, str]]] = []

        def translate_cues(self, cues, *, target, source=None):
            raise AssertionError("translate_cues should not be used when --batch-size > 1")

        def translate_items(self, items, *, target, source=None):
            self.calls.append(list(items))
            return [{"id": x["id"], "text": f"[{target}] {x['text']}"} for x in items]

    fake = _Fake()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch("comecut_py.ai.openai_translate.OpenAITranslate", return_value=fake):
        result = CliRunner().invoke(
            app,
            [
                "translate-subs",
                str(src),
                str(dst),
                "--to",
                "Vietnamese",
                "--batch-size",
                "2",
            ],
        )

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 2
    assert len(fake.calls[0]) == 2
    assert len(fake.calls[1]) == 1

    reparsed = list(parse_srt(dst.read_text(encoding="utf-8")))
    assert [c.text for c in reparsed] == [
        "[Vietnamese] Hello",
        "[Vietnamese] World",
        "[Vietnamese] Again",
    ]
