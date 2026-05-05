"""Converters between the legacy ``Project`` model and V2 draft JSON.

The app keeps using :mod:`comecut_py.core.project` at runtime.  This module is
the bridge used only when reading/writing ``draft_content.json`` so the store
can dual-write a CapCut-like project file without destabilising the editor.
"""

from __future__ import annotations

import time
from pathlib import Path

from .project import (
    ChromaKey,
    Clip,
    ClipAudioEffects,
    ClipEffects,
    CropRect,
    ImageOverlay,
    Project,
    TextOverlay,
    Track,
    Transition,
)
from .project_schema_v2 import (
    AudioEffectMaterial,
    AudioMaterial,
    CanvasConfig,
    ChromaMaterial,
    ClipTransform,
    CropMaterial,
    EffectMaterial,
    Flip,
    ImageMaterial,
    KeyframeV2,
    Materials,
    ProjectV2,
    Scale2,
    Segment,
    TextMaterial,
    TimeRange,
    TrackV2,
    TransitionMaterial,
    US_PER_SECOND,
    Vec2,
    VideoMaterial,
    seconds_to_us,
    us_to_seconds,
)


def is_v2_format(data: dict) -> bool:
    """Return ``True`` when *data* looks like ``draft_content.json`` V2."""
    if not isinstance(data, dict) or "materials" not in data:
        return False
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return False
    return not tracks or "segments" in tracks[0]


