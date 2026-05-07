"""
Segment creation logic with selectable sync modes.
"""
import os
import bisect
from typing import List, Dict, Optional
from utils.logger import get_logger, ProgressLogger

logger = get_logger(__name__)
SCREEN_BOUNDARY_TOLERANCE_US = 5_000

def resolve_screen_index(start_time_us: int, timestamp_screen_us: List[int]) -> int:
    """Resolve screen index with tolerance for timestamp rounding drift."""
    if not timestamp_screen_us:
        return 0
    return bisect.bisect_right(timestamp_screen_us, start_time_us + SCREEN_BOUNDARY_TOLERANCE_US)

def normalize_timestamp_screen_to_us(timestamp_screen: List[int]) -> List[int]:
    """Normalize timestamp_screen values to microseconds."""
    if not timestamp_screen:
        return []

    numeric_values = []
    for ts in timestamp_screen:
        try:
            numeric_values.append(float(ts))
        except (TypeError, ValueError):
            logger.warning(f"Ignoring invalid timestamp_screen value: {ts}")

    if not numeric_values:
        return []

    # Heuristic: distinguish microseconds, milliseconds, and seconds.
    max_value = max(abs(v) for v in numeric_values)
    has_fractional = any(not float(v).is_integer() for v in numeric_values)
    if max_value >= 100_000:
        logger.info("timestamp_screen detected as microseconds")
        return sorted(int(v) for v in numeric_values)

    if max_value >= 1_000 and not has_fractional:
        logger.info("timestamp_screen detected as milliseconds and converted to microseconds")
        return sorted(int(v * 1_000) for v in numeric_values)

    logger.info("timestamp_screen detected as seconds and converted to microseconds")
    return sorted(int(v * 1_000_000) for v in numeric_values)

