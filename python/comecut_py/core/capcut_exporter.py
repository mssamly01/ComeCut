"""Export ComeCut projects as CapCut-style ``draft_content.json`` files."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .project import Project
from .project_draft_adapter import project_to_v2
from .project_schema_v2 import ProjectV2, Segment, TextMaterial, TrackV2, seconds_to_us


CAPCUT_SCHEMA_VERSION = 360_000
CAPCUT_APP_VERSION = "153.0.0"
CAPCUT_PLATFORM_OS = "windows"
CAPCUT_PLATFORM_OS_VERSION = "10.0.26100"
CAPCUT_PLATFORM_APP_ID = 359_289
CAPCUT_PLATFORM_APP_VERSION = "7.8.0"
CAPCUT_PLATFORM_APP_SOURCE = "cc"
RENDER_INDEX_TEXT = 14_000

# Mirror the sample draft's material categories so exported files match
# CapCut's expected pool topology closely.
_MATERIAL_KEYS = (
    "ai_translates",
    "audio_balances",
    "audio_effects",
    "audio_fades",
    "audio_pannings",
    "audio_pitch_shifts",
    "audio_track_indexes",
    "audios",
    "beats",
    "canvases",
    "chromas",
    "color_curves",
    "common_mask",
    "digital_human_model_dressing",
    "digital_humans",
    "drafts",
    "effects",
    "flowers",
    "green_screens",
    "handwrites",
    "hsl",
    "hsl_curves",
    "images",
    "log_color_wheels",
    "loudnesses",
    "manual_beautys",
    "manual_deformations",
    "material_animations",
    "material_colors",
    "multi_language_refs",
    "placeholder_infos",
    "placeholders",
    "plugin_effects",
    "primary_color_wheels",
    "realtime_denoises",
    "shapes",
    "smart_crops",
    "smart_relights",
    "sound_channel_mappings",
    "speeds",
    "stickers",
    "tail_leaders",
    "text_templates",
    "texts",
    "time_marks",
    "transitions",
    "video_effects",
    "video_radius",
    "video_shadows",
    "video_strokes",
    "video_trackings",
    "videos",
    "vocal_beautifys",
    "vocal_separations",
)


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _empty_materials_skeleton() -> dict[str, list]:
    return {key: [] for key in _MATERIAL_KEYS}


def _ensure_hex(value: str | None, default: str = "#ffffff") -> str:
    if not value:
        return default
    text = str(value).strip()
    if not text:
        return default
    if not text.startswith("#"):
        text = f"#{text.lstrip('#')}"
    if len(text) == 4:
        text = f"#{text[1] * 2}{text[2] * 2}{text[3] * 2}"
    if len(text) != 7:
        return default
    return text.lower()


def _hex_to_rgb_floats(value: str | None) -> list[float]:
    color = _ensure_hex(value)
    try:
        return [
            int(color[1:3], 16) / 255.0,
            int(color[3:5], 16) / 255.0,
            int(color[5:7], 16) / 255.0,
        ]
    except ValueError:
        return [1.0, 1.0, 1.0]


def _capcut_canvas_config(project: Project) -> dict[str, Any]:
    return {
        "ratio": "original",
        "width": int(project.width),
        "height": int(project.height),
        "background": None,
    }


def _capcut_platform() -> dict[str, Any]:
    return {
        "os": CAPCUT_PLATFORM_OS,
        "os_version": CAPCUT_PLATFORM_OS_VERSION,
        "app_id": CAPCUT_PLATFORM_APP_ID,
        "app_version": CAPCUT_PLATFORM_APP_VERSION,
        "app_source": CAPCUT_PLATFORM_APP_SOURCE,
        "device_id": "",
        "hard_disk_id": "",
        "mac_address": "",
    }


def _capcut_keyframes_skeleton() -> dict[str, list]:
    return {
        "adjusts": [],
        "audios": [],
        "effects": [],
        "filters": [],
        "handwrites": [],
        "stickers": [],
        "texts": [],
        "videos": [],
    }


def _capcut_config_skeleton() -> dict[str, Any]:
    return {
        "video_mute": False,
        "record_audio_last_index": 0,
        "extract_audio_last_index": 0,
        "original_sound_last_index": 0,
        "subtitle_recognition_id": "",
        "subtitle_taskinfo": [],
        "lyrics_recognition_id": "",
        "lyrics_taskinfo": [],
        "subtitle_sync": True,
        "lyrics_sync": True,
        "sticker_max_index": 0,
        "adjust_max_index": 0,
        "material_save_mode": 0,
        "export_range": None,
        "maintrack_adsorb": True,
        "combination_max_index": 0,
        "attachment_info": [],
        "zoom_info_params": None,
        "system_font_list": [],
        "multi_language_mode": "none",
        "multi_language_main": "none",
        "multi_language_current": "none",
        "multi_language_list": [],
        "subtitle_keywords_config": None,
        "use_float_render": False,
    }


def _capcut_function_assistant_skeleton(fps: float) -> dict[str, Any]:
    return {
        "smart_rec_applied": False,
        "fixed_rec_applied": False,
        "auto_adjust": False,
        "auto_adjust_segid_list": [],
        "color_correction": False,
        "color_correction_segid_list": [],
        "enhance_quality": False,
        "smooth_slow_motion": False,
        "deflicker_segid_list": [],
        "video_noise_segid_list": [],
        "enhance_quality_segid_list": [],
        "smart_segid_list": [],
        "retouch": False,
        "retouch_segid_list": [],
        "enhande_voice": False,
        "enhance_voice_segid_list": [],
        "audio_noise_segid_list": [],
        "auto_caption": False,
        "auto_caption_segid_list": [],
        "auto_caption_template_id": "",
        "caption_opt": False,
        "caption_opt_segid_list": [],
        "eye_correction": False,
        "eye_correction_segid_list": [],
        "normalize_loudness": False,
        "normalize_loudness_segid_list": [],
        "normalize_loudness_audio_denoise_segid_list": [],
        "auto_adjust_fixed": False,
        "auto_adjust_fixed_value": 0,
        "color_correction_fixed": False,
        "color_correction_fixed_value": 0,
        "normalize_loudness_fixed": False,
        "enhande_voice_fixed": False,
        "retouch_fixed": False,
        "enhance_quality_fixed": False,
        "smooth_slow_motion_fixed": False,
        "fps": int(round(fps or 30.0)),
    }


def _make_video_segment_materials(materials: dict[str, list], *, speed: float) -> list[str]:
    speed_id = _new_id()
    placeholder_id = _new_id()
    canvas_id = _new_id()
    sound_id = _new_id()
    color_id = _new_id()
    vocal_id = _new_id()

    materials["speeds"].append(
        {"id": speed_id, "type": "speed", "mode": 0, "speed": float(speed), "curve_speed": None}
    )
    materials["placeholder_infos"].append(
        {
            "id": placeholder_id,
            "type": "placeholder_info",
            "meta_type": "none",
            "res_path": "",
            "res_text": "",
            "error_path": "",
            "error_text": "",
        }
    )
    materials["canvases"].append(
        {
            "id": canvas_id,
            "type": "canvas_color",
            "color": "",
            "blur": 0.0,
            "image": "",
            "album_image": "",
            "image_id": "",
            "image_name": "",
            "source_platform": 0,
            "team_id": "",
        }
    )
    materials["sound_channel_mappings"].append(
        {"id": sound_id, "type": "none", "audio_channel_mapping": 0, "is_config_open": False}
    )
    materials["material_colors"].append(
        {
            "id": color_id,
            "is_color_clip": False,
            "is_gradient": False,
            "solid_color": "",
            "gradient_colors": [],
            "gradient_percents": [],
            "gradient_angle": 90.0,
            "width": 0.0,
            "height": 0.0,
        }
    )
    materials["vocal_separations"].append(
        {
            "id": vocal_id,
            "type": "vocal_separation",
            "choice": 0,
            "removed_sounds": [],
            "time_range": None,
            "production_path": "",
            "final_algorithm": "",
            "enter_from": "",
        }
    )
    return [speed_id, placeholder_id, canvas_id, sound_id, color_id, vocal_id]


def _make_audio_segment_materials(materials: dict[str, list], *, speed: float) -> list[str]:
    speed_id = _new_id()
    placeholder_id = _new_id()
    beats_id = _new_id()
    sound_id = _new_id()
    vocal_id = _new_id()

    materials["speeds"].append(
        {"id": speed_id, "type": "speed", "mode": 0, "speed": float(speed), "curve_speed": None}
    )
    materials["placeholder_infos"].append(
        {
            "id": placeholder_id,
            "type": "placeholder_info",
            "meta_type": "none",
            "res_path": "",
            "res_text": "",
            "error_path": "",
            "error_text": "",
        }
    )
    materials["beats"].append(
        {
            "id": beats_id,
            "type": "beats",
            "enable_ai_beats": False,
            "gear": 404,
            "gear_count": 0,
            "mode": 404,
            "user_beats": [],
            "user_delete_ai_beats": None,
            "ai_beats": {
                "melody_url": "",
                "melody_path": "",
                "beats_url": "",
                "beats_path": "",
                "melody_percents": [0.0],
                "beat_speed_infos": [],
            },
        }
    )
    materials["sound_channel_mappings"].append(
        {"id": sound_id, "type": "", "audio_channel_mapping": 0, "is_config_open": False}
    )
    materials["vocal_separations"].append(
        {
            "id": vocal_id,
            "type": "vocal_separation",
            "choice": 0,
            "removed_sounds": [],
            "time_range": None,
            "production_path": "",
            "final_algorithm": "",
            "enter_from": "",
        }
    )
    return [speed_id, placeholder_id, beats_id, sound_id, vocal_id]


def _append_audio_fade_ref(
    seg: Segment,
    *,
    refs: list[str],
    materials: dict[str, list],
    audio_effects_by_id: dict[str, Any] | None,
) -> None:
    if not audio_effects_by_id:
        return
    fade_in = 0.0
    fade_out = 0.0
    found = False
    for ref in seg.extra_material_refs:
        material = audio_effects_by_id.get(ref)
        if material is None:
            continue
        fade_in = float(getattr(material, "fade_in", 0.0) or 0.0)
        fade_out = float(getattr(material, "fade_out", 0.0) or 0.0)
        found = True
        break

    if not found:
        return

    fade_in = max(0.0, fade_in)
    fade_out = max(0.0, fade_out)
    if fade_in <= 0.0 and fade_out <= 0.0:
        return

    fade_id = _new_id()
    materials["audio_fades"].append(
        {
            "id": fade_id,
            "type": "audio_fade",
            "fade_in_duration": int(round(fade_in * 1_000_000)),
            "fade_out_duration": int(round(fade_out * 1_000_000)),
        }
    )
    refs.append(fade_id)


def _make_text_segment_materials(materials: dict[str, list]) -> list[str]:
    animation_id = _new_id()
    materials["material_animations"].append(
        {
            "id": animation_id,
            "type": "sticker_animation",
            "animations": [],
            "multi_language_current": "none",
        }
    )
    return [animation_id]


def _video_material_capcut(material: Any) -> dict[str, Any]:
    return {
        "id": material.id,
        "path": material.path,
        "duration": int(material.duration),
        "width": int(material.width),
        "height": int(material.height),
        "has_audio": bool(material.has_audio),
        "material_name": material.name or Path(material.path or "").name,
        "local_material_id": "",
        "local_id": "",
        "type": "",
    }


def _audio_material_capcut(material: Any) -> dict[str, Any]:
    return {
        "id": material.id,
        "path": material.path,
        "duration": int(material.duration),
        "name": material.name or Path(material.path or "").name,
        "effect_id": "",
        "local_material_id": "",
        "music_id": "",
        "type": "",
    }


def _text_style_dict(start: int, end: int, color: list[float], size: float, family: str) -> dict[str, Any]:
    return {
        "fill": {
            "alpha": 1.0,
            "content": {
                "render_type": "solid",
                "solid": {"alpha": 1.0, "color": color},
            },
        },
        "font": {"id": "", "path": family},
        "range": [start, end],
        "size": size,
    }


def _text_material_capcut(material: TextMaterial) -> dict[str, Any]:
    primary_color = _hex_to_rgb_floats(material.color or "#ffffff")
    secondary_color = _hex_to_rgb_floats(material.second_color or material.color or "#ffffff")
    primary_size = float(material.font_size or 30) / 6.0
    secondary_size = float(material.second_font_size or material.font_size or 30) / 6.0
    family = material.font_family or "Verdana"
    main = material.text_main or ""
    second = material.text_second or ""

    if material.text_display == "second":
        full_text = second or main
        if second:
            styles = [_text_style_dict(0, len(full_text), secondary_color, secondary_size, family)]
            direct_color = _ensure_hex(material.second_color or material.color or "#ffffff")
            direct_size = int(material.second_font_size or material.font_size or 30)
            font_size_norm = secondary_size
        else:
            styles = [_text_style_dict(0, len(full_text), primary_color, primary_size, family)]
            direct_color = _ensure_hex(material.color or "#ffffff")
            direct_size = int(material.font_size or 30)
            font_size_norm = primary_size
    elif material.text_display == "bilingual" and main and second:
        full_text = f"{main}\n{second}"
        main_end = len(main)
        styles = [
            _text_style_dict(0, main_end, primary_color, primary_size, family),
            _text_style_dict(main_end + 1, len(full_text), secondary_color, secondary_size, family),
        ]
        direct_color = _ensure_hex(material.color or "#ffffff")
        direct_size = int(material.font_size or 30)
        font_size_norm = primary_size
    else:
        full_text = main or second
        styles = [_text_style_dict(0, len(full_text), primary_color, primary_size, family)]
        direct_color = _ensure_hex(material.color or "#ffffff")
        direct_size = int(material.font_size or 30)
        font_size_norm = primary_size

    content = {"styles": styles, "text": full_text}
    return {
        "id": material.id,
        "type": "subtitle",
        "name": "",
        "recognize_text": "",
        "recognize_model": "",
        "punc_model": "",
        "content": json.dumps(content, ensure_ascii=False),
        "base_content": "",
        "words": {"start_time": [], "end_time": [], "text": []},
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0,
        "background_color": "",
        "background_alpha": 1.0,
        "background_style": 0,
        "combo_info": {"text_templates": []},
        "caption_template_info": {
            "resource_id": "",
            "third_resource_id": "",
            "resource_name": "",
            "category_id": "",
            "category_name": "",
            "effect_id": "",
            "request_id": "",
            "path": "",
            "is_new": False,
            "source_platform": 0,
        },
        "layer_weight": 1,
        "letter_spacing": 0.0,
        "text_color": direct_color,
        "text_alpha": 1.0,
        "text_size": direct_size,
        "text_to_audio_ids": [],
        "border_color": _ensure_hex(material.stroke_color or "#000000", "#000000"),
        "border_width": float(material.stroke_width or 0) / 100.0,
        "border_alpha": 1.0,
        "shadow_color": "",
        "shadow_alpha": 0.9,
        "font_path": family,
        "font_name": family,
        "font_size": font_size_norm,
        "font_title": "none",
        "font_id": "",
        "font_resource_id": "",
        "font_team_id": "",
        "font_category_id": "",
        "font_category_name": "",
        "font_source_platform": 0,
    }


def _source_timerange_dict(seg: Segment) -> dict[str, int] | None:
    if seg.source_timerange is None:
        duration = int(round(seg.target_timerange.duration * float(seg.speed or 1.0)))
        return {
            "start": 0,
            "duration": max(0, duration),
        }
    duration = int(seg.source_timerange.duration)
    if duration <= 0:
        duration = int(round(seg.target_timerange.duration * float(seg.speed or 1.0)))
    return {
        "start": int(seg.source_timerange.start),
        "duration": max(0, duration),
    }


def _segment_capcut(
    seg: Segment,
    *,
    track_type: str,
    track_render_index: int,
    materials: dict[str, list],
    audio_effects_by_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if track_type == "video":
        refs = _make_video_segment_materials(materials, speed=float(seg.speed))
        clip = {
            "scale": {"x": float(seg.clip.scale.x), "y": float(seg.clip.scale.y)},
            "rotation": float(seg.clip.rotation),
            "transform": {
                "x": float(seg.clip.transform.x),
                "y": float(seg.clip.transform.y),
            },
            "flip": {
                "vertical": bool(seg.clip.flip.vertical),
                "horizontal": bool(seg.clip.flip.horizontal),
            },
            "alpha": float(seg.clip.alpha),
        }
        render_index = 0
        source_tr = _source_timerange_dict(seg)
    elif track_type == "audio":
        refs = _make_audio_segment_materials(materials, speed=float(seg.speed))
        _append_audio_fade_ref(
            seg,
            refs=refs,
            materials=materials,
            audio_effects_by_id=audio_effects_by_id,
        )
        clip = {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": 0.0},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        }
        render_index = 0
        source_tr = _source_timerange_dict(seg)
    else:
        refs = _make_text_segment_materials(materials)
        clip = {
            "scale": {"x": float(seg.clip.scale.x), "y": float(seg.clip.scale.y)},
            "rotation": float(seg.clip.rotation),
            "transform": {
                "x": float(seg.clip.transform.x),
                "y": float(seg.clip.transform.y),
            },
            "flip": {
                "vertical": bool(seg.clip.flip.vertical),
                "horizontal": bool(seg.clip.flip.horizontal),
            },
            "alpha": float(seg.clip.alpha),
        }
        render_index = RENDER_INDEX_TEXT
        source_tr = None

    target_tr = {
        "start": int(seg.target_timerange.start),
        "duration": int(seg.target_timerange.duration),
    }
    enable_video_flags = track_type == "video"

    return {
        "id": seg.id,
        "source_timerange": source_tr,
        "target_timerange": target_tr,
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "",
        "state": 0,
        "speed": float(seg.speed),
        "is_loop": False,
        "is_tone_modify": bool(seg.voice_preset_id and seg.voice_preset_id != "none"),
        "tone_modify": {
            "none": 0, "kid_girl": 1, "kid_boy": 2, "robot": 3, "monster": 4,
            "elder": 5, "helium": 6, "lofi": 7,
        }.get(seg.voice_preset_id or "none", 0),
        "reverse": bool(seg.reverse),
        "intensifies_audio": False,
        "cartoon": False,
        "volume": float(seg.volume),
        "last_nonzero_volume": float(seg.volume) if seg.volume else 1.0,
        "clip": clip,
        "uniform_scale": {"on": True, "value": 1.0},
        "material_id": seg.material_id,
        "extra_material_refs": refs,
        "render_index": render_index,
        "keyframe_refs": [],
        "enable_lut": enable_video_flags,
        "enable_adjust": enable_video_flags,
        "enable_hsl": False,
        "visible": bool(seg.visible),
        "group_id": "",
        "enable_color_curves": enable_video_flags,
        "enable_hsl_curves": enable_video_flags,
        "track_render_index": track_render_index,
        "hdr_settings": {"mode": 1, "intensity": 1.0, "nits": 1000} if enable_video_flags else None,
        "enable_color_wheels": enable_video_flags,
        "track_attribute": 0,
        "is_placeholder": False,
        "template_id": "",
        "enable_smart_color_adjust": False,
        "template_scene": "default",
        "common_keyframes": [],
        "caption_info": None,
        "responsive_layout": {
            "enable": False,
            "target_follow": "",
            "size_layout": 0,
            "horizontal_pos_layout": 0,
            "vertical_pos_layout": 0,
        },
        "enable_color_match_adjust": False,
        "enable_color_correct_adjust": False,
        "enable_adjust_mask": False,
        "raw_segment_id": "",
        "lyric_keyframes": None,
        "enable_video_mask": True,
        "digital_human_template_group_id": "",
        "color_correct_alg_result": "",
        "source": "segmentsourcenormal",
        "enable_mask_stroke": False,
        "enable_mask_shadow": False,
    }


def _track_capcut(
    track: TrackV2,
    track_render_index: int,
    materials: dict[str, list],
    *,
    audio_effects_by_id: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Export one V2 track. Unsupported types are skipped in Phase 1."""
    if track.type not in ("video", "audio", "text"):
        return None

    segments = [
        _segment_capcut(
            seg,
            track_type=track.type,
            track_render_index=track_render_index,
            materials=materials,
            audio_effects_by_id=audio_effects_by_id,
        )
        for seg in track.segments
    ]
    return {
        "id": track.id,
        "type": track.type,
        "flag": 0,
        "attribute": 0,
        "name": track.name,
        "is_default_name": not bool(track.name),
        "segments": segments,
        "locked": bool(track.locked),
        "hidden": bool(track.hidden),
        "muted": bool(track.muted),
    }


