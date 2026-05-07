"""Timeline-driven adapter for the bundled local capcut_generator code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import types
from typing import Callable

from ...core.project import Clip, Project, Track
from ...subtitles.cue import Cue, CueList
from ...subtitles.srt import dump_srt

ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True)
class TimelineVoiceMatchInputs:
    video_path: Path
    audio_files: list[Path]
    srt_path: Path
    timestamp_screen: None = None


@dataclass(frozen=True)
class TimelineVoiceMatchOptions:
    project: Project
    output_json_path: Path
    work_dir: Path
    sync_mode: str = "video_priority"
    target_audio_speed: float = 1.0
    keep_pitch: bool = True
    video_speed_enabled: bool = False
    target_video_speed: float = 1.0
    remove_silence: bool = False
    waveform_sync: bool = False
    skip_stretch_shorter: bool = False
    export_lt8: bool = False


def _is_visible_track(track: Track) -> bool:
    return not bool(getattr(track, "hidden", False)) and not bool(getattr(track, "muted", False))


def _main_video_track(project: Project) -> Track | None:
    for track in project.tracks:
        if track.kind == "video" and track.name.strip().lower() == "main":
            return track
    return None


def _clip_text_for_srt(clip: Clip) -> str:
    main = (clip.text_main or "").strip()
    second = (clip.text_second or "").strip()
    display = str(getattr(clip, "text_display", "main") or "main")
    if display == "second":
        return second or main
    if display == "bilingual" and second:
        return f"{main}\n{second}" if main else second
    return main or second


def _collect_main_video(project: Project) -> Path | None:
    main = _main_video_track(project)
    if main is None:
        return None
    clips = [
        clip
        for clip in main.clips
        if not bool(getattr(clip, "is_text_clip", False))
        and str(getattr(clip, "source", "") or "").strip()
    ]
    if not clips:
        return None
    clips.sort(key=lambda c: (float(c.start), str(c.source)))
    return Path(clips[0].source)


def _collect_audio_files(project: Project) -> list[Path]:
    items: list[tuple[float, int, str]] = []
    for track_index, track in enumerate(project.tracks):
        if track.kind != "audio" or not _is_visible_track(track):
            continue
        for clip in track.clips:
            source = str(getattr(clip, "source", "") or "").strip()
            if source:
                items.append((float(clip.start), track_index, source))
    items.sort(key=lambda item: (item[0], item[1], item[2]))
    return [Path(source) for _start, _track_index, source in items]


def _collect_text_cues(project: Project) -> CueList:
    cues: list[Cue] = []
    for track in project.tracks:
        if track.kind != "text" or not _is_visible_track(track):
            continue
        for clip in track.clips:
            duration = clip.timeline_duration
            if duration is None or duration <= 0:
                continue
            text = _clip_text_for_srt(clip)
            if not text:
                continue
            start = max(0.0, float(clip.start))
            end = start + max(0.001, float(duration))
            cues.append(Cue(start=start, end=end, text=text))
    return CueList(cues).sorted()


def prepare_timeline_voice_match_inputs(project: Project, work_dir: Path) -> TimelineVoiceMatchInputs:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    video_path = _collect_main_video(project)
    audio_files = _collect_audio_files(project)
    cues = _collect_text_cues(project)

    missing: list[str] = []
    if video_path is None:
        missing.append("- Track Main chưa có video")
    if not audio_files:
        missing.append("- Chưa có audio trên timeline")
    if len(cues) == 0:
        missing.append("- Chưa có phụ đề/text trên timeline")
    if missing:
        raise ValueError("\n".join(missing))

    srt_path = work_dir / "timeline_voice_match_subtitles.srt"
    dump_srt(srt_path, cues)
    return TimelineVoiceMatchInputs(
        video_path=Path(video_path),
        audio_files=audio_files,
        srt_path=srt_path,
        timestamp_screen=None,
    )


class _ProgressEmitter:
    def __init__(self, callback: ProgressCallback | None) -> None:
        self._callback = callback

    def emit(self, percent: int, message: str) -> None:
        if self._callback is not None:
            self._callback(int(percent), str(message))


def _load_capcut_generator_class():
    repo_root = Path(__file__).resolve().parents[4]
    generator_root = repo_root / "capcut_generator"
    if not generator_root.exists():
        raise RuntimeError("Không tìm thấy thư mục capcut_generator local.")
    if "PyQt6.QtCore" not in sys.modules:
        try:
            __import__("PyQt6.QtCore")
        except ModuleNotFoundError:
            pyqt6_module = types.ModuleType("PyQt6")
            qtcore_module = types.ModuleType("PyQt6.QtCore")
            qtcore_module.pyqtSignal = object
            pyqt6_module.QtCore = qtcore_module
            sys.modules.setdefault("PyQt6", pyqt6_module)
            sys.modules.setdefault("PyQt6.QtCore", qtcore_module)
    generator_root_s = str(generator_root)
    if generator_root_s not in sys.path:
        sys.path.insert(0, generator_root_s)
    from core.capcut_generator import CapCutDraftGenerator  # type: ignore

    return CapCutDraftGenerator


def generate_voice_match_from_timeline(
    options: TimelineVoiceMatchOptions,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    inputs = prepare_timeline_voice_match_inputs(options.project, options.work_dir)
    output_json_path = Path(options.output_json_path)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)

    progress = _ProgressEmitter(progress_callback)
    progress.emit(1, "Đã lấy nguồn ngầm từ timeline")

    generator_cls = _load_capcut_generator_class()
    generator = generator_cls(
        fps=float(options.project.fps),
        canvas_width=int(options.project.width),
        canvas_height=int(options.project.height),
    )
    result = generator.generate_single_json(
        progress,
        str(inputs.video_path),
        [str(path) for path in inputs.audio_files],
        str(inputs.srt_path),
        str(output_json_path),
        True,
        float(options.target_audio_speed),
        bool(options.keep_pitch),
        str(options.sync_mode),
        bool(options.video_speed_enabled),
        float(options.target_video_speed),
        bool(options.remove_silence),
        bool(options.waveform_sync),
        None,
        bool(options.skip_stretch_shorter),
        bool(options.export_lt8),
    )
    if not result:
        raise RuntimeError("Tạo draft khớp voice thất bại.")
    return Path(result)


__all__ = [
    "TimelineVoiceMatchInputs",
    "TimelineVoiceMatchOptions",
    "generate_voice_match_from_timeline",
    "prepare_timeline_voice_match_inputs",
]
