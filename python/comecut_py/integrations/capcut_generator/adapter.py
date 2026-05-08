"""Timeline-driven adapter for the bundled local capcut_generator code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import types
from typing import Callable
from uuid import uuid4

from ...core.capcut_importer import import_capcut_draft
from ...core.media_probe import probe as probe_media
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


@dataclass(frozen=True)
class TimelineVoiceMatchResult:
    output_json_path: Path
    project: Project


def _is_visible_track(track: Track) -> bool:
    return not bool(getattr(track, "hidden", False)) and not bool(getattr(track, "muted", False))


def _main_video_track(project: Project) -> Track | None:
    for track in project.tracks:
        if track.kind == "video" and track.name.strip().lower() == "main":
            return track
    return _first_visible_video_track(project)


def _first_visible_video_track(project: Project) -> Track | None:
    return next(
        (
            track
            for track in project.tracks
            if track.kind == "video"
            and track.clips
            and not bool(getattr(track, "hidden", False))
        ),
        None,
    )


def _matched_tracks_for_kind(matched: Project, kind: str, default_name: str) -> list[Track]:
    tracks: list[Track] = []
    for track in matched.tracks:
        if track.kind != kind or not track.clips:
            continue
        copied = track.model_copy(deep=True)
        if not copied.name.strip():
            index = len(tracks) + 1
            copied.name = default_name if index == 1 else f"{default_name} {index}"
        tracks.append(copied)
    return tracks


def _source_key(source: object) -> str:
    raw = str(source or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve()).lower()
    except Exception:
        return raw.lower()


def _copy_matched_main_video_clips(
    matched_video_track: Track,
    original_main_track: Track | None = None,
) -> list[Clip]:
    original_volume_by_source: dict[str, float] = {}
    if original_main_track is not None:
        for original_clip in original_main_track.clips:
            if bool(getattr(original_clip, "is_text_clip", False)):
                continue
            key = _source_key(getattr(original_clip, "source", ""))
            if not key or key in original_volume_by_source:
                continue
            try:
                original_volume_by_source[key] = max(0.0, float(original_clip.volume))
            except Exception:
                original_volume_by_source[key] = 1.0

    clips: list[Clip] = []
    for clip in matched_video_track.clips:
        copied = clip.model_copy(deep=True)
        source_key = _source_key(getattr(copied, "source", ""))
        if source_key in original_volume_by_source:
            copied.volume = original_volume_by_source[source_key]
        copied.volume_keyframes = []
        copied.audio_effects.fade_in = 0.0
        copied.audio_effects.fade_out = 0.0
        clips.append(copied)
    return clips


def _clip_timeline_range(clip: Clip) -> tuple[float, float]:
    try:
        start = max(0.0, float(getattr(clip, "start", 0.0) or 0.0))
    except Exception:
        start = 0.0
    try:
        duration = max(0.0, float(getattr(clip, "timeline_duration", 0.0) or 0.0))
    except Exception:
        duration = 0.0
    return start, start + duration


def _best_voice_match_parent_clip(child: Clip, parents: list[Clip]) -> Clip | None:
    if not parents:
        return None
    child_start, child_end = _clip_timeline_range(child)
    child_mid = (child_start + child_end) * 0.5
    best_parent: Clip | None = None
    best_overlap = 0.0
    for parent in parents:
        parent_start, parent_end = _clip_timeline_range(parent)
        overlap = max(0.0, min(child_end, parent_end) - max(child_start, parent_start))
        if overlap > best_overlap + 1e-6:
            best_parent = parent
            best_overlap = overlap
    if best_parent is not None:
        return best_parent
    for parent in parents:
        parent_start, parent_end = _clip_timeline_range(parent)
        if parent_start <= child_start < parent_end:
            return parent
    return min(
        parents,
        key=lambda parent: abs(
            ((_clip_timeline_range(parent)[0] + _clip_timeline_range(parent)[1]) * 0.5)
            - child_mid
        ),
    )


def _ensure_unique_project_clip_ids(project: Project) -> None:
    seen: set[str] = set()
    for track in project.tracks:
        for clip in track.clips:
            clip_id = str(getattr(clip, "clip_id", "") or "").strip()
            if not clip_id or clip_id in seen:
                clip.clip_id = uuid4().hex
                clip_id = str(clip.clip_id)
            seen.add(clip_id)


def _link_voice_match_children_to_main(main_clips: list[Clip], child_tracks: list[Track]) -> None:
    if not main_clips or not child_tracks:
        return
    for child_track in child_tracks:
        for child in child_track.clips:
            parent = _best_voice_match_parent_clip(child, main_clips)
            if parent is None:
                continue
            parent_id = str(getattr(parent, "clip_id", "") or "").strip()
            if not parent_id:
                parent.clip_id = uuid4().hex
                parent_id = str(parent.clip_id)
            group_id = str(getattr(parent, "link_group_id", "") or "").strip()
            if not group_id:
                group_id = f"voice-match-{parent_id}"
                parent.link_group_id = group_id
            parent.linked_parent_id = None
            parent.linked_offset = 0.0
            child.link_group_id = group_id
            child.linked_parent_id = parent_id
            child.linked_offset = float(child.start) - float(parent.start)


def build_direct_main_voice_match_project(original: Project, matched: Project) -> Project:
    result = original.model_copy(deep=True)
    result_main = _main_video_track(result)
    matched_video_track = _first_visible_video_track(matched)
    if result_main is None or matched_video_track is None:
        raise ValueError("Không tìm thấy track Main hoặc track video đã khớp.")

    result_main.name = "Main"
    original_main_track = _main_video_track(original)
    result_main.clips = _copy_matched_main_video_clips(
        matched_video_track,
        original_main_track,
    )
    result_main.transitions = [
        transition.model_copy(deep=True)
        for transition in getattr(matched_video_track, "transitions", [])
    ]

    matched_text_tracks = _matched_tracks_for_kind(matched, "text", "Khớp voice - Text")
    matched_audio_tracks = _matched_tracks_for_kind(matched, "audio", "Khớp voice - Voice")
    _ensure_unique_project_clip_ids(result)
    _link_voice_match_children_to_main(
        result_main.clips,
        [*matched_text_tracks, *matched_audio_tracks],
    )
    if not matched_text_tracks and not matched_audio_tracks:
        return result

    rebuilt_tracks: list[Track] = []
    inserted_text = False
    inserted_audio = False
    for track in result.tracks:
        if matched_text_tracks and track.kind == "text":
            if not inserted_text:
                rebuilt_tracks.extend([tr.model_copy(deep=True) for tr in matched_text_tracks])
                inserted_text = True
            continue
        if matched_audio_tracks and track.kind == "audio":
            if not inserted_audio:
                rebuilt_tracks.extend([tr.model_copy(deep=True) for tr in matched_audio_tracks])
                inserted_audio = True
            continue
        rebuilt_tracks.append(track)

    if matched_text_tracks and not inserted_text:
        main_idx = next(
            (idx for idx, track in enumerate(rebuilt_tracks) if track is result_main),
            len(rebuilt_tracks),
        )
        for track in reversed(matched_text_tracks):
            rebuilt_tracks.insert(main_idx, track.model_copy(deep=True))
    if matched_audio_tracks and not inserted_audio:
        main_idx = next(
            (idx for idx, track in enumerate(rebuilt_tracks) if track is result_main),
            len(rebuilt_tracks) - 1,
        )
        insert_idx = max(0, main_idx + 1)
        for offset, track in enumerate(matched_audio_tracks):
            rebuilt_tracks.insert(insert_idx + offset, track.model_copy(deep=True))

    result.tracks = rebuilt_tracks
    return result


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
        self.last_message = ""

    def emit(self, percent: int, message: str) -> None:
        self.last_message = str(message)
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


def _probe_duration_us(path: Path | str) -> int:
    media_path = Path(path)
    if not media_path.exists():
        raise FileNotFoundError(f"Không tìm thấy file media: {media_path}")
    if media_path.is_file() and media_path.stat().st_size <= 0:
        raise ValueError(f"File media rỗng: {media_path.name}")
    info = probe_media(media_path)
    duration = info.duration
    if duration is None or duration <= 0:
        raise ValueError(f"Không đọc được thời lượng media: {media_path.name}")
    return max(1, int(float(duration) * 1_000_000))


def _probe_video_dimensions(path: Path | str, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    try:
        info = probe_media(Path(path))
    except Exception:
        return int(fallback_width), int(fallback_height)
    width = int(info.width or 0)
    height = int(info.height or 0)
    if width <= 0 or height <= 0:
        return int(fallback_width), int(fallback_height)
    return width, height


def _validate_timeline_voice_match_media(inputs: TimelineVoiceMatchInputs) -> None:
    try:
        _probe_duration_us(inputs.video_path)
    except Exception as exc:
        raise RuntimeError(f"Không đọc được video Main: {exc}") from exc

    failed_audio: list[str] = []
    for audio_path in inputs.audio_files:
        try:
            _probe_duration_us(audio_path)
        except Exception as exc:
            failed_audio.append(f"- {Path(audio_path).name}: {exc}")
    if failed_audio:
        raise RuntimeError("Không đọc được audio voice:\n" + "\n".join(failed_audio))


def _install_comecut_media_probe(generator: object) -> None:
    width = int(getattr(generator, "canvas_width", 1920) or 1920)
    height = int(getattr(generator, "canvas_height", 1080) or 1080)

    def _get_media_duration(media_path: str) -> int:
        return _probe_duration_us(media_path)

    def _get_video_dimensions(media_path: str) -> tuple[int, int]:
        return _probe_video_dimensions(media_path, width, height)

    # The bundled generator expects ffmpeg-python. ComeCut already ships a
    # local ffprobe-based media_probe, so keep Khớp voice independent of that package.
    setattr(generator, "get_media_duration", _get_media_duration)
    setattr(generator, "get_video_dimensions", _get_video_dimensions)


def _smart_trimming_available() -> bool:
    try:
        from core.audio_video_sync import AudioVideoSyncProcessor  # type: ignore

        return bool(AudioVideoSyncProcessor().is_available())
    except Exception:
        return False


def generate_voice_match_from_timeline(
    options: TimelineVoiceMatchOptions,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    inputs = prepare_timeline_voice_match_inputs(options.project, options.work_dir)
    _validate_timeline_voice_match_media(inputs)
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
    _install_comecut_media_probe(generator)
    remove_silence = bool(options.remove_silence)
    if remove_silence and not _smart_trimming_available():
        progress.emit(2, "Xóa khoảng lặng bị bỏ qua vì thiếu librosa/soundfile.")
        remove_silence = False
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
        remove_silence,
        bool(options.waveform_sync),
        None,
        bool(options.skip_stretch_shorter),
        bool(options.export_lt8),
    )
    if not result:
        last_step = progress.last_message.strip()
        detail = f" Bước cuối: {last_step}" if last_step else ""
        raise RuntimeError(
            "Tạo draft khớp voice thất bại."
            f"{detail} "
            "Nếu đang bật Xóa khoảng lặng, hãy thử tắt mục này "
            "hoặc cài thêm thư viện librosa/soundfile cho môi trường Python."
        )
    return Path(result)


def generate_voice_match_project_from_timeline(
    options: TimelineVoiceMatchOptions,
    progress_callback: ProgressCallback | None = None,
) -> TimelineVoiceMatchResult:
    output_json_path = generate_voice_match_from_timeline(options, progress_callback)
    matched_project = import_capcut_draft(output_json_path)
    project = build_direct_main_voice_match_project(options.project, matched_project)
    return TimelineVoiceMatchResult(
        output_json_path=output_json_path,
        project=project,
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
