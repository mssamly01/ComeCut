"""Render a :class:`~comecut_py.core.Project` into a single output file.

Supports:

* Any number of video tracks, each with multiple clips placed on the timeline.
* Any number of audio tracks, mixed with ``amix``.
* Simple trimming via each clip's ``in_point`` / ``out_point``.
* Per-clip volume.
* Per-track text overlays via ``drawtext``.
* Optional transitions between consecutive clips on the same track — uses
  ffmpeg's ``xfade`` for video tracks and ``acrossfade`` for audio tracks.
* Per-clip ``speed``, ``reverse`` and colour effects (blur, brightness,
  contrast, saturation, grayscale).
"""

from __future__ import annotations

from pathlib import Path

from ..core.audio_mixer import track_output_gain
from ..core.ffmpeg_cmd import FFmpegCommand
from ..core.keyframes import evaluate_keyframes
from ..core.project import (
    Clip,
    Keyframe,
    Project,
    TextOverlay,
    Track,
    Transition,
)
from .overlay_text import _escape_drawtext
from .presets import PRESETS, ExportPreset, preset_output_args


_AUDIO_EXPORT_CODECS: dict[str, tuple[str, tuple[str, ...]]] = {
    "aac": ("aac", ("-b:a", "192k")),
    "m4a": ("aac", ("-b:a", "192k")),
    "mp3": ("libmp3lame", ("-b:a", "192k")),
    "wav": ("pcm_s16le", ()),
    "flac": ("flac", ()),
    "ogg": ("libvorbis", ("-q:a", "5")),
}


def _clip_trim_args(clip: Clip) -> list[str]:
    args = ["-ss", f"{clip.in_point}"]
    if clip.out_point is not None:
        args.extend(["-to", f"{clip.out_point}"])
    return args


def _video_effect_chain(clip: Clip) -> str:
    """Build the filter chain applied to a video clip *before* scale/pad/PTS.

    Returns a comma-joined chain (no leading ``,``) or ``""`` if no effects
    are active. ``reverse`` and ``speed`` are also applied here so the clip's
    presentation duration on the timeline is correct downstream.
    """
    parts: list[str] = []
    if clip.reverse:
        parts.append("reverse")
    fx = clip.effects
    # Geometric transforms run *before* colour / blur so the cropped region
    # is what gets graded, not the original full frame.
    if fx.crop is not None:
        parts.append(f"crop={fx.crop.width}:{fx.crop.height}:{fx.crop.x}:{fx.crop.y}")
    if fx.hflip:
        parts.append("hflip")
    if fx.vflip:
        parts.append("vflip")
    if fx.rotate != 0.0:
        # ffmpeg rotate= takes radians; ow/oh=rotw/roth auto-expand the
        # canvas so the rotated frame isn't clipped. Fill with transparent
        # so the later overlay composition doesn't leak a border.
        parts.append(
            f"rotate=PI*{fx.rotate}/180:ow=rotw(PI*{fx.rotate}/180):"
            f"oh=roth(PI*{fx.rotate}/180):c=black@0"
        )
    if fx.chromakey is not None:
        ck = fx.chromakey
        parts.append(f"chromakey=color={ck.color}:similarity={ck.similarity}:blend={ck.blend}")
    # eq() is a no-op when every parameter is at its default. Only emit it if
    # at least one colour knob was touched.
    if (
        fx.brightness != 0.0
        or fx.contrast != 1.0
        or fx.saturation != 1.0
    ):
        parts.append(
            f"eq=brightness={fx.brightness}:contrast={fx.contrast}:saturation={fx.saturation}"
        )
    if fx.grayscale:
        parts.append("hue=s=0")
    if fx.blur > 0.0:
        parts.append(f"gblur=sigma={fx.blur}")
    if clip.speed != 1.0:
        # setpts scales the *presentation timestamps*, so PTS *= 1/speed.
        parts.append(f"setpts=PTS/{clip.speed}")
    return ",".join(parts)


