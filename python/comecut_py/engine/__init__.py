"""High-level edit operations built on :mod:`comecut_py.core.ffmpeg_cmd`.

All functions return a ready-to-run :class:`~comecut_py.core.FFmpegCommand`.
Callers may either call ``.run()`` to execute, or ``.build()`` to get the argv
list for a dry-run / logging.
"""

from .audio import adjust_volume, extract_audio
from .audio_levels import (
    AudioLevelStats,
    amplitude_to_dbfs,
    analyze_audio_levels,
    audio_clipping_warning,
    build_audio_level_command,
    parse_pcm_s16le_levels,
)
from .concat import concat
from .cut import cut
from .ducking import duck
from .freeze_frame import freeze_frame
from .loudnorm import loudnorm_twopass
from .overlay_text import burn_bilingual_subtitles, burn_subtitles, overlay_text
from .presets import PRESETS, ExportPreset, preset_output_args
from .render import (
    render_project,
    render_project_audio_only,
    render_project_still_frame,
    render_project_twopass,
)
from .stabilize import stabilize
from .timeline_audio_proxy import (
    clip_source_has_audio,
    make_timeline_audio_proxy,
    timeline_audio_project,
    timeline_audio_proxy_path,
)
from .trim import trim
from .zoompan import zoompan_image

__all__ = [
    "PRESETS",
    "AudioLevelStats",
    "ExportPreset",
    "adjust_volume",
    "amplitude_to_dbfs",
    "analyze_audio_levels",
    "audio_clipping_warning",
    "build_audio_level_command",
    "burn_bilingual_subtitles",
    "burn_subtitles",
    "clip_source_has_audio",
    "concat",
    "cut",
    "duck",
    "extract_audio",
    "freeze_frame",
    "loudnorm_twopass",
    "make_timeline_audio_proxy",
    "overlay_text",
    "parse_pcm_s16le_levels",
    "preset_output_args",
    "render_project",
    "render_project_audio_only",
    "render_project_still_frame",
    "render_project_twopass",
    "stabilize",
    "timeline_audio_project",
    "timeline_audio_proxy_path",
    "trim",
    "zoompan_image",
]
