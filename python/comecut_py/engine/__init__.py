"""High-level edit operations built on :mod:`comecut_py.core.ffmpeg_cmd`.

All functions return a ready-to-run :class:`~comecut_py.core.FFmpegCommand`.
Callers may either call ``.run()`` to execute, or ``.build()`` to get the argv
list for a dry-run / logging.
"""

from .audio import adjust_volume, extract_audio
from .concat import concat
from .cut import cut
from .ducking import duck
from .freeze_frame import freeze_frame
from .loudnorm import loudnorm_twopass
from .overlay_text import burn_bilingual_subtitles, burn_subtitles, overlay_text
from .presets import PRESETS, ExportPreset, preset_output_args
from .render import render_project, render_project_twopass
from .stabilize import stabilize
from .trim import trim
from .zoompan import zoompan_image

__all__ = [
    "PRESETS",
    "ExportPreset",
    "adjust_volume",
    "burn_bilingual_subtitles",
    "burn_subtitles",
    "concat",
    "cut",
    "duck",
    "extract_audio",
    "freeze_frame",
    "loudnorm_twopass",
    "overlay_text",
    "preset_output_args",
    "render_project",
    "render_project_twopass",
    "stabilize",
    "trim",
    "zoompan_image",
]
