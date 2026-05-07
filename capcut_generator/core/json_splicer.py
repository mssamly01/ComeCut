"""
Core Logic for Splicing/Respeeding Video and Text with a Priority Rule.
FINAL ROBUST VERSION: Handles JSON files with inconsistent segment structures,
especially regarding the 'extra_material_refs' for speed.
"""
import json
import copy
import uuid
import os
import bisect
from typing import Dict, List, Optional
from PyQt6.QtCore import pyqtSignal
from utils.logger import get_logger
from core.audio_video_sync import apply_audio_sync_to_draft

logger = get_logger(__name__)

TARGET_AUDIO_SPEED = 1.1 
SCREEN_BOUNDARY_TOLERANCE_US = 5_000
DEFAULT_TIMELINE_FPS = 30.0
CROSS_SCREEN_TEXT_MERGE_MAX_FRAMES = 10

def find_track_by_type(tracks: List[Dict], track_type: str) -> Optional[Dict]:
    """Finds the first track of a specific type."""
    for track in tracks:
        if track.get("type") == track_type:
            return track
    return None

def find_all_tracks_by_type(tracks: List[Dict], track_type: str) -> List[Dict]:
    """Finds all tracks of a specific type."""
    return [track for track in tracks if track.get("type") == track_type]

def create_new_speed_material(speed_value: float) -> Dict:
    """Helper to create a new, unique speed material dictionary."""
    return { "id": f"SPEED_MAT_{uuid.uuid4().hex.upper()}", "speed": speed_value, "type": "speed", "curve_speed": None, "mode": 0 }

def safe_set_speed_ref(segment: Dict, speed_material: Dict):
    """Safely sets the speed material reference in a segment."""
    if "extra_material_refs" not in segment or not isinstance(segment.get("extra_material_refs"), list):
        segment["extra_material_refs"] = []
    
    if len(segment["extra_material_refs"]) > 0:
        segment["extra_material_refs"][0] = speed_material["id"]
    else:
        segment["extra_material_refs"].append(speed_material["id"])

def resolve_screen_index(start_time_us: int, timestamp_screen_us: List[int]) -> int:
    """Resolve screen index from segment start (microseconds)."""
    if not timestamp_screen_us:
        return 0
    # Tolerance avoids boundary drift when source timestamps are rounded/truncated
    # a few hundred microseconds below the exact screen cut.
    return bisect.bisect_right(timestamp_screen_us, start_time_us + SCREEN_BOUNDARY_TOLERANCE_US)

def normalize_timestamp_screen_to_us(timestamp_screen: Optional[List[int]]) -> List[int]:
    """
    Normalize timestamp_screen to microseconds.

    Accepted input units:
    - Seconds (float/int) from config JSON
    - Milliseconds (int) from external tools
    - Microseconds (int) from advanced/manual input
    """
    if not timestamp_screen:
        return []

    numeric_values = []
    for ts in timestamp_screen:
        try:
            numeric_values.append(float(ts))
        except (TypeError, ValueError):
            logger.warning(f"Splicer: Ignoring invalid timestamp_screen value: {ts}")

    if not numeric_values:
        return []

    # Heuristic: distinguish microseconds, milliseconds, and seconds.
    max_value = max(abs(v) for v in numeric_values)
    has_fractional = any(not float(v).is_integer() for v in numeric_values)
    if max_value >= 100_000:
        normalized = [int(v) for v in numeric_values]
        logger.info("Splicer: timestamp_screen detected as microseconds")
    elif max_value >= 1_000 and not has_fractional:
        normalized = [int(v * 1_000) for v in numeric_values]
        logger.info("Splicer: timestamp_screen detected as milliseconds and converted to microseconds")
    else:
        normalized = [int(v * 1_000_000) for v in numeric_values]
        logger.info("Splicer: timestamp_screen detected as seconds and converted to microseconds")

    return sorted(normalized)