def _clip_scale_pad(clip: Clip, W: int, H: int) -> str:
    """Build the scale + (optional pad) segment that fits a clip to the canvas.

    Two modes:

    * **Fill-and-center (default)** — when ``clip.scale is None``: the clip
      is scaled to fit inside the project canvas preserving its aspect ratio
      and padded to the full ``W x H`` so the downstream overlay can composite
      it at position 0,0. This is the legacy behaviour.
    * **Picture-in-picture** — when ``clip.scale`` is set: the clip is resized
      to ``W * scale`` pixels wide (height auto, preserving aspect) and NOT
      padded. Position on the canvas is controlled by ``clip.pos_x`` /
      ``clip.pos_y`` on the ``overlay`` filter downstream.
    """
    has_axis_scale = clip.scale_x is not None or clip.scale_y is not None
    if not has_axis_scale and clip.scale is None:
        return (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
    if has_axis_scale:
        sx = clip.scale_x
        sy = clip.scale_y
        base = 1.0 if clip.scale is None else max(0.01, min(5.0, float(clip.scale)))
        if sx is None:
            sx = sy if sy is not None else base
        if sy is None:
            sy = sx if sx is not None else base
        sx = max(0.01, min(5.0, float(sx)))
        sy = max(0.01, min(5.0, float(sy)))
        return (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"scale='max(1,trunc(iw*{sx}/2)*2)':'max(1,trunc(ih*{sy}/2)*2)',setsar=1"
        )
    target_w = max(1, int(W * clip.scale))
    # -2 keeps an even height and preserves aspect ratio.
    return f"scale={target_w}:-2,setsar=1"


def _clip_overlay_pos(clip: Clip, W: int, H: int) -> tuple[str, str]:
    """Return the ``(x, y)`` expressions used by the ``overlay`` filter.

    For full-canvas clips the overlay sits at ``(0, 0)``. For PiP clips, the
    caller-supplied ``pos_x`` / ``pos_y`` win; ``None`` centers the clip on
    the canvas (using ``overlay_w`` / ``overlay_h`` which ffmpeg substitutes
    at filter-time).
    """
    has_explicit_scale = (
        clip.scale is not None or clip.scale_x is not None or clip.scale_y is not None
    )
    if not has_explicit_scale:
        return ("0", "0")
    x = str(clip.pos_x) if clip.pos_x is not None else "(main_w-overlay_w)/2"
    y = str(clip.pos_y) if clip.pos_y is not None else "(main_h-overlay_h)/2"
    return (x, y)


def _audio_effect_chain(clip: Clip) -> str:
    """Build the filter chain applied to a clip's audio track."""
    if clip.volume_keyframes:
        expr = _clip_keyframes_to_local_expr(
            clip.volume_keyframes,
            clip_start=float(clip.start),
            default=float(clip.volume),
        )
        parts: list[str] = [f"volume='{expr}':eval=frame"]
    else:
        parts = [f"volume={clip.volume}"]
    if clip.reverse:
        parts.append("areverse")
    # atempo accepts 0.5..2.0 per invocation — chain multiple copies for
    # values outside that range (e.g. 4x → atempo=2.0,atempo=2.0).
    if clip.speed != 1.0:
        remaining = clip.speed
        while remaining > 2.0:
            parts.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            parts.append("atempo=0.5")
            remaining *= 2.0
        if abs(remaining - 1.0) > 1e-9:
            parts.append(f"atempo={remaining}")
    # Per-clip shaping order: denoise → pitch → normalize → fade.
    # Denoise runs first so the noise floor is cleaned before everything
    # else. rubberband must run BEFORE loudnorm because loudnorm buffers
    # audio and flushes extra frames on EOF, which rubberband rejects with
    # "Cannot process again after final chunk".
    afx = clip.audio_effects
    if afx.denoise:
        if afx.denoise_method == "rnnoise":
            # ffmpeg's ``arnndn`` filter requires an external .rnnn model
            # file (a number of pre-trained ones are available from the
            # rnnoise-models project). Without a model the filter errors
            # at filtergraph init, so we fail loudly here with a clearer
            # message instead of a cryptic libavfilter line.
            if not afx.denoise_model:
                raise ValueError(
                    "denoise_method='rnnoise' requires denoise_model to point "
                    "at an .rnnn model file (see "
                    "https://github.com/GregorR/rnnoise-models)."
                )
            # ffmpeg arnndn syntax: arnndn=m=<path>. Quote so paths with
            # ':' or spaces survive filter_complex parsing.
            esc = afx.denoise_model.replace("\\", "\\\\").replace(":", r"\:")
            parts.append(f"arnndn=m='{esc}'")
        else:
            # afftdn defaults are conservative and work well for typical
            # room-tone / mic hiss without audible artefacts.
            parts.append("afftdn")
    if afx.pitch_semitones != 0.0 or afx.formant_shift != 0.0:
        # rubberband supports independent pitch + formant ratios. When
        # only one is set, the other defaults to 1.0 (passthrough).
        ratio_args: list[str] = []
        if afx.pitch_semitones != 0.0:
            pitch_ratio = 2.0 ** (afx.pitch_semitones / 12.0)
            ratio_args.append(f"pitch={pitch_ratio}")
        if afx.formant_shift != 0.0:
            formant_ratio = 2.0 ** (afx.formant_shift / 12.0)
            ratio_args.append(f"formant=preserved:formantscale={formant_ratio}")
        parts.append("rubberband=" + ":".join(ratio_args))

    if afx.chorus_depth > 0.0:
        # ffmpeg ``chorus`` syntax: chorus=in_gain:out_gain:delays:decays:speeds:depths
        # Single voice with delay 40ms + decay 0.4 + speed 0.5Hz + depth scaled by user.
        depth = max(0.05, min(1.0, afx.chorus_depth))
        parts.append(f"chorus=0.7:0.9:55:0.4:0.25:{depth}")
    if afx.normalize:
        # Single-pass loudnorm — fast; ``loudnorm`` with no args uses the
        # EBU R128 default target of -24 LUFS. Callers wanting a true
        # two-pass measurement should use the standalone ``loudnorm``
        # command instead.
        parts.append("loudnorm")
    if afx.fade_in > 0.0:
        # ``ss=0`` anchors the fade to the clip start (which is t=0 after
        # asetpts downstream).
        parts.append(f"afade=t=in:ss=0:d={afx.fade_in}")
    if afx.fade_out > 0.0:
        # Fade-out anchors to the tail of the clip. The effective audio
        # duration is ``(out_point - in_point) / speed`` — same formula
        # as ``timeline_duration``. When the duration is unknown (an
        # open-ended clip with no ``out_point``) we skip the fade-out
        # entirely — emitting ``st=0`` would fade to silence in the first
        # ``d`` seconds and then HOLD the signal at zero for the rest of
        # the clip, silencing all audio after ``d`` seconds.
        dur = clip.timeline_duration
        if dur is not None:
            d = afx.fade_out
            st = max(0.0, dur - d)
            parts.append(f"afade=t=out:st={st}:d={d}")
    return ",".join(parts)


def _clip_keyframes_to_local_expr(
    kfs: list[Keyframe],
    *,
    clip_start: float,
    default: float = 0.0,
) -> str:
    """Compile global timeline keyframes for a per-clip ffmpeg stream."""
    if not kfs:
        return f"{default}"
    start = max(0.0, float(clip_start))
    local_kfs = [
        Keyframe(time=max(0.0, float(kf.time) - start), value=float(kf.value))
        for kf in kfs
        if float(kf.time) >= start
    ]
    if not local_kfs or local_kfs[0].time > 0.0:
        local_kfs.insert(
            0,
            Keyframe(
                time=0.0,
                value=evaluate_keyframes(kfs, start, default=default),
            ),
        )
    return _keyframes_to_expr(local_kfs, default=default)


def _keyframes_to_expr(kfs: list[Keyframe], *, default: float = 0.0) -> str:
    """Compile a keyframe list into a piecewise-linear ffmpeg expression.

    The result is an ``if(...)``-chained expression that interpolates linearly
    between consecutive keyframes. Before the first keyframe it clamps to the
    first value; after the last keyframe it clamps to the last value. An empty
    list returns ``str(default)`` so callers can unconditionally embed it.
    """
    if not kfs:
        return f"{default}"
    if len(kfs) == 1:
        return f"{kfs[0].value}"
    # Build nested `if(lt(t,T_i), lerp_i, else)` from left to right. Plain
    # commas are used throughout — the emitted expression is always embedded
    # inside single-quoted drawtext parameter values, where the filtergraph
    # parser passes the content through literally, so ``\,`` escaping is both
    # unnecessary and inconsistent with the adjacent ``enable='between(...)'``.
    expr = f"{kfs[-1].value}"  # clamp to final value after the last keyframe
    for a, b in reversed(list(zip(kfs, kfs[1:], strict=False))):
        dt = b.time - a.time
        if dt <= 0:
            continue
        # Linear interpolation: a.value + (t - a.time) * (b.value - a.value) / dt
        lerp = f"({a.value}+({b.value}-{a.value})*(t-{a.time})/{dt})"
        expr = f"if(lt(t,{b.time}),{lerp},{expr})"
    # Anything before the first keyframe clamps to kfs[0].value.
    expr = f"if(lt(t,{kfs[0].time}),{kfs[0].value},{expr})"
    return expr


def _drawtext_filter(ov: TextOverlay) -> str:
    parts = [
        f"text={_escape_drawtext(ov.text)}",
        f"fontsize={ov.font_size}",
        f"fontcolor={ov.font_color}",
        f"enable='between(t,{ov.start},{ov.end})'",
    ]
    # Animated x/y take precedence over the static literal values when present.
    if ov.x_keyframes:
        parts.append(f"x='{_keyframes_to_expr(ov.x_keyframes)}'")
    else:
        parts.append(f"x={ov.x}")
    if ov.y_keyframes:
        parts.append(f"y='{_keyframes_to_expr(ov.y_keyframes)}'")
    else:
        parts.append(f"y={ov.y}")
    if ov.opacity_keyframes:
        parts.append(f"alpha='{_keyframes_to_expr(ov.opacity_keyframes, default=1.0)}'")
    if ov.box:
        parts.append("box=1")
        parts.append(f"boxcolor={ov.box_color}")
        parts.append("boxborderw=8")
    return "drawtext=" + ":".join(parts)


def _color_for_drawtext(color: str, fallback: str) -> str:
    c = (color or "").strip()
    if not c:
        return fallback
    if c.startswith("#") and len(c) == 7:
        return "0x" + c[1:]
    return c


def _drawtext_filter_for_text_clip(
    clip: Clip,
    *,
    text: str,
    start: float,
    end: float,
    y_expr: str,
    font_size: int | None = None,
    color: str | None = None,
) -> str:
    resolved_size = max(8, int(font_size if font_size is not None else clip.text_font_size))
    resolved_color = _color_for_drawtext(color if color is not None else clip.text_color, "white")
    parts = [
        f"text={_escape_drawtext(text)}",
        f"fontsize={resolved_size}",
        f"fontcolor={resolved_color}",
        f"bordercolor={_color_for_drawtext(clip.text_stroke_color, 'black')}",
        f"borderw={max(0, int(clip.text_stroke_width))}",
        f"enable='between(t,{start},{end})'",
        "x=(w-text_w)/2",
        f"y={y_expr}",
    ]
    return "drawtext=" + ":".join(parts)


def _clip_or_raise_duration(clip: Clip, what: str) -> float:
    d = clip.timeline_duration
    if d is None:
        raise ValueError(
            f"{what}: clip {clip.source!r} has no out_point — transitions need "
            "explicit clip durations."
        )
    return d


def _transitions_by_from(transitions: list[Transition]) -> dict[int, Transition]:
    """Index transitions by ``from_index``.

    Only adjacent (``to_index == from_index + 1``) transitions are allowed for
    the chained ``xfade``/``acrossfade`` pipeline. Anything else raises.
    """
    out: dict[int, Transition] = {}
    for tr in transitions:
        if tr.to_index != tr.from_index + 1:
            raise ValueError(
                f"Only adjacent transitions are supported (got from={tr.from_index} to={tr.to_index})"
            )
        if tr.from_index in out:
            raise ValueError(f"Duplicate transition at from_index={tr.from_index}")
        out[tr.from_index] = tr
    return out


def _build_video_chain(
    track: Track,
    clip_inputs: dict[int, int],
    W: int,
    H: int,
    track_tag: str = "0",
) -> tuple[list[str], str, float]:
    """Produce a filter chain that emits ONE labelled stream for this video track.

    Returns ``(filters, out_label, timeline_start)`` — ``out_label`` already
    includes the enclosing ``[...]`` wrapping. ``timeline_start`` is the
    ``start`` of the first clip (used to place the track's stream on the base
    canvas). ``track_tag`` is a globally unique suffix used to namespace the
    chained labels so they don't collide with other tracks' chains.
    """
    filters: list[str] = []
    if not track.clips:
        raise ValueError("Track has no clips")

    trans = _transitions_by_from(track.transitions)

    # 1. Scale+pad each clip to the project size and reset its PTS so xfade
    #    gets a clean 0-based stream. ``vs_{idx}`` labels use the *global*
    #    input index so they're unique across tracks without needing a suffix.
    scaled_labels: list[str] = []
    durations: list[float] = []
    for clip in track.clips:
        idx = clip_inputs[id(clip)]
        label = f"vs_{idx}"
        fx_chain = _video_effect_chain(clip)
        fx_prefix = f"{fx_chain}," if fx_chain else ""
        # Transition-chained tracks always need full-canvas frames because
        # xfade expects both inputs to share the same resolution — ignore
        # per-clip ``scale`` here (PiP isn't meaningful inside a single
        # crossfaded chain).
        filters.append(
            f"[{idx}:v]{fx_prefix}scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[{label}]"
        )
        scaled_labels.append(label)
        durations.append(_clip_or_raise_duration(clip, "video transition"))

    # 2. Chain via xfade where a transition is declared, otherwise concat.
    current = scaled_labels[0]
    offset = durations[0]  # cumulative end time of the *chain so far*
    for i in range(1, len(scaled_labels)):
        tr = trans.get(i - 1)
        next_label = f"vx_{track_tag}_{i}"
        if tr is None:
            # No transition — hard cut via concat.
            filters.append(
                f"[{current}][{scaled_labels[i]}]concat=n=2:v=1:a=0[{next_label}]"
            )
            offset += durations[i]
        else:
            xfade_offset = max(0.0, offset - tr.duration)
            filters.append(
                f"[{current}][{scaled_labels[i]}]"
                f"xfade=transition={tr.kind}:duration={tr.duration}:offset={xfade_offset}"
                f"[{next_label}]"
            )
            offset = xfade_offset + tr.duration + (durations[i] - tr.duration)
        current = next_label

    return filters, current, track.clips[0].start


def _build_audio_chain(
    track: Track,
    clip_inputs: dict[int, int],
    track_tag: str = "0",
) -> tuple[list[str], str, float]:
    """Produce a filter chain that emits ONE labelled audio stream for this track.

    ``track_tag`` must be unique across all audio tracks passed to the same
    :func:`render_project` call — it namespaces the intermediate ``ax_…``
    labels so chains on different tracks don't collide.
    """
    filters: list[str] = []
    if not track.clips:
        raise ValueError("Track has no clips")

    trans = _transitions_by_from(track.transitions)

    prepared: list[str] = []
    durations: list[float] = []
    for clip in track.clips:
        idx = clip_inputs[id(clip)]
        label = f"as_{idx}"
        afx = _audio_effect_chain(clip)
        filters.append(f"[{idx}:a]{afx},asetpts=PTS-STARTPTS[{label}]")
        prepared.append(label)
        durations.append(_clip_or_raise_duration(clip, "audio transition"))

    current = prepared[0]
    for i in range(1, len(prepared)):
        tr = trans.get(i - 1)
        next_label = f"ax_{track_tag}_{i}"
        if tr is None:
            filters.append(f"[{current}][{prepared[i]}]concat=n=2:v=0:a=1[{next_label}]")
        else:
            filters.append(
                f"[{current}][{prepared[i]}]"
                f"acrossfade=d={tr.duration}:c1=tri:c2=tri[{next_label}]"
            )
        current = next_label

    return filters, current, track.clips[0].start


def _clip_input_path(clip: Clip, *, use_proxies: bool) -> str:
    """Return the path ffmpeg should read for this clip.

    When ``use_proxies`` is True and the clip has a ``proxy`` attached, the
    proxy is preferred. Otherwise (or if the proxy file is missing on disk)
    the original ``source`` is used.
    """
    if use_proxies and clip.proxy:
        pp = Path(clip.proxy)
        if pp.exists():
            return str(pp)
    return str(clip.source)


def _audio_export_args(
    dst: str | Path,
    *,
    audio_format: str | None,
    sample_rate: int,
) -> list[str]:
    fmt = (audio_format or Path(dst).suffix.lstrip(".") or "m4a").strip().lower()
    codec, extra = _AUDIO_EXPORT_CODECS.get(fmt, _AUDIO_EXPORT_CODECS["m4a"])
    args = ["-vn", "-c:a", codec, "-ar", str(int(sample_rate))]
    args.extend(extra)
    return args


def _still_frame_preset(dst: str | Path) -> ExportPreset:
    ext = Path(dst).suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg"}:
        return ExportPreset(
            name="still-jpeg",
            vcodec="mjpeg",
            acodec=None,
            crf=None,
            x264_preset=None,
            profile=None,
            pix_fmt="",
            container="jpg",
            extra_args=("-q:v", "2", "-frames:v", "1"),
        )
    if ext == "webp":
        return ExportPreset(
            name="still-webp",
            vcodec="libwebp",
            acodec=None,
            crf=None,
            x264_preset=None,
            profile=None,
            pix_fmt="",
            container="webp",
            extra_args=("-lossless", "1", "-frames:v", "1"),
        )
    return ExportPreset(
        name="still-png",
        vcodec="png",
        acodec=None,
        crf=None,
        x264_preset=None,
        profile=None,
        pix_fmt="",
        container="png",
        extra_args=("-frames:v", "1"),
    )


def render_project_audio_only(
    project: Project,
    dst: str | Path,
    *,
    use_proxies: bool = False,
    audio_format: str | None = None,
) -> FFmpegCommand:
    """Build an audio-only export command from audible timeline audio tracks."""
    if not project.tracks:
        raise ValueError("Project has no tracks.")

    audio_tracks = [
        t
        for t in project.tracks
        if t.kind == "audio" and not getattr(t, "hidden", False)
    ]
    cmd = FFmpegCommand()
    input_idx = 0
    clip_inputs: dict[int, int] = {}
    for track in audio_tracks:
        for clip in track.clips:
            cmd.add_input(
                _clip_input_path(clip, use_proxies=use_proxies),
                *_clip_trim_args(clip),
            )
            clip_inputs[id(clip)] = input_idx
            input_idx += 1

    filters: list[str] = []
    audio_streams: list[str] = []
    for i, track in enumerate(audio_tracks):
        if track.muted or not track.clips:
            continue
        track_gain = track_output_gain(track)
        if track.transitions:
            afilters, alabel, astart = _build_audio_chain(
                track,
                clip_inputs,
                track_tag=f"ao{i}",
            )
            filters.extend(afilters)
            delayed = f"aod_{i}"
            delay_ms = round(astart * 1000)
            if delay_ms > 0:
                filters.append(f"[{alabel}]adelay={delay_ms}|{delay_ms}[{delayed}]")
                stream_label = delayed
            else:
                stream_label = alabel
            if abs(track_gain - 1.0) > 1e-9:
                gained = f"aog_{i}"
                filters.append(f"[{stream_label}]volume={track_gain}[{gained}]")
                stream_label = gained
            audio_streams.append(stream_label)
        else:
            for clip in track.clips:
                idx = clip_inputs[id(clip)]
                label = f"ao{idx}"
                delay_ms = round(clip.start * 1000)
                afx = _audio_effect_chain(clip)
                track_gain_suffix = (
                    f",volume={track_gain}" if abs(track_gain - 1.0) > 1e-9 else ""
                )
                filters.append(
                    f"[{idx}:a]{afx},adelay={delay_ms}|{delay_ms}{track_gain_suffix}[{label}]"
                )
                audio_streams.append(label)

    if not audio_streams:
        raise ValueError("Project has no audible audio clips to export.")
    if len(audio_streams) == 1:
        audio_out = f"[{audio_streams[0]}]"
    else:
        joined = "".join(f"[{stream}]" for stream in audio_streams)
        filters.append(
            f"{joined}amix=inputs={len(audio_streams)}:duration=longest:dropout_transition=0[aout]"
        )
        audio_out = "[aout]"
    filters.append(f"{audio_out}alimiter=limit=0.95[amaster]")

    cmd.set_filter_complex(";".join(filters))
    cmd.map("[amaster]")
    cmd.out(
        dst,
        *_audio_export_args(
            dst,
            audio_format=audio_format,
            sample_rate=int(project.sample_rate),
        ),
    )
    return cmd


def render_project_still_frame(
    project: Project,
    dst: str | Path,
    *,
    at_seconds: float = 0.0,
    use_proxies: bool = False,
) -> FFmpegCommand:
    """Build a one-frame still-image export command for the composed timeline."""
    frame_step = 1.0 / max(1.0, float(project.fps or 30.0))
    start = max(0.0, float(at_seconds))
    if project.duration > 0.0:
        start = min(start, max(0.0, project.duration - frame_step))
    return render_project(
        project,
        dst,
        use_proxies=use_proxies,
        preset=_still_frame_preset(dst),
        export_range=(start, start + frame_step),
    )


def render_project(
    project: Project,
    dst: str | Path,
    *,
    use_proxies: bool = False,
    preset: str | ExportPreset | None = None,
    export_range: tuple[float, float] | None = None,
    _pass_number: int | None = None,
    _pass_log_prefix: str | None = None,
) -> FFmpegCommand:
    """Build an :class:`FFmpegCommand` that renders ``project`` to ``dst``.

    Parameters
    ----------
    use_proxies
        Render from each clip's ``proxy`` file instead of its full-res
        source (fast preview path).
    preset
        Name of a registered preset in :data:`~comecut_py.engine.presets.PRESETS`
        (``"youtube-1080p"``, ``"reels"``, ``"gif"``, ...) or an inline
        :class:`ExportPreset` instance. When set, the preset's codecs,
        bitrate/CRF, audio settings and (optional) output resolution
        replace the default libx264 CRF-20 pipeline.
    export_range
        ``(start, end)`` in timeline seconds — only the clip of video
        between those points is written to ``dst``. This is added as
        ``-ss``/``-to`` output args so it composes correctly with the
        filter graph.
    _pass_number, _pass_log_prefix
        Internal — used by :func:`render_project_twopass` to set
        ``-pass 1`` / ``-pass 2`` and ``-passlogfile`` on the two
        underlying commands.
    """
    cmd = FFmpegCommand()

    # Resolve the preset up-front so we know whether to build the audio
    # graph at all. Video-only containers (GIF) reject unconnected filter
    # outputs with "Filter adelay has an unconnected output", so we must
    # skip audio filter construction entirely — not just drop the map.
    resolved_preset: ExportPreset | None = None
    if preset is not None:
        if isinstance(preset, str):
            if preset not in PRESETS:
                raise ValueError(
                    f"Unknown preset {preset!r}. Known: {sorted(PRESETS)}"
                )
            resolved_preset = PRESETS[preset]
        else:
            resolved_preset = preset
    skip_audio = resolved_preset is not None and resolved_preset.acodec is None

    video_tracks = [
        t for t in project.tracks
        if t.kind == "video" and not getattr(t, "hidden", False)
    ]
    audio_tracks = [] if skip_audio else [
        t for t in project.tracks
        if t.kind == "audio" and not getattr(t, "hidden", False)
    ]
    text_tracks = [
        t for t in project.tracks
        if t.kind == "text" and not getattr(t, "hidden", False)
    ]

    if not project.tracks:
        raise ValueError("Project has no tracks.")

    input_idx = 0
    clip_inputs: dict[int, int] = {}
    for track in [*video_tracks, *audio_tracks]:
        for clip in track.clips:
            cmd.add_input(_clip_input_path(clip, use_proxies=use_proxies), *_clip_trim_args(clip))
            clip_inputs[id(clip)] = input_idx
            input_idx += 1

    W, H, fps = project.width, project.height, project.fps
    duration = project.duration if project.duration > 0 else 1.0

    filters: list[str] = []

    # Base canvas.
    filters.append(f"color=c=black:s={W}x{H}:r={fps}:d={duration}[base0]")
    current_label = "base0"
    overlay_counter = 0

    # Video tracks: if the track has transitions, build a single chained stream
    # via xfade and overlay it at the first clip's start time. Otherwise fall
    # back to the simpler per-clip overlay that supports sparse/gapped layouts.
    for vt_idx, track in enumerate(video_tracks):
        if not track.clips:
            continue
        if track.transitions:
            tfilters, tlabel, tstart = _build_video_chain(
                track, clip_inputs, W, H, track_tag=f"vt{vt_idx}"
            )
            filters.extend(tfilters)
            overlay_counter += 1
            next_label = f"base{overlay_counter}"
            shifted = f"vshift_vt{vt_idx}"
            filters.append(f"[{tlabel}]setpts=PTS-STARTPTS+{tstart}/TB[{shifted}]")
            filters.append(
                f"[{current_label}][{shifted}]overlay=enable='gte(t,{tstart})':shortest=0[{next_label}]"
            )
            current_label = next_label
        else:
            for clip in track.clips:
                idx = clip_inputs[id(clip)]
                scaled = f"v{idx}s"
                overlay_counter += 1
                next_label = f"base{overlay_counter}"
                fx_chain = _video_effect_chain(clip)
                fx_prefix = f"{fx_chain}," if fx_chain else ""
                scale_pad = _clip_scale_pad(clip, W, H)
                ox, oy = _clip_overlay_pos(clip, W, H)
                filters.append(
                    f"[{idx}:v]{fx_prefix}{scale_pad},"
                    f"setpts=PTS-STARTPTS+{clip.start}/TB[{scaled}]"
                )
                filters.append(
                    f"[{current_label}][{scaled}]"
                    f"overlay=x={ox}:y={oy}:enable='gte(t,{clip.start})':shortest=0[{next_label}]"
                )
                current_label = next_label

    # Image overlays (watermarks / logos / stickers). Each image is added as
    # a separate ffmpeg input and then looped + scaled + alpha-blended with
    # the running canvas inside its declared ``[start, end]`` time window.
    for track in video_tracks:
        for io in track.image_overlays:
            cmd.add_input(io.source)
            ii = input_idx
            input_idx += 1
            prepped = f"iov{ii}"
            overlay_counter += 1
            next_label = f"base{overlay_counter}"
            # ``loop=-1`` turns a still image into a looping stream; the
            # explicit ``trim=duration={io.end}`` keeps it finite so the
            # composed overlay doesn't extend the output beyond the project
            # timeline. ``format=yuva420p`` preserves the alpha channel
            # through the scale + opacity step.
            filters.append(
                f"[{ii}:v]loop=loop=-1:size=1:start=0,"
                f"scale=iw*{io.scale}:-2,format=yuva420p,"
                f"colorchannelmixer=aa={io.opacity},"
                f"trim=duration={io.end},setpts=PTS-STARTPTS[{prepped}]"
            )
            filters.append(
                f"[{current_label}][{prepped}]"
                f"overlay=x={io.x}:y={io.y}:enable='between(t,{io.start},{io.end})'"
                f":shortest=0[{next_label}]"
            )
            current_label = next_label

    # Text overlays.
    for track in video_tracks:
        for ov in track.overlays:
            overlay_counter += 1
            next_label = f"base{overlay_counter}"
            filters.append(f"[{current_label}]{_drawtext_filter(ov)}[{next_label}]")
            current_label = next_label

    # Timeline text/subtitle clips (HTML-like text track behavior).
    for track in text_tracks:
        for clip in track.clips:
            if not clip.is_text_clip:
                continue
            dur = clip.timeline_duration
            if dur is None or dur <= 0.0:
                continue
            start = clip.start
            end = clip.start + dur
            main = (clip.text_main or "").strip()
            second = (clip.text_second or "").strip()
            mode = clip.text_display

            def _add_text_layer(
                txt: str,
                y_expr: str,
                *,
                font_size: int | None = None,
                color: str | None = None,
            ) -> None:
                nonlocal current_label, overlay_counter
                if not txt:
                    return
                overlay_counter += 1
                next_label = f"base{overlay_counter}"
                filt = _drawtext_filter_for_text_clip(
                    clip,
                    text=txt,
                    start=start,
                    end=end,
                    y_expr=y_expr,
                    font_size=font_size,
                    color=color,
                )
                filters.append(f"[{current_label}]{filt}[{next_label}]")
                current_label = next_label

            if mode == "second":
                _add_text_layer(
                    second or main,
                    "(h-text_h)-70",
                    font_size=clip.text_second_font_size,
                    color=clip.text_second_color,
                )
            elif mode == "bilingual" and second:
                _add_text_layer(main, "(h-text_h)-120", font_size=clip.text_font_size, color=clip.text_color)
                _add_text_layer(
                    second,
                    "(h-text_h)-70",
                    font_size=clip.text_second_font_size,
                    color=clip.text_second_color,
                )
            else:
                _add_text_layer(main or second, "(h-text_h)-70", font_size=clip.text_font_size, color=clip.text_color)

    video_out = f"[{current_label}]"

    # Audio tracks: same story — crossfade chain only when transitions are
    # declared, otherwise plain per-clip adelay + amix (handles gaps).
    audio_streams: list[str] = []
    for i, track in enumerate(audio_tracks):
        if track.muted or not track.clips:
            continue
        track_gain = track_output_gain(track)
        if track.transitions:
            afilters, alabel, astart = _build_audio_chain(
                track, clip_inputs, track_tag=f"at{i}"
            )
            filters.extend(afilters)
            delayed = f"atd_{i}"
            delay_ms = round(astart * 1000)
            if delay_ms > 0:
                filters.append(f"[{alabel}]adelay={delay_ms}|{delay_ms}[{delayed}]")
                stream_label = delayed
            else:
                stream_label = alabel
            if abs(track_gain - 1.0) > 1e-9:
                gained = f"atg_{i}"
                filters.append(f"[{stream_label}]volume={track_gain}[{gained}]")
                stream_label = gained
            audio_streams.append(stream_label)
        else:
            for clip in track.clips:
                idx = clip_inputs[id(clip)]
                label = f"a{idx}"
                delay_ms = round(clip.start * 1000)
                afx = _audio_effect_chain(clip)
                track_gain_suffix = (
                    f",volume={track_gain}" if abs(track_gain - 1.0) > 1e-9 else ""
                )
                filters.append(
                    f"[{idx}:a]{afx},adelay={delay_ms}|{delay_ms}{track_gain_suffix}[{label}]"
                )
                audio_streams.append(label)

    audio_out = None
    if len(audio_streams) == 1:
        audio_out = f"[{audio_streams[0]}]"
    elif audio_streams:
        joined = "".join(f"[{s}]" for s in audio_streams)
        filters.append(
            f"{joined}amix=inputs={len(audio_streams)}:duration=longest:dropout_transition=0[aout]"
        )
        audio_out = "[aout]"
    if audio_out:
        filters.append(f"{audio_out}alimiter=limit=0.95[amaster]")
        audio_out = "[amaster]"

    # Append a final scale+pad stage to fit the composition canvas into
    # the preset's target resolution (only when the preset's output
    # resolution differs from the project canvas).
    if resolved_preset is not None:
        out_w = resolved_preset.width or W
        out_h = resolved_preset.height or H
        if out_w != W or out_h != H:
            # Letterbox/pillarbox — preserve aspect. GIF presets typically
            # leave height=None which means "follow source aspect"; we
            # detect that with ``resolved_preset.height is None`` and skip
            # padding so ffmpeg chooses the height from the scale.
            if resolved_preset.height is None:
                filters.append(f"{video_out}scale={out_w}:-2[scaled]")
            else:
                filters.append(
                    f"{video_out}scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                    f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[scaled]"
                )
            video_out = "[scaled]"

    cmd.set_filter_complex(";".join(filters))
    cmd.map(video_out)
    if audio_out:
        cmd.map(audio_out)

    # Output-range trim (``-ss <s> -to <e>``) goes BEFORE the codec/bitrate
    # args so ffmpeg applies it against the composited stream rather than
    # the individual inputs.
    out_args: list[str] = []
    if export_range is not None:
        start, end = export_range
        if end <= start:
            raise ValueError(
                f"export_range end must be > start (got {start=!r}, {end=!r})."
            )
        out_args += ["-ss", f"{start}", "-to", f"{end}"]

    if resolved_preset is not None:
        out_args += preset_output_args(
            resolved_preset,
            pass_number=_pass_number,
            pass_log_prefix=_pass_log_prefix,
        )
    else:
        out_args += [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
        ]

    cmd.out(dst, *out_args)
    return cmd


def render_project_twopass(
    project: Project,
    dst: str | Path,
    *,
    preset: str | ExportPreset,
    use_proxies: bool = False,
    export_range: tuple[float, float] | None = None,
    pass_log_prefix: str | None = None,
) -> tuple[FFmpegCommand, FFmpegCommand]:
    """Build the two :class:`FFmpegCommand`s needed for a two-pass encode.

    Two-pass only makes sense with bitrate-targeted encodes
    (``preset.video_bitrate``); if the selected preset only has a CRF it
    won't produce different results from a single pass. The first command
    analyses the input and writes ``<prefix>-0.log``; the second reads
    that log and emits the final file.
    """
    resolved = (
        PRESETS[preset] if isinstance(preset, str) and preset in PRESETS
        else preset if isinstance(preset, ExportPreset)
        else None
    )
    if resolved is None:
        raise ValueError(f"Unknown preset {preset!r}.")
    if not resolved.video_bitrate:
        raise ValueError(
            f"Preset {resolved.name!r} has no video_bitrate set — two-pass "
            "encoding needs a bitrate target. Use a single pass (no "
            "--two-pass) for CRF-only presets."
        )
    # Default log prefix is derived from ``dst`` so parallel exports to
    # different files don't clobber each other's stats.
    if pass_log_prefix is None:
        pass_log_prefix = str(Path(dst).with_suffix("")) + ".pass"
    pass1 = render_project(
        project, "/dev/null",
        use_proxies=use_proxies, preset=resolved,
        export_range=export_range,
        _pass_number=1, _pass_log_prefix=pass_log_prefix,
    )
    # Pass 1 analyses the stream but throws the encoded frames away.
    # Force the null muxer; the ``-f null`` must precede the output path
    # in the argv, so we push it into ``output_flags``.
    pass1.output_flags.extend(["-f", "null"])
    pass2 = render_project(
        project, dst,
        use_proxies=use_proxies, preset=resolved,
        export_range=export_range,
        _pass_number=2, _pass_log_prefix=pass_log_prefix,
    )
    return pass1, pass2


__all__ = [
    "render_project",
    "render_project_audio_only",
    "render_project_still_frame",
    "render_project_twopass",
]
