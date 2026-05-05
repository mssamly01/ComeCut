"""Helpers for batch subtitle translation flows (GUI + CLI)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, TypeVar

from ..core.project import Clip

T = TypeVar("T")


@dataclass
class ClipTranslateItem:
    """A text clip plus its stable batch translation identifier."""

    item_id: str
    clip: Clip
    source_text: str


def chunked(items: Sequence[T], size: int) -> list[list[T]]:
    """Split a sequence into chunks of ``size`` (minimum 1)."""
    n = max(1, int(size))
    return [list(items[i : i + n]) for i in range(0, len(items), n)]


def collect_clip_translate_items(
    clips: Iterable[Clip],
    *,
    only_missing_second: bool = True,
) -> list[ClipTranslateItem]:
    """Collect subtitle clips that can be translated into ``text_second``.

    Source preference mirrors the editor flow: ``text_main`` first, then fallback
    to ``text_second`` if ``text_main`` is empty.
    """

    out: list[ClipTranslateItem] = []
    idx = 1
    for clip in clips:
        if not clip.is_text_clip:
            continue
        main = (clip.text_main or "").strip()
        second = (clip.text_second or "").strip()
        source_text = main or second
        if not source_text:
            continue
        if only_missing_second and second:
            continue
        out.append(ClipTranslateItem(item_id=str(idx), clip=clip, source_text=source_text))
        idx += 1
    return out


def apply_clip_translations(
    items: Sequence[ClipTranslateItem],
    translated_items: Iterable[dict[str, str]],
) -> int:
    """Apply batch translation output to clips by ``id``.

    ``translated_items`` accepts objects like ``{"id": "1", "text": "..."}``.
    Returns how many clips were updated.
    """

    translated_by_id: dict[str, str] = {}
    for row in translated_items:
        rid = str((row or {}).get("id") or "").strip()
        text = str((row or {}).get("text") or "").strip()
        if rid and text:
            translated_by_id[rid] = text

    changed = 0
    for item in items:
        translated = translated_by_id.get(item.item_id, "").strip()
        if not translated:
            continue
        old_second = (item.clip.text_second or "").strip()
        item.clip.text_second = translated
        _normalize_clip_display(item.clip)
        if translated != old_second:
            changed += 1
    return changed


def _normalize_clip_display(clip: Clip) -> None:
    main = (clip.text_main or "").strip()
    second = (clip.text_second or "").strip()
    if main and second:
        clip.text_display = "bilingual"
    elif second:
        clip.text_display = "second"
    else:
        clip.text_display = "main"


__all__ = [
    "ClipTranslateItem",
    "apply_clip_translations",
    "chunked",
    "collect_clip_translate_items",
]