def collapse_video_segments_by_screen(
    video_segments: List[Dict],
    text_segments: List[Dict],
    audio_segments: List[Dict],
    timestamp_screen_us: List[int],
    speed_materials: List[Dict],
    fps: float = DEFAULT_TIMELINE_FPS,
    cross_text_merge_max_frames: int = CROSS_SCREEN_TEXT_MERGE_MAX_FRAMES,
) -> List[Dict]:
    """
    Collapse consecutive video segments into one segment per screen.

    Text/audio segments keep their own target positions; only group metadata is updated
    to point to the collapsed screen-level video segment.
    """
    if not video_segments or not timestamp_screen_us:
        return video_segments

    last_boundary = int(timestamp_screen_us[-1])
    max_source_end = max(
        int(seg.get("source_timerange", {}).get("start", 0)) + int(seg.get("source_timerange", {}).get("duration", 0))
        for seg in video_segments
    )
    max_target_end = max(
        int(seg.get("target_timerange", {}).get("start", 0)) + int(seg.get("target_timerange", {}).get("duration", 0))
        for seg in video_segments
    )
    use_target_boundaries = abs(last_boundary - max_target_end) < abs(last_boundary - max_source_end)
    logger.info(
        "Splicer: Interpreting screen boundaries as %s timeline",
        "target" if use_target_boundaries else "source",
    )

    def split_segment_at_screen_boundaries(seg: Dict) -> List[Dict]:
        src = seg.get("source_timerange") or {}
        tgt = seg.get("target_timerange") or {}
        src_start = int(src.get("start", 0))
        src_dur = int(src.get("duration", 0))
        tgt_start = int(tgt.get("start", 0))
        tgt_dur = int(tgt.get("duration", 0))

        if src_dur <= 0 or tgt_dur <= 0:
            return [seg]

        if use_target_boundaries:
            tgt_end = tgt_start + tgt_dur
            internal_cuts = [b for b in timestamp_screen_us if tgt_start < b < tgt_end]
            if not internal_cuts:
                return [seg]

            cut_points = [tgt_start, *internal_cuts, tgt_end]
            split_parts = []
            running_src_start = src_start
            remaining_src = src_dur
            remaining_tgt = tgt_dur

            for i in range(len(cut_points) - 1):
                part_tgt_start = cut_points[i]
                part_tgt_dur = int(cut_points[i + 1] - cut_points[i])
                if part_tgt_dur <= 0:
                    continue

                is_last = i == (len(cut_points) - 2)
                if is_last:
                    part_src_dur = max(1, remaining_src)
                else:
                    tentative = int(round((part_tgt_dur / max(1, remaining_tgt)) * remaining_src))
                    parts_left = (len(cut_points) - 1) - i
                    min_reserved_for_rest = parts_left - 1
                    max_allowed = max(1, remaining_src - min_reserved_for_rest)
                    part_src_dur = min(max(1, tentative), max_allowed)

                part = copy.deepcopy(seg)
                part["id"] = f"SPLIT_{uuid.uuid4().hex}"
                part["source_timerange"] = {"start": int(running_src_start), "duration": int(part_src_dur)}
                part["target_timerange"] = {"start": int(part_tgt_start), "duration": int(part_tgt_dur)}
                part["speed"] = (part_src_dur / part_tgt_dur) if part_tgt_dur > 0 else seg.get("speed", 1.0)
                split_parts.append(part)

                running_src_start += part_src_dur
                remaining_src -= part_src_dur
                remaining_tgt -= part_tgt_dur

            return split_parts if split_parts else [seg]

        src_end = src_start + src_dur
        internal_cuts = [b for b in timestamp_screen_us if src_start < b < src_end]
        if not internal_cuts:
            return [seg]

        cut_points = [src_start, *internal_cuts, src_end]
        split_parts = []
        running_tgt_start = tgt_start
        remaining_src = src_dur
        remaining_tgt = tgt_dur

        for i in range(len(cut_points) - 1):
            part_src_start = cut_points[i]
            part_src_dur = int(cut_points[i + 1] - cut_points[i])
            if part_src_dur <= 0:
                continue

            is_last = i == (len(cut_points) - 2)
            if is_last:
                part_tgt_dur = max(1, remaining_tgt)
            else:
                # Proportional split in target timeline with rounding safeguards.
                tentative = int(round((part_src_dur / max(1, remaining_src)) * remaining_tgt))
                parts_left = (len(cut_points) - 1) - i
                min_reserved_for_rest = parts_left - 1
                max_allowed = max(1, remaining_tgt - min_reserved_for_rest)
                part_tgt_dur = min(max(1, tentative), max_allowed)

            part = copy.deepcopy(seg)
            part["id"] = f"SPLIT_{uuid.uuid4().hex}"
            part["source_timerange"] = {"start": int(part_src_start), "duration": int(part_src_dur)}
            part["target_timerange"] = {"start": int(running_tgt_start), "duration": int(part_tgt_dur)}
            part["speed"] = (part_src_dur / part_tgt_dur) if part_tgt_dur > 0 else seg.get("speed", 1.0)
            split_parts.append(part)

            running_tgt_start += part_tgt_dur
            remaining_src -= part_src_dur
            remaining_tgt -= part_tgt_dur

        return split_parts if split_parts else [seg]

    sorted_video = sorted(video_segments, key=lambda s: s.get("target_timerange", {}).get("start", 0))
    expanded_video = []
    for seg in sorted_video:
        expanded_video.extend(split_segment_at_screen_boundaries(seg))

    grouped = []
    for seg in expanded_video:
        boundary_start = seg.get("target_timerange", {}).get("start", 0) if use_target_boundaries else seg.get("source_timerange", {}).get("start", 0)
        screen_idx = bisect.bisect_right(timestamp_screen_us, int(boundary_start) + SCREEN_BOUNDARY_TOLERANCE_US)
        if not grouped or grouped[-1]["screen_idx"] != screen_idx:
            grouped.append({"screen_idx": screen_idx, "segments": [seg]})
        else:
            grouped[-1]["segments"].append(seg)

    collapsed = []
    screen_ranges = []
    for group in grouped:
        segs = group["segments"]
        first = segs[0]

        if len(segs) == 1:
            only_seg = first
            target_start = only_seg.get("target_timerange", {}).get("start", 0)
            target_duration = only_seg.get("target_timerange", {}).get("duration", 0)
            screen_ranges.append(
                {
                    "start": target_start,
                    "end": target_start + target_duration,
                    "group_id": only_seg.get("group_id", ""),
                    "raw_segment_id": only_seg.get("raw_segment_id", ""),
                }
            )
            collapsed.append(only_seg)
            continue

        source_start = first.get("source_timerange", {}).get("start", 0)
        source_end = max(
            (s.get("source_timerange", {}).get("start", 0) + s.get("source_timerange", {}).get("duration", 0))
            for s in segs
        )

        target_start = first.get("target_timerange", {}).get("start", 0)
        target_end = max(
            (s.get("target_timerange", {}).get("start", 0) + s.get("target_timerange", {}).get("duration", 0))
            for s in segs
        )

        source_duration = max(1, int(source_end - source_start))
        target_duration = max(1, int(target_end - target_start))
        merged_speed = source_duration / target_duration

        merged_seg = copy.deepcopy(first)
        merged_seg["id"] = f"SCREEN_{uuid.uuid4().hex}"
        merged_seg["source_timerange"] = {"start": int(source_start), "duration": int(source_duration)}
        merged_seg["target_timerange"] = {"start": int(target_start), "duration": int(target_duration)}
        merged_seg["speed"] = merged_speed

        merged_group_id = first.get("group_id") or str(uuid.uuid4()).upper()
        merged_raw_id = first.get("raw_segment_id") or str(uuid.uuid4()).upper()
        merged_seg["group_id"] = merged_group_id
        merged_seg["raw_segment_id"] = merged_raw_id

        merged_speed_mat = create_new_speed_material(merged_speed)
        speed_materials.append(merged_speed_mat)
        safe_set_speed_ref(merged_seg, merged_speed_mat)

        collapsed.append(merged_seg)
        screen_ranges.append(
            {
                "start": target_start,
                "end": target_start + target_duration,
                "group_id": merged_group_id,
                "raw_segment_id": merged_raw_id,
            }
        )

        logger.info(
            "Splicer: Collapsed Screen %s from %s video segments into 1",
            group["screen_idx"],
            len(segs),
        )

    # Merge consecutive screens that contain only gap (no text/audio content).
    if collapsed:
        effective_fps = float(fps) if isinstance(fps, (int, float)) and float(fps) > 0 else DEFAULT_TIMELINE_FPS
        frame_duration_us = max(1, int(round(1_000_000 / effective_fps)))
        max_cross_text_overlap_us = max(0, int(cross_text_merge_max_frames)) * frame_duration_us

        def overlaps_screen(seg_range: tuple, screen_info: Dict) -> bool:
            seg_start, seg_end = seg_range
            return seg_start < screen_info["end"] and seg_end > screen_info["start"]

        def overlap_duration_us(seg_range: tuple, screen_info: Dict) -> int:
            seg_start, seg_end = seg_range
            overlap_start = max(seg_start, int(screen_info["start"]))
            overlap_end = min(seg_end, int(screen_info["end"]))
            return max(0, int(overlap_end - overlap_start))

        def clamp_minor_cross_overlap(segments: List[Dict], segment_label: str):
            adjusted = 0
            for seg in segments:
                target_timerange = seg.get("target_timerange") or {}
                seg_start = target_timerange.get("start")
                seg_duration = target_timerange.get("duration", 0)
                if seg_start is None or seg_duration <= 0:
                    continue

                seg_start = int(seg_start)
                seg_end = seg_start + int(seg_duration)

                for idx in range(len(screen_ranges) - 1):
                    left = screen_ranges[idx]
                    right = screen_ranges[idx + 1]
                    left_overlap = overlap_duration_us((seg_start, seg_end), left)
                    right_overlap = overlap_duration_us((seg_start, seg_end), right)
                    if left_overlap <= 0 or right_overlap <= 0:
                        continue

                    minor_overlap = min(left_overlap, right_overlap)
                    if minor_overlap > max_cross_text_overlap_us:
                        continue

                    if left_overlap >= right_overlap:
                        new_start = max(seg_start, int(left["start"]))
                        new_end = min(seg_end, int(left["end"]))
                    else:
                        new_start = max(seg_start, int(right["start"]))
                        new_end = min(seg_end, int(right["end"]))

                    if new_end > new_start:
                        seg.setdefault("target_timerange", {})["start"] = int(new_start)
                        seg["target_timerange"]["duration"] = int(max(1, new_end - new_start))
                        adjusted += 1
                    break

            if adjusted:
                logger.info(
                    "Splicer: Snapped %s %s segments with minor cross-screen overlap (<= %s frames)",
                    adjusted,
                    segment_label,
                    cross_text_merge_max_frames,
                )

        # For tiny spill-over (<= 10 frames), keep one screen and snap segment timing to that screen.
        clamp_minor_cross_overlap(text_segments, "text")
        clamp_minor_cross_overlap(audio_segments, "audio")

        text_ranges = [
            (
                int(seg.get("target_timerange", {}).get("start", 0)),
                int(seg.get("target_timerange", {}).get("start", 0)) + max(1, int(seg.get("target_timerange", {}).get("duration", 0))),
            )
            for seg in text_segments
            if seg.get("target_timerange", {}).get("start") is not None
        ]
        audio_content_ranges = [
            (
                int(seg.get("target_timerange", {}).get("start", 0)),
                int(seg.get("target_timerange", {}).get("start", 0)) + max(1, int(seg.get("target_timerange", {}).get("duration", 0))),
            )
            for seg in audio_segments
            if seg.get("material_id") and seg.get("target_timerange", {}).get("start") is not None
        ]

        content_ranges = [*text_ranges, *audio_content_ranges]

        def has_content_in_range(screen_info: Dict) -> bool:
            for seg_range in content_ranges:
                if overlaps_screen(seg_range, screen_info):
                    return True
            return False

        def has_cross_content_between(prev_screen: Dict, cur_screen: Dict) -> bool:
            # Merge screens only when text overlap across boundary is significant (> threshold).
            for seg_range in text_ranges:
                prev_overlap = overlap_duration_us(seg_range, prev_screen)
                cur_overlap = overlap_duration_us(seg_range, cur_screen)
                if prev_overlap > 0 and cur_overlap > 0:
                    if min(prev_overlap, cur_overlap) > max_cross_text_overlap_us:
                        return True
            return False

        merged_collapsed = []
        merged_ranges = []
        merged_content_flags = []

        for idx, seg in enumerate(collapsed):
            info = screen_ranges[idx]
            has_content = has_content_in_range(info)
            cross_content = False

            should_merge = False
            if merged_collapsed:
                prev_has_content = merged_content_flags[-1]
                cross_content = has_cross_content_between(merged_ranges[-1], info)
                should_merge = ((not has_content and not prev_has_content) or cross_content)

            if should_merge:
                prev_seg = merged_collapsed[-1]
                prev_info = merged_ranges[-1]

                prev_src_start = int(prev_seg.get("source_timerange", {}).get("start", 0))
                prev_src_end = prev_src_start + int(prev_seg.get("source_timerange", {}).get("duration", 0))
                cur_src_start = int(seg.get("source_timerange", {}).get("start", 0))
                cur_src_end = cur_src_start + int(seg.get("source_timerange", {}).get("duration", 0))

                prev_tgt_start = int(prev_seg.get("target_timerange", {}).get("start", 0))
                prev_tgt_end = prev_tgt_start + int(prev_seg.get("target_timerange", {}).get("duration", 0))
                cur_tgt_start = int(seg.get("target_timerange", {}).get("start", 0))
                cur_tgt_end = cur_tgt_start + int(seg.get("target_timerange", {}).get("duration", 0))

                new_src_start = min(prev_src_start, cur_src_start)
                new_src_end = max(prev_src_end, cur_src_end)
                new_tgt_start = min(prev_tgt_start, cur_tgt_start)
                new_tgt_end = max(prev_tgt_end, cur_tgt_end)

                new_src_duration = max(1, int(new_src_end - new_src_start))
                new_tgt_duration = max(1, int(new_tgt_end - new_tgt_start))
                new_speed = new_src_duration / new_tgt_duration

                prev_seg["source_timerange"] = {"start": new_src_start, "duration": new_src_duration}
                prev_seg["target_timerange"] = {"start": new_tgt_start, "duration": new_tgt_duration}
                prev_seg["speed"] = new_speed

                merged_speed_mat = create_new_speed_material(new_speed)
                speed_materials.append(merged_speed_mat)
                safe_set_speed_ref(prev_seg, merged_speed_mat)

                prev_info["start"] = min(prev_info["start"], info["start"])
                prev_info["end"] = max(prev_info["end"], info["end"])
                merged_content_flags[-1] = merged_content_flags[-1] or has_content or cross_content

                if cross_content:
                    logger.info(
                        "Splicer: Merged screens due to significant cross-screen text overlap (> %s frames)",
                        cross_text_merge_max_frames,
                    )
                else:
                    logger.info("Splicer: Merged consecutive gap-only screens")
            else:
                merged_collapsed.append(seg)
                merged_ranges.append(dict(info))
                merged_content_flags.append(has_content)

        collapsed = merged_collapsed
        screen_ranges = merged_ranges

    # Re-assign group metadata so text/audio remain attached to the collapsed screen segment.
    for collection in (text_segments, audio_segments):
        for seg in collection:
            seg_start = seg.get("target_timerange", {}).get("start")
            if seg_start is None:
                continue
            for idx, screen_info in enumerate(screen_ranges):
                is_last = idx == len(screen_ranges) - 1
                if seg_start >= screen_info["start"] and (seg_start < screen_info["end"] or (is_last and seg_start <= screen_info["end"])):
                    seg["group_id"] = screen_info["group_id"]
                    seg["raw_segment_id"] = screen_info["raw_segment_id"]
                    break

    used_speed_ids = set()
    for collection in (collapsed, audio_segments):
        for seg in collection:
            refs = seg.get("extra_material_refs")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, str):
                    used_speed_ids.add(ref)

    if speed_materials is not None:
        before_speed_count = len(speed_materials)
        speed_materials[:] = [
            speed_mat for speed_mat in speed_materials
            if speed_mat.get("id") in used_speed_ids
        ]
        removed_speed_count = before_speed_count - len(speed_materials)
        if removed_speed_count > 0:
            logger.info(
                "Splicer: Pruned %s unreferenced speed materials after screen collapse",
                removed_speed_count,
            )

    return collapsed

