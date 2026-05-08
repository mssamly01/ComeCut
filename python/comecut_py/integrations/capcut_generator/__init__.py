"""Local adapter around the bundled capcut_generator reference project."""

from .adapter import (
    TimelineVoiceMatchResult,
    TimelineVoiceMatchInputs,
    TimelineVoiceMatchOptions,
    build_direct_main_voice_match_project,
    generate_voice_match_from_timeline,
    generate_voice_match_project_from_timeline,
    prepare_timeline_voice_match_inputs,
)

__all__ = [
    "TimelineVoiceMatchResult",
    "TimelineVoiceMatchInputs",
    "TimelineVoiceMatchOptions",
    "build_direct_main_voice_match_project",
    "generate_voice_match_from_timeline",
    "generate_voice_match_project_from_timeline",
    "prepare_timeline_voice_match_inputs",
]
