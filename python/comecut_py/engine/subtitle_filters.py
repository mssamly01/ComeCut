"""Pure-Python subtitle filter helpers.

These helpers are extracted from the HTML/Python subtitle editor behavior and
kept free of Qt dependencies so they can be reused by GUI handlers.
"""

from __future__ import annotations

import re

from comecut_py.core.project import Clip

# Common Chinese interjections from the original subtitle editor logic.
CHINESE_INTERJECTIONS = set(
    "\u554a\u54e6\u5594\u5672\u5443\u54ce\u5440\u54c7\u563f\u5478"
    "\u5618\u5567\u54fc\u55ef\u5582\u54a6\u54c8\u543c\u563b\u561b"
    "\u5462\u5427\u5417\u5566\u54d2\u54df\u55f7\u5514\u5495\u565c"
    "\u550f\u55d0\u54bf\u55b5\u5450\u5475\u5600\u54af\u54b3"
)

_OCR_INVALID_CHAR_REGEX = re.compile(
    r"[^0-9\u4e00-\u9fff\uFF0C\u3002\uFF01\uFF1F\u3001\uFF1A\uFF1B"
    r"\uFF08\uFF09\u300A\u300B\u201C\u201D\u2018\u2019.,!?()\[\]\-]+"
)
_OCR_DIGITS_ONLY_REGEX = re.compile(r"[0-9\s]+")
_OCR_MEANINGFUL_CHAR_REGEX = re.compile(
    r"[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
_READING_CHAR_REGEX = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaffA-Za-z0-9]")


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    return text.replace("\xa0", " ").replace("\u3000", " ").replace("\t", " ")


def is_interjection(text: str) -> bool:
    """Return True if text only contains Chinese interjection characters."""
    if not text:
        return False
    clean_chars = [c for c in text if c.isalpha() or "\u4e00" <= c <= "\u9fff"]
    if not clean_chars:
        return False
    return all(c in CHINESE_INTERJECTIONS for c in clean_chars)


def is_ocr_error_text(text: str) -> bool:
    """Return True if text looks like OCR garbage."""
    normalized = _normalize_whitespace(text or "").strip()
    if not normalized:
        return True
    if _OCR_DIGITS_ONLY_REGEX.fullmatch(normalized):
        return True
    if not _OCR_MEANINGFUL_CHAR_REGEX.search(normalized):
        return True
    if _OCR_INVALID_CHAR_REGEX.search(normalized):
        return True
    return False


def reading_speed_cps(clip: Clip) -> float:
    """Characters per second for a subtitle clip."""
    text = clip.text_main or ""
    chars = len(_READING_CHAR_REGEX.findall(text))
    duration = (clip.out_point or 0.0) - clip.in_point
    if duration <= 0.0:
        return 0.0
    return chars / duration


def filter_interjection_clips(clips: list[Clip]) -> list[Clip]:
    return [c for c in clips if c.is_text_clip and is_interjection(c.text_main or "")]


def filter_ocr_error_clips(clips: list[Clip]) -> list[Clip]:
    return [c for c in clips if c.is_text_clip and is_ocr_error_text(c.text_main or "")]


def filter_reading_speed_issue_clips(clips: list[Clip], min_cps: float = 3.0) -> list[Clip]:
    return [c for c in clips if c.is_text_clip and 0.0 < reading_speed_cps(c) < min_cps]


def filter_adjacent_duplicate_clips(clips: list[Clip]) -> list[Clip]:
    sorted_clips = sorted((c for c in clips if c.is_text_clip), key=lambda c: c.start)
    duplicates: list[Clip] = []
    prev_text: str | None = None
    for clip in sorted_clips:
        cur_text = (clip.text_main or "").strip()
        if prev_text is not None and cur_text and cur_text == prev_text:
            duplicates.append(clip)
        prev_text = cur_text
    return duplicates


__all__ = [
    "is_interjection",
    "is_ocr_error_text",
    "reading_speed_cps",
    "filter_interjection_clips",
    "filter_ocr_error_clips",
    "filter_reading_speed_issue_clips",
    "filter_adjacent_duplicate_clips",
]
