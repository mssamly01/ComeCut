"""Subtitle styling — builds libass ``force_style`` strings.

The ffmpeg ``subtitles`` filter accepts a ``force_style=…`` parameter in
libass ``Key=Value,Key=Value,…`` syntax. This module provides a typed
:class:`SubtitleStyle` so callers don't have to hand-assemble those
strings (easy to misspell ``Fontsize``, ``Outline``, etc., and easy to
get the colour byte-order wrong — libass wants ``&H00BBGGRR``).

Reference: https://ffmpeg.org/ffmpeg-filters.html#subtitles-1 and
ASS/SSA v4+ spec §2.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# libass alignment codes: ``numpad`` layout — 7 8 9 top row; 4 5 6 middle;
# 1 2 3 bottom. Most user-visible names map unambiguously.
_ALIGNMENT = {
    "bottom-left": 1, "bottom-center": 2, "bottom-right": 3,
    "middle-left": 4, "middle-center": 5, "middle-right": 6,
    "top-left": 7, "top-center": 8, "top-right": 9,
}
Alignment = Literal[
    "bottom-left", "bottom-center", "bottom-right",
    "middle-left", "middle-center", "middle-right",
    "top-left", "top-center", "top-right",
]


def _css_or_hex_to_libass(colour: str) -> str:
    """Convert a ``#RRGGBB`` or ``#RRGGBBAA`` CSS colour to libass ``&HAABBGGRR``.

    libass colours are hex little-endian BGR with an alpha byte PREPENDED
    where ``alpha=0`` means fully opaque and ``alpha=255`` means fully
    transparent (inverse of CSS). Accepts the canonical ``&H…`` form
    unchanged.
    """
    if colour.startswith("&H") or colour.startswith("&h"):
        return colour  # already libass-native
    c = colour.lstrip("#")
    if len(c) == 6:
        rr, gg, bb = c[0:2], c[2:4], c[4:6]
        return f"&H00{bb}{gg}{rr}".upper().replace("&H", "&H")
    if len(c) == 8:
        rr, gg, bb, aa = c[0:2], c[2:4], c[4:6], c[6:8]
        # CSS alpha ``ff`` → libass ``00`` (opaque). Invert by subtracting
        # from 0xFF.
        inv = f"{255 - int(aa, 16):02X}"
        return f"&H{inv}{bb}{gg}{rr}".upper().replace("&H", "&H")
    raise ValueError(
        f"colour {colour!r} must be #RRGGBB, #RRGGBBAA or a libass &H… string"
    )


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    """Libass-compatible subtitle appearance.

    Colours accept either CSS hex (``"#FFFFFF"``) or native libass
    (``"&H00FFFFFF"``). The to_force_style() renderer normalises both.
    """
    font_name: str | None = None
    font_size: int | None = None
    primary_colour: str | None = None
    outline_colour: str | None = None
    back_colour: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    outline: float | None = None
    shadow: float | None = None
    # ``1`` = outline+shadow (the usual caption look); ``3`` = opaque box.
    border_style: Literal[1, 3] | None = None
    alignment: Alignment | int | None = None
    margin_l: int | None = None
    margin_r: int | None = None
    margin_v: int | None = None

    def to_force_style(self) -> str:
        """Render this style as a libass ``force_style`` string.

        Only fields that were set (i.e. not ``None``) appear in the
        output, so burning a plain ``SubtitleStyle()`` is a no-op
        equivalent to not passing ``force_style`` at all.
        """
        parts: list[str] = []
        if self.font_name is not None:
            parts.append(f"FontName={self.font_name}")
        if self.font_size is not None:
            parts.append(f"Fontsize={self.font_size}")
        if self.primary_colour is not None:
            parts.append(
                f"PrimaryColour={_css_or_hex_to_libass(self.primary_colour)}"
            )
        if self.outline_colour is not None:
            parts.append(
                f"OutlineColour={_css_or_hex_to_libass(self.outline_colour)}"
            )
        if self.back_colour is not None:
            parts.append(
                f"BackColour={_css_or_hex_to_libass(self.back_colour)}"
            )
        if self.bold is not None:
            parts.append(f"Bold={1 if self.bold else 0}")
        if self.italic is not None:
            parts.append(f"Italic={1 if self.italic else 0}")
        if self.outline is not None:
            parts.append(f"Outline={self.outline}")
        if self.shadow is not None:
            parts.append(f"Shadow={self.shadow}")
        if self.border_style is not None:
            parts.append(f"BorderStyle={self.border_style}")
        if self.alignment is not None:
            # Map string alignment names to libass integer codes. Integer
            # values are passed through as-is.
            al = self.alignment
            if isinstance(al, str):
                if al not in _ALIGNMENT:
                    raise ValueError(
                        f"alignment {al!r} not in {sorted(_ALIGNMENT)}"
                    )
                al = _ALIGNMENT[al]
            parts.append(f"Alignment={al}")
        if self.margin_l is not None:
            parts.append(f"MarginL={self.margin_l}")
        if self.margin_r is not None:
            parts.append(f"MarginR={self.margin_r}")
        if self.margin_v is not None:
            parts.append(f"MarginV={self.margin_v}")
        return ",".join(parts)


__all__ = ["SubtitleStyle", "_css_or_hex_to_libass"]
