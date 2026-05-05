"""Core project model, timing utilities, and FFmpeg command building."""

from .capcut_exporter import export_to_capcut
from .capcut_importer import import_capcut_draft, is_capcut_format
from .ffmpeg_cmd import FFmpegCommand, ensure_ffmpeg, ensure_ffprobe
from .media_probe import MediaInfo, probe
from .project import (
    ChromaKey,
    Clip,
    ClipAudioEffects,
    ClipEffects,
    CropRect,
    ImageOverlay,
    LibraryEntry,
    Project,
    TextOverlay,
    Track,
)
from .library_resolver import (
    collect_search_dirs,
    resolve_entry,
    resolve_project_library,
)
from .project_draft_adapter import is_v2_format, project_to_v2, v2_to_project
from .project_schema_v2 import ProjectV2
from .time_utils import format_timecode, parse_timecode

__all__ = [
    "ChromaKey",
    "Clip",
    "ClipAudioEffects",
    "ClipEffects",
    "CropRect",
    "FFmpegCommand",
    "LibraryEntry",
    "Project",
    "ProjectV2",
    "TextOverlay",
    "Track",
    "collect_search_dirs",
    "resolve_entry",
    "resolve_project_library",
    "ensure_ffmpeg",
    "ensure_ffprobe",
    "export_to_capcut",
    "format_timecode",
    "import_capcut_draft",
    "is_v2_format",
    "is_capcut_format",
    "parse_timecode",
    "probe",
    "project_to_v2",
    "v2_to_project",
]