def project_to_v2(project: Project) -> ProjectV2:
    """Convert the current in-memory project to the V2 draft schema."""
    materials = Materials()
    videos_by_path: dict[str, VideoMaterial] = {}
    audios_by_path: dict[str, AudioMaterial] = {}
    images_by_path: dict[str, ImageMaterial] = {}

    def intern_video(path: str, *, proxy: str | None, duration_us: int) -> str:
        key = str(path)
        material = videos_by_path.get(key)
        if material is None:
            material = VideoMaterial(
                path=key,
                proxy_path=proxy,
                duration=duration_us,
                name=Path(key).name if key else "",
            )
            videos_by_path[key] = material
            materials.videos.append(material)
        else:
            material.duration = max(material.duration, duration_us)
            if proxy and not material.proxy_path:
                material.proxy_path = proxy
        return material.id

    def intern_audio(path: str, *, duration_us: int) -> str:
        key = str(path)
        material = audios_by_path.get(key)
        if material is None:
            material = AudioMaterial(
                path=key,
                duration=duration_us,
                name=Path(key).name if key else "",
            )
            audios_by_path[key] = material
            materials.audios.append(material)
        else:
            material.duration = max(material.duration, duration_us)
        return material.id

    def intern_image(path: str) -> str:
        key = str(path)
        material = images_by_path.get(key)
        if material is None:
            material = ImageMaterial(path=key, name=Path(key).name if key else "")
            images_by_path[key] = material
            materials.images.append(material)
        return material.id

    def add_effect_refs(effects: ClipEffects, audio_effects: ClipAudioEffects) -> list[str]:
        refs: list[str] = []
        default_effects = ClipEffects()
        if (
            effects.blur != default_effects.blur
            or effects.brightness != default_effects.brightness
            or effects.contrast != default_effects.contrast
            or effects.saturation != default_effects.saturation
            or effects.grayscale != default_effects.grayscale
            or effects.rotate != default_effects.rotate
            or effects.hflip != default_effects.hflip
            or effects.vflip != default_effects.vflip
        ):
            material = EffectMaterial(
                blur=float(effects.blur),
                brightness=float(effects.brightness),
                contrast=float(effects.contrast),
                saturation=float(effects.saturation),
                grayscale=bool(effects.grayscale),
                rotate=float(effects.rotate),
                hflip=bool(effects.hflip),
                vflip=bool(effects.vflip),
            )
            materials.effects.append(material)
            refs.append(material.id)

        if effects.crop is not None:
            crop = effects.crop
            material = CropMaterial(
                x=int(crop.x),
                y=int(crop.y),
                width=int(crop.width),
                height=int(crop.height),
            )
            materials.crops.append(material)
            refs.append(material.id)

        if effects.chromakey is not None:
            chroma = effects.chromakey
            material = ChromaMaterial(
                color=chroma.color,
                similarity=float(chroma.similarity),
                blend=float(chroma.blend),
            )
            materials.chromas.append(material)
            refs.append(material.id)

        default_audio = ClipAudioEffects()
        if audio_effects != default_audio:
            material = AudioEffectMaterial(
                fade_in=float(audio_effects.fade_in),
                fade_out=float(audio_effects.fade_out),
                pitch_semitones=float(audio_effects.pitch_semitones),
                formant_shift=float(audio_effects.formant_shift),
                chorus_depth=float(audio_effects.chorus_depth),
                voice_preset_id=audio_effects.voice_preset_id,
                denoise=bool(audio_effects.denoise),
                denoise_method=audio_effects.denoise_method,
                denoise_model=audio_effects.denoise_model,
                normalize=bool(audio_effects.normalize),
            )
            materials.audio_effects.append(material)
            refs.append(material.id)

        return refs

    def text_material_from_clip(clip: Clip) -> TextMaterial:
        material = TextMaterial(
            text_main=clip.text_main,
            text_second=clip.text_second,
            text_display=clip.text_display,
            font_family=clip.text_font_family,
            font_size=int(clip.text_font_size),
            color=clip.text_color,
            second_font_size=int(clip.text_second_font_size),
            second_color=clip.text_second_color,
            stroke_color=clip.text_stroke_color,
            stroke_width=int(clip.text_stroke_width),
        )
        materials.texts.append(material)
        return material

    def segment_from_clip(clip: Clip, *, track_kind: str) -> Segment:
        duration_s = clip.timeline_duration
        source_duration_s = clip.source_duration
        duration_us = seconds_to_us(duration_s)

        if clip.is_text_clip:
            material_id = text_material_from_clip(clip).id
            source_timerange = None
            if duration_us <= 0:
                duration_us = seconds_to_us(clip.out_point)
        elif track_kind == "audio":
            material_id = intern_audio(clip.source, duration_us=seconds_to_us(source_duration_s))
            source_timerange = TimeRange(
                start=seconds_to_us(clip.in_point),
                duration=seconds_to_us(source_duration_s),
            )
        else:
            material_id = intern_video(
                clip.source,
                proxy=clip.proxy,
                duration_us=seconds_to_us(source_duration_s),
            )
            source_timerange = TimeRange(
                start=seconds_to_us(clip.in_point),
                duration=seconds_to_us(source_duration_s),
            )

        has_axis_scale = clip.scale_x is not None or clip.scale_y is not None
        if has_axis_scale:
            base = float(clip.scale) if clip.scale is not None else 1.0
            sx_raw = clip.scale_x
            sy_raw = clip.scale_y
            if sx_raw is None:
                sx_raw = sy_raw if sy_raw is not None else base
            if sy_raw is None:
                sy_raw = sx_raw if sx_raw is not None else base
            scale_x = max(0.01, min(5.0, float(sx_raw)))
            scale_y = max(0.01, min(5.0, float(sy_raw)))
        else:
            scale = float(clip.scale) if clip.scale is not None else 1.0
            scale_x = scale
            scale_y = scale
        pos_x = float(clip.pos_x) if clip.pos_x is not None else 0.0
        pos_y = float(clip.pos_y) if clip.pos_y is not None else 0.0
        transform = ClipTransform(
            scale=Scale2(x=scale_x, y=scale_y),
            transform=Vec2(x=pos_x, y=pos_y),
            rotation=float(clip.effects.rotate),
            flip=Flip(
                horizontal=bool(clip.effects.hflip),
                vertical=bool(clip.effects.vflip),
            ),
        )
        pip_scale = clip.scale
        if has_axis_scale:
            pip_scale = scale_x if abs(scale_x - scale_y) <= 1e-9 and scale_x != 1.0 else None

        return Segment(
            material_id=material_id,
            source_timerange=source_timerange,
            target_timerange=TimeRange(
                start=seconds_to_us(clip.start),
                duration=max(0, duration_us),
            ),
            speed=float(clip.speed),
            volume=float(clip.volume),
            reverse=bool(clip.reverse),
            visible=True,
            clip=transform,
            extra_material_refs=add_effect_refs(clip.effects, clip.audio_effects),
            pip_scale=pip_scale,
            pip_pos_x=clip.pos_x,
            pip_pos_y=clip.pos_y,
            voice_preset_id=clip.audio_effects.voice_preset_id,
        )

    def segment_from_text_overlay(overlay: TextOverlay) -> Segment:
        material = TextMaterial(
            text_main=overlay.text,
            font_size=int(overlay.font_size),
            color=overlay.font_color,
        )
        materials.texts.append(material)
        return Segment(
            material_id=material.id,
            source_timerange=None,
            target_timerange=TimeRange(
                start=seconds_to_us(overlay.start),
                duration=seconds_to_us(max(0.0, overlay.end - overlay.start)),
            ),
            opacity_keyframes=[
                KeyframeV2(time=seconds_to_us(k.time), value=float(k.value))
                for k in overlay.opacity_keyframes
            ],
            x_keyframes=[
                KeyframeV2(time=seconds_to_us(k.time), value=float(k.value))
                for k in overlay.x_keyframes
            ],
            y_keyframes=[
                KeyframeV2(time=seconds_to_us(k.time), value=float(k.value))
                for k in overlay.y_keyframes
            ],
        )

    def segment_from_image_overlay(overlay: ImageOverlay) -> Segment:
        start_us = seconds_to_us(overlay.start)
        duration_us = seconds_to_us(max(0.0, overlay.end - overlay.start))
        return Segment(
            material_id=intern_image(overlay.source),
            source_timerange=TimeRange(start=0, duration=duration_us),
            target_timerange=TimeRange(start=start_us, duration=duration_us),
            clip=ClipTransform(
                scale=Scale2(x=float(overlay.scale), y=float(overlay.scale)),
                transform=Vec2(x=float(overlay.x), y=float(overlay.y)),
                alpha=float(overlay.opacity),
            ),
            pip_scale=float(overlay.scale),
            pip_pos_x=int(overlay.x),
            pip_pos_y=int(overlay.y),
        )

    tracks: list[TrackV2] = []
    for track in project.tracks:
        base_track = TrackV2(
            type=track.kind,
            name=track.name,
            locked=track.locked,
            hidden=track.hidden,
            muted=track.muted,
            segments=[segment_from_clip(clip, track_kind=track.kind) for clip in track.clips],
        )
        tracks.append(base_track)

        for transition in track.transitions:
            from_id = ""
            to_id = ""
            if 0 <= transition.from_index < len(base_track.segments):
                from_id = base_track.segments[transition.from_index].id
            if 0 <= transition.to_index < len(base_track.segments):
                to_id = base_track.segments[transition.to_index].id
            materials.transitions.append(
                TransitionMaterial(
                    kind=transition.kind,
                    duration=seconds_to_us(transition.duration),
                    from_segment_id=from_id,
                    to_segment_id=to_id,
                )
            )

        if track.overlays:
            tracks.append(
                TrackV2(
                    type="text",
                    name=f"{track.name or 'Track'} Text Overlays",
                    segments=[segment_from_text_overlay(overlay) for overlay in track.overlays],
                )
            )
        if track.image_overlays:
            tracks.append(
                TrackV2(
                    type="image",
                    name=f"{track.name or 'Track'} Image Overlays",
                    segments=[segment_from_image_overlay(overlay) for overlay in track.image_overlays],
                )
            )

    now_us = int(time.time() * US_PER_SECOND)
    return ProjectV2(
        name=project.name,
        duration=seconds_to_us(project.duration),
        fps=float(project.fps),
        sample_rate=int(project.sample_rate),
        create_time=now_us,
        update_time=now_us,
        canvas_config=CanvasConfig(width=int(project.width), height=int(project.height)),
        tracks=tracks,
        materials=materials,
        keyframes={},
    )