def export_to_capcut(project: Project, dest_path: str | Path) -> Path:
    """Write *project* as a CapCut-style ``draft_content.json`` file."""
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    v2: ProjectV2 = project_to_v2(project)
    materials = _empty_materials_skeleton()

    for material in v2.materials.videos:
        materials["videos"].append(_video_material_capcut(material))
    for material in v2.materials.audios:
        materials["audios"].append(_audio_material_capcut(material))
    for material in v2.materials.texts:
        materials["texts"].append(_text_material_capcut(material))
    audio_effects_by_id: dict[str, Any] = {material.id: material for material in v2.materials.audio_effects}

    tracks_out: list[dict[str, Any]] = []
    cursor = 0
    for track in v2.tracks:
        exported = _track_capcut(
            track,
            track_render_index=cursor,
            materials=materials,
            audio_effects_by_id=audio_effects_by_id,
        )
        if exported is None:
            continue
        tracks_out.append(exported)
        cursor += 1

    platform = _capcut_platform()
    fps = float(project.fps or 30.0)
    root: dict[str, Any] = {
        "id": _new_id(),
        "version": CAPCUT_SCHEMA_VERSION,
        "new_version": CAPCUT_APP_VERSION,
        "name": project.name or "",
        "duration": int(seconds_to_us(project.duration)),
        "create_time": 0,
        "update_time": 0,
        "fps": fps,
        "is_drop_frame_timecode": False,
        "color_space": 0,
        "config": _capcut_config_skeleton(),
        "canvas_config": _capcut_canvas_config(project),
        "tracks": tracks_out,
        "group_container": None,
        "materials": materials,
        "keyframes": _capcut_keyframes_skeleton(),
        "keyframe_graph_list": [],
        "platform": platform,
        "last_modified_platform": dict(platform),
        "mutable_config": None,
        "cover": None,
        "retouch_cover": None,
        "extra_info": None,
        "relationships": [],
        "render_index_track_mode_on": True,
        "free_render_index_mode_on": False,
        "static_cover_image_path": "",
        "source": "default",
        "time_marks": None,
        "path": "",
        "lyrics_effects": [],
        "uneven_animation_template_info": {
            "composition": "",
            "content": "",
            "order": "",
            "sub_template_info_list": [],
        },
        "draft_type": "video",
        "smart_ads_info": {"page_from": "", "routine": "", "draft_url": ""},
        "function_assistant_info": _capcut_function_assistant_skeleton(fps),
    }

    dest.write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


__all__ = ["export_to_capcut"]