def normalize_audio_and_group_segments(video_segments: List[Dict], text_segments: List[Dict], audio_segments: List[Dict], audio_template: Dict, draft_data: Dict, remove_silence: bool = False, processor = None) -> List[Dict]:
    if not video_segments or not audio_segments:
        return audio_segments
    
    template_audio = copy.deepcopy(next((s for s in audio_segments if s.get("material_id")), audio_template))
    template_refs = (template_audio.get("extra_material_refs") or [])[1:]
    
    audio_by_start = {}
    for seg in audio_segments:
        start = seg.get("target_timerange", {}).get("start")
        if start is not None:
            if start not in audio_by_start:
                audio_by_start[start] = []
            audio_by_start[start].append(seg)
    
    text_by_start = {}
    for seg in text_segments:
        start = seg.get("target_timerange", {}).get("start")
        if start is not None:
            text_by_start[start] = seg
            
    audio_mats = {m["id"]: m for m in draft_data.get("materials", {}).get("audios", [])}
    text_mats = {m["id"]: m for m in draft_data.get("materials", {}).get("texts", [])}
    
    normalized_audio = []
    for idx, video_seg in enumerate(video_segments):
        timerange = video_seg.get("target_timerange", {})
        start = timerange.get("start", 0)
        duration = timerange.get("duration", 0)
        
        group_id = video_seg.get("group_id") or str(uuid.uuid4()).upper()
        bundle_id = video_seg.get("raw_segment_id") or str(uuid.uuid4()).upper()
        video_seg["group_id"] = group_id
        video_seg["raw_segment_id"] = bundle_id
        video_seg["render_index"] = idx
        
        text_seg = text_by_start.get(start)
        if text_seg is not None:
            text_seg["group_id"] = group_id
            text_seg["raw_segment_id"] = bundle_id
        
        audio_segs = audio_by_start.get(start, [])
        for audio_seg in audio_segs:
            audio_seg.setdefault("target_timerange", {})
            audio_seg["target_timerange"]["start"] = start
            
            source_timerange = audio_seg.get("source_timerange")
            if isinstance(source_timerange, dict):
                source_timerange["start"] = source_timerange.get("start", 0)
        
            speed_ref = None
            audio_refs = audio_seg.get("extra_material_refs") or []
            if audio_refs:
                speed_ref = audio_refs[0]
            
            if speed_ref:
                audio_seg["extra_material_refs"] = [speed_ref, *template_refs]
            
            audio_seg["group_id"] = group_id
            audio_seg["raw_segment_id"] = bundle_id
            audio_seg["render_index"] = idx
            
            if text_seg:
                a_mat_id = audio_seg.get("material_id")
                t_mat_id = text_seg.get("material_id")
                if a_mat_id in audio_mats and t_mat_id in text_mats:
                    a_mat = audio_mats[a_mat_id]
                    t_mat = text_mats[t_mat_id]
                    a_mat["type"] = "text_to_audio"
                    a_mat["text_id"] = t_mat_id
                    if "text_to_audio_ids" not in t_mat:
                        t_mat["text_to_audio_ids"] = []
                    if audio_seg["id"] not in t_mat["text_to_audio_ids"]:
                        t_mat["text_to_audio_ids"].append(audio_seg["id"])
                        
            normalized_audio.append(audio_seg)
    
    return normalized_audio