class SegmentCreator:
    """Handles creation of video, audio, and text segments"""
    
    def __init__(self, generator, helpers: Dict, gap_aware_mode: bool = False):
        self.generator = generator
        self.helpers = helpers
        self.gap_aware_mode = gap_aware_mode
        
    def create_all_segments(self, timeline_segments: List[Dict], audio_materials: List[Dict],
                           text_materials: List[Dict], video_material: Dict, 
                           target_audio_speed: float, keep_pitch: bool, mode: str,
                           video_speed_enabled: bool = False, target_video_speed: float = 1.0,
                           remove_silence: bool = False,
                           processor = None,
                           progress_callback: Optional[object] = None,
                           timestamp_screen: List[int] = None,
                           skip_stretch_shorter: bool = False) -> Dict:
        video_speed_info = f", Target Video Speed: {target_video_speed}x" if target_video_speed != 1.0 else ", Video Speed: 1.0x (default mode)"
        logger.info(f"Creating segments - Mode: {'Gap-Aware' if self.gap_aware_mode else 'Classic'}, Target Audio Speed: {target_audio_speed}x{video_speed_info}")
        
        video_segments, audio_segments, text_segments = [], [], []
        timeline_current_time = 0
        audio_material_index = 0
        
        # Screen-based speed sync state
        # Normalize timestamp_screen to microseconds (accept seconds or microseconds)
        timestamp_screen = normalize_timestamp_screen_to_us(timestamp_screen)
        if timestamp_screen:
            logger.info(f"Screen boundary logic enabled. Timestamps (us): {timestamp_screen}")

        # Pre-calculate stable speed per screen for video_priority mode so gaps and
        # subtitle segments in the same screen always use one consistent speed.
        precomputed_screen_speeds = {}
        if timestamp_screen and mode == 'video_priority':
            baseline_video_speed = target_video_speed if (video_speed_enabled or target_video_speed != 1.0) else 1.0
            screen_stats = {}

            for seg_idx, timeline_segment in enumerate(timeline_segments):
                seg_original_start = timeline_segment.get('srt_start_time') or timeline_segment.get('start_time', 0)
                seg_original_duration = timeline_segment.get('srt_duration') or timeline_segment.get('duration', 0)
                if not seg_original_duration:
                    continue

                screen_idx = resolve_screen_index(seg_original_start, timestamp_screen)
                stats = screen_stats.setdefault(
                    screen_idx,
                    {
                        "video_source_total": 0,
                        "video_timeline_total": 0,
                        "audio_timeline_total": 0,
                    },
                )
                
                # Screen duration includes ALL segments (video gaps + subtitles)
                stats["video_source_total"] += seg_original_duration
                
                # Calculate audio/video timeline duration based on baseline
                video_timeline_duration = int(seg_original_duration / baseline_video_speed) if baseline_video_speed != 1.0 else seg_original_duration
                stats["video_timeline_total"] += video_timeline_duration

                # Only sum audio duration if segment has a subtitle (and thus an audio file)
                has_audio = False
                audio_material = None
                if self.gap_aware_mode:
                    if timeline_segment.get('has_subtitle', False):
                        audio_file_idx = timeline_segment.get('audio_file_index')
                        if audio_file_idx is not None and audio_file_idx < len(audio_materials):
                            audio_material = audio_materials[audio_file_idx]
                            has_audio = True
                else:
                    if seg_idx < len(audio_materials):
                        audio_material = audio_materials[seg_idx]
                        has_audio = True

                if has_audio and audio_material:
                    source_duration = audio_material.get("duration", 0)
                    if source_duration:
                        if remove_silence and processor:
                            try:
                                trim_start, trim_end = processor.find_speech_range(audio_material["path"])
                                if trim_end > trim_start:
                                    trimmed_dur = int((trim_end - trim_start) * 1000000)
                                    source_duration = max(100000, trimmed_dur)
                            except Exception as e:
                                logger.error(f"Failed to pre-calculate smart trim audio: {e}")

                        audio_timeline_duration = int(source_duration / target_audio_speed) if target_audio_speed > 0 else source_duration
                        stats["audio_timeline_total"] += audio_timeline_duration

            for screen_idx, stats in screen_stats.items():
                screen_video_speed = baseline_video_speed
                # If audio total is longer than screen total at baseline speed, reduce video speed
                if (
                    not skip_stretch_shorter
                    and stats["audio_timeline_total"] > stats["video_timeline_total"]
                    and stats["audio_timeline_total"] > 0
                ):
                    screen_video_speed = stats["video_source_total"] / stats["audio_timeline_total"]

                precomputed_screen_speeds[screen_idx] = (screen_video_speed, target_audio_speed)
                logger.info(
                    "Precomputed Screen %s speed -> video=%.6f, audio=%.6f "
                    "(screen_source=%dus, audio_timeline=%dus)",
                    screen_idx,
                    screen_video_speed,
                    target_audio_speed,
                    stats["video_source_total"],
                    stats["audio_timeline_total"],
                )
        
        current_screen_idx = 0
        screen_speeds = dict(precomputed_screen_speeds) # idx -> (video_speed, audio_speed)

        on_demand_trim_cache = {}

        def get_segment_audio_source_duration(seg_idx: int, seg_data: Dict) -> Optional[int]:
            if seg_idx in on_demand_trim_cache:
                return on_demand_trim_cache[seg_idx]

            audio_material = None
            if self.gap_aware_mode:
                if not seg_data.get('has_subtitle', False):
                    on_demand_trim_cache[seg_idx] = None
                    return None
                audio_file_idx = seg_data.get('audio_file_index')
                if audio_file_idx is None or audio_file_idx >= len(audio_materials):
                    on_demand_trim_cache[seg_idx] = None
                    return None
                audio_material = audio_materials[audio_file_idx]
            else:
                if seg_idx >= len(audio_materials):
                    on_demand_trim_cache[seg_idx] = None
                    return None
                audio_material = audio_materials[seg_idx]

            source_duration = audio_material.get("duration", 0)
            if not source_duration:
                on_demand_trim_cache[seg_idx] = None
                return None

            if remove_silence and processor:
                try:
                    trim_start, trim_end = processor.find_speech_range(audio_material["path"])
                    if trim_end > trim_start:
                        trimmed_dur = int((trim_end - trim_start) * 1000000)
                        source_duration = max(100000, trimmed_dur)
                except Exception as e:
                    logger.error(f"Failed to compute on-demand trim duration: {e}")

            on_demand_trim_cache[seg_idx] = source_duration
            return source_duration

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

            for scan_idx, scan_segment in enumerate(timeline_segments):
                scan_start = scan_segment.get('srt_start_time') or scan_segment.get('start_time', 0)
                scan_duration = scan_segment.get('srt_duration') or scan_segment.get('duration', 0)
                if not scan_duration:
                    continue

                if resolve_screen_index(scan_start, timestamp_screen) != screen_idx:
                    continue
                
                stats["video_source_total"] += scan_duration
                video_timeline_duration = int(scan_duration / baseline_video_speed) if baseline_video_speed != 1.0 else scan_duration
                stats["video_timeline_total"] += video_timeline_duration

                source_duration = get_segment_audio_source_duration(scan_idx, scan_segment)
                if source_duration:
                    audio_timeline_duration = int(source_duration / target_audio_speed) if target_audio_speed > 0 else source_duration
                    stats["audio_timeline_total"] += audio_timeline_duration

            if stats["video_source_total"] <= 0:
                return None

            screen_video_speed = baseline_video_speed
            if (
                not skip_stretch_shorter
                and stats["audio_timeline_total"] > stats["video_timeline_total"]
                and stats["audio_timeline_total"] > 0
            ):
                screen_video_speed = stats["video_source_total"] / stats["audio_timeline_total"]

            result = (screen_video_speed, target_audio_speed)
            screen_speeds[screen_idx] = result
            logger.info(
                "On-demand Screen %s speed -> video=%.6f, audio=%.6f",
                screen_idx,
                screen_video_speed,
                target_audio_speed,
            )
            return result
        
        # Pointer to the next threshold we are waiting for
        next_ts_ptr = 0
        next_screen_threshold = timestamp_screen[0] if timestamp_screen else float('inf')

        total_segments = len(timeline_segments)
        
        # Track separate audio timeline for packing in video_priority mode
        screen_audio_timeline_current = timeline_current_time
        
        for i, timeline_segment in enumerate(timeline_segments):
            try:
                if progress_callback:
                    percent = 60 + int((i / total_segments) * 30) 
                    progress_callback.emit(percent, f"Processing segment {i+1} of {total_segments}...")

                # Determine Screen Index
                seg_original_start = timeline_segment.get('srt_start_time') or timeline_segment.get('start_time', 0)
                seg_original_duration = timeline_segment.get('srt_duration') or timeline_segment.get('duration', 0)
                seg_original_end = seg_original_start + seg_original_duration

                # Determine Screen Index: Advance pointer if this segment starts after/at current threshold
                prev_idx = current_screen_idx
                if timestamp_screen: # ONLY use screen logic if timestamps are provided
                    while next_ts_ptr < len(timestamp_screen) and (seg_original_start + SCREEN_BOUNDARY_TOLERANCE_US) >= timestamp_screen[next_ts_ptr]:
                        next_ts_ptr += 1
                        current_screen_idx = next_ts_ptr 
                    
                    if current_screen_idx != prev_idx:
                        logger.info(f"Segment {i+1} crossed threshold. New Screen Index: {current_screen_idx}")
                        # Reset audio timeline for the new screen
                        screen_audio_timeline_current = timeline_current_time

                    # Update next threshold for future segments
                    if next_ts_ptr < len(timestamp_screen):
                        next_screen_threshold = timestamp_screen[next_ts_ptr]
                    else:
                        next_screen_threshold = float('inf')
                
                # Only use cached speed if screen sync is active (timestamps provided)
                cached_speed = None
                if timestamp_screen:
                    cached_speed = get_or_compute_screen_speed(current_screen_idx)
                if cached_speed:
                    logger.debug(f"Segment {i+1} using cached speed for Screen {current_screen_idx}: {cached_speed}")

                # Calculate audio override: in video_priority ONLY if screen speed was precomputed
                # this indicates audio packing is required.
                audio_start_override = None
                if timestamp_screen and mode == 'video_priority' and cached_speed:
                    audio_start_override = screen_audio_timeline_current

                if self.gap_aware_mode:
                    segment_result = self._create_gap_aware_segment(
                        timeline_segment, audio_materials, text_materials, 
                        video_material, timeline_current_time, audio_material_index, i,
                        target_audio_speed, keep_pitch, mode,
                        video_speed_enabled, target_video_speed,
                        remove_silence, processor,
                        cached_speed=cached_speed,
                        skip_stretch_shorter=skip_stretch_shorter,
                        audio_timeline_start_override=audio_start_override
                    )
                else:
                    segment_result = self._create_classic_segment(
                        timeline_segment, audio_materials, text_materials,
                        video_material, timeline_current_time, i,
                        target_audio_speed, keep_pitch, mode,
                        target_video_speed,
                        remove_silence, processor,
                        cached_speed=cached_speed,
                        skip_stretch_shorter=skip_stretch_shorter,
                        audio_timeline_start_override=audio_start_override
                    )
                
                if segment_result:
                    # Update screen speed cache if it was newly calculated AND screen sync is active
                    if timestamp_screen and current_screen_idx not in screen_speeds and segment_result.get('calculated_speeds'):
                        screen_speeds[current_screen_idx] = segment_result['calculated_speeds']
                        logger.info(f"Cached speed for Screen {current_screen_idx}: {screen_speeds[current_screen_idx]}")
                    
                    # Boundary check for logging/state (informational)
                    if timestamp_screen and seg_original_end > next_screen_threshold:
                        next_screen_threshold = seg_original_end
                
                if segment_result:
                    if segment_result['video_segment']: video_segments.append(segment_result['video_segment'])
                    if segment_result['audio_segment']: audio_segments.append(segment_result['audio_segment'])
                    if segment_result['text_segment']: text_segments.append(segment_result['text_segment'])
                    
                    timeline_current_time = segment_result['next_timeline_time']
                    if segment_result.get('audio_index_increment'):
                        audio_material_index += 1
                        # Track audio end for packing
                        if segment_result.get('actual_audio_duration'):
                            screen_audio_timeline_current += segment_result['actual_audio_duration']
            except Exception as e:
                logger.error(f"Error creating segment {i+1}: {e}")
                continue
        
        logger.info(f"Segments created: Video={len(video_segments)}, Audio={len(audio_segments)}, Text={len(text_segments)}")
        return {'video_segments': video_segments, 'audio_segments': audio_segments, 'text_segments': text_segments, 'total_duration': timeline_current_time}
    
    def _create_gap_aware_segment(self, timeline_segment, audio_materials, text_materials, video_material,
                                 timeline_current_time, audio_material_index, segment_index,
                                 target_audio_speed, keep_pitch, mode,
                                 video_speed_enabled, target_video_speed,
                                 remove_silence, processor,
                                 cached_speed=None,
                                 skip_stretch_shorter: bool = False,
                                 audio_timeline_start_override: Optional[int] = None):
        has_subtitle = timeline_segment['has_subtitle']
        original_video_duration = timeline_segment['duration']
        
        new_video_speed = 1.0
        new_video_duration_on_timeline = original_video_duration
        
        audio_segment = None
        text_segment = None
        audio_index_increment = False
        actual_audio_duration = 0

        if has_subtitle:
            audio_file_idx = timeline_segment.get('audio_file_index')
            if audio_file_idx is not None and audio_file_idx < len(audio_materials):
                audio_material = audio_materials[audio_file_idx]
                text_material = text_materials[audio_file_idx]
                
                # --- PRE-CALCULATE TRIMMED DURATION FOR SYNC ---
                source_start = 0
                source_duration = audio_material["duration"]
                if remove_silence and processor:
                    try:
                        trim_start, trim_end = processor.find_speech_range(audio_material["path"])
                        # Only apply trim if speech was actually detected
                        if trim_end > trim_start:
                            source_start = int(trim_start * 1000000)
                            trimmed_dur = int((trim_end - trim_start) * 1000000)
                            source_duration = max(100000, trimmed_dur)
                        else:
                            logger.debug(f"No speech detected in {audio_material.get('path','?')} – keeping original duration")
                    except Exception as e:
                        logger.error(f"Failed to pre-calculate smart trim: {e}")

                original_audio_duration = source_duration
                # Dùng biến cục bộ để KHÔNG bao giờ ghi đè target_audio_speed gốc
                actual_audio_speed = target_audio_speed
                
                # Check for cached speed
                if cached_speed:
                    new_video_speed, actual_audio_speed = cached_speed
                    new_video_duration_on_timeline = int(original_video_duration / new_video_speed)
                    actual_audio_duration = int(original_audio_duration / actual_audio_speed)
                else:
                    new_audio_target_duration = int(original_audio_duration / target_audio_speed)
                    actual_audio_duration = new_audio_target_duration

                    # Calculate baseline video speed
                    baseline_video_speed = target_video_speed if (video_speed_enabled or target_video_speed != 1.0) else 1.0
                    adjusted_video_duration = int(original_video_duration / baseline_video_speed)
                
                    if mode == 'audio_sync' or mode == 'audio_sync_priority':
                        # Audio sync modes: Video follows baseline speed, Audio stretches to match
                        new_video_speed = baseline_video_speed
                        new_video_duration_on_timeline = adjusted_video_duration
                        
                        calculated_audio_speed = original_audio_duration / new_video_duration_on_timeline if new_video_duration_on_timeline > 0 else 1.0
                        
                        if mode == 'audio_sync_priority' and new_video_duration_on_timeline > actual_audio_duration:
                            # Priority: video dài hơn audio → giữ nguyên tốc độ audio gốc
                            pass
                        elif skip_stretch_shorter and actual_audio_duration < new_video_duration_on_timeline:
                            # Không co giãn audio nếu audio ngắn hơn video
                            pass
                        else:
                            # Standard sync: kéo giãn audio theo video
                            actual_audio_speed = calculated_audio_speed
                            actual_audio_duration = new_video_duration_on_timeline
                    elif mode == 'video_priority':
                        if actual_audio_duration > adjusted_video_duration:
                            if skip_stretch_shorter:
                                # Giữ nguyên video speed baseline, không co giãn để khớp audio (audio sẽ bị cắt hoặc video bị hụt)
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
                
                speed_idx_aud = min(len(self.helpers["speeds"]) - audio_material_index - 1, len(self.helpers["speeds"]) - 1)
                self.helpers["speeds"][speed_idx_aud]["speed"] = actual_audio_speed
                
                audio_start = audio_timeline_start_override if audio_timeline_start_override is not None else timeline_current_time
                
                # Pass pre-calculated trim info to avoid redundant processing
                audio_segment = self.create_audio_segment(
                    audio_material, 
                    actual_audio_duration, 
                    actual_audio_speed, 
                    self.helpers["speeds"][speed_idx_aud]["id"], 
                    audio_start, 
                    keep_pitch, 
                    render_index=segment_index,
                    remove_silence=remove_silence,
                    processor=processor,
                    source_start=source_start,
                    source_duration=source_duration
                )
                
                text_segment = self.create_text_segment(text_material, timeline_current_time, new_video_duration_on_timeline, timeline_segment['subtitle_data']['index'])
                audio_index_increment = True
        else:
            # Trường hợp không có subtitle (GAP)
            if cached_speed:
                new_video_speed, _ = cached_speed
                new_video_duration_on_timeline = int(original_video_duration / new_video_speed)
            elif video_speed_enabled or target_video_speed != 1.0:
                new_video_speed = target_video_speed
                new_video_duration_on_timeline = int(original_video_duration / target_video_speed)
        
        speed_idx_vid = min(segment_index, len(self.helpers["speeds"]) - 1)
        self.helpers["speeds"][speed_idx_vid]["speed"] = new_video_speed
        video_segment = self.create_video_segment(video_material, timeline_segment, new_video_duration_on_timeline, new_video_speed, self.helpers["speeds"][speed_idx_vid]["id"], timeline_current_time, render_index=segment_index)
        
        return {
            'video_segment': video_segment, 
            'audio_segment': audio_segment, 
            'text_segment': text_segment, 
            'next_timeline_time': timeline_current_time + new_video_duration_on_timeline, 
            'audio_index_increment': audio_index_increment,
            'calculated_speeds': (new_video_speed, actual_audio_speed) if has_subtitle else None,
            'actual_audio_duration': actual_audio_duration
        }

    def _create_classic_segment(self, timeline_segment, audio_materials, text_materials, video_material,
                                timeline_current_time, segment_index, target_audio_speed, keep_pitch, mode,
                                target_video_speed,
                                remove_silence, processor,
                                cached_speed=None,
                                skip_stretch_shorter: bool = False,
                                audio_timeline_start_override: Optional[int] = None):
        if segment_index >= len(audio_materials): return None
        
        audio_material = audio_materials[segment_index]
        text_material = text_materials[segment_index] if segment_index < len(text_materials) else None
        
        # --- PRE-CALCULATE TRIMMED DURATION FOR SYNC ---
        source_start = 0
        source_duration = audio_material["duration"]
        if remove_silence and processor:
            try:
                trim_start, trim_end = processor.find_speech_range(audio_material["path"])
                # Only apply trim if speech was actually detected
                if trim_end > trim_start:
                    source_start = int(trim_start * 1000000)
                    trimmed_dur = int((trim_end - trim_start) * 1000000)
                    source_duration = max(100000, trimmed_dur)
                else:
                    logger.debug(f"No speech detected in {audio_material.get('path','?')} – keeping original duration")
            except Exception as e:
                logger.error(f"Failed to pre-calculate smart trim: {e}")

        original_audio_duration = source_duration
        original_video_duration = timeline_segment.get('srt_duration')
        if not original_video_duration:
            # Fallback to general duration if srt_duration is missing
            original_video_duration = timeline_segment.get('duration', 0)
            
        if not original_video_duration:
            logger.warning(f"Segment {segment_index+1} has no valid duration. Skipping."); return None

        # Dùng biến cục bộ để KHÔNG bao giờ ghi đè target_audio_speed gốc
        actual_audio_speed = target_audio_speed
        
        # Video speed logic
        new_video_speed = 1.0
        new_video_duration_on_timeline = original_video_duration
        
        # Check for cached speed
        if cached_speed:
            new_video_speed, actual_audio_speed = cached_speed
            new_video_duration_on_timeline = int(original_video_duration / new_video_speed)
            actual_audio_duration = int(original_audio_duration / actual_audio_speed)
        else:
            new_audio_target_duration = int(original_audio_duration / target_audio_speed)
            actual_audio_duration = new_audio_target_duration

            # Calculate baseline video speed
            baseline_video_speed = target_video_speed if (target_video_speed != 1.0) else 1.0
            adjusted_video_duration = int(original_video_duration / baseline_video_speed)
        
            if mode == 'audio_sync' or mode == 'audio_sync_priority':
                # Audio sync modes: Video follows baseline speed, Audio stretches to match
                new_video_speed = baseline_video_speed
                new_video_duration_on_timeline = adjusted_video_duration
                
                calculated_audio_speed = original_audio_duration / new_video_duration_on_timeline if new_video_duration_on_timeline > 0 else 1.0
                
                if mode == 'audio_sync_priority' and new_video_duration_on_timeline > actual_audio_duration:
                    # Priority: video dài hơn audio → giữ nguyên tốc độ audio gốc
                    pass
                elif skip_stretch_shorter and actual_audio_duration < new_video_duration_on_timeline:
                    # Không co giãn audio nếu audio ngắn hơn video
                    pass
                else:
                    # Standard sync: kéo giãn audio theo video
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
        
        speed_idx_vid = min(segment_index * 2, len(self.helpers["speeds"]) - 1)
        speed_idx_aud = min(segment_index * 2 + 1, len(self.helpers["speeds"]) - 1)
        self.helpers["speeds"][speed_idx_vid]["speed"] = new_video_speed
        self.helpers["speeds"][speed_idx_aud]["speed"] = actual_audio_speed
        
        video_segment = self.create_video_segment(video_material, timeline_segment, new_video_duration_on_timeline, new_video_speed, self.helpers["speeds"][speed_idx_vid]["id"], timeline_current_time, render_index=segment_index)
        
        audio_start = audio_timeline_start_override if audio_timeline_start_override is not None else timeline_current_time

        # Pass pre-calculated trim info to avoid redundant processing
        # Use audio_start instead of timeline_current_time
        audio_segment = self.create_audio_segment(
            audio_material, 
            actual_audio_duration, 
            actual_audio_speed, 
            self.helpers["speeds"][speed_idx_aud]["id"], 
            audio_start, 
            keep_pitch, 
            render_index=segment_index,
            remove_silence=remove_silence,
            processor=processor,
            source_start=source_start,
            source_duration=source_duration
        )
        
        text_segment = None
        if text_material:
            text_segment = self.create_text_segment(text_material, timeline_current_time, new_video_duration_on_timeline, timeline_segment['index'])
        
        return {
            'video_segment': video_segment, 
            'audio_segment': audio_segment, 
            'text_segment': text_segment, 
            'next_timeline_time': timeline_current_time + new_video_duration_on_timeline, 
            'audio_index_increment': True,
            'actual_audio_duration': actual_audio_duration
        }

    def create_video_segment(self, video_material: Dict, timeline_segment: Dict, target_duration: int, speed: float, speed_material_id: str, timeline_start_time: int, render_index: int = 0) -> Dict:
        segment_start = timeline_segment.get('srt_start_time') or timeline_segment.get('start_time', 0)
        segment_duration = timeline_segment.get('srt_duration') or timeline_segment.get('duration', 1000000)
        return {"caption_info": None, "cartoon": False, "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}}, "color_correct_alg_result": "", "common_keyframes": [], "desc": "", "digital_human_template_group_id": "", "enable_adjust": True, "enable_adjust_mask": False, "enable_color_correct_adjust": False, "enable_color_curves": True, "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_hsl": False, "enable_hsl_curves": True, "enable_lut": True, "enable_smart_color_adjust": False, "enable_video_mask": True, "extra_material_refs": [speed_material_id], "group_id": "", "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000}, "id": self.generator.generate_uuid(), "intensifies_audio": False, "is_loop": False, "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [], "last_nonzero_volume": 1.0, "lyric_keyframes": None, "material_id": video_material["id"], "raw_segment_id": "", "render_index": render_index, "render_timerange": {"duration": 0, "start": 0}, "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0}, "reverse": False, "source": "segmentsourcenormal", "source_timerange": {"duration": segment_duration, "start": segment_start}, "speed": speed, "state": 0, "target_timerange": {"duration": target_duration, "start": timeline_start_time}, "template_id": "", "template_scene": "default", "track_attribute": 0, "track_render_index": 0, "uniform_scale": {"on": True, "value": 1.0}, "visible": True, "volume": 1.0}

    def create_audio_segment(self, audio_material: Dict, target_duration: int, speed: float, speed_material_id: str, timeline_start_time: int, keep_pitch: bool, render_index: int = 0, remove_silence: bool = False, processor = None, source_start: int = 0, source_duration: Optional[int] = None) -> Dict:
        """
        Create audio segment for timeline.
        If source_duration is None, it uses audio_material["duration"].
        If remove_silence=True and processor is provided and source_duration was not pre-calculated, it performs trimming.
        """
        if source_duration is None:
            source_start = 0
            source_duration = audio_material["duration"]

            # --- SMART TRIMMING (METADATA-ONLY) ---
            if remove_silence and processor:
                try:
                    trim_start, trim_end = processor.find_speech_range(audio_material["path"])
                    # Only apply trim if speech was actually detected
                    if trim_end > trim_start:
                        source_start = int(trim_start * 1000000)
                        trimmed_dur = int((trim_end - trim_start) * 1000000)
                        source_duration = max(100000, trimmed_dur)
                        # Recalculate target_duration to match trimmed source
                        target_duration = int(source_duration / speed)
                        logger.debug(f"Smart Trimmed {os.path.basename(audio_material['path'])}: {trim_start:.2f}s - {trim_end:.2f}s")
                    else:
                        logger.debug(f"No speech detected in {os.path.basename(audio_material.get('path','?'))} – keeping original duration")
                except Exception as e:
                    logger.error(f"Failed to smart trim audio material: {e}")

        return {"caption_info": None, "cartoon": False, "clip": None, "color_correct_alg_result": "", "common_keyframes": [], "desc": "", "digital_human_template_group_id": "", "enable_adjust": False, "enable_adjust_mask": False, "enable_color_correct_adjust": False, "enable_color_curves": True, "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_hsl": False, "enable_hsl_curves": True, "enable_lut": False, "enable_smart_color_adjust": False, "enable_video_mask": True, "extra_material_refs": [speed_material_id], "group_id": "", "hdr_settings": None, "id": self.generator.generate_uuid(), "intensifies_audio": False, "is_loop": False, "is_placeholder": False, "is_tone_modify": keep_pitch, "keyframe_refs": [], "last_nonzero_volume": 1.0, "lyric_keyframes": None, "material_id": audio_material["id"], "raw_segment_id": "", "render_index": render_index, "render_timerange": {"duration": 0, "start": 0}, "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0}, "reverse": False, "source": "segmentsourcenormal", "source_timerange": {"duration": source_duration, "start": source_start}, "speed": speed, "state": 0, "target_timerange": {"duration": target_duration, "start": timeline_start_time}, "template_id": "", "template_scene": "default", "track_attribute": 0, "track_render_index": 2, "uniform_scale": None, "visible": True, "volume": 1.0}
    
    def create_text_segment(self, text_material: Dict, timeline_start_time: int, target_duration: int, subtitle_index: int) -> Dict:
        return {"caption_info": None, "cartoon": False, "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": -0.8}}, "color_correct_alg_result": "", "common_keyframes": [], "desc": "", "digital_human_template_group_id": "", "enable_adjust": False, "enable_adjust_mask": False, "enable_color_correct_adjust": False, "enable_color_curves": True, "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_hsl": False, "enable_hsl_curves": True, "enable_lut": False, "enable_smart_color_adjust": False, "enable_video_mask": True, "extra_material_refs": [], "group_id": "", "hdr_settings": None, "id": self.generator.generate_uuid(), "intensifies_audio": False, "is_loop": False, "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [], "last_nonzero_volume": 1.0, "lyric_keyframes": None, "material_id": text_material["id"], "raw_segment_id": "", "render_index": 14000 + subtitle_index - 1, "render_timerange": {"duration": 0, "start": 0}, "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0}, "reverse": False, "source": "segmentsourcenormal", "source_timerange": None, "speed": 1.0, "state": 0, "target_timerange": {"duration": target_duration, "start": timeline_start_time}, "template_id": "", "template_scene": "default", "track_attribute": 0, "track_render_index": 1, "uniform_scale": {"on": True, "value": 1.0}, "visible": True, "volume": 1.0}
    
    def create_silence_audio_segment(self, target_duration: int, timeline_start_time: int, render_index: int = 0) -> Dict:
        """Tạo audio segment im lặng cho gap giữa các subtitle để đảm bảo đồng bộ audio-video"""
        return {
            "caption_info": None, "cartoon": False, "clip": None, "color_correct_alg_result": "",
            "common_keyframes": [], "desc": "", "digital_human_template_group_id": "",
            "enable_adjust": False, "enable_adjust_mask": False, "enable_color_correct_adjust": False,
            "enable_color_curves": True, "enable_color_match_adjust": False, "enable_color_wheels": True,
            "enable_hsl": False, "enable_hsl_curves": True, "enable_lut": False, "enable_smart_color_adjust": False,
            "enable_video_mask": True, "extra_material_refs": [], "group_id": "", "hdr_settings": None,
            "id": self.generator.generate_uuid(), "intensifies_audio": False, "is_loop": False,
            "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [], "last_nonzero_volume": 0.0,
            "lyric_keyframes": None, "material_id": "", "raw_segment_id": "", "render_index": render_index,
            "render_timerange": {"duration": 0, "start": 0}, 
            "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
            "reverse": False, "source": "segmentsourcenormal", "source_timerange": {"duration": target_duration, "start": 0},
            "speed": 1.0, "state": 0, "target_timerange": {"duration": target_duration, "start": timeline_start_time},
            "template_id": "", "template_scene": "default", "track_attribute": 0, "track_render_index": 2,
            "uniform_scale": None, "visible": True, "volume": 0.0
        }
