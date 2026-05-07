"""
Audio-Video Synchronization functionality for CapCut Draft Generator
Handles audio stretching/compression to match video duration
"""

import os
import ffmpeg
import uuid
import logging
import tempfile
from typing import Optional, List, Dict, Any, Tuple
try:
    import librosa
    import numpy as np
    import soundfile as sf
    AUDIO_SYNC_AVAILABLE = True
except ImportError as e:
    import logging
    logging.getLogger("CapCutGenerator.audio_video_sync").error(f"Missing dependency for silence removal: {str(e)}")
    AUDIO_SYNC_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger(__name__)


class AudioVideoSyncProcessor:
    """Handles audio-video synchronization operations"""
    
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
    
    def is_available(self) -> bool:
        """Check if audio sync functionality is available and log paths"""
        import shutil
        ffmpeg_bin = shutil.which("ffmpeg")
        ffprobe_bin = shutil.which("ffprobe")
        logger.info(f"FFmpeg path: {ffmpeg_bin if ffmpeg_bin else 'NOT FOUND'}")
        logger.info(f"FFprobe path: {ffprobe_bin if ffprobe_bin else 'NOT FOUND'}")
        return AUDIO_SYNC_AVAILABLE
    
    def get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds"""
        try:
            probe = ffmpeg.probe(video_path)
            streams = probe.get('streams', [])
            video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)

            if video_stream and video_stream.get('duration') not in (None, ''):
                duration = float(video_stream['duration'])
            else:
                duration = None
                for stream in streams:
                    stream_duration = stream.get('duration')
                    if stream_duration not in (None, ''):
                        duration = float(stream_duration)
                        break

                if duration is None:
                    format_duration = probe.get('format', {}).get('duration')
                    if format_duration in (None, ''):
                        raise KeyError("duration")
                    duration = float(format_duration)

            logger.info(f"Video duration: {duration:.2f}s")
            return duration
        except Exception as e:
            logger.error(f"Error getting video duration: {str(e)}")
            raise Exception(f"Error getting video duration: {str(e)}")
    
    def get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration in seconds"""
        if not AUDIO_SYNC_AVAILABLE:
            raise Exception("Audio sync libraries not available. Please install: pip install librosa soundfile")
        
        try:
            y, sr = librosa.load(audio_path, sr=None)
            duration = len(y) / sr
            logger.info(f"Audio duration: {duration:.2f}s")
            return duration
        except Exception as e:
            logger.error(f"Error getting audio duration: {str(e)}")
            raise Exception(f"Error getting audio duration: {str(e)}")
    
    def stretch_audio(self, audio_path: str, target_duration: float, output_path: str) -> str:
        """Stretch or compress audio to match target duration"""
        if not AUDIO_SYNC_AVAILABLE:
            raise Exception("Audio sync libraries not available. Please install: pip install librosa soundfile")
        
        try:
            logger.info(f"Stretching audio from {audio_path} to {target_duration:.2f}s")
            
            # Load audio
            y, sr = librosa.load(audio_path, sr=None)
            current_duration = len(y) / sr
            
            # Calculate stretch ratio
            stretch_ratio = target_duration / current_duration
            logger.info(f"Stretch ratio: {stretch_ratio:.3f}")
            
            # Apply time stretching using librosa
            y_stretched = librosa.effects.time_stretch(y, rate=stretch_ratio)
            
            # Save stretched audio
            sf.write(output_path, y_stretched, sr)
            logger.info(f"Stretched audio saved to: {output_path}")
            
            return output_path
        except Exception as e:
            logger.error(f"Error stretching audio: {str(e)}")
            raise Exception(f"Error stretching audio: {str(e)}")
    
    def remove_silence(self, audio_path: str, output_path: str, top_db: int = 40, padding_sec: float = 0.0) -> str:
        """
        Remove silence from audio file by trimming start and end with optional padding
        
        Args:
            audio_path: Path to input audio file
            output_path: Path for output processed audio
            top_db: Threshold (in dB) below reference to consider as silence
            padding_sec: Additional silence to keep at the end (in seconds)
            
        Returns:
            Path to processed audio file
        """
        if not AUDIO_SYNC_AVAILABLE:
            raise Exception("Audio sync libraries not available. Please install: pip install librosa soundfile")
            
        try:
            logger.info(f"Trimming silence from {audio_path} (threshold: {top_db}dB, padding: {padding_sec}s)")
            
            # Load audio
            y, sr = librosa.load(audio_path, sr=None)
            original_duration = len(y) / sr
            
            # Find non-silent boundaries
            _, index = librosa.effects.trim(y, top_db=top_db)
            start_sample, end_sample = index
            
            # Apply padding at the end (as requested by user)
            padding_samples = int(padding_sec * sr)
            end_sample = min(len(y), end_sample + padding_samples)
            
            y_trimmed = y[start_sample:end_sample]
            new_duration = len(y_trimmed) / sr
            
            logger.info(f"Silence trimmed: {original_duration:.2f}s -> {new_duration:.2f}s (reduced by {original_duration - new_duration:.2f}s)")
            
            # Save processed audio
            sf.write(output_path, y_trimmed, sr)
            logger.info(f"Processed audio saved to: {output_path}")
            
            return output_path
        except Exception as e:
            logger.error(f"Error trimming silence: {str(e)}")
            raise Exception(f"Error trimming silence: {str(e)}")
    
    def extract_audio_from_video(self, video_path: str, output_path: str) -> str:
        """Extract audio track from video file using ffmpeg"""
        try:
            logger.info(f"Extracting audio from {video_path} to {output_path}")
            input_video = ffmpeg.input(video_path)
            output = ffmpeg.output(input_video.audio, output_path, acodec='pcm_s16le', ac=1, ar='22050')
            ffmpeg.run(output, overwrite_output=True, quiet=True)
            return output_path
        except Exception as e:
            logger.error(f"Error extracting audio from video: {str(e)}")
            raise Exception(f"Error extracting audio from video: {str(e)}")

    def find_speech_range(self, audio_path: str, top_db: int = 40, padding_sec: float = 0.0) -> Tuple[float, float]:
        """
        Find the (start, end) timestamps (in seconds) where speech/sound actually occurs.
        Returns (0.0, total_duration) on failure.
        """
        try:
            y, sr = librosa.load(audio_path, sr=22050)
            total_dur = len(y) / sr
            if len(y) == 0:
                return 0.0, 0.0
            
            # Normalize to ensure we capture peaks correctly
            y = librosa.util.normalize(y)
                
            _, index = librosa.effects.trim(y, top_db=top_db)
            
            # No padding to match user request (removed the +/- 1 frame logic)
            start_sec = max(0.0, float(index[0]) / sr - padding_sec)
            end_sec = min(total_dur, float(index[1]) / sr + padding_sec)
            
            return start_sec, end_sec
        except Exception as e:
            import traceback
            logger.error(f"Error finding speech range for {audio_path}: {e}\n{traceback.format_exc()}")
            return 0.0, 0.0

    def find_sync_offset(self, video_audio_path: str, mp3_audio_path: str,
                         mp3_source_start: float = 0.0, mp3_source_dur: float = None) -> Optional[float]:
        """
        Find time offset (in seconds) between video audio and mp3 audio using waveform correlation.

        Args:
            video_audio_path: Path to extracted video segment audio (WAV).
            mp3_audio_path: Path to MP3 audio material file.
            mp3_source_start: Where in the MP3 the usable audio starts (seconds).
            mp3_source_dur: Duration of usable MP3 audio (seconds). None = whole file.

        Returns:
            offset_seconds: positive → mp3 speech starts AFTER video speech (needs delay).
                            None if correlation fails or both are silent.
        """
        if not AUDIO_SYNC_AVAILABLE:
            raise Exception("Audio sync libraries (librosa, numpy) not available.")

        try:
            sr = 22050
            y_video, _ = librosa.load(video_audio_path, sr=sr)

            # Load only the usable portion of the MP3 (skip leading silence etc.)
            y_mp3_full, _ = librosa.load(mp3_audio_path, sr=sr)
            start_sample = int(mp3_source_start * sr)
            if mp3_source_dur is not None:
                end_sample = start_sample + int(mp3_source_dur * sr)
                y_mp3 = y_mp3_full[start_sample:min(end_sample, len(y_mp3_full))]
            else:
                y_mp3 = y_mp3_full[start_sample:]

            # Silence check
            if len(y_video) == 0 or np.max(np.abs(y_video)) < 0.01:
                logger.debug("find_sync_offset: video audio is silent → None")
                return None
            if len(y_mp3) == 0 or np.max(np.abs(y_mp3)) < 0.01:
                logger.debug("find_sync_offset: mp3 audio slice is silent → None")
                return None

            # Normalize
            y_video = librosa.util.normalize(y_video)
            y_mp3 = librosa.util.normalize(y_mp3)

            # Use onset envelopes for matching dialogue beats
            onset_video = librosa.onset.onset_strength(y=y_video, sr=sr)
            onset_mp3 = librosa.onset.onset_strength(y=y_mp3, sr=sr)

            # Cross-correlation: find best alignment of mp3 onset vs video onset
            correlation = np.correlate(onset_mp3, onset_video, mode='full')
            peak_idx = int(np.argmax(correlation))

            # Zero-lag index: len(onset_video) - 1
            # peak_idx > center → mp3 is shifted right (delayed relative to video)
            # peak_idx < center → mp3 is shifted left (advanced relative to video)
            center = len(onset_video) - 1
            offset_frames = peak_idx - center  # positive = mp3 lags behind video
            hop_length = 512
            offset_seconds = (offset_frames * hop_length) / sr

            logger.debug(f"find_sync_offset: peak_idx={peak_idx}, center={center}, offset={offset_seconds:.3f}s")
            return offset_seconds

        except Exception as e:
            logger.error(f"Error finding sync offset: {str(e)}")
            return None

    def _sync_one_pair(self, v_seg: dict, a_seg: dict,
                       video_mat_map: dict, audio_mat_map: dict) -> dict:
        """
        Sync a single MP3 audio segment to its paired video segment using waveform matching.

        Strategy:
          1. Extract the video's source audio slice to a temp WAV.
          2. Find where speech actually starts in the video slice (v_speech_start).
          3. Find where speech starts in the MP3 (a_speech_start) → use as source_start offset.
          4. Cross-correlate onset envelopes to confirm/refine alignment.
          5. Compute timeline start = v_seg timeline start + speech onset offset in video.
          6. Keep source_timerange pointing at the real speech content of the MP3.
          7. Recalculate target_timerange.duration from source duration / speed.
        """
        v_mat = video_mat_map.get(v_seg.get('material_id'))
        a_mat = audio_mat_map.get(a_seg.get('material_id'))

        if not v_mat or not a_mat:
            return a_seg

        v_path = v_mat.get('path', '')
        a_path = a_mat.get('path', '')

        if not v_path or not a_path or not os.path.exists(v_path) or not os.path.exists(a_path):
            return a_seg

        v_tgt_start_us  = v_seg['target_timerange']['start']       # microseconds on timeline
        v_tgt_dur_us    = v_seg['target_timerange']['duration']     # microseconds on timeline
        v_src_start_s   = v_seg['source_timerange']['start']   / 1_000_000.0
        v_src_dur_s     = v_seg['source_timerange']['duration'] / 1_000_000.0

        # Speed of audio segment (float, not a UUID)
        audio_speed = a_seg.get('speed', 1.0)
        if not isinstance(audio_speed, (int, float)) or audio_speed <= 0:
            audio_speed = 1.0

        import time as _time
        temp_v_audio = os.path.join(
            self.temp_dir,
            f"vsync_{int(_time.time()*1000)}_{v_seg['id'][:8]}.wav"
        )

        try:
            # ── Step 1: Extract video source segment audio ──────────────────────
            ffmpeg.run(
                ffmpeg.output(
                    ffmpeg.input(v_path, ss=v_src_start_s, t=v_src_dur_s).audio,
                    temp_v_audio,
                    acodec='pcm_s16le', ac=1, ar='22050'
                ),
                overwrite_output=True, quiet=True
            )

            # ── Step 2: Find speech onset inside the video slice ─────────────────
            #    v_speech_start_s: seconds from the START of the video SOURCE clip
            v_speech_start_s, _ = self.find_speech_range(temp_v_audio, top_db=40)

            # ── Step 3: Find speech range in the full MP3 material ──────────────
            a_speech_start_s, a_speech_end_s = self.find_speech_range(a_path, top_db=40)
            a_full_dur_s = _get_file_duration(a_path)

            # Guard: if find_speech_range returns (0,0) treat whole file as speech
            if a_speech_end_s <= a_speech_start_s:
                a_speech_start_s = 0.0
                a_speech_end_s   = a_full_dur_s

            # ── Step 4: Cross-correlation to refine offset ───────────────────────
            #    We pass only the actual speech slice of the MP3 to avoid noise.
            mp3_speech_dur_s = a_speech_end_s - a_speech_start_s
            corr_offset = self.find_sync_offset(
                temp_v_audio, a_path,
                mp3_source_start=a_speech_start_s,
                mp3_source_dur=mp3_speech_dur_s
            )

            # ── Step 5: Determine final timeline start offset ────────────────────
            #    Positive corr_offset means "mp3 speech beats lag behind video beats"
            #    → we should start the audio earlier OR the video speech starts later.
            #
            #    Best strategy:
            #      • Use v_speech_start_s as the base offset (where dialogue begins
            #        in the video clip → where MP3 should be placed on the timeline).
            #      • Optionally adjust by a small corr_offset if reliable.

            # Decide whether correlation is reliable:
            # - corr_offset is None  → fall back to speech-start alignment
            # - |corr_offset| is very large (> video duration) → unreliable, ignore
            max_reliable_offset = v_src_dur_s  # can't be longer than the clip itself
            if corr_offset is not None and abs(corr_offset) <= max_reliable_offset:
                # corr_offset tells us how much later (positive) or earlier (negative)
                # the mp3 speech beats are relative to the video speech beats.
                # Subtract it so they align:
                alignment_offset_s = v_speech_start_s - corr_offset
            else:
                # Fallback: align by speech-start timestamps
                alignment_offset_s = v_speech_start_s - 0.0  # mp3 speech starts at source_start

            # Clamp to [0, v_src_dur_s - 0.05] so we stay inside the video segment
            alignment_offset_s = max(0.0, min(alignment_offset_s, max(0.0, v_src_dur_s - 0.05)))

            # ── Step 6: Update audio segment fields ─────────────────────────────
            # source_timerange → points at the actual speech in the MP3
            new_src_start_us = int(a_speech_start_s * 1_000_000)
            new_src_dur_us   = max(100_000, int(mp3_speech_dur_s * 1_000_000))

            # target_timerange → duration = source / speed
            new_tgt_dur_us   = max(100_000, int(new_src_dur_us / audio_speed))

            # target start = video segment's timeline start + alignment offset
            new_tgt_start_us = v_tgt_start_us + int(alignment_offset_s * 1_000_000)

            # Safety: don't let audio start beyond the video segment's end
            v_tgt_end_us = v_tgt_start_us + v_tgt_dur_us
            new_tgt_start_us = min(new_tgt_start_us, max(v_tgt_start_us, v_tgt_end_us - 100_000))

            a_seg['source_timerange']['start']    = new_src_start_us
            a_seg['source_timerange']['duration'] = new_src_dur_us
            a_seg['target_timerange']['start']    = new_tgt_start_us
            a_seg['target_timerange']['duration'] = new_tgt_dur_us

            # Keep group linking intact
            a_seg['group_id']       = v_seg.get('group_id', a_seg.get('group_id', ''))
            a_seg['raw_segment_id'] = v_seg.get('raw_segment_id', a_seg.get('raw_segment_id', ''))

            if corr_offset is not None:
                logger.info(
                    f"WaveSync [{os.path.basename(a_path)}] → "
                    f"timeline {new_tgt_start_us/1e6:.3f}s "
                    f"(v_speech_offset={v_speech_start_s:.3f}s, "
                    f"corr_offset={corr_offset:.3f}s, "
                    f"align={alignment_offset_s:.3f}s, "
                    f"mp3_src=[{a_speech_start_s:.3f}-{a_speech_end_s:.3f}]s)"
                )
            else:
                logger.info(
                    f"WaveSync [{os.path.basename(a_path)}] → "
                    f"timeline {new_tgt_start_us/1e6:.3f}s "
                    f"(speech fallback, mp3_src=[{a_speech_start_s:.3f}-{a_speech_end_s:.3f}]s)"
                )

        except Exception as e:
            logger.error(f"_sync_one_pair failed for audio {a_seg.get('id','')} / video {v_seg.get('id','')}): {e}")

        finally:
            if os.path.exists(temp_v_audio):
                try:
                    os.remove(temp_v_audio)
                except Exception:
                    pass

        return a_seg