def splice_video_track(draft_data: Dict, target_audio_speed: float, mode: str, keep_pitch: bool, progress_callback: Optional[pyqtSignal] = None, video_speed_enabled: bool = False, target_video_speed: float = 1.0, remove_silence: bool = False, project_dir: Optional[str] = None, waveform_sync: bool = False, timestamp_screen: Optional[List[int]] = None, skip_stretch_shorter: bool = False) -> Optional[Dict]:
    """Performs audio-mastered splicing with robust handling of JSON structure."""
    def emit_progress(percent, message):
        if progress_callback:
            progress_callback.emit(percent, message)
            
    try:
        emit_progress(0, f"Starting Splice process. Mode: '{mode}'...")
        
        modified_data = copy.deepcopy(draft_data)
        tracks = modified_data.get("tracks", [])

        # ... [omitted silence removal logic for brevity in this view, tool will handle replacement] ...
        # (I will use a more precise TargetContent to avoid long replacement)

        # Process silence removal if requested
        processor = None  # Ensure processor is always defined
        if remove_silence:
            from core.audio_video_sync import AudioVideoSyncProcessor
            import time
            _proc = AudioVideoSyncProcessor()
            if _proc.is_available():
                emit_progress(5, "Processing silence removal for audio materials...")
                # Collect all potential audio materials
                all_mats = []
                if "materials" in modified_data:
                    for cat in ["audios", "videos"]:
                        all_mats.extend(modified_data["materials"].get(cat, []))

                # Determine output directory based on first valid audio path
                import tempfile
                audio_base_dir = tempfile.gettempdir()  # Safe default
                for mat in all_mats:
                    if mat.get("type") in ["extract_music", "audio", "text_to_audio", "cloud_music"]:
                        test_path = mat.get("path")
                        if not test_path:
                            continue
                        if "##_draftpath_placeholder_" in test_path and project_dir:
                            import re
                            test_path = re.sub(
                                r'##_draftpath_placeholder_.*?_##[/\\]?',
                                lambda _: project_dir + os.sep,
                                test_path
                            )
                            test_path = os.path.normpath(test_path)
                        elif project_dir and not os.path.isabs(test_path):
                            test_path = os.path.join(project_dir, test_path)

                        if os.path.exists(test_path):
                            audio_base_dir = os.path.dirname(os.path.abspath(test_path))
                            break

                temp_dir = os.path.join(audio_base_dir, f"splicer_silence_{int(time.time())}")
                if not os.path.exists(temp_dir):
                    os.makedirs(temp_dir)

                emit_progress(5, f"Analyzing {len(all_mats)} materials for silence removal...")
                processor = _proc  # Only assign if available
            else:
                logger.warning("Silence removal requested in splicer but libraries (librosa/soundfile) missing.")

        text_track = find_track_by_type(tracks, "text")
        video_track = find_track_by_type(tracks, "video")
        all_audio_tracks = find_all_tracks_by_type(tracks, "audio")

        if not all([text_track, video_track, all_audio_tracks]):
            logger.error("Splice failed: Critical tracks not found.")
            return None

        video_template = copy.deepcopy(video_track["segments"][0])
        audio_template = copy.deepcopy(all_audio_tracks[0]["segments"][0])
        
        video_materials_map = {mat["id"]: mat for mat in modified_data.get("materials", {}).get("videos", [])}
        total_original_video_duration = video_materials_map.get(video_template.get("material_id"), {}).get("duration")
        if not total_original_video_duration:
             msg = "Splice failed: Could not determine original video duration."
             logger.error(msg)
             with open("splicer_error.log", "w", encoding="utf-8") as f: f.write(msg)
             return None
        
        emit_progress(10, "Analyzing text and audio segments...")
        sorted_text_segments = sorted(text_track.get("segments", []), key=lambda s: s.get("target_timerange", {}).get("start", 0))
        all_original_audio_segments = [seg for track in all_audio_tracks for seg in track.get("segments", [])]
        sorted_audio_segments = sorted(all_original_audio_segments, key=lambda s: s.get("target_timerange", {}).get("start", 0))
        
        if len(sorted_text_segments) != len(sorted_audio_segments):
            logger.error(f"FATAL MISMATCH: {len(sorted_text_segments)} text vs {len(sorted_audio_segments)} audio segments. Aborting.")
            return None

        audio_materials_map = {mat["id"]: mat for mat in modified_data.get("materials", {}).get("audios", [])}
        
        new_video_segments, new_audio_segments, new_text_segments = [], [], []
        new_speed_materials = []
        current_timeline_time = 0
        last_original_text_end_time = 0
        # Lưu giá trị gốc từ user, KHÔNG bao giờ ghi đè bên trong vòng lặp
        user_target_audio_speed = target_audio_speed

        # Screen-based speed sync initialization
        # Prioritize passed timestamp_screen, then fallback to JSON data
        if timestamp_screen is None:
            timestamp_screen = modified_data.get("timestamp_screen", modified_data.get("timetamp_screen", []))
        
        # Normalize timestamp_screen to microseconds (accept seconds or microseconds)
        timestamp_screen = normalize_timestamp_screen_to_us(timestamp_screen)
        if timestamp_screen:
            logger.info(f"Splicer: Screen boundary logic enabled. Timestamps (us): {timestamp_screen}")

        # Pre-calculate stable speed per screen for video_priority mode so gaps and segments
        # in the same screen always share one video speed.
        precomputed_trim_map = {}
        precomputed_screen_speeds = {}
        if timestamp_screen and mode == 'video_priority':
            emit_progress(12, "Pre-calculating screen speeds...")
            baseline_video_speed = target_video_speed if (video_speed_enabled or target_video_speed != 1.0) else 1.0
            screen_stats = {}

            for i, (text_seg, audio_seg) in enumerate(zip(sorted_text_segments, sorted_audio_segments)):
                audio_mat = audio_materials_map.get(audio_seg.get("material_id"))
                if not audio_mat:
                    continue

                original_audio_duration = audio_mat.get("duration", 0)
                if not original_audio_duration:
                    continue

                original_timerange = text_seg.get("target_timerange", {})
                original_start_time = original_timerange.get("start")
                original_video_duration = original_timerange.get("duration")
                if original_start_time is None or not original_video_duration:
                    continue

                source_start = 0
                source_duration = original_audio_duration
                if remove_silence and processor:
                    try:
                        trim_start, trim_end = processor.find_speech_range(audio_mat["path"])
                        if trim_end > trim_start:
                            source_start = int(trim_start * 1000000)
                            trimmed_dur = int((trim_end - trim_start) * 1000000)
                            source_duration = max(100000, trimmed_dur)
                    except Exception as e:
                        logger.error(f"Failed to pre-calculate smart trim audio: {e}")

                precomputed_trim_map[i] = (source_start, source_duration)

                if user_target_audio_speed > 0:
                    audio_timeline_duration = int(source_duration / user_target_audio_speed)
                else:
                    audio_timeline_duration = source_duration

                if baseline_video_speed != 1.0:
                    video_timeline_duration = int(original_video_duration / baseline_video_speed)
                else:
                    video_timeline_duration = original_video_duration

                screen_idx = resolve_screen_index(original_start_time, timestamp_screen)
                stats = screen_stats.setdefault(
                    screen_idx,
                    {
                        "video_source_total": 0,
                        "video_timeline_total": 0,
                        "audio_timeline_total": 0,
                    },
                )
                stats["video_source_total"] += original_video_duration
                stats["video_timeline_total"] += video_timeline_duration
                stats["audio_timeline_total"] += audio_timeline_duration

            for screen_idx, stats in screen_stats.items():
                screen_video_speed = baseline_video_speed
                if (
                    not skip_stretch_shorter
                    and stats["audio_timeline_total"] > stats["video_timeline_total"]
                    and stats["audio_timeline_total"] > 0
                ):
                    screen_video_speed = stats["video_source_total"] / stats["audio_timeline_total"]

                precomputed_screen_speeds[screen_idx] = (screen_video_speed, user_target_audio_speed)
                logger.info(
                    "Splicer: Precomputed Screen %s speed -> video=%.6f, audio=%.6f "
                    "(video_timeline=%dus, audio_timeline=%dus)",
                    screen_idx,
                    screen_video_speed,
                    user_target_audio_speed,
                    stats["video_timeline_total"],
                    stats["audio_timeline_total"],
                )
        
        current_screen_idx = 0
        screen_speeds = dict(precomputed_screen_speeds) # screen_idx -> (video_speed, audio_speed)

        def get_or_compute_screen_speed(screen_idx: int):
            cached = screen_speeds.get(screen_idx)
            if cached:
                return cached

            if not timestamp_screen or mode != 'video_priority':
                return None

            baseline_video_speed = target_video_speed if (video_speed_enabled or target_video_speed != 1.0) else 1.0
            stats = {
                "video_source_total": 0,
                "video_timeline_total": 0,
                "audio_timeline_total": 0,
            }

            for j, (screen_text_seg, screen_audio_seg) in enumerate(zip(sorted_text_segments, sorted_audio_segments)):
                screen_timerange = screen_text_seg.get("target_timerange", {})
                screen_start = screen_timerange.get("start")
                screen_video_duration = screen_timerange.get("duration")
                if screen_start is None or not screen_video_duration:
                    continue

                if resolve_screen_index(screen_start, timestamp_screen) != screen_idx:
                    continue

                screen_audio_mat = audio_materials_map.get(screen_audio_seg.get("material_id"))
                if not screen_audio_mat:
                    continue

                screen_audio_original_duration = screen_audio_mat.get("duration", 0)
                if not screen_audio_original_duration:
                    continue

                if j in precomputed_trim_map:
                    _, screen_source_duration = precomputed_trim_map[j]
                else:
                    screen_source_duration = screen_audio_original_duration

                if user_target_audio_speed > 0:
                    screen_audio_timeline_duration = int(screen_source_duration / user_target_audio_speed)
                else:
                    screen_audio_timeline_duration = screen_source_duration

                if baseline_video_speed != 1.0:
                    screen_video_timeline_duration = int(screen_video_duration / baseline_video_speed)
                else:
                    screen_video_timeline_duration = screen_video_duration

                stats["video_source_total"] += screen_video_duration
                stats["video_timeline_total"] += screen_video_timeline_duration
                stats["audio_timeline_total"] += screen_audio_timeline_duration

            if stats["video_source_total"] <= 0:
                return None

            screen_video_speed = baseline_video_speed
            if (
                not skip_stretch_shorter
                and stats["audio_timeline_total"] > stats["video_timeline_total"]
                and stats["audio_timeline_total"] > 0
            ):
                screen_video_speed = stats["video_source_total"] / stats["audio_timeline_total"]

            result = (screen_video_speed, user_target_audio_speed)
            screen_speeds[screen_idx] = result
            logger.info(
                "Splicer: On-demand Screen %s speed -> video=%.6f, audio=%.6f",
                screen_idx,
                screen_video_speed,
                user_target_audio_speed,
            )
            return result
        
        # Pointer to the next threshold we are waiting for
        next_ts_ptr = 0
        next_screen_threshold = timestamp_screen[0] if timestamp_screen else float('inf')
        
        total_segments_to_process = len(sorted_text_segments)
        for i, text_seg in enumerate(sorted_text_segments):
            emit_progress(15 + int((i / total_segments_to_process) * 75), f"Processing segment {i+1}/{total_segments_to_process}...")
            
            audio_seg = sorted_audio_segments[i]
            audio_mat = audio_materials_map.get(audio_seg.get("material_id"))
            if not audio_mat: continue
            
            original_audio_duration = audio_mat.get("duration", 0)
            if not original_audio_duration: continue

            original_timerange = text_seg.get("target_timerange", {})
            original_start_time = original_timerange.get("start")
            original_video_duration = original_timerange.get("duration")
            if original_start_time is None or not original_video_duration: continue
            
            seg_original_end = original_start_time + original_video_duration

            # Determine Screen Index: Advance pointer if this segment starts after/at current threshold
            prev_idx = current_screen_idx
            if timestamp_screen: # ONLY use screen logic if timestamps are provided
                while next_ts_ptr < len(timestamp_screen) and (original_start_time + SCREEN_BOUNDARY_TOLERANCE_US) >= timestamp_screen[next_ts_ptr]:
                    next_ts_ptr += 1
                    current_screen_idx = next_ts_ptr # Screen index follows the pointer (0, 1, 2...)
                
                if current_screen_idx != prev_idx:
                    logger.info(f"Splicer: Segment {i+1} crossed threshold. New Screen Index: {current_screen_idx}")

                # Update next threshold for future segments
                if next_ts_ptr < len(timestamp_screen):
                    next_screen_threshold = timestamp_screen[next_ts_ptr]
                else:
                    next_screen_threshold = float('inf')

            cached_speed = None
            if timestamp_screen:
                cached_speed = get_or_compute_screen_speed(current_screen_idx)
                if cached_speed:
                    logger.debug(f"Splicer: Segment {i+1} using cached speed for Screen {current_screen_idx}: {cached_speed}")

            # --- GAP HANDLING ---
            if original_start_time > last_original_text_end_time:
                gap_duration = original_start_time - last_original_text_end_time
                
                # Gap speed logic: uses cached screen speed if available, else baseline
                if cached_speed:
                    gap_video_speed = cached_speed[0]
                else:
                    gap_video_speed = target_video_speed if (video_speed_enabled or target_video_speed != 1.0) else 1.0
                
                gap_duration_on_timeline = int(gap_duration / gap_video_speed) if gap_video_speed != 1.0 else gap_duration
                
                gap_speed_mat = create_new_speed_material(gap_video_speed); new_speed_materials.append(gap_speed_mat)
                gap_segment = copy.deepcopy(video_template); gap_segment.update({"id": f"GAP_{uuid.uuid4().hex}", "target_timerange": {"start": current_timeline_time, "duration": gap_duration_on_timeline}, "source_timerange": {"start": last_original_text_end_time, "duration": gap_duration}, "speed": gap_video_speed}); 
                safe_set_speed_ref(gap_segment, gap_speed_mat)
                new_video_segments.append(gap_segment)
                current_timeline_time += gap_duration_on_timeline

            # --- SMART TRIMMING (METADATA-ONLY) ---
            if i in precomputed_trim_map:
                source_start, source_duration = precomputed_trim_map[i]
            else:
                source_start = 0
                source_duration = original_audio_duration
                if remove_silence and processor:
                    try:
                        trim_start, trim_end = processor.find_speech_range(audio_mat["path"])
                        # Only apply trim if speech was actually detected
                        if trim_end > trim_start:
                            source_start = int(trim_start * 1000000)
                            trimmed_dur = int((trim_end - trim_start) * 1000000)
                            source_duration = max(100000, trimmed_dur)
                            logger.debug(f"Smart Trimmed {os.path.basename(audio_mat['path'])}: {trim_start:.2f}s - {trim_end:.2f}s")
                        else:
                            logger.debug(f"No speech detected in {os.path.basename(audio_mat.get('path','?'))} – keeping original duration")
                    except Exception as e:
                        logger.error(f"Failed to smart trim audio: {e}")

            # Use trimmed duration for all subsequent calculations
            effective_audio_duration = source_duration

            # Dùng user_target_audio_speed (không thay đổi) để tính duration gốc
            new_audio_target_duration = int(effective_audio_duration / user_target_audio_speed)
            # actual_audio_speed: speed thực tế cho segment này (có thể khác nếu mode điều chỉnh)
            actual_audio_speed = user_target_audio_speed
            actual_audio_duration = new_audio_target_duration

            # Only use cached speed if screen sync is active (timestamps provided)
            if cached_speed is None and timestamp_screen:
                cached_speed = get_or_compute_screen_speed(current_screen_idx)
            if cached_speed:
                new_video_speed, actual_audio_speed = cached_speed
                logger.debug(f"Splicer: Segment {i+1} using cached speed for Screen {current_screen_idx}: {(new_video_speed, actual_audio_speed)}")
                new_video_duration_on_timeline = int(original_video_duration / new_video_speed)
                actual_audio_duration = int(effective_audio_duration / actual_audio_speed)
            else:
                # First segment of the screen - Calculate baseline video speed
                baseline_video_speed = target_video_speed if (video_speed_enabled or target_video_speed != 1.0) else 1.0
                adjusted_video_duration = int(original_video_duration / baseline_video_speed)
                new_video_speed = baseline_video_speed
                new_video_duration_on_timeline = adjusted_video_duration

                if mode == 'audio_sync' or mode == 'audio_sync_priority':
                    # Audio sync modes: Video follows baseline speed, Audio stretches to match
                    calculated_audio_speed = effective_audio_duration / new_video_duration_on_timeline if new_video_duration_on_timeline > 0 else 1.0

                    if mode == 'audio_sync_priority' and new_video_duration_on_timeline > actual_audio_duration:
                        # Priority: video dài hơn audio → giữ nguyên tốc độ audio gốc của user
                        pass
                    elif skip_stretch_shorter and actual_audio_duration < new_video_duration_on_timeline:
                        # Không co giãn audio nếu audio ngắn hơn video
                        pass
                    else:
                        # Standard sync: kéo giãn audio theo video → speed tính theo tỉ lệ thực tế
                        actual_audio_speed = calculated_audio_speed
                        actual_audio_duration = new_video_duration_on_timeline
                elif mode == 'video_priority':
                    if actual_audio_duration > adjusted_video_duration:
                        if skip_stretch_shorter:
                            # Giữ nguyên video speed baseline
                            new_video_speed = baseline_video_speed
                            new_video_duration_on_timeline = adjusted_video_duration
                        else:
                            # Video ngắn hơn audio: kéo giãn video để khớp audio
                            new_video_speed = original_video_duration / actual_audio_duration if actual_audio_duration > 0 else 1.0
                            new_video_duration_on_timeline = actual_audio_duration
                    else:
                        # Video dài hơn audio (hoặc bằng) → giữ nguyên video speed baseline
                        new_video_speed = baseline_video_speed
                        new_video_duration_on_timeline = adjusted_video_duration
                else:
                    # force_sync: luôn kéo giãn video theo audio, audio giữ đúng target_audio_speed
                    new_video_speed = original_video_duration / actual_audio_duration if actual_audio_duration > 0 else 1.0
                    new_video_duration_on_timeline = actual_audio_duration
                
                # Cache the results for this screen
                if timestamp_screen:
                    screen_speeds[current_screen_idx] = (new_video_speed, actual_audio_speed)
                    logger.info(f"Splicer: Cached speed for Screen {current_screen_idx}: {screen_speeds[current_screen_idx]}")

            # Boundary check for logging (informational)
            if timestamp_screen and seg_original_end > next_screen_threshold:
                next_screen_threshold = seg_original_end

            vid_speed_mat = create_new_speed_material(new_video_speed); new_speed_materials.append(vid_speed_mat)
            new_vid_seg = copy.deepcopy(video_template); 
            safe_set_speed_ref(new_vid_seg, vid_speed_mat)
            new_vid_seg.update({"id": f"VID_{uuid.uuid4().hex}", "target_timerange": {"start": current_timeline_time, "duration": new_video_duration_on_timeline}, "source_timerange": {"start": original_start_time, "duration": original_video_duration}, "speed": new_video_speed}); 
            new_video_segments.append(new_vid_seg)

            new_txt_seg = copy.deepcopy(text_seg); new_txt_seg.update({"id": f"TXT_{uuid.uuid4().hex}", "target_timerange": {"start": current_timeline_time, "duration": new_video_duration_on_timeline}}); 
            new_text_segments.append(new_txt_seg)

            # consistent_source_duration = thời lượng nguồn gốc của audio (trước khi speed)
            consistent_source_duration = source_duration
            aud_speed_mat = create_new_speed_material(actual_audio_speed); new_speed_materials.append(aud_speed_mat)
            new_aud_seg = copy.deepcopy(audio_template); 
            new_aud_seg["material_id"] = audio_seg.get("material_id")
            safe_set_speed_ref(new_aud_seg, aud_speed_mat)
            new_aud_seg.update({"id": f"AUD_{uuid.uuid4().hex}", "target_timerange": {"start": current_timeline_time, "duration": actual_audio_duration}, "source_timerange": {"start": source_start, "duration": consistent_source_duration}, "speed": actual_audio_speed, "is_tone_modify": keep_pitch}); 
            new_audio_segments.append(new_aud_seg)

            current_timeline_time += new_video_duration_on_timeline
            last_original_text_end_time = original_start_time + original_video_duration

        if last_original_text_end_time < total_original_video_duration:
            tail_duration = total_original_video_duration - last_original_text_end_time
            # Áp dụng video speed cho tail segment nếu được bật
            tail_video_speed = target_video_speed if video_speed_enabled or target_video_speed != 1.0 else 1.0
            tail_duration_on_timeline = int(tail_duration / tail_video_speed) if tail_video_speed != 1.0 else tail_duration
            
            tail_speed_mat = create_new_speed_material(tail_video_speed); new_speed_materials.append(tail_speed_mat)
            tail_segment = copy.deepcopy(video_template); tail_segment.update({"id": f"TAIL_{uuid.uuid4().hex}", "target_timerange": {"start": current_timeline_time, "duration": tail_duration_on_timeline}, "source_timerange": {"start": last_original_text_end_time, "duration": tail_duration}, "speed": tail_video_speed}); 
            safe_set_speed_ref(tail_segment, tail_speed_mat)
            new_video_segments.append(tail_segment)
            current_timeline_time += tail_duration_on_timeline

        emit_progress(95, "Finalizing project structure...")
        modified_data["duration"] = current_timeline_time
        
        # Force maintrack_adsorb to True to ensure segments move together
        if "config" not in modified_data:
            modified_data["config"] = {}
        modified_data["config"]["maintrack_adsorb"] = True
        
        new_audio_segments = normalize_audio_and_group_segments(
            new_video_segments, 
            new_text_segments, 
            new_audio_segments, 
            audio_template, 
            modified_data,
            remove_silence=remove_silence,
            processor=processor
        )

        # Collapse video segments to screen-level after audio/text mapping is complete.
        if timestamp_screen:
            draft_fps = modified_data.get("fps", DEFAULT_TIMELINE_FPS)
            try:
                draft_fps = float(draft_fps)
            except (TypeError, ValueError):
                draft_fps = DEFAULT_TIMELINE_FPS
            if draft_fps <= 0:
                draft_fps = DEFAULT_TIMELINE_FPS

            new_video_segments = collapse_video_segments_by_screen(
                new_video_segments,
                new_text_segments,
                new_audio_segments,
                timestamp_screen,
                new_speed_materials,
                fps=draft_fps,
                cross_text_merge_max_frames=CROSS_SCREEN_TEXT_MERGE_MAX_FRAMES,
            )

        video_track["segments"] = new_video_segments
        text_track["segments"] = new_text_segments
        modified_data["materials"]["speeds"] = new_speed_materials
        
        # Group new_audio_segments into multiple tracks to avoid overlap collisions
        audio_tracks_list = []
        sorted_new_audio = sorted(new_audio_segments, key=lambda s: s.get("target_timerange", {}).get("start", 0))
        for aud_seg in sorted_new_audio:
            seg_start = aud_seg.get("target_timerange", {}).get("start", 0)
            seg_duration = aud_seg.get("target_timerange", {}).get("duration", 0)
            seg_end = seg_start + seg_duration
            
            placed = False
            for track_segs in audio_tracks_list:
                if not track_segs:
                    continue
                last_seg = track_segs[-1]
                last_seg_end = last_seg.get("target_timerange", {}).get("start", 0) + last_seg.get("target_timerange", {}).get("duration", 0)
                if seg_start >= last_seg_end:
                    track_segs.append(aud_seg)
                    placed = True
                    break
            if not placed:
                audio_tracks_list.append([aud_seg])
        
        final_audio_tracks = []
        for idx, track_segs in enumerate(audio_tracks_list):
            new_audio_track = copy.deepcopy(all_audio_tracks[0])
            new_audio_track["id"] = f"CONSOLIDATED_AUDIO_TRACK_{idx}_{uuid.uuid4().hex}"
            new_audio_track["segments"] = track_segs
            final_audio_tracks.append(new_audio_track)
            
        final_tracks = [t for t in tracks if t.get("type") not in ["audio", "video", "text"]]
        final_tracks.extend([video_track, text_track])
        if final_audio_tracks:
            final_tracks.extend(final_audio_tracks)
        else:
            # Fallback if no audio
            new_audio_track = copy.deepcopy(all_audio_tracks[0])
            new_audio_track["id"] = f"CONSOLIDATED_AUDIO_TRACK_EMPTY_{uuid.uuid4().hex}"
            new_audio_track["segments"] = []
            final_tracks.append(new_audio_track)
            
        modified_data["tracks"] = final_tracks
        
        # Apply waveform sync if requested
        if waveform_sync:
            emit_progress(98, "Applying waveform synchronization...")
            sync_mode_for_audio_sync = 'audio_sync' if mode == 'audio_sync' else 'waveform_only'
            modified_data = apply_audio_sync_to_draft(
                modified_data,
                sync_mode=sync_mode_for_audio_sync,
                waveform_sync=waveform_sync,
                progress_callback=progress_callback
            )
        
        emit_progress(100, "Process complete!")
        return modified_data

    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        logger.error(f"An unexpected error occurred during splicing: {e}\n{tb_str}")
        with open("splicer_error.log", "w", encoding="utf-8") as f:
            f.write(f"Error: {e}\n{tb_str}")
        return None
