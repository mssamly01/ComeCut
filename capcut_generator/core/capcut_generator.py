"""
Core CapCut Draft Generator - Modular version
Split from main app to improve performance and prevent crashes
"""

import os
import json
import copy
import bisect
import uuid
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor

import pysrt
from PyQt6.QtCore import pyqtSignal
from utils.logger import get_logger, log_execution_time, ProgressLogger
from core.audio_video_sync import apply_audio_sync_to_draft

logger = get_logger(__name__)
SCREEN_BOUNDARY_TOLERANCE_US = 5_000
DEFAULT_TIMELINE_FPS = 30.0
CROSS_SCREEN_TEXT_MERGE_MAX_FRAMES = 10

class CapCutDraftGenerator:
    """Main CapCut Draft JSON Generator"""
    
    def __init__(self, 
                 fps: float = 30.0,
                 canvas_width: int = 1920,
                 canvas_height: int = 1440):
        
        self.fps = fps
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.MAX_CONCURRENT_AUDIO = 8 # Recommended: 4, 8, or os.cpu_count() * 2
        
        logger.info(f"CapCut Generator initialized - Max concurrent audio: {self.MAX_CONCURRENT_AUDIO}")
    
    def generate_uuid(self) -> str:
        """Generate UUID in CapCut format"""
        return str(uuid.uuid4()).upper()
    
    def parse_srt(self, srt_file_path: str) -> List[Dict]:
        """Parse SRT file"""
        logger.info(f"Parsing SRT file: {os.path.basename(srt_file_path)}")
        
        try:
            subs = pysrt.open(srt_file_path, encoding='utf-8')
            
            subtitle_segments = []
            
            for sub in subs:
                # Convert SRT time to microseconds
                start_time = (sub.start.hours * 3600 + sub.start.minutes * 60 + 
                             sub.start.seconds + sub.start.milliseconds / 1000.0) * 1000000
                end_time = (sub.end.hours * 3600 + sub.end.minutes * 60 + 
                           sub.end.seconds + sub.end.milliseconds / 1000.0) * 1000000
                
                subtitle_segments.append({
                    'index': sub.index,
                    'srt_start_time': int(start_time),
                    'srt_end_time': int(end_time),
                    'srt_duration': int(end_time - start_time),
                    'text': sub.text.replace('\n', ' ').strip()
                })
            
            logger.info(f"Parsed {len(subtitle_segments)} subtitle segments")
            return subtitle_segments
            
        except Exception as e:
            logger.error(f"Error parsing SRT file: {e}")
            raise
    
    def analyze_subtitle_gaps(self, subtitle_segments: List[Dict], video_duration: int) -> Dict:
        """Analyze gaps in subtitles and create timeline segments"""
        if not subtitle_segments:
            return {
                'timeline_segments': [],
                'subtitle_mapping': {},
                'audio_mapping': {}
            }
        
        logger.info("Analyzing subtitle gaps for timeline...")
        
        sorted_subs = sorted(subtitle_segments, key=lambda x: x['srt_start_time'])
        
        timeline_segments = []
        subtitle_mapping = {}
        audio_mapping = {}
        
        current_time = 0
        segment_index = 0
        audio_file_index = 0
        
        progress = ProgressLogger(len(sorted_subs) + 1, logger)
        
        for i, subtitle in enumerate(sorted_subs):
            sub_start = subtitle['srt_start_time']
            sub_end = subtitle['srt_end_time']
            
            # Check for gaps before this subtitle
            start_time_for_segment = sub_start
            
            if current_time < sub_start:
                gap_duration = sub_start - current_time
                
                # MIN_GAP_THRESHOLD: 50ms = 50000 microseconds
                # If gap is significant, create a gap segment
                if gap_duration > 50000:
                    logger.debug(f"Gap segment {segment_index + 1}: {current_time/1000000:.2f}s→{sub_start/1000000:.2f}s")
                    
                    timeline_segments.append({
                        'segment_index': segment_index,
                        'start_time': current_time,
                        'end_time': sub_start,
                        'duration': gap_duration,
                        'has_subtitle': False,
                        'subtitle_data': None
                    })
                    segment_index += 1
                    current_time = sub_start # Advance current time to start of this subtitle
                else:
                    # Micro-gap: Snap this segment to the previous end time (current_time)
                    logger.debug(f"Micro-gap ignored ({gap_duration/1000:.2f}ms). Snapping segment {segment_index+1} start to {current_time/1000000:.2f}s")
                    start_time_for_segment = current_time

            # Subtitle segment
            # Recalculate duration because we might have snapped start time
            subtitle_duration = sub_end - start_time_for_segment
            
            has_content = subtitle['text'].strip() != ""
            current_audio_index = None
            
            if has_content:
                current_audio_index = audio_file_index
                audio_mapping[audio_file_index] = {
                    'subtitle_index': subtitle['index'],
                    'timeline_segment_index': segment_index,
                    'subtitle_text': subtitle['text']
                }
                audio_file_index += 1
            
            timeline_segments.append({
                'segment_index': segment_index,
                'start_time': start_time_for_segment,
                'end_time': sub_end,
                'duration': subtitle_duration,
                'has_subtitle': has_content,
                'subtitle_data': subtitle if has_content else None,
                'audio_file_index': current_audio_index
            })
            
            subtitle_mapping[segment_index] = subtitle if has_content else None
            segment_index += 1
            current_time = sub_end
            
            progress.step(f"Processed subtitle {i + 1}")
            

        
        # Handle remaining time after last subtitle
        if current_time < video_duration:
            remaining_duration = video_duration - current_time
            timeline_segments.append({
                'segment_index': segment_index,
                'start_time': current_time,
                'end_time': video_duration,
                'duration': remaining_duration,
                'has_subtitle': False,
                'subtitle_data': None
            })
        
        progress.step("Analysis completed")
        
        logger.info(f"Timeline analysis complete: {len(timeline_segments)} segments, "
                   f"{len(audio_mapping)} with audio")
        
        return {
            'timeline_segments': timeline_segments,
            'subtitle_mapping': subtitle_mapping,
            'audio_mapping': audio_mapping
        }
    
    def get_media_duration(self, media_path: str) -> int:
        """Get media duration using ffmpeg-python with fallback"""
        try:
            # Check if file exists first
            if not os.path.exists(media_path):
                raise FileNotFoundError(f"Video file not found: {media_path}")
            
            # Check file size
            file_size = os.path.getsize(media_path)
            if file_size == 0:
                raise ValueError(f"Video file is empty: {media_path}")
                
            import ffmpeg
            
            # Try to probe the file
            try:
                probe = ffmpeg.probe(media_path)
                duration = float(probe['format']['duration'])
                return int(duration * 1000000)  # Convert to microseconds
            except ffmpeg.Error as e:
                # FFmpeg specific error
                logger.error(f"FFmpeg error for {os.path.basename(media_path)}: {e}")
                raise Exception(f"FFmpeg could not process video file: {os.path.basename(media_path)}")
            except Exception as e:
                # Other errors (like subprocess not found)
                logger.error(f"Subprocess/FFmpeg not found: {e}")
                raise Exception(f"FFmpeg executable not found. Please ensure FFmpeg is properly bundled with the application.")
            
        except FileNotFoundError as e:
            logger.error(f"File not found: {media_path}")
            raise e
        except ValueError as e:
            logger.error(str(e))
            raise e
        except Exception as e:
            if "FFmpeg" in str(e):
                raise e
            logger.error(f"Unexpected error getting duration for {os.path.basename(media_path)}: {e}")
            raise Exception(f"Could not get video duration from {os.path.basename(media_path)}: {str(e)}")
    
    def get_video_dimensions(self, media_path: str) -> Tuple[int, int]:
        """Get video width and height using ffmpeg-python."""
        try:
            import ffmpeg
            probe = ffmpeg.probe(media_path)
            video_streams = [s for s in probe.get('streams', []) if s.get('codec_type') == 'video']
            if not video_streams:
                raise ValueError("No video stream found")
            stream = video_streams[0]
            width = int(stream.get('width'))
            height = int(stream.get('height'))
            # Handle potential rotation metadata (transpose width/height if needed)
            tags = stream.get('tags') or {}
            side_data_list = stream.get('side_data_list') or []
            rotation = None
            if 'rotate' in tags:
                try:
                    rotation = int(tags['rotate'])
                except Exception:
                    rotation = None
            else:
                for sd in side_data_list:
                    if sd.get('side_data_type') == 'Display Matrix' and 'rotation' in sd:
                        rotation = int(sd['rotation'])
                        break
            if rotation is not None and abs(rotation) in (90, 270):
                width, height = height, width
            return width, height
        except Exception as e:
            logger.warning(f"Falling back to default canvas size, unable to get dimensions for {os.path.basename(media_path)}: {e}")
            return self.canvas_width, self.canvas_height
    
    def create_material_audio_batch(self, audio_paths_batch: List[str], start_index: int) -> List[Dict]:
        """Create audio materials in batch to optimize memory and speed using multiple threads"""
        audio_materials = []
        
        logger.info(f"Processing audio batch: {len(audio_paths_batch)} files (starting from #{start_index}) using up to {self.MAX_CONCURRENT_AUDIO} threads.")
        
        def process_single_audio(audio_path_with_index):
            """Helper function to process one audio file."""
            original_index, audio_path = audio_path_with_index
            try:
                audio_duration = self.get_media_duration(audio_path)
                filename = os.path.basename(audio_path)
                
                audio_material = self._create_audio_material_dict(audio_path, audio_duration, filename)
                
                # Log progress for first/last items to avoid spamming the log
                if original_index < start_index + 2 or original_index >= start_index + len(audio_paths_batch) - 2:
                    logger.debug(f"Audio {original_index + 1}: '{filename}' ({audio_duration/1000000:.2f}s) processed.")
                
                return audio_material
            except Exception as e:
                logger.error(f"Error processing audio file {os.path.basename(audio_path)}: {e}")
                return None # Return None on failure

        # Use a thread pool to process audio files in parallel
        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT_AUDIO) as executor:
                # We map the process_single_audio function to each path in the batch
                # We also pass the original index for logging purposes
                paths_with_indices = list(enumerate(audio_paths_batch, start=start_index))
                
                # executor.map will run the function on each item in parallel
                results = list(executor.map(process_single_audio, paths_with_indices))

                # Filter out any 'None' results from failed processing
                audio_materials = [res for res in results if res is not None]

        return audio_materials
    
    def _create_audio_material_dict(self, audio_path: str, duration: int, filename: str) -> Dict:
        """Create audio material dictionary"""
        return {
            "ai_music_generate_scene": 0,
            "ai_music_type": 0,
            "aigc_history_id": "",
            "aigc_item_id": "",
            "app_id": 0,
            "category_id": "",
            "category_name": "local",
            "check_flag": 1,
            "cloned_model_type": "",
            "copyright_limit_type": "none",
            "duration": duration,
            "effect_id": "",
            "formula_id": "",
            "id": self.generate_uuid(),
            "intensifies_path": "",
            "is_ai_clone_tone": False,
            "is_ai_clone_tone_post": False,
            "is_text_edit_overdub": False,
            "is_ugc": False,
            "local_material_id": self.generate_uuid().lower(),
            "lyric_type": 0,
            "moyin_emotion": "",
            "music_id": self.generate_uuid().lower(),
            "music_source": "",
            "name": filename,
            "path": os.path.abspath(audio_path),
            "pgc_id": "",
            "pgc_name": "",
            "query": "",
            "request_id": "",
            "resource_id": "",
            "search_id": "",
            "similiar_music_info": {
                "original_song_id": "",
                "original_song_name": ""
            },
            "sound_separate_type": "",
            "source_from": "",
            "source_platform": 0,
            "team_id": "",
            "text_id": "",
            "third_resource_id": "",
            "tone_category_id": "",
            "tone_category_name": "",
            "tone_effect_id": "",
            "tone_effect_name": "",
            "tone_emotion_name_key": "",
            "tone_emotion_role": "",
            "tone_emotion_scale": 0.0,
            "tone_emotion_selection": "",
            "tone_emotion_style": "",
            "tone_platform": "",
            "tone_second_category_id": "",
            "tone_second_category_name": "",
            "tone_speaker": "",
            "tone_type": "",
            "tts_generate_scene": "",
            "tts_task_id": "",
            "type": "extract_music",
            "video_id": "",
            "wave_points": []
        }
    
    def create_material_video(self, video_path: str, export_lt8: bool = False) -> Dict:
        video_duration = self.get_media_duration(video_path)
        video_width, video_height = self.get_video_dimensions(video_path)
        filename = os.path.basename(video_path)
        logger.info(f"Creating video material (new structure): {filename} ({video_duration/1000000:.2f}s)")

        video_material = {
            "aigc_history_id": "", "aigc_item_id": "", "aigc_type": "none", "audio_fade": None,
            "beauty_body_preset_id": "",
            "beauty_face_auto_preset": {"name": "", "preset_id": "", "rate_map": "", "scene": ""},
            "beauty_face_auto_preset_infos": [], "beauty_face_preset_infos": [], "cartoon_path": "",
            "category_id": "", "category_name": "local", "check_flag": 62978047,
            "content_feature_info": None,
            "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0, "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
            "crop_ratio": "free", "crop_scale": 1.0, "duration": video_duration,
            "extra_type_option": 0,
            "formula_id": "", "freeze": None, "has_audio": True,
            "has_sound_separated": False,
            "height": video_height, "id": self.generate_uuid(), "intensifies_audio_path": "", "intensifies_path": "",
            "is_ai_generate_content": False, "is_copyright": False, "is_text_edit_overdub": False, "is_unified_beauty_mode": False,
            "live_photo_cover_path": "", "live_photo_timestamp": -1, "local_id": "", "local_material_from": "",
            "local_material_id": self.generate_uuid().lower(), "material_id": "", "material_name": filename, "material_url": "",
            "matting": {"custom_matting_id": "", "enable_matting_stroke": False, "expansion": 0, "feather": 0, "flag": 0, "has_use_quick_brush": False, "has_use_quick_eraser": False, "interactiveTime": [], "path": "", "reverse": False, "strokes": []},
            "media_path": "", "multi_camera_info": None, "object_locked": None, "origin_material_id": "",
            "path": os.path.abspath(video_path), "picture_from": "none", "picture_set_category_id": "", "picture_set_category_name": "", "request_id": "",
            "reverse_intensifies_path": "", "reverse_path": "", "smart_match_info": None, "smart_motion": None,
            "source": 0, "source_platform": 0,
            "stable": {"matrix_path": "", "stable_level": 0, "time_range": {"duration": 0, "start": 0}},
            "team_id": "", "type": "video",
            "video_algorithm": {
                "ai_background_configs": [], "ai_expression_driven": None, "ai_motion_driven": None, "aigc_generate": None,
                "algorithms": [], "complement_frame_config": None, "deflicker": None, "gameplay_configs": [],
                "image_interpretation": None, "motion_blur_config": None, "mouth_shape_driver": None, "noise_reduction": None,
                "path": "", "quality_enhance": None, "smart_complement_frame": None,
                "story_video_modify_video_config": {"is_overwrite_last_video": False, "task_id": "", "tracker_task_id": ""},
                "super_resolution": None,
                "time_range": None
            },
            "width": video_width
        }

        if export_lt8:
            # Legacy (<8.0) profile keeps simpler video material, but still needs
            # these algorithm keys for compatibility with older drafts.
            video_algorithm = video_material.get("video_algorithm", {})
            video_algorithm.update({
                "ai_in_painting_config": [],
                "aigc_generate_list": [],
                "skip_algorithm_index": [],
                "time_range": None
            })

        return video_material

    def _create_function_assistant_info(self) -> Dict:
        """Create default function assistant metadata for legacy (<8.0) drafts."""
        return {
            "audio_noise_segid_list": [],
            "auto_adjust": False,
            "auto_adjust_fixed": False,
            "auto_adjust_fixed_value": 50.0,
            "auto_adjust_segid_list": [],
            "auto_caption": False,
            "auto_caption_segid_list": [],
            "auto_caption_template_id": "",
            "caption_opt": False,
            "caption_opt_segid_list": [],
            "color_correction": False,
            "color_correction_fixed": False,
            "color_correction_fixed_value": 50.0,
            "color_correction_segid_list": [],
            "deflicker_segid_list": [],
            "enhance_quality": False,
            "enhance_quality_fixed": False,
            "enhance_quality_segid_list": [],
            "enhance_voice_segid_list": [],
            "enhande_voice": False,
            "enhande_voice_fixed": False,
            "eye_correction": False,
            "eye_correction_segid_list": [],
            "fixed_rec_applied": False,
            "fps": {
                "den": 1,
                "num": 0
            },
            "normalize_loudness": False,
            "normalize_loudness_audio_denoise_segid_list": [],
            "normalize_loudness_fixed": False,
            "normalize_loudness_segid_list": [],
            "retouch": False,
            "retouch_fixed": False,
            "retouch_segid_list": [],
            "smart_rec_applied": False,
            "smart_segid_list": [],
            "smooth_slow_motion": False,
            "smooth_slow_motion_fixed": False,
            "video_noise_segid_list": []
        }

    def create_material_text(self, text_content: str, group_id: str) -> Dict:
        """Create text material from subtitle"""
        return {
            "add_type": 2,
            "alignment": 1,
            "background_alpha": 1.0,
            "background_color": "",
            "background_fill": "",
            "background_height": 0.14,
            "background_horizontal_offset": 0.0,
            "background_round_radius": 0.0,
            "background_style": 0,
            "background_vertical_offset": 0.0,
            "background_width": 0.14,
            "base_content": "",
            "bold_width": 0.0,
            "border_alpha": 1.0,
            "border_color": "",
            "border_width": 0.08,
            "caption_template_info": {
                "category_id": "",
                "category_name": "",
                "effect_id": "",
                "is_new": False,
                "path": "",
                "request_id": "",
                "resource_id": "",
                "resource_name": "",
                "source_platform": 0,
                "third_resource_id": ""
            },
            "check_flag": 7,
            "combo_info": {
                "text_templates": []
            },
            "content": json.dumps({
                "styles": [{
                    "fill": {
                        "alpha": 1.0,
                        "content": {
                            "render_type": "solid",
                            "solid": {
                                "alpha": 1.0,
                                "color": [1.0, 1.0, 1.0]
                            }
                        }
                    },
                    "font": {
                        "id": "",
                        "path": ""
                    },
                    "range": [0, len(text_content)],
                    "size": 5.0
                }],
                "text": text_content
            }),
            "current_words": {
                "end_time": [],
                "start_time": [],
                "text": []
            },
            "cutoff_postfix": "",
            "fixed_height": -1.0,
            "fixed_width": -1.0,
            "font_category_id": "",
            "font_category_name": "",
            "font_id": "",
            "font_name": "",
            "font_path": "",
            "font_resource_id": "",
            "font_size": 5.0,
            "font_source_platform": 0,
            "font_team_id": "",
            "font_third_resource_id": "",
            "font_title": "none",
            "font_url": "",
            "fonts": [],
            "force_apply_line_max_width": False,
            "global_alpha": 1.0,
            "group_id": group_id,
            "has_shadow": False,
            "id": self.generate_uuid(),
            "initial_scale": 1.0,
            "inner_padding": -1.0,
            "is_lyric_effect": False,
            "is_rich_text": False,
            "is_words_linear": False,
            "italic_degree": 0,
            "ktv_color": "",
            "language": "",
            "layer_weight": 1,
            "letter_spacing": 0.0,
            "line_feed": 1,
            "line_max_width": 0.82,
            "line_spacing": 0.02,
            "lyric_group_id": "",
            "lyrics_template": {
                "category_id": "",
                "category_name": "",
                "effect_id": "",
                "panel": "",
                "path": "",
                "request_id": "",
                "resource_id": "",
                "resource_name": ""
            },
            "multi_language_current": "none",
            "name": "",
            "oneline_cutoff": False,
            "operation_type": 0,
            "original_size": [],
            "preset_category": "",
            "preset_category_id": "",
            "preset_has_set_alignment": False,
            "preset_id": "",
            "preset_index": 0,
            "preset_name": "",
            "recognize_task_id": "",
            "recognize_text": "",
            "recognize_type": 0,
            "relevance_segment": [],
            "shadow_alpha": 0.9,
            "shadow_angle": -45.0,
            "shadow_color": "",
            "shadow_distance": 5.0,
            "shadow_point": {
                "x": 0.6363961030678928,
                "y": -0.6363961030678928
            },
            "shadow_smoothing": 0.45,
            "shape_clip_x": False,
            "shape_clip_y": False,
            "source_from": "",
            "ssml_content": "",
            "style_name": "",
            "sub_template_id": -1,
            "sub_type": 0,
            "subtitle_keywords": None,
            "subtitle_keywords_config": None,
            "subtitle_template_original_fontsize": 0.0,
            "text_alpha": 1.0,
            "text_color": "#FFFFFF",
            "text_curve": None,
            "text_preset_resource_id": "",
            "text_size": 30,
            "text_to_audio_ids": [],
            "translate_original_text": "",
            "tts_auto_update": False,
            "type": "subtitle",
            "typesetting": 0,
            "underline": False,
            "underline_offset": 0.22,
            "underline_width": 0.05,
            "use_effect_default_color": True,
            "words": {
                "end_time": [],
                "start_time": [],
                "text": []
            }
        }
    
    def create_helper_materials(self, count: int) -> Dict:
        """Create helper materials"""
        
        logger.info(f"Creating {count} helper materials...")
        
        helpers = {
            "speeds": [],
            "beats": [],
            "canvases": [],
            "material_animations": [],
            "placeholder_infos": [],
            "sound_channel_mappings": [],
            "vocal_separations": []
        }
        
        for i in range(count):
            helpers["speeds"].append(self._create_speed_material())
            helpers["beats"].append(self._create_beat_material())
            helpers["canvases"].append(self._create_canvas_material())
            helpers["material_animations"].append(self._create_animation_material())
            helpers["placeholder_infos"].append(self._create_placeholder_material())
            helpers["sound_channel_mappings"].append(self._create_sound_channel_material())
            helpers["vocal_separations"].append(self._create_vocal_separation_material())
        
        logger.info("Helper materials creation completed")
        return helpers
    
    def _create_speed_material(self) -> Dict:
        """Create speed material"""
        return {
            "curve_speed": None,
            "id": self.generate_uuid(),
            "mode": 0,
            "speed": 1.0,
            "type": "speed"
        }
    
    def _create_beat_material(self) -> Dict:
        """Create beat material"""
        return {
            "ai_beats": {
                "beat_speed_infos": [],
                "beats_path": "",
                "beats_url": "",
                "melody_path": "",
                "melody_percents": [0.0],
                "melody_url": ""
            },
            "enable_ai_beats": False,
            "gear": 404,
            "gear_count": 0,
            "id": self.generate_uuid(),
            "mode": 404,
            "type": "beats",
            "user_beats": [],
            "user_delete_ai_beats": None
        }
    
    def _create_canvas_material(self) -> Dict:
        """Create canvas material"""
        return {
            "album_image": "",
            "blur": 0.0,
            "color": "",
            "id": self.generate_uuid(),
            "image": "",
            "image_id": "",
            "image_name": "",
            "source_platform": 0,
            "team_id": "",
            "type": "canvas_color"
        }
    
    def _create_animation_material(self) -> Dict:
        """Create animation material"""
        return {
            "animations": [],
            "id": self.generate_uuid(),
            "multi_language_current": "none",
            "type": "sticker_animation"
        }
    
    def _create_placeholder_material(self) -> Dict:
        """Create placeholder material"""
        return {
            "error_path": "",
            "error_text": "",
            "id": self.generate_uuid(),
            "meta_type": "none",
            "res_path": "",
            "res_text": "",
            "type": "placeholder_info"
        }
    
    def _create_sound_channel_material(self) -> Dict:
        """Create sound channel material"""
        return {
            "audio_channel_mapping": 0,
            "id": self.generate_uuid(),
            "is_config_open": False,
            "type": ""
        }
    
    def _create_vocal_separation_material(self) -> Dict:
        """Create vocal separation material"""
        return {
            "choice": 0,
            "enter_from": "",
            "final_algorithm": "",
            "id": self.generate_uuid(),
            "production_path": "",
            "removed_sounds": [],
            "time_range": None,
            "type": "vocal_separation"
        }
    
    def calculate_speed(self, original_duration: int, target_duration: int) -> float:
        """Calculate speed to match target duration"""
        if target_duration <= 0:
            return 1.0
        return original_duration / target_duration
    
    @log_execution_time(logger)
    def generate_single_json(self, 
                           progress_callback: Optional[pyqtSignal], 
                           video_path: str, 
                           audio_files: List[str], 
                           srt_path: str, 
                           output_json_path: str, 
                           gap_aware_mode: bool = False,
                           target_audio_speed: float = 1.0,
                           keep_pitch: bool = True,
                           sync_mode: str = 'video_priority',
                           video_speed_enabled: bool = False,
                           target_video_speed: float = 1.0,
                           remove_silence: bool = False,
                           waveform_sync: bool = False,
                           timestamp_screen: List[int] = None,
                           skip_stretch_shorter: bool = False,
                           export_lt8: bool = False) -> Optional[str]:
        """
        Main function to generate CapCut draft JSON file
        Returns path to created JSON file or None if failed
        """
        def emit_progress(percent, message):
            if progress_callback:
                progress_callback.emit(percent, message)

        mode_name = "Gap-Aware Mode" if gap_aware_mode else "Classic Mode"
        silence_info = " - Remove Silence: Enabled" if remove_silence else ""
        video_speed_info = f" - Video Speed: {target_video_speed}x" if target_video_speed != 1.0 else " - Video Speed: 1.0x (default)"
        logger.info(f"Starting CapCut Draft JSON Generator - {mode_name} - Target Audio Speed: {target_audio_speed}x{video_speed_info}{silence_info}")
        
        processed_temp_audios = [] # To keep track for cleanup

        try:
            emit_progress(0, "Starting generation process...")
            
            # Step 0: Smart Trimming Initialization (if enabled)
            processor = None
            if remove_silence:
                from core.audio_video_sync import AudioVideoSyncProcessor
                processor = AudioVideoSyncProcessor()
                
                if not processor.is_available():
                    logger.error("Smart Trimming (silence removal) requested but libraries (librosa/soundfile) are not available.")
                    emit_progress(2, "Smart Trimming FAILED (libraries missing)...")
                    processor = None
                else:
                    emit_progress(2, "Smart Trimming initialized...")
                    logger.info("Smart Trimming enabled (metadata-only mode)")

            # Step 1: Parse SRT file
            emit_progress(5, f"Parsing SRT file: {os.path.basename(srt_path)}...")
            subtitle_segments = self.parse_srt(srt_path)
            if not subtitle_segments:
                logger.error("No subtitles found in SRT file")
                return None
            
            # Step 2: Analyze video
            emit_progress(10, "Analyzing video duration...")
            total_video_duration = self.get_media_duration(video_path)
            if total_video_duration <= 0:
                logger.error("Could not get video duration")
                return None
            
            logger.info(f"Video duration: {total_video_duration/1000000:.2f}s")
            
            # Step 3: Process based on mode
            emit_progress(15, "Processing materials...")
            if gap_aware_mode:
                timeline_data = self.analyze_subtitle_gaps(subtitle_segments, total_video_duration)
                timeline_segments = timeline_data['timeline_segments']
                audio_mapping = timeline_data['audio_mapping']
                
                audio_materials, text_materials = self._process_gap_aware_materials(
                    audio_files, audio_mapping
                )
            else:
                timeline_segments = subtitle_segments
                audio_materials, text_materials = self._process_classic_materials(
                    audio_files, subtitle_segments
                )
            
            # Step 4: Create video material
            emit_progress(40, "Creating video material...")
            video_material = self.create_material_video(video_path, export_lt8=export_lt8)
            
            # Step 5: Create helper materials
            emit_progress(50, "Creating helper materials...")
            helper_count = len(timeline_segments) * 5
            helpers = self.create_helper_materials(helper_count)
            
            # Step 6: Create segments
            emit_progress(60, "Creating timeline segments...")
            segments_data = self._create_segments(
                timeline_segments, audio_materials, text_materials, 
                video_material, helpers, gap_aware_mode,
                target_audio_speed,
                keep_pitch,
                sync_mode,
                remove_silence=remove_silence,
                processor=processor,
                progress_callback=progress_callback,
                timestamp_screen=timestamp_screen,
                target_video_speed=target_video_speed,
                video_speed_enabled=video_speed_enabled,
                skip_stretch_shorter=skip_stretch_shorter
            )
            
            # Step 7: Create final draft content
            emit_progress(90, "Assembling final JSON file...")
            draft_content = self._create_draft_content(
                segments_data, audio_materials, text_materials, 
                video_material, helpers, segments_data['total_duration'],
                export_lt8=export_lt8
            )
            
            # Step 7.5: Apply audio-video sync if needed
            if sync_mode == 'audio_sync' or waveform_sync:
                emit_progress(92, "Applying audio-video synchronization...")
                synced_draft = apply_audio_sync_to_draft(draft_content, sync_mode, waveform_sync, progress_callback)
                if synced_draft:
                    draft_content = synced_draft
                    logger.info("Audio-video synchronization applied")
            
            # Step 8: Save JSON file
            emit_progress(95, f"Saving to {os.path.basename(output_json_path)}...")
            self._save_project(draft_content, output_json_path)
            
            logger.info(f"✅ Successfully created: {output_json_path}")
            logger.info(f"Mode: {mode_name}")
            
            emit_progress(100, "Generation complete!")
            return output_json_path
            
        except Exception as e:
            logger.error(f"Error generating JSON: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _process_gap_aware_materials(self, audio_files: List[str], audio_mapping: Dict) -> Tuple[List[Dict], List[Dict]]:
        """Process materials for gap-aware mode"""
        audio_materials = []
        text_materials = []
        text_group_id = f"import_{int(time.time() * 1000)}"
        
        # Get audio files based on mapping
        audio_files_to_process = []
        for audio_idx, mapping_info in audio_mapping.items():
            if audio_idx < len(audio_files):
                audio_files_to_process.append((audio_idx, audio_files[audio_idx], mapping_info))
        
        # Process audio in batches
        batch_size = 50 # This batch size is for feeding into the multi-threaded function
        for batch_start in range(0, len(audio_files_to_process), batch_size):
            batch_end = min(batch_start + batch_size, len(audio_files_to_process))
            current_batch = audio_files_to_process[batch_start:batch_end]
            
            # Process audio batch using the multi-threaded function
            batch_audio_paths = [item[1] for item in current_batch]
            batch_audio_materials = self.create_material_audio_batch(batch_audio_paths, batch_start)
            
            # Create text materials for this batch
            for i, (audio_idx, audio_path, mapping_info) in enumerate(current_batch):
                if i < len(batch_audio_materials):
                    text_material = self.create_material_text(mapping_info['subtitle_text'], text_group_id)
                    text_materials.append(text_material)
            
            audio_materials.extend(batch_audio_materials)
        
        return audio_materials, text_materials
    
    def _process_classic_materials(self, audio_files: List[str], subtitle_segments: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Process materials for classic mode"""
        audio_materials = []
        text_materials = []
        
        num_to_process = min(len(subtitle_segments), len(audio_files))
        batch_size = 50 # This batch size is for feeding into the multi-threaded function
        text_group_id = f"import_{int(time.time() * 1000)}"
        
        for batch_start in range(0, num_to_process, batch_size):
            batch_end = min(batch_start + batch_size, num_to_process)
            
            # Process audio batch using the multi-threaded function
            batch_audio_paths = audio_files[batch_start:batch_end]
            batch_audio_materials = self.create_material_audio_batch(batch_audio_paths, batch_start)
            
            # Process text batch
            for i in range(batch_start, batch_end):
                if i < len(subtitle_segments):
                    text_material = self.create_material_text(subtitle_segments[i]['text'], text_group_id)
                    text_materials.append(text_material)
            
            audio_materials.extend(batch_audio_materials)
        
        return audio_materials, text_materials
    
    def _create_segments(self, timeline_segments: List[Dict], audio_materials: List[Dict], 
                        text_materials: List[Dict], video_material: Dict, helpers: Dict, 
                        gap_aware_mode: bool, target_audio_speed: float, keep_pitch: bool, 
                        sync_mode: str, 
                        remove_silence: bool = False,
                        processor = None,
                        progress_callback: Optional[pyqtSignal] = None,
                        timestamp_screen: List[int] = None,
                        target_video_speed: float = 1.0,
                        video_speed_enabled: bool = False,
                        skip_stretch_shorter: bool = False) -> Dict:
        """Create all segments with memory optimization"""
        
        from core.segment_creator import SegmentCreator
        
        segment_creator = SegmentCreator(self, helpers, gap_aware_mode)
        
        segments_result = segment_creator.create_all_segments(
            timeline_segments, 
            audio_materials, 
            text_materials, 
            video_material,
            target_audio_speed, 
            keep_pitch,
            sync_mode,
            video_speed_enabled,
            target_video_speed,
            remove_silence,
            processor,
            progress_callback,
            timestamp_screen,
            skip_stretch_shorter
        )
        
        # Post-process for gap-aware mode - DISABLED to avoid silent gaps
        # if gap_aware_mode:
        #     segments_result = self._fix_gap_aware_audio_sync(
        #         segments_result, timeline_segments, segment_creator
        #     )
        
        # Bind segments to groups and enforce structural alignment
        segments_result = self._bind_segments_by_timeline_group(segments_result, audio_materials, text_materials)

        # Collapse video segments to one segment per screen while keeping text/audio positions.
        if timestamp_screen:
            segments_result = self._collapse_video_segments_by_screen(segments_result, timestamp_screen, helpers)
        
        return segments_result

    def _normalize_timestamp_screen_to_us(self, timestamp_screen: List[int]) -> List[int]:
        """Normalize timestamp_screen values to microseconds."""
        if not timestamp_screen:
            return []

        numeric_values = []
        for ts in timestamp_screen:
            try:
                numeric_values.append(float(ts))
            except (TypeError, ValueError):
                logger.warning(f"Generator: Ignoring invalid timestamp_screen value: {ts}")

        if not numeric_values:
            return []

        max_value = max(abs(v) for v in numeric_values)
        has_fractional = any(not float(v).is_integer() for v in numeric_values)
        if max_value >= 100_000:
            logger.info("Generator: timestamp_screen detected as microseconds")
            return sorted(int(v) for v in numeric_values)

        if max_value >= 1_000 and not has_fractional:
            logger.info("Generator: timestamp_screen detected as milliseconds and converted to microseconds")
            return sorted(int(v * 1_000) for v in numeric_values)

        logger.info("Generator: timestamp_screen detected as seconds and converted to microseconds")
        return sorted(int(v * 1_000_000) for v in numeric_values)

    def _collapse_video_segments_by_screen(self, segments_result: Dict, timestamp_screen: List[int], helpers: Dict) -> Dict:
        """
        Collapse consecutive video segments into one segment per screen.
        Audio/text segments keep their target positions and are re-linked by group metadata.
        """
        timestamp_screen_us = self._normalize_timestamp_screen_to_us(timestamp_screen)
        if not timestamp_screen_us:
            return segments_result

        video_segments = segments_result.get('video_segments', [])
        text_segments = segments_result.get('text_segments', [])
        audio_segments = segments_result.get('audio_segments', [])
        if not video_segments:
            return segments_result

        last_boundary = int(timestamp_screen_us[-1])
        max_source_end = max(
            int(seg.get('source_timerange', {}).get('start', 0)) + int(seg.get('source_timerange', {}).get('duration', 0))
            for seg in video_segments
        )
        max_target_end = max(
            int(seg.get('target_timerange', {}).get('start', 0)) + int(seg.get('target_timerange', {}).get('duration', 0))
            for seg in video_segments
        )
        use_target_boundaries = abs(last_boundary - max_target_end) < abs(last_boundary - max_source_end)
        logger.info(
            "Generator: Interpreting screen boundaries as %s timeline",
            "target" if use_target_boundaries else "source",
        )

        def split_segment_at_screen_boundaries(seg: Dict) -> List[Dict]:
            src = seg.get('source_timerange') or {}
            tgt = seg.get('target_timerange') or {}
            src_start = int(src.get('start', 0))
            src_dur = int(src.get('duration', 0))
            tgt_start = int(tgt.get('start', 0))
            tgt_dur = int(tgt.get('duration', 0))

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
                    part['id'] = self.generate_uuid()
                    part['source_timerange'] = {'start': int(running_src_start), 'duration': int(part_src_dur)}
                    part['target_timerange'] = {'start': int(part_tgt_start), 'duration': int(part_tgt_dur)}
                    part['speed'] = (part_src_dur / part_tgt_dur) if part_tgt_dur > 0 else seg.get('speed', 1.0)
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
                    tentative = int(round((part_src_dur / max(1, remaining_src)) * remaining_tgt))
                    parts_left = (len(cut_points) - 1) - i
                    min_reserved_for_rest = parts_left - 1
                    max_allowed = max(1, remaining_tgt - min_reserved_for_rest)
                    part_tgt_dur = min(max(1, tentative), max_allowed)

                part = copy.deepcopy(seg)
                part['id'] = self.generate_uuid()
                part['source_timerange'] = {'start': int(part_src_start), 'duration': int(part_src_dur)}
                part['target_timerange'] = {'start': int(running_tgt_start), 'duration': int(part_tgt_dur)}
                part['speed'] = (part_src_dur / part_tgt_dur) if part_tgt_dur > 0 else seg.get('speed', 1.0)
                split_parts.append(part)

                running_tgt_start += part_tgt_dur
                remaining_src -= part_src_dur
                remaining_tgt -= part_tgt_dur

            return split_parts if split_parts else [seg]

        sorted_video = sorted(video_segments, key=lambda s: s.get('target_timerange', {}).get('start', 0))
        expanded_video = []
        for seg in sorted_video:
            expanded_video.extend(split_segment_at_screen_boundaries(seg))

        grouped = []
        for seg in expanded_video:
            boundary_start = seg.get('target_timerange', {}).get('start', 0) if use_target_boundaries else seg.get('source_timerange', {}).get('start', 0)
            screen_idx = bisect.bisect_right(timestamp_screen_us, int(boundary_start) + SCREEN_BOUNDARY_TOLERANCE_US)
            if not grouped or grouped[-1]['screen_idx'] != screen_idx:
                grouped.append({'screen_idx': screen_idx, 'segments': [seg]})
            else:
                grouped[-1]['segments'].append(seg)

        collapsed_video_segments = []
        screen_ranges = []

        def attach_speed_material(seg: Dict, speed_value: float):
            speed_material = {
                'id': self.generate_uuid(),
                'speed': speed_value,
                'type': 'speed',
                'curve_speed': None,
                'mode': 0,
            }
            helpers['speeds'].append(speed_material)

            refs = seg.get('extra_material_refs')
            if not isinstance(refs, list):
                refs = []
            if refs:
                refs[0] = speed_material['id']
            else:
                refs.append(speed_material['id'])
            seg['extra_material_refs'] = refs

        for group in grouped:
            segs = group['segments']
            first = segs[0]

            if len(segs) == 1:
                only_seg = first
                target_start = only_seg.get('target_timerange', {}).get('start', 0)
                target_duration = only_seg.get('target_timerange', {}).get('duration', 0)
                screen_ranges.append({
                    'start': target_start,
                    'end': target_start + target_duration,
                    'group_id': only_seg.get('group_id', ''),
                    'raw_segment_id': only_seg.get('raw_segment_id', ''),
                })
                collapsed_video_segments.append(only_seg)
                continue

            source_start = first.get('source_timerange', {}).get('start', 0)
            source_end = max(
                (s.get('source_timerange', {}).get('start', 0) + s.get('source_timerange', {}).get('duration', 0))
                for s in segs
            )
            target_start = first.get('target_timerange', {}).get('start', 0)
            target_end = max(
                (s.get('target_timerange', {}).get('start', 0) + s.get('target_timerange', {}).get('duration', 0))
                for s in segs
            )

            source_duration = max(1, int(source_end - source_start))
            target_duration = max(1, int(target_end - target_start))
            merged_speed = source_duration / target_duration

            merged_seg = copy.deepcopy(first)
            merged_seg['id'] = self.generate_uuid()
            merged_seg['source_timerange'] = {'start': int(source_start), 'duration': int(source_duration)}
            merged_seg['target_timerange'] = {'start': int(target_start), 'duration': int(target_duration)}
            merged_seg['speed'] = merged_speed

            merged_group_id = first.get('group_id') or self.generate_uuid()
            merged_raw_id = first.get('raw_segment_id') or self.generate_uuid()
            merged_seg['group_id'] = merged_group_id
            merged_seg['raw_segment_id'] = merged_raw_id

            attach_speed_material(merged_seg, merged_speed)

            collapsed_video_segments.append(merged_seg)
            screen_ranges.append({
                'start': target_start,
                'end': target_start + target_duration,
                'group_id': merged_group_id,
                'raw_segment_id': merged_raw_id,
            })

            logger.info(
                "Generator: Collapsed Screen %s from %s video segments into 1",
                group['screen_idx'],
                len(segs),
            )

        # Merge consecutive screens that contain only gap (no text/audio content).
        if collapsed_video_segments:
            effective_fps = float(self.fps) if isinstance(self.fps, (int, float)) and float(self.fps) > 0 else DEFAULT_TIMELINE_FPS
            frame_duration_us = max(1, int(round(1_000_000 / effective_fps)))
            max_cross_text_overlap_us = CROSS_SCREEN_TEXT_MERGE_MAX_FRAMES * frame_duration_us
            multi_screen_merge_min_screens = 3
            multi_screen_dominant_overlap_ratio_max = 0.60

            def overlaps_screen(seg_range: tuple, screen_info: Dict) -> bool:
                seg_start, seg_end = seg_range
                return seg_start < screen_info['end'] and seg_end > screen_info['start']

            def overlap_duration_us(seg_range: tuple, screen_info: Dict) -> int:
                seg_start, seg_end = seg_range
                overlap_start = max(seg_start, int(screen_info['start']))
                overlap_end = min(seg_end, int(screen_info['end']))
                return max(0, int(overlap_end - overlap_start))

            def clamp_minor_cross_overlap(segments: List[Dict], segment_label: str):
                adjusted = 0
                for seg in segments:
                    target_timerange = seg.get('target_timerange') or {}
                    seg_start = target_timerange.get('start')
                    seg_duration = target_timerange.get('duration', 0)
                    if seg_start is None or seg_duration <= 0:
                        continue

                    seg_start = int(seg_start)
                    seg_end = seg_start + int(seg_duration)

                    seg_range = (seg_start, seg_end)
                    overlapping_screens = []
                    for idx, screen_info in enumerate(screen_ranges):
                        overlap_us = overlap_duration_us(seg_range, screen_info)
                        if overlap_us <= 0:
                            continue

                        screen_duration = int(screen_info['end']) - int(screen_info['start'])
                        overlapping_screens.append({
                            'index': idx,
                            'overlap': overlap_us,
                            'screen': screen_info,
                            'screen_duration': screen_duration,
                        })

                    if len(overlapping_screens) < 2:
                        continue

                    has_minor_adjacent_overlap = False
                    for i in range(len(overlapping_screens) - 1):
                        left = overlapping_screens[i]
                        right = overlapping_screens[i + 1]
                        if right['index'] != left['index'] + 1:
                            continue

                        if min(left['overlap'], right['overlap']) <= max_cross_text_overlap_us:
                            has_minor_adjacent_overlap = True
                            break

                    if not has_minor_adjacent_overlap:
                        continue

                    significant_overlaps = [
                        item for item in overlapping_screens
                        if item['overlap'] > max_cross_text_overlap_us
                    ]
                    if len(significant_overlaps) >= 2:
                        continue

                    target_overlap = max(overlapping_screens, key=lambda item: item['overlap'])

                    # Avoid snapping to very short transition screens when a regular screen overlaps.
                    if target_overlap['screen_duration'] <= max_cross_text_overlap_us:
                        non_transition_candidates = [
                            item for item in overlapping_screens
                            if item['screen_duration'] > max_cross_text_overlap_us
                        ]
                        if non_transition_candidates:
                            target_overlap = max(non_transition_candidates, key=lambda item: item['overlap'])

                    target_screen = target_overlap['screen']
                    new_start = max(seg_start, int(target_screen['start']))
                    new_end = min(seg_end, int(target_screen['end']))
                    if new_end > new_start:
                        seg.setdefault('target_timerange', {})['start'] = int(new_start)
                        seg['target_timerange']['duration'] = int(max(1, new_end - new_start))
                        adjusted += 1

                if adjusted:
                    logger.info(
                        "Generator: Snapped %s %s segments with minor cross-screen overlap (<= %s frames)",
                        adjusted,
                        segment_label,
                        CROSS_SCREEN_TEXT_MERGE_MAX_FRAMES,
                    )

            # For tiny spill-over (<= 10 frames), keep one screen and snap segment timing to that screen.
            clamp_minor_cross_overlap(text_segments, 'text')
            clamp_minor_cross_overlap(audio_segments, 'audio')

            text_ranges = [
                (
                    int(seg.get('target_timerange', {}).get('start', 0)),
                    int(seg.get('target_timerange', {}).get('start', 0)) + max(1, int(seg.get('target_timerange', {}).get('duration', 0))),
                )
                for seg in text_segments
                if seg.get('target_timerange', {}).get('start') is not None
            ]
            text_range_stats = []
            for seg_range in text_ranges:
                per_screen_overlaps = [
                    overlap_duration_us(seg_range, screen_info)
                    for screen_info in screen_ranges
                ]
                positive_overlaps = [ov for ov in per_screen_overlaps if ov > 0]
                total_overlap = sum(positive_overlaps)
                max_overlap = max(positive_overlaps) if positive_overlaps else 0
                dominant_ratio = (max_overlap / total_overlap) if total_overlap > 0 else 1.0
                text_range_stats.append({
                    'range': seg_range,
                    'screen_count': len(positive_overlaps),
                    'dominant_ratio': dominant_ratio,
                })
            audio_content_ranges = [
                (
                    int(seg.get('target_timerange', {}).get('start', 0)),
                    int(seg.get('target_timerange', {}).get('start', 0)) + max(1, int(seg.get('target_timerange', {}).get('duration', 0))),
                )
                for seg in audio_segments
                if seg.get('material_id') and seg.get('target_timerange', {}).get('start') is not None
            ]

            content_ranges = [*text_ranges, *audio_content_ranges]

            def has_content_in_range(screen_info: Dict) -> bool:
                for seg_range in content_ranges:
                    if overlaps_screen(seg_range, screen_info):
                        return True
                return False

            def has_cross_content_between(prev_screen: Dict, cur_screen: Dict) -> bool:
                # Merge screens when a subtitle strongly overlaps both screens,
                # or when one subtitle is distributed across many consecutive screens.
                for seg_info in text_range_stats:
                    seg_range = seg_info['range']
                    prev_overlap = overlap_duration_us(seg_range, prev_screen)
                    cur_overlap = overlap_duration_us(seg_range, cur_screen)
                    if prev_overlap <= 0 or cur_overlap <= 0:
                        continue

                    if min(prev_overlap, cur_overlap) > max_cross_text_overlap_us:
                        return True

                    if (
                        seg_info['screen_count'] >= multi_screen_merge_min_screens
                        and seg_info['dominant_ratio'] <= multi_screen_dominant_overlap_ratio_max
                    ):
                        return True
                return False

            merged_segments = []
            merged_ranges = []
            merged_content_flags = []

            for idx, seg in enumerate(collapsed_video_segments):
                info = screen_ranges[idx]
                has_content = has_content_in_range(info)
                cross_content = False

                should_merge = False
                if merged_segments:
                    prev_has_content = merged_content_flags[-1]
                    cross_content = has_cross_content_between(merged_ranges[-1], info)
                    should_merge = ((not has_content and not prev_has_content) or cross_content)

                if should_merge:
                    prev_seg = merged_segments[-1]
                    prev_info = merged_ranges[-1]

                    prev_src_start = int(prev_seg.get('source_timerange', {}).get('start', 0))
                    prev_src_end = prev_src_start + int(prev_seg.get('source_timerange', {}).get('duration', 0))
                    cur_src_start = int(seg.get('source_timerange', {}).get('start', 0))
                    cur_src_end = cur_src_start + int(seg.get('source_timerange', {}).get('duration', 0))

                    prev_tgt_start = int(prev_seg.get('target_timerange', {}).get('start', 0))
                    prev_tgt_end = prev_tgt_start + int(prev_seg.get('target_timerange', {}).get('duration', 0))
                    cur_tgt_start = int(seg.get('target_timerange', {}).get('start', 0))
                    cur_tgt_end = cur_tgt_start + int(seg.get('target_timerange', {}).get('duration', 0))

                    new_src_start = min(prev_src_start, cur_src_start)
                    new_src_end = max(prev_src_end, cur_src_end)
                    new_tgt_start = min(prev_tgt_start, cur_tgt_start)
                    new_tgt_end = max(prev_tgt_end, cur_tgt_end)

                    new_src_duration = max(1, int(new_src_end - new_src_start))
                    new_tgt_duration = max(1, int(new_tgt_end - new_tgt_start))
                    new_speed = new_src_duration / new_tgt_duration

                    prev_seg['source_timerange'] = {'start': new_src_start, 'duration': new_src_duration}
                    prev_seg['target_timerange'] = {'start': new_tgt_start, 'duration': new_tgt_duration}
                    prev_seg['speed'] = new_speed
                    attach_speed_material(prev_seg, new_speed)

                    prev_info['start'] = min(prev_info['start'], info['start'])
                    prev_info['end'] = max(prev_info['end'], info['end'])
                    merged_content_flags[-1] = merged_content_flags[-1] or has_content or cross_content

                    if cross_content:
                        logger.info(
                            "Generator: Merged screens due to cross-screen subtitle continuity",
                        )
                    else:
                        logger.info("Generator: Merged consecutive gap-only screens")
                else:
                    merged_segments.append(seg)
                    merged_ranges.append(dict(info))
                    merged_content_flags.append(has_content)

            collapsed_video_segments = merged_segments
            screen_ranges = merged_ranges

        for collection in (text_segments, audio_segments):
            for seg in collection:
                seg_start = seg.get('target_timerange', {}).get('start')
                if seg_start is None:
                    continue
                for idx, screen_info in enumerate(screen_ranges):
                    is_last = idx == len(screen_ranges) - 1
                    if seg_start >= screen_info['start'] and (seg_start < screen_info['end'] or (is_last and seg_start <= screen_info['end'])):
                        seg['group_id'] = screen_info['group_id']
                        seg['raw_segment_id'] = screen_info['raw_segment_id']
                        break

        used_speed_ids = set()
        for collection in (collapsed_video_segments, audio_segments):
            for seg in collection:
                refs = seg.get('extra_material_refs')
                if not isinstance(refs, list):
                    continue
                for ref in refs:
                    if isinstance(ref, str):
                        used_speed_ids.add(ref)

        if helpers.get('speeds'):
            before_speed_count = len(helpers['speeds'])
            helpers['speeds'] = [
                speed_mat for speed_mat in helpers['speeds']
                if speed_mat.get('id') in used_speed_ids
            ]
            removed_speed_count = before_speed_count - len(helpers['speeds'])
            if removed_speed_count > 0:
                logger.info(
                    "Generator: Pruned %s unreferenced speed materials after screen collapse",
                    removed_speed_count,
                )

        segments_result['video_segments'] = collapsed_video_segments
        return segments_result
    
    def _bind_segments_by_timeline_group(self, segments_result: Dict, audio_materials: List[Dict], text_materials: List[Dict]) -> Dict:
        """
        Groups video, audio, and text segments based on their indices and hierarchy.
        Ensures proper track management and protects Waveform Sync offsets.
        """
        video_segments = segments_result.get('video_segments', [])
        audio_segments = segments_result.get('audio_segments', [])
        text_segments = segments_result.get('text_segments', [])
        
        if not video_segments:
            return segments_result
        
        # Maps for material lookups
        audio_mats = {m['id']: m for m in audio_materials} if audio_materials else {}
        text_mats = {m['id']: m for m in text_materials} if text_materials else {}
        
        # Pre-process audio segments to get template extra refs (for speed materials etc)
        template_extra_refs = []
        if audio_segments:
            first_audio = next((s for s in audio_segments if s.get('material_id')), audio_segments[0])
            template_extra_refs = (first_audio.get('extra_material_refs') or [])[1:]

        # Map video/text by render_index and start time for robust matching
        video_by_index = {}
        video_by_start = {}
        for idx, v_seg in enumerate(video_segments):
            v_idx = v_seg.get('render_index')
            if v_idx is None:
                v_idx = idx
                v_seg['render_index'] = v_idx
                
            group_id = v_seg.get('group_id') or self.generate_uuid()
            bundle_id = v_seg.get('raw_segment_id') or self.generate_uuid()
            v_seg['group_id'] = group_id
            v_seg['raw_segment_id'] = bundle_id
            
            video_by_index[v_idx] = v_seg
            start = v_seg.get('target_timerange', {}).get('start')
            if start is not None:
                video_by_start[start] = v_seg

        text_by_start = {}
        for text_seg in text_segments:
            start = text_seg.get('target_timerange', {}).get('start')
            if start is not None:
                text_by_start[start] = text_seg

        # Bind audio to video groups
        for audio_seg in audio_segments:
            aud_idx = audio_seg.get('render_index')
            aud_start = audio_seg.get('target_timerange', {}).get('start')
            
            # Prioritize matching by render_index, then by start time proximity
            target_v_seg = video_by_index.get(aud_idx)
            if target_v_seg is None and aud_start is not None:
                target_v_seg = video_by_start.get(aud_start)
                
            if target_v_seg:
                v_start = target_v_seg.get('target_timerange', {}).get('start')
                v_group_id = target_v_seg.get('group_id')
                v_bundle_id = target_v_seg.get('raw_segment_id')
                v_render_index = target_v_seg.get('render_index')
                
                # Apply structural alignment:
                # 1. Update IDs for magnetic grouping
                audio_seg['group_id'] = v_group_id
                audio_seg['raw_segment_id'] = v_bundle_id
                audio_seg['render_index'] = v_render_index
                
                # 2. Add extra material refs from template
                current_refs = audio_seg.get('extra_material_refs') or []
                if current_refs:
                    audio_seg['extra_material_refs'] = [current_refs[0], *template_extra_refs]

                # 3. Handle Timing with 1-second tolerance (Waveform Sync protection)
                # If offset is > 1s, we assume it's a structural drift and snap it.
                # If offset is < 1s, we respect it as an intentional sync offset.
                if aud_start is not None and v_start is not None:
                    offset = abs(aud_start - v_start)
                    if offset > 1000000: # 1 second
                        audio_seg.setdefault('target_timerange', {})['start'] = v_start
                
                # 4. Establish metadata links
                matched_text = text_by_start.get(v_start)
                if matched_text:
                    a_mat_id = audio_seg.get('material_id')
                    t_mat_id = matched_text.get('material_id')
                    if a_mat_id in audio_mats and t_mat_id in text_mats:
                        a_mat = audio_mats[a_mat_id]
                        t_mat = text_mats[t_mat_id]
                        a_mat['type'] = 'text_to_audio'
                        a_mat['text_id'] = t_mat_id
                        if 'text_to_audio_ids' not in t_mat:
                            t_mat['text_to_audio_ids'] = []
                        if audio_seg['id'] not in t_mat['text_to_audio_ids']:
                            t_mat['text_to_audio_ids'].append(audio_seg['id'])
        
        # Bind text to video groups
        for text_seg in text_segments:
            start = text_seg.get('target_timerange', {}).get('start')
            if start is not None:
                target_v_seg = video_by_start.get(start)
                if target_v_seg:
                    text_seg['group_id'] = target_v_seg['group_id']
                    text_seg['raw_segment_id'] = target_v_seg['raw_segment_id']
        
        return segments_result
    
    
    def _fix_gap_aware_audio_sync(self, segments_result: Dict, timeline_segments: List[Dict], segment_creator) -> Dict:
        """Fix audio sync issues in gap-aware mode by adding silence segments for gaps"""
        logger.info("Fixing gap-aware audio sync...")
        
        video_segments = segments_result['video_segments']
        audio_segments = segments_result['audio_segments']
        
        # Tạo audio segments mới với silence cho gaps
        new_audio_segments = []
        audio_idx = 0
        
        for i, timeline_segment in enumerate(timeline_segments):
            has_subtitle = timeline_segment.get('has_subtitle', False)
            
            if has_subtitle:
                # Có subtitle, sử dụng audio segment hiện tại
                if audio_idx < len(audio_segments):
                    new_audio_segments.append(audio_segments[audio_idx])
                    audio_idx += 1
            else:
                # Gap - tạo silence audio segment
                if i < len(video_segments):
                    video_seg = video_segments[i]
                    silence_segment = segment_creator.create_silence_audio_segment(
                        video_seg['target_timerange']['duration'],
                        video_seg['target_timerange']['start'],
                        render_index=i
                    )
                    new_audio_segments.append(silence_segment)
                    logger.debug(f"Added silence segment for gap at {video_seg['target_timerange']['start']/1000000:.2f}s")
        
        # Cập nhật kết quả
        segments_result['audio_segments'] = new_audio_segments
        logger.info(f"Fixed audio sync: {len(new_audio_segments)} audio segments total")
        
        return segments_result
    
    def _create_draft_content(self, segments_data: Dict, audio_materials: List[Dict], 
                             text_materials: List[Dict], video_material: Dict, 
                             helpers: Dict, total_duration: int,
                             export_lt8: bool = False) -> Dict:
        """Create final draft content structure"""
        
        # Group audio segments by tracks to prevent overlap collisions
        audio_segments = segments_data.get('audio_segments', [])
        audio_tracks_list = []
        sorted_new_audio = sorted(audio_segments, key=lambda s: s.get("target_timerange", {}).get("start", 0))
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
                
        final_tracks = [
            {
                "attribute": 0,
                "flag": 0,
                "id": self.generate_uuid(),
                "is_default_name": True,
                "name": "",
                "segments": segments_data['video_segments'],
                "type": "video"
            },
            {
                "attribute": 0,
                "flag": 1,
                "id": self.generate_uuid(),
                "is_default_name": True,
                "name": "",
                "segments": segments_data['text_segments'],
                "type": "text"
            }
        ]
        
        for track_segs in audio_tracks_list:
            final_tracks.append({
                "attribute": 0,
                "flag": 0,
                "id": self.generate_uuid(),
                "is_default_name": True,
                "name": "",
                "segments": track_segs,
                "type": "audio"
            })
            
        if not audio_tracks_list:
            final_tracks.append({
                "attribute": 0,
                "flag": 0,
                "id": self.generate_uuid(),
                "is_default_name": True,
                "name": "",
                "segments": [],
                "type": "audio"
            })
        
        draft_content = {
            "canvas_config": {
                "background": None,
                "height": video_material.get("height", self.canvas_height),
                "ratio": "original", 
                "width": video_material.get("width", self.canvas_width)
            },
            "color_space": -1,
            "config": {
                "adjust_max_index": 1,
                "attachment_info": [],
                "combination_max_index": 1,
                "export_range": None,
                "extract_audio_last_index": 1,
                "lyrics_recognition_id": "",
                "lyrics_sync": True,
                "lyrics_taskinfo": [],
                "maintrack_adsorb": True,
                "material_save_mode": 0,
                "multi_language_current": "none",
                "multi_language_list": [],
                "multi_language_main": "none",
                "multi_language_mode": "none",
                "original_sound_last_index": 4,
                "record_audio_last_index": 1,
                "sticker_max_index": 1,
                "subtitle_keywords_config": None,
                "subtitle_recognition_id": "",
                "subtitle_sync": True,
                "subtitle_taskinfo": [],
                "system_font_list": [],
                "use_float_render": False,
                "video_mute": False,
                "zoom_info_params": None
            },
            "cover": None,
            "create_time": 0,
            "duration": total_duration,
            "extra_info": None,
            "fps": self.fps,
            "free_render_index_mode_on": False,
            "group_container": None,
            "id": self.generate_uuid(),
            "is_drop_frame_timecode": False,
            "keyframe_graph_list": [],
            "keyframes": {
                "adjusts": [],
                "audios": [],
                "effects": [],
                "filters": [],
                "handwrites": [],
                "stickers": [],
                "texts": [],
                "videos": []
            },
            "last_modified_platform": {
                "app_id": 359289,
                "app_source": "cc",
                "app_version": "8.2.0",
                "device_id": "7e2eed94d9142a47a974d912aa3fb372",
                "hard_disk_id": "",
                "mac_address": "411f629e25ab7c98622607eaad6188b8",
                "os": "windows",
                "os_version": "10.0.26100"
            },
            "lyrics_effects": [],
            "materials": {
                "ai_translates": [],
                "audio_balances": [],
                "audio_effects": [],
                "audio_fades": [],
                "audio_track_indexes": [],
                "audios": audio_materials,
                "beats": helpers["beats"],
                "canvases": helpers["canvases"],
                "chromas": [],
                "color_curves": [],
                "common_mask": [],
                "digital_human_model_dressing": [],
                "digital_humans": [],
                "drafts": [],
                "effects": [],
                "flowers": [],
                "green_screens": [],
                "handwrites": [],
                "hsl": [],
                "images": [],
                "log_color_wheels": [],
                "loudnesses": [],
                "manual_beautys": [],
                "manual_deformations": [],
                "material_animations": helpers["material_animations"],
                "material_colors": [],
                "multi_language_refs": [],
                "placeholder_infos": helpers["placeholder_infos"],
                "placeholders": [],
                "plugin_effects": [],
                "primary_color_wheels": [],
                "realtime_denoises": [],
                "shapes": [],
                "smart_crops": [],
                "smart_relights": [],
                "sound_channel_mappings": helpers["sound_channel_mappings"],
                "speeds": helpers["speeds"],
                "stickers": [],
                "tail_leaders": [],
                "text_templates": [],
                "texts": text_materials,
                "time_marks": [],
                "transitions": [],
                "video_effects": [],
                "video_trackings": [],
                "videos": [video_material],
                "vocal_beautifys": [],
                "vocal_separations": helpers["vocal_separations"]
            },
            "mutable_config": None,
            "name": "",
            "new_version": "161.0.0",
            "path": "",
            "platform": {
                "app_id": 359289,
                "app_source": "cc",
                "app_version": "8.2.0",
                "device_id": "7e2eed94d9142a47a974d912aa3fb372",
                "hard_disk_id": "",
                "mac_address": "411f629e25ab7c98622607eaad6188b8",
                "os": "windows",
                "os_version": "10.0.26100"
            },
            "relationships": [],
            "render_index_track_mode_on": True,
            "retouch_cover": None,
            "source": "default",
            "static_cover_image_path": "",
            "time_marks": None,
            "tracks": final_tracks,
            "uneven_animation_template_info": {
                "composition": "",
                "content": "",
                "order": "",
                "sub_template_info_list": []
            },
            "update_time": 0,
            "version": 360000
        }


        if export_lt8:
            draft_content["color_space"] = 0
            draft_content["draft_type"] = "video"
            draft_content["function_assistant_info"] = self._create_function_assistant_info()
            draft_content["new_version"] = "153.0.0"

            if isinstance(draft_content.get("config"), dict):
                draft_content["config"]["original_sound_last_index"] = 1
                draft_content["config"].pop("voice_change_sync", None)

            materials = draft_content.get("materials")
            if isinstance(materials, dict):
                materials.setdefault("audio_pannings", [])
                materials.setdefault("audio_pitch_shifts", [])

            for platform_key in ("platform", "last_modified_platform"):
                if isinstance(draft_content.get(platform_key), dict):
                    draft_content[platform_key]["app_version"] = "7.8.0"

        return draft_content

    def _save_project(self, draft_content: dict, output_json_path: str):
        """Automatically detects 8.20+ Timelines structure and saves project correctly"""
        import os, json
        project_root = os.path.dirname(output_json_path)
        timelines_dir = os.path.join(project_root, "Timelines")
        
        if os.path.isdir(timelines_dir):
            try:
                project_info_path = os.path.join(timelines_dir, "project.json")
                if os.path.exists(project_info_path):
                    with open(project_info_path, 'r', encoding='utf-8') as f:
                        project_info = json.load(f)
                    
                    main_timeline_id = project_info.get("main_timeline_id")
                    if main_timeline_id:
                        draft_content["id"] = main_timeline_id
                        timeline_folder = os.path.join(timelines_dir, main_timeline_id)
                        if not os.path.exists(timeline_folder):
                            os.makedirs(timeline_folder)
                        timeline_extra_path = os.path.join(timeline_folder, "draft.extra")
                        if os.path.exists(timeline_extra_path):
                            os.remove(timeline_extra_path)
                            
                        timeline_json_path = os.path.join(timeline_folder, "draft_content.json")
                        with open(timeline_json_path, 'w', encoding='utf-8') as f:
                            json.dump(draft_content, f, ensure_ascii=False, indent=2)
            except Exception as e:
                pass
        
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(draft_content, f, ensure_ascii=False, indent=2)