def _get_file_duration(path: str) -> float:
    """Return audio/video file duration in seconds using ffprobe (fast)."""
    try:
        probe = ffmpeg.probe(path)
        for stream in probe.get('streams', []):
            dur = stream.get('duration')
            if dur:
                return float(dur)
        # fallback: use format duration
        return float(probe.get('format', {}).get('duration', 0.0))
    except Exception:
        # Last resort: librosa
        if AUDIO_SYNC_AVAILABLE:
            try:
                y, sr = librosa.load(path, sr=None)
                return len(y) / sr
            except Exception:
                pass
    return 0.0


def apply_waveform_sync_to_draft(draft_data: dict, progress_callback=None) -> dict:
    """
    Synchronize audio (MP3) segments with the video dialogue waveform.

    For each audio segment that is paired with a video segment (by render_index,
    then by timeline proximity), we:
      1. Extract the video source audio for that segment.
      2. Detect where dialogue starts in both video and MP3.
      3. Cross-correlate onset envelopes to find the best alignment.
      4. Update source_timerange (pointing to the real speech part of the MP3)
         and target_timerange (timeline placement + correct duration).

    Audio segments that could not be paired are left untouched.
    Overlapping audio segments are redistributed to separate tracks.
    """
    if not AUDIO_SYNC_AVAILABLE:
        logger.warning("Audio sync libraries not available. Skipping waveform sync.")
        return draft_data

    try:
        if progress_callback:
            progress_callback.emit(5, "Starting waveform synchronization...")

        tracks    = draft_data.get('tracks', [])
        materials = draft_data.get('materials', {})

        video_tracks  = [t for t in tracks if t.get('type') == 'video']
        audio_tracks  = [t for t in tracks if t.get('type') == 'audio']

        if not video_tracks or not audio_tracks:
            logger.info("apply_waveform_sync_to_draft: no video or audio tracks found.")
            return draft_data

        processor = AudioVideoSyncProcessor()

        video_mat_map = {m['id']: m for m in materials.get('videos', [])}
        audio_mat_map = {m['id']: m for m in materials.get('audios', [])}

        # ── Collect real MP3 audio segments (not muted, have a material) ────────
        all_audio_segments: List[dict] = []
        for track in audio_tracks:
            for s in track.get('segments', []):
                mat_id = s.get('material_id', '')
                if mat_id and mat_id in audio_mat_map and (s.get('volume', 1.0) or 0) > 0:
                    all_audio_segments.append(s)

        if not all_audio_segments:
            logger.info("apply_waveform_sync_to_draft: no real audio segments to sync.")
            return draft_data

        # ── Build video segment lookup ────────────────────────────────────────────
        video_track    = video_tracks[0]
        video_segments = video_track.get('segments', [])

        # Index by render_index for O(1) lookup
        video_by_render: Dict[int, dict] = {}
        for idx, v_seg in enumerate(video_segments):
            ri = v_seg.get('render_index')
            if ri is None:
                ri = idx
            video_by_render[ri] = v_seg

        # ── Phase 1: Match by render_index ────────────────────────────────────────
        processed: List[dict] = []
        used_ids: set = set()

        total = len(all_audio_segments)
        for i, a_seg in enumerate(all_audio_segments):
            if progress_callback:
                pct = 10 + int(70 * i / max(total, 1))
                progress_callback.emit(pct, f"Syncing segment {i+1}/{total}...")

            aud_ri = a_seg.get('render_index')
            v_seg  = video_by_render.get(aud_ri) if aud_ri is not None else None

            if v_seg:
                a_seg = processor._sync_one_pair(v_seg, a_seg, video_mat_map, audio_mat_map)
                used_ids.add(a_seg['id'])
            processed.append(a_seg)

        # ── Phase 2: Fallback match by timeline proximity ────────────────────────
        for a_seg in processed:
            if a_seg['id'] in used_ids:
                continue
            aud_start = a_seg.get('target_timerange', {}).get('start')
            if aud_start is None:
                continue

            best_v = None
            min_diff = 2_000_000  # 2-second tolerance (microseconds)
            for v_seg in video_segments:
                diff = abs(v_seg['target_timerange']['start'] - aud_start)
                if diff < min_diff:
                    min_diff = diff
                    best_v = v_seg

            if best_v:
                a_seg = processor._sync_one_pair(best_v, a_seg, video_mat_map, audio_mat_map)
                used_ids.add(a_seg['id'])

        # ── Redistribute to non-overlapping tracks ────────────────────────────────
        processed.sort(key=lambda s: s['target_timerange']['start'])
        track_pool: List[List[dict]] = []

        for a_seg in processed:
            placed = False
            seg_start = a_seg['target_timerange']['start']
            for slot in track_pool:
                last = slot[-1]
                last_end = last['target_timerange']['start'] + last['target_timerange']['duration']
                if seg_start >= last_end:
                    slot.append(a_seg)
                    placed = True
                    break
            if not placed:
                track_pool.append([a_seg])

        # ── Rebuild tracks (remove old audio tracks, add fresh ones) ─────────────
        final_tracks = [t for t in tracks if t.get('type') not in ('audio', 'audio_track')]
        for i, slot in enumerate(track_pool):
            final_tracks.append({
                "attribute": 0,
                "flag": 0,
                "id": str(uuid.uuid4()).upper(),
                "is_default_name": True,
                "name": f"Audio {i+1}",
                "segments": slot,
                "type": "audio"
            })

        draft_data['tracks'] = final_tracks

        if progress_callback:
            progress_callback.emit(100, f"Waveform sync completed — {len(processed)} segments synced.")

        logger.info(f"apply_waveform_sync_to_draft: done. {len(processed)} audio segments across {len(track_pool)} tracks.")
        return draft_data

    except Exception as e:
        import traceback
        logger.error(f"Error in apply_waveform_sync_to_draft: {e}\n{traceback.format_exc()}")
        return draft_data


