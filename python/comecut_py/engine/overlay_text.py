"""Text overlay + subtitle burn-in operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..core.ffmpeg_cmd import FFmpegCommand

if TYPE_CHECKING:
    from ..subtitles.style import SubtitleStyle


def _escape_drawtext(s: str) -> str:
    """Escape a literal string so it can be used *unquoted* as the ``text=`` value of ``drawtext``.

    We deliberately do NOT wrap the result in single quotes — ffmpeg's filter
    syntax does not allow ``\\'`` inside single-quoted regions, so the only
    safe approach is to escape every special char inline. The caller must
    therefore emit ``text=<escaped>`` (no surrounding quotes).
    """
    # Order matters: backslash first.
    return (
        s.replace("\\", "\\\\")
        .replace("'", r"\\\'")  # single quote: escape twice (shell + drawtext)
        .replace(":", r"\:")
        .replace(",", r"\,")
        .replace(";", r"\;")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace("%", r"\%")
    )


def overlay_text(
    src: str | Path,
    dst: str | Path,
    text: str,
    *,
    start: float = 0.0,
    end: float | None = None,
    x: str = "(w-text_w)/2",
    y: str = "(h-text_h)-40",
    font_size: int = 48,
    font_color: str = "white",
    box: bool = True,
    box_color: str = "black@0.5",
    font_file: str | Path | None = None,
) -> FFmpegCommand:
    """Draw a single line of text on top of the input video via ``drawtext``."""
    parts = [
        f"text={_escape_drawtext(text)}",
        f"x={x}",
        f"y={y}",
        f"fontsize={font_size}",
        f"fontcolor={font_color}",
    ]
    if box:
        parts.append("box=1")
        parts.append(f"boxcolor={box_color}")
        parts.append("boxborderw=8")
    if font_file is not None:
        parts.append(f"fontfile='{font_file!s}'")
    if end is not None:
        parts.append(f"enable='between(t,{start},{end})'")
    elif start > 0:
        parts.append(f"enable='gte(t,{start})'")
    filt = "drawtext=" + ":".join(parts)

    cmd = FFmpegCommand().add_input(src).set_filter_complex(f"[0:v]{filt}[v]")
    cmd.map("[v]").map("0:a?")
    cmd.extra("-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy")
    cmd.out(dst)
    return cmd


def _subtitles_filter(
    path: str | Path,
    *,
    force_style: str | None = None,
    charenc: str | None = None,
) -> str:
    """Build a single ``subtitles=…`` filter string with ffmpeg-safe escaping."""
    p = str(path).replace("\\", "/").replace(":", r"\:")
    filt = f"subtitles='{p}'"
    if charenc:
        filt += f":charenc={charenc}"
    if force_style:
        filt += f":force_style='{force_style}'"
    return filt


def burn_subtitles(
    src: str | Path,
    subs: str | Path,
    dst: str | Path,
    *,
    force_style: str | None | SubtitleStyle = None,
) -> FFmpegCommand:
    """Burn an SRT/ASS subtitle file into the video via the ``subtitles`` filter.

    ``force_style`` accepts either a raw libass ``Key=Value,…`` string
    or a :class:`~comecut_py.subtitles.SubtitleStyle` instance (which is
    rendered via ``.to_force_style()``).
    """
    from ..subtitles.style import SubtitleStyle
    if isinstance(force_style, SubtitleStyle):
        force_style = force_style.to_force_style() or None
    filt = _subtitles_filter(subs, force_style=force_style)
    cmd = FFmpegCommand().add_input(src).set_filter_complex(f"[0:v]{filt}[v]")
    cmd.map("[v]").map("0:a?")
    cmd.extra("-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy")
    cmd.out(dst)
    return cmd


# Sensible defaults for the bilingual burn — libass-compatible key=value pairs.
# The primary (usually source-language) track sits at the bottom; the secondary
# (translated) track sits at the top. Both are horizontally centred.
_BILINGUAL_PRIMARY_STYLE = (
    "Alignment=2,"
    "Fontsize=24,"
    "PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,"
    "BorderStyle=1,"
    "Outline=1.5,"
    "Shadow=0,"
    "MarginV=30"
)
_BILINGUAL_SECONDARY_STYLE = (
    "Alignment=8,"  # top-center
    "Fontsize=22,"
    "PrimaryColour=&H00F0F0F0,"
    "OutlineColour=&H00000000,"
    "BorderStyle=1,"
    "Outline=1.2,"
    "Shadow=0,"
    "MarginV=30"
)


def burn_bilingual_subtitles(
    src: str | Path,
    primary_subs: str | Path,
    secondary_subs: str | Path,
    dst: str | Path,
    *,
    primary_style: str | None = None,
    secondary_style: str | None = None,
) -> FFmpegCommand:
    """Burn two subtitle tracks side-by-side (primary on top of secondary).

    The primary track is rendered at the bottom-center of the frame with a
    larger font; the secondary (usually translation) track is rendered at the
    top-center. Callers can override either style with a libass
    ``Key=Value,…`` string (see the ``ffmpeg -h filter=subtitles`` docs and
    libass ``force_style`` syntax).
    """
    primary_filt = _subtitles_filter(
        primary_subs, force_style=primary_style or _BILINGUAL_PRIMARY_STYLE
    )
    secondary_filt = _subtitles_filter(
        secondary_subs, force_style=secondary_style or _BILINGUAL_SECONDARY_STYLE
    )
    # Chain: video → primary → secondary → output.
    filter_complex = f"[0:v]{primary_filt}[vp];[vp]{secondary_filt}[v]"
    cmd = FFmpegCommand().add_input(src).set_filter_complex(filter_complex)
    cmd.map("[v]").map("0:a?")
    cmd.extra("-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy")
    cmd.out(dst)
    return cmd


__all__ = ["burn_bilingual_subtitles", "burn_subtitles", "overlay_text"]