def v2_to_project(v2: ProjectV2) -> Project:
    """Convert a V2 draft model back to the legacy in-memory project."""
    videos = {item.id: item for item in v2.materials.videos}
    audios = {item.id: item for item in v2.materials.audios}
    texts = {item.id: item for item in v2.materials.texts}
    images = {item.id: item for item in v2.materials.images}
    effects = {item.id: item for item in v2.materials.effects}
    audio_effects = {item.id: item for item in v2.materials.audio_effects}
    crops = {item.id: item for item in v2.materials.crops}
    chromas = {item.id: item for item in v2.materials.chromas}

    def resolve_extras(refs: list[str], transform: ClipTransform) -> tuple[ClipEffects, ClipAudioEffects]:
        visual = ClipEffects(
            rotate=float(transform.rotation),
            hflip=bool(transform.flip.horizontal),
            vflip=bool(transform.flip.vertical),
        )
        audio = ClipAudioEffects()
        for ref in refs:
            if ref in effects:
                material = effects[ref]
                visual = visual.model_copy(
                    update={
                        "blur": material.blur,
                        "brightness": material.brightness,
                        "contrast": material.contrast,
                        "saturation": material.saturation,
                        "grayscale": material.grayscale,
                        "rotate": material.rotate or visual.rotate,
                        "hflip": material.hflip or visual.hflip,
                        "vflip": material.vflip or visual.vflip,
                    }
                )
            elif ref in audio_effects:
                material = audio_effects[ref]
                audio = ClipAudioEffects(
                    fade_in=material.fade_in,
                    fade_out=material.fade_out,
                    pitch_semitones=material.pitch_semitones,
                    formant_shift=material.formant_shift,
                    chorus_depth=material.chorus_depth,
                    voice_preset_id=material.voice_preset_id,
                    denoise=material.denoise,
                    denoise_method=material.denoise_method,
                    denoise_model=material.denoise_model,
                    normalize=material.normalize,
                )
            elif ref in crops:
                material = crops[ref]
                visual = visual.model_copy(
                    update={
                        "crop": CropRect(
                            x=int(material.x),
                            y=int(material.y),
                            width=int(material.width),
                            height=int(material.height),
                        )
                    }
                )
            elif ref in chromas:
                material = chromas[ref]
                visual = visual.model_copy(
                    update={
                        "chromakey": ChromaKey(
                            color=material.color,
                            similarity=float(material.similarity),
                            blend=float(material.blend),
                        )
                    }
                )
        return visual, audio

    def safe_scale(seg: Segment) -> float | None:
        value = seg.pip_scale
        if value is None:
            sx = float(seg.clip.scale.x)
            sy = float(seg.clip.scale.y)
            if sx == sy and sx != 1.0:
                value = sx
        if value is None or value <= 0.0 or value > 5.0:
            return None
        return float(value)

    def safe_axis_scale(value: float) -> float:
        if value <= 0.0 or value > 5.0:
            return 1.0
        return float(value)

    def safe_pos_x(seg: Segment) -> int | None:
        if seg.pip_pos_x is not None:
            return int(seg.pip_pos_x)
        value = int(round(seg.clip.transform.x))
        return value if value else None

    def safe_pos_y(seg: Segment) -> int | None:
        if seg.pip_pos_y is not None:
            return int(seg.pip_pos_y)
        value = int(round(seg.clip.transform.y))
        return value if value else None

    def clip_from_segment(seg: Segment, *, material_type: str) -> Clip | None:
        visual, audio = resolve_extras(seg.extra_material_refs, seg.clip)
        source_range = seg.source_timerange or TimeRange()
        in_point = us_to_seconds(source_range.start)
        out_point = None
        if source_range.duration > 0:
            out_point = us_to_seconds(source_range.start + source_range.duration)
        start = us_to_seconds(seg.target_timerange.start)

        if material_type == "video" and seg.material_id in videos:
            material = videos[seg.material_id]
            sx = safe_axis_scale(float(seg.clip.scale.x))
            sy = safe_axis_scale(float(seg.clip.scale.y))
            uniform_scale = abs(sx - sy) <= 1e-9
            return Clip(
                clip_type="media",
                source=material.path,
                proxy=material.proxy_path,
                in_point=in_point,
                out_point=out_point,
                start=start,
                volume=float(seg.volume),
                speed=float(seg.speed),
                reverse=bool(seg.reverse),
                scale=safe_scale(seg) if uniform_scale else None,
                scale_x=None if uniform_scale else sx,
                scale_y=None if uniform_scale else sy,
                pos_x=safe_pos_x(seg),
                pos_y=safe_pos_y(seg),
                effects=visual,
                audio_effects=audio,
            )

        if material_type == "audio" and seg.material_id in audios:
            material = audios[seg.material_id]
            return Clip(
                clip_type="media",
                source=material.path,
                in_point=in_point,
                out_point=out_point,
                start=start,
                volume=float(seg.volume),
                speed=float(seg.speed),
                reverse=bool(seg.reverse),
                effects=visual,
                audio_effects=audio,
            )

        if seg.material_id in texts:
            material = texts[seg.material_id]
            duration = max(0.001, us_to_seconds(seg.target_timerange.duration))
            return Clip(
                clip_type="text",
                source="",
                in_point=0.0,
                out_point=duration,
                start=start,
                text_main=material.text_main,
                text_second=material.text_second,
                text_display=material.text_display,
                text_font_family=material.font_family,
                text_font_size=int(material.font_size),
                text_color=material.color,
                text_second_font_size=int(material.second_font_size),
                text_second_color=material.second_color,
                text_stroke_color=material.stroke_color,
                text_stroke_width=int(material.stroke_width),
            )

        return None

    legacy_tracks: list[Track] = []
    segment_positions: dict[str, tuple[int, int]] = {}

    for track in v2.tracks:
        if track.type in ("video", "audio", "text"):
            legacy_track = Track(
                kind=track.type,
                name=track.name,
                locked=track.locked,
                hidden=track.hidden,
                muted=track.muted,
            )
            legacy_index = len(legacy_tracks)
            for seg in track.segments:
                clip = clip_from_segment(seg, material_type=track.type)
                if clip is None:
                    continue
                segment_positions[seg.id] = (legacy_index, len(legacy_track.clips))
                legacy_track.clips.append(clip)
            legacy_tracks.append(legacy_track)
            continue

        if track.type == "image":
            if not legacy_tracks or legacy_tracks[-1].kind != "video":
                legacy_tracks.append(Track(kind="video", name=track.name or "Images"))
            host = legacy_tracks[-1]
            for seg in track.segments:
                material = images.get(seg.material_id)
                if material is None:
                    continue
                start = us_to_seconds(seg.target_timerange.start)
                end = start + us_to_seconds(seg.target_timerange.duration)
                host.image_overlays.append(
                    ImageOverlay(
                        source=material.path,
                        start=start,
                        end=max(start + 0.001, end),
                        x=safe_pos_x(seg) or 0,
                        y=safe_pos_y(seg) or 0,
                        scale=float(seg.clip.scale.x),
                        opacity=float(seg.clip.alpha),
                    )
                )

    for material in v2.materials.transitions:
        left = segment_positions.get(material.from_segment_id)
        right = segment_positions.get(material.to_segment_id)
        if left is None or right is None or left[0] != right[0] or right[1] <= left[1]:
            continue
        try:
            legacy_tracks[left[0]].transitions.append(
                Transition(
                    from_index=left[1],
                    to_index=right[1],
                    duration=max(0.001, us_to_seconds(material.duration)),
                    kind=material.kind,
                )
            )
        except Exception:
            continue

    return Project(
        name=v2.name,
        width=int(v2.canvas_config.width),
        height=int(v2.canvas_config.height),
        fps=float(v2.fps),
        sample_rate=int(v2.sample_rate),
        tracks=legacy_tracks,
    )


__all__ = [
    "is_v2_format",
    "project_to_v2",
    "v2_to_project",
]