def apply_audio_sync_to_draft(draft_data: dict, sync_mode: str,
                               waveform_sync: bool = False, progress_callback=None) -> dict:
    """
    Apply audio-video sync logic to draft data.

    Args:
        draft_data:    CapCut draft JSON data.
        sync_mode:     'audio_sync' to apply global speed equalisation.
        waveform_sync: If True, apply per-segment waveform synchronisation first.
        progress_callback: Progress callback signal.

    Returns:
        Modified draft data.
    """
    if waveform_sync:
        draft_data = apply_waveform_sync_to_draft(draft_data, progress_callback)

    if sync_mode != 'audio_sync':
        return draft_data

    if not AUDIO_SYNC_AVAILABLE:
        logger.warning("Audio sync libraries not available. Skipping audio-video sync.")
        if progress_callback:
            progress_callback.emit(100, "Audio sync skipped - libraries not available")
        return draft_data

    try:
        if progress_callback:
            progress_callback.emit(5, "Applying audio-video synchronization...")

        tracks        = draft_data.get('tracks', [])
        video_tracks  = [t for t in tracks if t.get('type') == 'video']
        audio_tracks  = [t for t in tracks if t.get('type') == 'audio']

        if not video_tracks or not audio_tracks:
            logger.info("No video or audio tracks found for sync")
            return draft_data

        # Total video timeline duration (sum of all video segment target durations)
        video_duration_us = sum(
            seg.get('target_timerange', {}).get('duration', 0)
            for seg in video_tracks[0].get('segments', [])
        )
        video_duration_s = video_duration_us / 1_000_000.0

        if progress_callback:
            progress_callback.emit(30, f"Video duration: {video_duration_s:.1f}s")

        # Total audio timeline duration
        all_audio_segs = [
            seg
            for track in audio_tracks
            for seg in track.get('segments', [])
        ]
        total_audio_s = sum(
            seg.get('target_timerange', {}).get('duration', 0)
            for seg in all_audio_segs
        ) / 1_000_000.0

        logger.info(f"Total audio: {total_audio_s:.2f}s  |  Video: {video_duration_s:.2f}s")

        if total_audio_s <= video_duration_s or video_duration_s <= 0:
            logger.info("Total audio <= video duration — no speed adjustment needed.")
        else:
            speed_ratio = total_audio_s / video_duration_s
            logger.info(f"Total audio > video → speeding up all audio by {speed_ratio:.4f}x")
            for seg in all_audio_segs:
                old_speed = seg.get('speed', 1.0)
                if not isinstance(old_speed, (int, float)) or old_speed <= 0:
                    old_speed = 1.0
                new_speed = old_speed * speed_ratio
                seg['speed'] = new_speed

                tgt = seg.get('target_timerange', {})
                old_dur = tgt.get('duration', 0)
                tgt['duration'] = max(1, int(old_dur / speed_ratio))
                logger.debug(f"  Speed {old_speed:.3f}x → {new_speed:.3f}x, dur {old_dur} → {tgt['duration']}")

        if progress_callback:
            progress_callback.emit(90, "Audio-video sync applied to draft")

        logger.info("Audio-video synchronization applied to draft data")
        return draft_data

    except Exception as e:
        logger.error(f"Error applying audio-video sync: {str(e)}")
        if progress_callback:
            progress_callback.emit(100, f"Audio sync failed: {str(e)}")
        return draft_data
