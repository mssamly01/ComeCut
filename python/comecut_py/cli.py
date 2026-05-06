"""Typer-based CLI entry point. Exposed as the ``comecut-py`` console script."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .core.ffmpeg_cmd import FFmpegNotFoundError, format_argv
from .core.media_probe import probe as probe_media
from .core.project import Project
from .engine import audio as audio_ops
from .engine import (
    burn_bilingual_subtitles,
    burn_subtitles,
    concat,
    cut,
    overlay_text,
    render_project,
    trim,
)
from .subtitles import convert as convert_subtitles

app = typer.Typer(
    name="comecut-py",
    add_completion=False,
    no_args_is_help=True,
    help="ComeCut-Py — pure-Python video editor (CLI + optional PySide6 GUI).",
)
console = Console()


def _run(cmd, dry_run: bool) -> None:
    argv = cmd.build()
    if dry_run:
        console.print(f"[dim]$[/dim] {format_argv(argv)}")
        return
    try:
        cmd.run(check=True)
    except FFmpegNotFoundError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e


# ---- top-level ------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the comecut-py version."""
    console.print(f"comecut-py {__version__}")


@app.command()
def probe(path: Path) -> None:
    """Probe a media file with ffprobe and print stream info."""
    try:
        info = probe_media(path)
    except FFmpegNotFoundError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    t = Table(title=str(path), show_header=False)
    t.add_row("duration", f"{info.duration:.3f}s" if info.duration else "?")
    t.add_row("video", f"{info.video_codec} {info.width}x{info.height} @ {info.fps}")
    t.add_row(
        "audio",
        f"{info.audio_codec} {info.sample_rate}Hz {info.channels}ch" if info.has_audio else "—",
    )
    console.print(t)


# ---- edit operations -----------------------------------------------------


@app.command("cut")
def cut_cmd(
    src: Path,
    dst: Path,
    start: str = typer.Option(..., "--start", "-s", help="Start time (e.g. 00:00:05 or 5.5)."),
    end: str = typer.Option(..., "--end", "-e", help="End time."),
    copy: bool = typer.Option(False, help="Stream-copy (fast, only keyframe-accurate)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the ffmpeg command, don't run."),
) -> None:
    """Cut ``src[start:end]`` into ``dst``."""
    _run(cut(src, dst, start=start, end=end, copy=copy), dry_run)


@app.command("concat")
def concat_cmd(
    inputs: list[Path] = typer.Argument(..., help="Input files (in order)."),
    dst: Path = typer.Option(..., "--out", "-o", help="Output file."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Concatenate multiple files (re-encodes)."""
    _run(concat(inputs, dst), dry_run)


@app.command("trim")
def trim_cmd(
    src: Path,
    dst: Path,
    head: str = typer.Option("0", "--head", help="Seconds to drop from the start."),
    tail: str = typer.Option("0", "--tail", help="Seconds to drop from the end."),
    copy: bool = typer.Option(False),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Trim head/tail from a file."""
    duration: float | None = None
    if float(tail) > 0:
        try:
            duration = probe_media(src).duration
        except FFmpegNotFoundError as e:
            console.print(f"[red]error:[/red] {e}")
            raise typer.Exit(code=2) from e
    _run(trim(src, dst, head=head, tail=tail, duration=duration, copy=copy), dry_run)


@app.command("burn-subs")
def burn_subs_cmd(
    src: Path,
    subs: Path,
    dst: Path,
    style_preset: str | None = typer.Option(
        None,
        "--style-preset",
        help="Load a local subtitle style preset before applying typed flags.",
    ),
    font_name: str | None = typer.Option(None, "--font-name", help="Font family name (e.g. 'Arial')."),
    font_size: int | None = typer.Option(None, "--font-size", help="Font size in points."),
    color: str | None = typer.Option(
        None, "--color",
        help="Primary text colour (CSS hex like '#FFFFFF' or libass '&H00FFFFFF').",
    ),
    outline_color: str | None = typer.Option(
        None, "--outline-color", help="Outline colour (CSS hex or libass).",
    ),
    back_color: str | None = typer.Option(
        None, "--back-color",
        help="Background/box colour (used when --border-style=3).",
    ),
    bold: bool | None = typer.Option(None, "--bold/--no-bold"),
    italic: bool | None = typer.Option(None, "--italic/--no-italic"),
    outline: float | None = typer.Option(
        None, "--outline", help="Outline thickness (libass Outline; e.g. 1.5).",
    ),
    shadow: float | None = typer.Option(
        None, "--shadow", help="Shadow depth (libass Shadow; 0 = off).",
    ),
    border_style: int | None = typer.Option(
        None, "--border-style",
        help="1 = outline+shadow (default look), 3 = opaque box behind text.",
    ),
    alignment: str | None = typer.Option(
        None, "--alignment",
        help="Anchor: bottom-center (default), bottom-left/right, middle-*, top-*, "
             "or a numpad libass int (1..9).",
    ),
    margin_l: int | None = typer.Option(None, "--margin-l", help="Left margin (px)."),
    margin_r: int | None = typer.Option(None, "--margin-r", help="Right margin (px)."),
    margin_v: int | None = typer.Option(
        None, "--margin-v", help="Vertical margin (px) from the anchor edge.",
    ),
    force_style: str | None = typer.Option(
        None, "--force-style",
        help="Raw libass override appended after the typed flags (last value wins). "
             "Example: 'Fontsize=24,PrimaryColour=&H00FFFFFF'.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Burn subtitles (SRT/ASS) into the video track.

    Individual ``--font-*``/``--color``/``--alignment``/... flags build a
    typed libass style; ``--force-style`` is appended raw after the typed
    flags, so a key in ``--force-style`` overrides the same key set by a
    flag (libass takes the last value).
    """
    from .core.subtitle_style_presets import (
        load_subtitle_style_from_preset,
        merge_subtitle_force_styles,
    )
    from .subtitles import SubtitleStyle

    if border_style is not None and border_style not in (1, 3):
        console.print(
            f"[red]error:[/red] --border-style must be 1 or 3, got {border_style}."
        )
        raise typer.Exit(code=2)

    style = SubtitleStyle(
        font_name=font_name,
        font_size=font_size,
        primary_colour=color,
        outline_colour=outline_color,
        back_colour=back_color,
        bold=bold,
        italic=italic,
        outline=outline,
        shadow=shadow,
        border_style=border_style,  # type: ignore[arg-type]
        alignment=_parse_alignment(alignment) if alignment is not None else None,
        margin_l=margin_l,
        margin_r=margin_r,
        margin_v=margin_v,
    )

    try:
        preset_style = (
            load_subtitle_style_from_preset(style_preset)
            if style_preset
            else None
        )
        merged = merge_subtitle_force_styles(preset_style, style, force_style)
    except (OSError, ValueError, TypeError) as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    try:
        cmd = burn_subtitles(src, subs, dst, force_style=merged)
    except ValueError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    _run(cmd, dry_run)


def _parse_alignment(value: str) -> str | int:
    """Accept a libass numpad int as a string or one of the named anchors."""
    v = value.strip()
    if v.isdigit():
        n = int(v)
        if 1 <= n <= 9:
            return n
        raise typer.BadParameter(
            f"--alignment integer must be 1..9, got {n}."
        )
    return v


@app.command("burn-bilingual-subs")
def burn_bilingual_subs_cmd(
    src: Path = typer.Argument(..., help="Source video."),
    primary: Path = typer.Argument(..., help="Primary subtitle file (bottom)."),
    secondary: Path = typer.Argument(..., help="Secondary subtitle file (top)."),
    dst: Path = typer.Argument(..., help="Output video."),
    primary_style: str | None = typer.Option(
        None, "--primary-style", help="libass force_style override for the primary track."
    ),
    secondary_style: str | None = typer.Option(
        None, "--secondary-style", help="libass force_style override for the secondary track."
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Burn two subtitle tracks onto the video (primary bottom + secondary top)."""
    _run(
        burn_bilingual_subtitles(
            src, primary, secondary, dst,
            primary_style=primary_style, secondary_style=secondary_style,
        ),
        dry_run,
    )


@app.command("overlay-text")
def overlay_text_cmd(
    src: Path,
    dst: Path,
    text: str = typer.Option(..., "--text", "-t"),
    start: float = typer.Option(0.0, "--start"),
    end: float | None = typer.Option(None, "--end"),
    font_size: int = typer.Option(48, "--size"),
    font_color: str = typer.Option("white", "--color"),
    font_file: Path | None = typer.Option(None, "--font-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Draw a text overlay on top of the video."""
    _run(
        overlay_text(
            src,
            dst,
            text,
            start=start,
            end=end,
            font_size=font_size,
            font_color=font_color,
            font_file=font_file,
        ),
        dry_run,
    )


@app.command("extract-audio")
def extract_audio_cmd(
    src: Path,
    dst: Path,
    bitrate: str = typer.Option("192k", "--bitrate"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Extract the audio track."""
    _run(audio_ops.extract_audio(src, dst, bitrate=bitrate), dry_run)


@app.command("volume")
def volume_cmd(
    src: Path,
    dst: Path,
    gain: float = typer.Argument(..., help="Gain multiplier (1.0 = unchanged)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Adjust audio volume by a multiplicative gain."""
    _run(audio_ops.adjust_volume(src, dst, gain), dry_run)


# ---- project render ------------------------------------------------------


@app.command("render")
def render_cmd(
    project_path: Path = typer.Argument(..., help="Path to a project JSON file."),
    dst: Path = typer.Argument(..., help="Output video file."),
    use_proxies: bool = typer.Option(
        False,
        "--use-proxies",
        help="Read from each clip's proxy (if present) instead of the full-res source.",
    ),
    preset: str | None = typer.Option(
        None, "--preset",
        help="Named export preset (youtube-1080p, youtube-4k, reels, tiktok, "
             "twitter, gif, webm). Overrides codec/bitrate/resolution.",
    ),
    start: float | None = typer.Option(
        None, "--start", help="Only export timeline seconds ≥ --start."
    ),
    end: float | None = typer.Option(
        None, "--end", help="Only export timeline seconds < --end."
    ),
    two_pass: bool = typer.Option(
        False, "--two-pass",
        help="Use two-pass VBR encoding (requires --preset with a video_bitrate).",
    ),
    video_bitrate: str | None = typer.Option(
        None, "--video-bitrate",
        help="Override the preset's video bitrate (e.g. '8M'). Needed for --two-pass on CRF presets.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Render a project file into a single output (MP4 by default).

    When ``--preset`` is set, the output codec, bitrate/CRF, resolution and
    container default reflect the preset. ``--start``/``--end`` trim the
    timeline to a sub-range without re-editing the project. ``--two-pass``
    runs an analyse pass then an encode pass — only meaningful for
    bitrate-targeted encodes, so combine with ``--video-bitrate`` to
    override a CRF-only preset.
    """
    from .engine import PRESETS
    from .engine.render import render_project_twopass

    project = Project.from_json(project_path)

    export_range = None
    if start is not None or end is not None:
        s = 0.0 if start is None else float(start)
        e = float(end) if end is not None else project.duration
        export_range = (s, e)

    # If the caller wants two-pass on a CRF-only preset, we clone the
    # preset on the fly and graft the supplied bitrate onto it.
    resolved_preset = None
    if preset is not None:
        if preset not in PRESETS:
            console.print(
                f"[red]error:[/red] unknown preset {preset!r}. "
                f"Known: {', '.join(sorted(PRESETS))}"
            )
            raise typer.Exit(code=2)
        resolved_preset = PRESETS[preset]
        if video_bitrate:
            from dataclasses import replace
            resolved_preset = replace(resolved_preset, video_bitrate=video_bitrate)

    if two_pass:
        if resolved_preset is None:
            console.print("[red]error:[/red] --two-pass requires --preset.")
            raise typer.Exit(code=2)
        if not resolved_preset.video_bitrate:
            console.print(
                f"[red]error:[/red] preset {preset!r} has no video_bitrate — "
                "combine --two-pass with --video-bitrate (e.g. --video-bitrate 8M)."
            )
            raise typer.Exit(code=2)
        pass1, pass2 = render_project_twopass(
            project, dst,
            preset=resolved_preset,
            use_proxies=use_proxies,
            export_range=export_range,
        )
        _run(pass1, dry_run)
        _run(pass2, dry_run)
        return

    _run(
        render_project(
            project, dst,
            use_proxies=use_proxies,
            preset=resolved_preset,
            export_range=export_range,
        ),
        dry_run,
    )


@app.command("make-proxy")
def make_proxy_cmd(
    src: Path = typer.Argument(..., help="Source media file."),
    width: int = typer.Option(640, "--width", help="Target width in pixels (height auto)."),
    crf: int = typer.Option(28, "--crf", help="libx264 CRF (higher = smaller file)."),
    force: bool = typer.Option(False, "--force", help="Regenerate even if a cached proxy exists."),
) -> None:
    """Generate a low-res proxy for a single media file and print its path."""
    from .engine.proxy import make_proxy

    try:
        out = make_proxy(src, width=width, crf=crf, force=force)
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    console.print(str(out))


@app.command("make-proxies")
def make_proxies_cmd(
    project_path: Path = typer.Argument(..., help="Project JSON file."),
    width: int = typer.Option(640, "--width"),
    crf: int = typer.Option(28, "--crf"),
    force: bool = typer.Option(False, "--force"),
    save: bool = typer.Option(
        True,
        "--save/--no-save",
        help="Write proxy paths back onto the project JSON.",
    ),
) -> None:
    """Generate proxies for every unique source in a project JSON."""
    from .engine.proxy import ensure_proxies

    project = Project.from_json(project_path)
    try:
        mapping = ensure_proxies(project, width=width, crf=crf, force=force)
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    for src, proxy in mapping:
        console.print(f"{src} -> {proxy}")
    if save:
        project.to_json(project_path)
        console.print(f"wrote proxy paths to {project_path}")


@app.command("apply-effects")
def apply_effects_cmd(
    src: Path = typer.Argument(..., help="Source media file."),
    dst: Path = typer.Argument(..., help="Output file."),
    speed: float = typer.Option(1.0, "--speed", help="Playback speed multiplier."),
    reverse: bool = typer.Option(False, "--reverse", help="Reverse the clip."),
    blur: float = typer.Option(0.0, "--blur", help="Gaussian blur sigma (0 = off)."),
    brightness: float = typer.Option(
        0.0, "--brightness", help="Brightness offset in eq() units (-1..1)."
    ),
    contrast: float = typer.Option(
        1.0, "--contrast", help="Contrast multiplier in eq() units (1 = no change)."
    ),
    saturation: float = typer.Option(
        1.0, "--saturation", help="Saturation multiplier in eq() units (1 = no change)."
    ),
    grayscale: bool = typer.Option(False, "--grayscale", help="Desaturate completely."),
    crop: str | None = typer.Option(
        None, "--crop", help="Crop region 'x,y,w,h' in source pixels (e.g. '0,0,1280,720')."
    ),
    rotate: float = typer.Option(0.0, "--rotate", help="Rotate clockwise by N degrees."),
    hflip: bool = typer.Option(False, "--hflip", help="Mirror horizontally."),
    vflip: bool = typer.Option(False, "--vflip", help="Mirror vertically."),
    chromakey_color: str | None = typer.Option(
        None, "--chromakey", help="Chroma-key colour (hex/name), e.g. '0x00FF00'."
    ),
    chromakey_similarity: float = typer.Option(
        0.1, "--chromakey-similarity", help="Chroma-key hue tolerance (0..1]."
    ),
    chromakey_blend: float = typer.Option(
        0.0, "--chromakey-blend", help="Chroma-key alpha softness (0..1)."
    ),
    fade_in: float = typer.Option(0.0, "--fade-in", help="Audio fade-in duration (s)."),
    fade_out: float = typer.Option(0.0, "--fade-out", help="Audio fade-out duration (s)."),
    pitch: float = typer.Option(
        0.0, "--pitch", help="Pitch shift in semitones (-24..+24, requires rubberband)."
    ),
    denoise: bool = typer.Option(
        False, "--denoise",
        help="Apply per-clip noise suppression (filter chosen by --denoise-method).",
    ),
    denoise_method: str = typer.Option(
        "afftdn", "--denoise-method",
        help="Noise-reduction algorithm: 'afftdn' (default, FFT-based, no "
             "model needed) or 'rnnoise' (RNN-based; requires --denoise-model).",
    ),
    denoise_model: Path | None = typer.Option(
        None, "--denoise-model",
        help="Path to a .rnnn model file (required when --denoise-method=rnnoise). "
             "Models: https://github.com/GregorR/rnnoise-models",
    ),
    normalize: bool = typer.Option(
        False, "--normalize", help="Apply single-pass EBU R128 loudnorm."
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Apply per-clip effects to a single media file using the project engine.

    This is a convenience wrapper around :func:`render_project` that builds a
    one-clip, one-track project on the fly. Great for quick tests without
    hand-rolling a JSON file.
    """
    from .core.project import ChromaKey, CropRect

    # Probe the source so the render canvas has a proper duration budget, and
    # so we know whether to add a parallel audio track.
    out_point: float | None = None
    has_audio = True
    try:
        info = probe_media(src)
        if info.duration:
            out_point = float(info.duration)
        has_audio = bool(info.has_audio)
    except Exception:
        # Probe failures shouldn't block the render — fall back to "render
        # both tracks and let ffmpeg figure it out". If the source truly has
        # no audio, the audio track will simply produce no samples.
        pass

    crop_rect: CropRect | None = None
    if crop:
        try:
            x, y, w, h = (int(p) for p in crop.split(","))
        except ValueError as e:
            console.print(f"[red]error:[/red] --crop expects 'x,y,w,h', got {crop!r}")
            raise typer.Exit(code=2) from e
        crop_rect = CropRect(x=x, y=y, width=w, height=h)

    ck = (
        ChromaKey(
            color=chromakey_color,
            similarity=chromakey_similarity,
            blend=chromakey_blend,
        )
        if chromakey_color
        else None
    )

    if denoise_method not in ("afftdn", "rnnoise"):
        console.print(
            f"[red]error:[/red] --denoise-method must be 'afftdn' or 'rnnoise', "
            f"got {denoise_method!r}."
        )
        raise typer.Exit(code=2)
    if denoise and denoise_method == "rnnoise" and denoise_model is None:
        console.print(
            "[red]error:[/red] --denoise-method=rnnoise requires --denoise-model "
            "(path to an .rnnn file)."
        )
        raise typer.Exit(code=2)

    project = _build_single_clip_project(
        src,
        out_point=out_point,
        has_audio=has_audio,
        speed=speed,
        reverse=reverse,
        crop_rect=crop_rect,
        chromakey=ck,
        blur=blur,
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
        grayscale=grayscale,
        rotate=rotate,
        hflip=hflip,
        vflip=vflip,
        fade_in=fade_in,
        fade_out=fade_out,
        pitch=pitch,
        denoise=denoise,
        denoise_method=denoise_method,
        denoise_model=str(denoise_model) if denoise_model else None,
        normalize=normalize,
    )

    _run(render_project(project, dst), dry_run)


def _build_single_clip_project(
    src: Path,
    *,
    out_point: float | None,
    has_audio: bool,
    speed: float = 1.0,
    reverse: bool = False,
    crop_rect=None,
    chromakey=None,
    blur: float = 0.0,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    grayscale: bool = False,
    rotate: float = 0.0,
    hflip: bool = False,
    vflip: bool = False,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    pitch: float = 0.0,
    denoise: bool = False,
    denoise_method: str = "afftdn",
    denoise_model: str | None = None,
    normalize: bool = False,
):
    """Build a 1-clip Project carrying every effect that ``apply-effects`` exposes.

    Lives here so the ``batch apply-effects`` command can reuse the
    exact same projection without re-emitting the typer.Option block.
    """
    from .core.project import (
        Clip,
        ClipAudioEffects,
        ClipEffects,
        Project,
        Track,
    )

    fx = ClipEffects(
        blur=blur,
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
        grayscale=grayscale,
        crop=crop_rect,
        rotate=rotate,
        hflip=hflip,
        vflip=vflip,
        chromakey=chromakey,
    )
    project = Project()

    video_track = Track(kind="video")
    video_track.clips.append(
        Clip(
            source=str(src),
            in_point=0.0,
            out_point=out_point,
            speed=speed,
            reverse=reverse,
            effects=fx,
        )
    )
    project.tracks.append(video_track)

    if has_audio:
        audio_fx = ClipAudioEffects(
            fade_in=fade_in,
            fade_out=fade_out,
            pitch_semitones=pitch,
            denoise=denoise,
            denoise_method=denoise_method,  # type: ignore[arg-type]
            denoise_model=denoise_model,
            normalize=normalize,
        )
        audio_track = Track(kind="audio")
        audio_track.clips.append(
            Clip(
                source=str(src),
                in_point=0.0,
                out_point=out_point,
                speed=speed,
                reverse=reverse,
                audio_effects=audio_fx,
            )
        )
        project.tracks.append(audio_track)

    return project


# ---- subtitles -----------------------------------------------------------


@app.command("convert-subs")
def convert_subs_cmd(src: Path, dst: Path) -> None:
    """Convert between SRT / VTT / LRC / ASS subtitle formats."""
    convert_subtitles(src, dst)
    console.print(f"wrote {dst}")


@app.command("split-subs")
def split_subs_cmd(
    src: Path = typer.Argument(..., help="Input subtitle file."),
    dst: Path = typer.Argument(..., help="Output subtitle file (same format family as input)."),
    max_chars: int = typer.Option(42, "--max-chars", help="Max characters per rendered line."),
    max_lines: int = typer.Option(2, "--max-lines", help="Max lines per cue."),
    max_duration: float | None = typer.Option(
        None, "--max-duration", help="Max seconds any single cue may span; longer cues are bisected."
    ),
) -> None:
    """Re-flow a subtitle file so each cue fits within per-line and per-duration caps.

    The output format is inferred from ``dst``'s extension; this is
    also a one-shot format converter (e.g. an SRT can be split into an
    ASS, or vice-versa).
    """
    from .subtitles import SubtitleStyle  # noqa: F401  (ensures module imports cleanly)
    from .subtitles.convert import detect_format
    from .subtitles.processing import split_long_cues

    src_text = src.read_text(encoding="utf-8-sig")
    src_fmt = detect_format(src, src_text)
    if src_fmt == "srt":
        from .subtitles.srt import parse_srt
        cues = parse_srt(src_text)
    elif src_fmt == "vtt":
        from .subtitles.vtt import parse_vtt
        cues = parse_vtt(src_text)
    elif src_fmt == "ass":
        from .subtitles.ass import parse_ass
        cues = parse_ass(src_text)
    else:
        from .subtitles.lrc import parse_lrc
        cues, _ = parse_lrc(src_text)

    out = split_long_cues(
        cues,
        max_chars_per_line=max_chars,
        max_lines=max_lines,
        max_duration=max_duration,
    )

    dst_ext = dst.suffix.lower()
    if dst_ext == ".srt":
        from .subtitles.srt import write_srt
        dst.write_text(write_srt(out), encoding="utf-8")
    elif dst_ext in {".vtt", ".webvtt"}:
        from .subtitles.vtt import write_vtt
        dst.write_text(write_vtt(out), encoding="utf-8")
    elif dst_ext in {".ass", ".ssa"}:
        from .subtitles.ass import write_ass
        dst.write_text(write_ass(out), encoding="utf-8")
    else:
        raise typer.BadParameter(
            f"Unknown destination subtitle extension: {dst_ext!r}."
        )
    console.print(f"wrote {dst} ({len(out)} cues)")


@app.command("realign-subs")
def realign_subs_cmd(
    subs: Path = typer.Argument(..., help="Existing subtitle file to realign."),
    audio: Path = typer.Argument(..., help="Audio/video source to re-transcribe."),
    dst: Path = typer.Argument(..., help="Output subtitle file (same format family as input)."),
    model: str = typer.Option("small", "--model", help="faster-whisper model size."),
    language: str | None = typer.Option(None, "--lang"),
    min_confidence: float = typer.Option(
        0.5, "--min-confidence",
        help="Fuzzy-match ratio below which the cue keeps its original timing.",
    ),
) -> None:
    """Re-align subtitle timings against a fresh ASR pass (whisper-local only for now)."""
    from .ai.whisper_local import FasterWhisperASR
    from .subtitles import realign_cues
    from .subtitles.convert import detect_format

    src_text = subs.read_text(encoding="utf-8-sig")
    src_fmt = detect_format(subs, src_text)
    if src_fmt == "srt":
        from .subtitles.srt import parse_srt
        cues = parse_srt(src_text)
    elif src_fmt == "vtt":
        from .subtitles.vtt import parse_vtt
        cues = parse_vtt(src_text)
    elif src_fmt == "ass":
        from .subtitles.ass import parse_ass
        cues = parse_ass(src_text)
    else:
        from .subtitles.lrc import parse_lrc
        cues, _ = parse_lrc(src_text)

    asr = FasterWhisperASR(model_size=model)
    words = asr.transcribe_words(audio, language=language)

    out = realign_cues(cues, words, min_confidence=min_confidence)

    dst_ext = dst.suffix.lower()
    if dst_ext == ".srt":
        from .subtitles.srt import write_srt
        dst.write_text(write_srt(out), encoding="utf-8")
    elif dst_ext in {".vtt", ".webvtt"}:
        from .subtitles.vtt import write_vtt
        dst.write_text(write_vtt(out), encoding="utf-8")
    elif dst_ext in {".ass", ".ssa"}:
        from .subtitles.ass import write_ass
        dst.write_text(write_ass(out), encoding="utf-8")
    else:
        raise typer.BadParameter(
            f"Unknown destination subtitle extension: {dst_ext!r}."
        )
    console.print(f"wrote {dst} ({len(out)} cues)")


@app.command("transcribe")
def transcribe_cmd(
    src: Path,
    dst: Path,
    provider: str = typer.Option(
        "whisper-local",
        "--provider",
        help="ASR backend: 'whisper-local' (faster-whisper), 'openai', 'deepgram', or 'azure'.",
    ),
    model: str = typer.Option(
        "small",
        "--model",
        help="Model name per provider (default: whisper-local='small', openai='whisper-1', deepgram='nova-2').",
    ),
    language: str | None = typer.Option(None, "--lang"),
) -> None:
    """Transcribe an audio/video file into an SRT."""
    from .subtitles.srt import dump_srt

    try:
        if provider == "whisper-local":
            from .ai.whisper_local import FasterWhisperASR

            asr = FasterWhisperASR(model_size=model)
        elif provider == "openai":
            from .ai.openai_asr import OpenAIASR

            asr = OpenAIASR(model=model if model != "small" else "whisper-1")
        elif provider == "deepgram":
            from .ai.deepgram_asr import DeepgramASR

            asr = DeepgramASR(model=model if model != "small" else "nova-2")
        elif provider == "azure":
            from .ai.azure_asr import AzureSpeechASR

            asr = AzureSpeechASR()
        else:
            console.print(f"[red]error:[/red] unknown provider {provider!r}")
            raise typer.Exit(code=2)
    except ImportError as e:
        console.print(
            f"[red]error:[/red] {e}\nInstall AI extras: `pip install 'comecut-py[ai]'`"
        )
        raise typer.Exit(code=2) from e
    except RuntimeError as e:  # missing API key
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    cues = asr.transcribe(src, language=language)
    dump_srt(dst, cues)
    console.print(f"wrote {dst} ({len(cues)} cues)")


@app.command("translate-subs")
def translate_subs_cmd(
    src: Path,
    dst: Path,
    target: str = typer.Option(..., "--to", "-t", help="Target language (e.g. 'vi', 'en', 'zh')."),
    source: str | None = typer.Option(None, "--from", help="Source language hint (optional)."),
    provider: str = typer.Option(
        "openai", "--provider", help="Translation backend: 'openai', 'gemini', or 'claude'."
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model name for the chosen provider (defaults per provider).",
    ),
    batch_size: int = typer.Option(
        1,
        "--batch-size",
        min=1,
        help="Translate N cues per batch request (default 1 = cue-by-cue).",
    ),
    system_prompt: str | None = typer.Option(
        None,
        "--system-prompt",
        help="Optional custom translation system prompt.",
    ),
    glossary: str | None = typer.Option(
        None,
        "--glossary",
        help="Optional glossary injected into provider prompts.",
    ),
) -> None:
    """Translate a subtitle file (SRT/VTT/LRC/ASS) cue-by-cue into another language."""
    from .subtitles.ass import parse_ass, write_ass
    from .subtitles.convert import detect_format
    from .subtitles.cue import Cue, CueList
    from .subtitles.lrc import parse_lrc, write_lrc
    from .subtitles.srt import parse_srt, write_srt
    from .subtitles.translate_batch import chunked
    from .subtitles.vtt import parse_vtt, write_vtt

    src_text = Path(src).read_text(encoding="utf-8-sig")
    src_fmt = detect_format(Path(src), src_text)
    if src_fmt == "srt":
        cues = parse_srt(src_text)
    elif src_fmt == "vtt":
        cues = parse_vtt(src_text)
    elif src_fmt == "ass":
        cues = parse_ass(src_text)
    else:
        cues, _meta = parse_lrc(src_text)

    try:
        if provider == "openai":
            from .ai.openai_translate import OpenAITranslate

            tr = OpenAITranslate(
                model=model or "gpt-4o-mini",
                system_prompt=system_prompt,
                glossary=glossary,
            )
        elif provider == "gemini":
            from .ai.gemini_translate import GeminiTranslate

            tr = GeminiTranslate(
                model=model or "gemini-1.5-flash",
                system_prompt=system_prompt,
                glossary=glossary,
            )
        elif provider == "claude":
            from .ai.claude_translate import ClaudeTranslate

            tr = ClaudeTranslate(
                model=model or "claude-3-5-haiku-latest",
                system_prompt=system_prompt,
                glossary=glossary,
            )
        else:
            console.print(f"[red]error:[/red] unknown provider {provider!r}")
            raise typer.Exit(code=2)
    except ImportError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    if batch_size <= 1:
        translated = tr.translate_cues(cues, target=target, source=source)
    else:
        items = [
            {"id": str(i), "text": cue.text}
            for i, cue in enumerate(cues, start=1)
            if (cue.text or "").strip()
        ]
        translated_by_id: dict[str, str] = {}
        for batch in chunked(items, batch_size):
            out_rows = tr.translate_items(batch, target=target, source=source)
            for row in out_rows:
                item_id = str((row or {}).get("id") or "").strip()
                text_out = str((row or {}).get("text") or "").strip()
                if item_id and text_out:
                    translated_by_id[item_id] = text_out

        out_cues: list[Cue] = []
        for i, cue in enumerate(cues, start=1):
            out_cues.append(
                Cue(
                    start=cue.start,
                    end=cue.end,
                    text=translated_by_id.get(str(i), cue.text),
                    index=cue.index,
                )
            )
        translated = CueList(out_cues)

    dst_ext = Path(dst).suffix.lower()
    if dst_ext == ".vtt":
        Path(dst).write_text(write_vtt(translated), encoding="utf-8")
    elif dst_ext == ".lrc":
        Path(dst).write_text(write_lrc(translated), encoding="utf-8")
    elif dst_ext in {".ass", ".ssa"}:
        Path(dst).write_text(write_ass(translated), encoding="utf-8")
    else:
        Path(dst).write_text(write_srt(translated), encoding="utf-8")
    console.print(f"wrote {dst}")


@app.command("tts")
def tts_cmd(
    text: str = typer.Argument(..., help="Text to synthesise (wrap in quotes)."),
    dst: Path = typer.Argument(..., help="Output audio file (.mp3/.wav/.opus/.flac/.aac)."),
    voice: str | None = typer.Option(None, "--voice"),
    model: str | None = typer.Option(None, "--model"),
    provider: str = typer.Option(
        "openai", "--provider", help="TTS backend: 'openai' or 'elevenlabs'."
    ),
) -> None:
    """Synthesise speech with OpenAI TTS (or another configured provider)."""
    from .plugins import get_provider

    if provider == "openai":
        voice = voice or "alloy"
    try:
        tts = get_provider("tts", provider, model=model)
    except KeyError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except ImportError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    tts.synthesize(text, dst, voice=voice)
    console.print(f"wrote {dst}")


# ---- motion / stills ----------------------------------------------------


@app.command("stabilize")
def stabilize_cmd(
    src: Path = typer.Argument(..., help="Source video."),
    dst: Path = typer.Argument(..., help="Stabilised output."),
    shakiness: int = typer.Option(5, "--shakiness", help="1 = mild .. 10 = very shaky."),
    smoothing: int = typer.Option(10, "--smoothing", help="Smoothing window in frames."),
    zoom: float = typer.Option(0.0, "--zoom", help="Extra zoom to hide warped borders (%)."),
) -> None:
    """Two-pass video stabilisation (vidstabdetect → vidstabtransform).

    Requires an ``ffmpeg`` binary built with the ``vid.stab`` filter
    (standard in Debian/Ubuntu's ``ffmpeg`` package).
    """
    from .engine.stabilize import stabilize as _stabilize

    try:
        out = _stabilize(
            src, dst, shakiness=shakiness, smoothing=smoothing, zoom=zoom
        )
    except (FFmpegNotFoundError, RuntimeError) as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    console.print(f"wrote {out}")


@app.command("freeze-frame")
def freeze_frame_cmd(
    src: Path = typer.Argument(..., help="Source video."),
    dst: Path = typer.Argument(..., help="Output file."),
    at: float = typer.Option(..., "--at", help="Freeze-point time in source seconds."),
    hold: float = typer.Option(..., "--hold", help="How long to hold the frozen frame (s)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Splice a held still frame into a video at ``--at`` for ``--hold`` seconds."""
    from .engine.freeze_frame import freeze_frame as _freeze

    try:
        cmd = _freeze(src, dst, at=at, hold=hold)
    except ValueError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    _run(cmd, dry_run)


@app.command("zoompan-image")
def zoompan_image_cmd(
    src: Path = typer.Argument(..., help="Still image (PNG/JPG)."),
    dst: Path = typer.Argument(..., help="Video output."),
    duration: float = typer.Option(..., "--duration", help="Output duration in seconds."),
    start_zoom: float = typer.Option(1.0, "--start-zoom"),
    end_zoom: float = typer.Option(1.2, "--end-zoom"),
    width: int = typer.Option(1920, "--width"),
    height: int = typer.Option(1080, "--height"),
    fps: float = typer.Option(30.0, "--fps"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Ken Burns effect — animated zoom over a still image into a video clip."""
    from .engine.zoompan import zoompan_image as _zoompan

    try:
        cmd = _zoompan(
            src, dst,
            duration=duration,
            start_zoom=start_zoom,
            end_zoom=end_zoom,
            width=width,
            height=height,
            fps=fps,
        )
    except ValueError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    _run(cmd, dry_run)


# ---- audio mastering ----------------------------------------------------


@app.command("loudnorm")
def loudnorm_cmd(
    src: Path = typer.Argument(..., help="Source media (audio or video)."),
    dst: Path = typer.Argument(..., help="Output with loudness-normalised audio."),
    target: float = typer.Option(
        -16.0, "--target", help="Integrated loudness target in LUFS (YouTube=-16, Spotify=-14, EBU=-23)."
    ),
    true_peak: float = typer.Option(
        -1.5, "--true-peak", help="Maximum true peak in dBTP."
    ),
    lra: float = typer.Option(11.0, "--lra", help="Target loudness range."),
) -> None:
    """Two-pass EBU R128 loudness normalisation.

    Pass 1 measures the input; pass 2 applies gain in linear mode so the
    result hits the target without the single-pass filter's dynamic
    compressor artefacts. Video stream is copied through unchanged.
    """
    from .engine.loudnorm import loudnorm_twopass

    try:
        out = loudnorm_twopass(
            src, dst,
            integrated_lufs=target,
            true_peak_dbtp=true_peak,
            lra=lra,
        )
    except (FFmpegNotFoundError, RuntimeError) as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    console.print(f"wrote {out}")


@app.command("duck")
def duck_cmd(
    voice: Path = typer.Argument(..., help="Voice track (the 'key')."),
    music: Path = typer.Argument(..., help="Music / ambience track to be ducked."),
    dst: Path = typer.Argument(..., help="Output mixed file."),
    threshold: float = typer.Option(
        0.05, "--threshold", help="Sidechain threshold (0..1). Lower = more aggressive."
    ),
    ratio: float = typer.Option(8.0, "--ratio", help="Compression ratio."),
    attack: float = typer.Option(5.0, "--attack", help="Attack time (ms)."),
    release: float = typer.Option(
        250.0, "--release", help="Release time (ms). ~100 for quick recovery."
    ),
    makeup: float = typer.Option(1.0, "--makeup", help="Make-up gain (1 = no boost)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Sidechain-duck ``music`` under ``voice`` and mix both to ``dst``.

    Uses ffmpeg's ``sidechaincompress`` so the music is pulled down
    automatically whenever the voice is active — the standard
    podcast/voiceover ducking technique.
    """
    from .engine.ducking import duck as _duck

    cmd = _duck(
        voice, music, dst,
        threshold=threshold, ratio=ratio,
        attack=attack, release=release, makeup=makeup,
    )
    _run(cmd, dry_run)


# ---- generative AI ------------------------------------------------------


@app.command("image-gen")
def image_gen_cmd(
    prompt: str = typer.Argument(..., help="Prompt (wrap in quotes)."),
    dst: Path = typer.Argument(..., help="Output image file (.png/.jpg/.webp)."),
    provider: str = typer.Option(
        "openai", "--provider",
        help="Backend: 'openai', 'stability', or 'replicate'.",
    ),
    model: str | None = typer.Option(
        None, "--model",
        help="Provider-specific model identifier (e.g. 'dall-e-3', "
             "'black-forest-labs/flux-schnell').",
    ),
    size: str | None = typer.Option(
        None, "--size",
        help="Provider-dependent size/aspect hint (e.g. '1024x1024' or '16:9').",
    ),
    negative_prompt: str | None = typer.Option(None, "--negative-prompt"),
    seed: int | None = typer.Option(None, "--seed"),
) -> None:
    """Generate an image from a text prompt."""
    from .plugins import get_provider

    try:
        gen = get_provider("image", provider, model=model)
    except KeyError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except ImportError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    gen.generate(prompt, dst, size=size, negative_prompt=negative_prompt, seed=seed)
    console.print(f"wrote {dst}")


@app.command("video-gen")
def video_gen_cmd(
    prompt: str = typer.Argument(..., help="Prompt (wrap in quotes)."),
    dst: Path = typer.Argument(..., help="Output video file (.mp4)."),
    provider: str = typer.Option(
        "runway", "--provider",
        help="Backend: 'runway', 'replicate', 'luma', 'kling', or 'veo'.",
    ),
    model: str | None = typer.Option(
        None, "--model",
        help="Provider-specific model (e.g. 'gen3a_turbo', 'minimax/video-01', "
             "'ray-2', 'kling-v2-6', 'veo-3.1-generate-preview').",
    ),
    duration: float = typer.Option(5.0, "--duration", help="Clip length in seconds."),
    aspect: str = typer.Option("16:9", "--aspect", help="Aspect ratio (e.g. '16:9' or '9:16')."),
    seed: int | None = typer.Option(None, "--seed"),
) -> None:
    """Generate a video from a text prompt (submit → poll → download)."""
    from .plugins import get_provider

    try:
        gen = get_provider("video", provider, model=model)
    except KeyError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except ImportError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    console.print(f"submitting {provider} {model or 'default-model'} — this can take minutes…")
    gen.generate(prompt, dst, duration=duration, aspect_ratio=aspect, seed=seed)
    console.print(f"wrote {dst}")


@app.command("voice-clone")
def voice_clone_cmd(
    name: str = typer.Argument(..., help="Human-readable name for the cloned voice."),
    samples: list[Path] = typer.Argument(
        ..., help="One or more audio samples (mp3 / wav / flac).",
    ),
    provider: str = typer.Option(
        "elevenlabs", "--provider", help="Voice-clone backend (currently only 'elevenlabs').",
    ),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    """Upload reference audio and print the resulting voice_id."""
    from .plugins import get_provider

    try:
        cloner = get_provider("voice_clone", provider)
    except KeyError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except ImportError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    except RuntimeError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e

    voice_id = cloner.clone(name, samples, description=description)
    console.print(f"voice_id={voice_id}")


# ---- GUI ----------------------------------------------------------------


@app.command("gui")
def gui_cmd() -> None:
    """Launch the PySide6 desktop GUI."""
    try:
        from .gui.app import run as run_gui
    except ImportError as e:
        console.print(
            f"[red]error:[/red] GUI extras missing ({e}). "
            "Install with `pip install 'comecut-py[gui]'`."
        )
        raise typer.Exit(code=2) from e
    run_gui()


# ---- providers / plugins ------------------------------------------------

providers_app = typer.Typer(
    name="providers",
    help="Inspect built-in and plugin-registered AI providers.",
    no_args_is_help=True,
)
app.add_typer(providers_app, name="providers")


@providers_app.command("list")
def providers_list_cmd(
    group: str | None = typer.Option(
        None, "--group",
        help="Filter to one provider group: 'video', 'image', 'tts', or 'voice_clone'. "
             "Without --group, every group is listed.",
    ),
) -> None:
    """Show every registered provider, including ones from installed plugins."""
    from rich.table import Table

    from .plugins import GROUPS, list_providers

    groups = [group] if group else list(GROUPS)
    for g in groups:
        if g not in GROUPS:
            console.print(
                f"[red]error:[/red] unknown provider group {g!r}; "
                f"expected one of {sorted(GROUPS)}."
            )
            raise typer.Exit(code=2)

    for g in groups:
        infos = list_providers(g)
        table = Table(title=f"{g} providers", show_lines=False)
        table.add_column("name", style="bold")
        table.add_column("source")
        for info in infos:
            table.add_row(info.name, info.source)
        console.print(table)


# ---- project store ------------------------------------------------------

projects_app = typer.Typer(
    name="projects",
    help="Manage saved projects under the on-disk store (~/.local/share/comecut-py/).",
    no_args_is_help=True,
)
app.add_typer(projects_app, name="projects")


@projects_app.command("save")
def projects_save_cmd(
    src: Path = typer.Argument(..., help="Existing project JSON file to import into the store."),
    project_id: str | None = typer.Option(
        None, "--id", help="Reuse an existing project ID (overwrite). Default: new UUID."
    ),
    name: str | None = typer.Option(
        None, "--name", help="Override the project's display name before storing.",
    ),
) -> None:
    """Save a project JSON file into the on-disk store and print its ID."""
    from .core.project import Project
    from .core.store import save_project

    project = Project.from_json(src)
    if name is not None:
        project = project.model_copy(update={"name": name})
    meta = save_project(project, project_id=project_id)
    console.print(f"{meta.project_id}\t{meta.name}\t{meta.path}")


@projects_app.command("list")
def projects_list_cmd() -> None:
    """List every saved project (newest first)."""
    from .core.store import default_store_dir, list_projects

    metas = list_projects()
    if not metas:
        console.print(f"[dim]no projects under {default_store_dir()}[/dim]")
        return
    t = Table()
    t.add_column("ID")
    t.add_column("Name")
    t.add_column("Modified (UTC)")
    t.add_column("Versions", justify="right")
    for m in metas:
        t.add_row(m.project_id, m.name, m.modified_iso, str(m.versions))
    console.print(t)


@projects_app.command("open")
def projects_open_cmd(
    project_id: str = typer.Argument(..., help="Project ID returned by `projects list`."),
    out: Path | None = typer.Option(
        None, "--out", "-o",
        help="Copy the latest project JSON to this path. Default: print the path.",
    ),
) -> None:
    """Print the path to a stored project's current.json (or copy it to ``--out``)."""
    import shutil as _shutil

    from .core.store import _current_path, _project_dir, default_store_dir

    cur = _current_path(_project_dir(default_store_dir(), project_id))
    if not cur.is_file():
        console.print(f"[red]error:[/red] no project with id {project_id!r}")
        raise typer.Exit(code=2)
    if out is None:
        console.print(str(cur))
        return
    _shutil.copy2(cur, out)
    console.print(f"wrote {out}")


@projects_app.command("delete")
def projects_delete_cmd(
    project_id: str = typer.Argument(..., help="Project ID to permanently remove."),
) -> None:
    """Delete a stored project and all its history."""
    from .core.store import delete_project

    try:
        delete_project(project_id)
    except FileNotFoundError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from e
    console.print(f"deleted {project_id}")


@projects_app.command("history")
def projects_history_cmd(
    project_id: str = typer.Argument(..., help="Project ID to inspect."),
) -> None:
    """List historical snapshot files for a stored project (oldest first)."""
    from .core.store import list_versions

    versions = list_versions(project_id)
    if not versions:
        console.print(f"[dim]no history for {project_id}[/dim]")
        return
    for v in versions:
        console.print(str(v))


# ---- batch processing ---------------------------------------------------

batch_app = typer.Typer(
    name="batch",
    help="Run a single operation across many input files in one command.",
    no_args_is_help=True,
)
app.add_typer(batch_app, name="batch")


@batch_app.command("apply-effects")
def batch_apply_effects_cmd(
    inputs: list[Path] = typer.Argument(..., help="Input media files (any number)."),
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o", help="Directory to write outputs into.",
    ),
    suffix: str = typer.Option(
        "_processed",
        "--suffix",
        help="String appended to the input stem before the extension (e.g. 'in.mp4' -> 'in_processed.mp4').",
    ),
    container: str = typer.Option(
        "mp4", "--container", help="Output extension (without dot).",
    ),
    speed: float = typer.Option(1.0, "--speed"),
    reverse: bool = typer.Option(False, "--reverse"),
    blur: float = typer.Option(0.0, "--blur"),
    brightness: float = typer.Option(0.0, "--brightness"),
    contrast: float = typer.Option(1.0, "--contrast"),
    saturation: float = typer.Option(1.0, "--saturation"),
    grayscale: bool = typer.Option(False, "--grayscale"),
    crop: str | None = typer.Option(
        None, "--crop", help="Crop region 'x,y,w,h' in source pixels.",
    ),
    rotate: float = typer.Option(0.0, "--rotate"),
    hflip: bool = typer.Option(False, "--hflip"),
    vflip: bool = typer.Option(False, "--vflip"),
    chromakey_color: str | None = typer.Option(None, "--chromakey"),
    chromakey_similarity: float = typer.Option(0.1, "--chromakey-similarity"),
    chromakey_blend: float = typer.Option(0.0, "--chromakey-blend"),
    fade_in: float = typer.Option(0.0, "--fade-in"),
    fade_out: float = typer.Option(0.0, "--fade-out"),
    pitch: float = typer.Option(0.0, "--pitch"),
    denoise: bool = typer.Option(False, "--denoise"),
    denoise_method: str = typer.Option(
        "afftdn", "--denoise-method",
        help="Noise-reduction algorithm: 'afftdn' or 'rnnoise'.",
    ),
    denoise_model: Path | None = typer.Option(
        None, "--denoise-model",
        help="Path to a .rnnn model file (required when --denoise-method=rnnoise).",
    ),
    normalize: bool = typer.Option(False, "--normalize"),
    keep_going: bool = typer.Option(
        False, "--keep-going",
        help="Continue processing remaining files after a failure (default: abort).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Apply the same effect chain as ``apply-effects`` to each input file."""
    from .core.project import ChromaKey, CropRect

    if denoise_method not in ("afftdn", "rnnoise"):
        console.print(
            f"[red]error:[/red] --denoise-method must be 'afftdn' or 'rnnoise', "
            f"got {denoise_method!r}."
        )
        raise typer.Exit(code=2)
    if denoise and denoise_method == "rnnoise" and denoise_model is None:
        console.print(
            "[red]error:[/red] --denoise-method=rnnoise requires --denoise-model "
            "(path to an .rnnn file)."
        )
        raise typer.Exit(code=2)

    output_dir.mkdir(parents=True, exist_ok=True)

    crop_rect: CropRect | None = None
    if crop:
        try:
            x, y, w, h = (int(p) for p in crop.split(","))
        except ValueError as e:
            console.print(f"[red]error:[/red] --crop expects 'x,y,w,h', got {crop!r}")
            raise typer.Exit(code=2) from e
        crop_rect = CropRect(x=x, y=y, width=w, height=h)

    ck = (
        ChromaKey(
            color=chromakey_color,
            similarity=chromakey_similarity,
            blend=chromakey_blend,
        )
        if chromakey_color
        else None
    )

    successes = 0
    failures = 0
    ext = container.lstrip(".")
    for src in inputs:
        out_point: float | None = None
        has_audio = True
        try:
            info = probe_media(src)
            if info.duration:
                out_point = float(info.duration)
            has_audio = bool(info.has_audio)
        except Exception:
            pass

        project = _build_single_clip_project(
            src,
            out_point=out_point,
            has_audio=has_audio,
            speed=speed,
            reverse=reverse,
            crop_rect=crop_rect,
            chromakey=ck,
            blur=blur,
            brightness=brightness,
            contrast=contrast,
            saturation=saturation,
            grayscale=grayscale,
            rotate=rotate,
            hflip=hflip,
            vflip=vflip,
            fade_in=fade_in,
            fade_out=fade_out,
            pitch=pitch,
            denoise=denoise,
            denoise_method=denoise_method,
            denoise_model=str(denoise_model) if denoise_model else None,
            normalize=normalize,
        )

        dst = output_dir / f"{src.stem}{suffix}.{ext}"
        console.print(f"[dim]→[/dim] {src} -> {dst}")
        try:
            _run(render_project(project, dst), dry_run)
            successes += 1
        except (typer.Exit, FFmpegNotFoundError, RuntimeError) as e:
            failures += 1
            console.print(f"[red]error:[/red] {src}: {e}")
            if not keep_going:
                console.print(f"[red]aborting[/red] after {failures} failure(s).")
                raise

    console.print(f"done: {successes} ok, {failures} failed.")


@batch_app.command("render")
def batch_render_cmd(
    projects: list[Path] = typer.Argument(..., help="Project JSON files to render."),
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o", help="Directory to write rendered outputs into.",
    ),
    preset: str | None = typer.Option(None, "--preset"),
    container: str | None = typer.Option(
        None, "--container",
        help="Override the output extension (default: derived from --preset or 'mp4').",
    ),
    use_proxies: bool = typer.Option(False, "--use-proxies"),
    keep_going: bool = typer.Option(False, "--keep-going"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Render multiple project JSON files in sequence into ``--output-dir``."""
    from .engine import PRESETS

    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_preset = None
    ext = container or "mp4"
    if preset is not None:
        if preset not in PRESETS:
            console.print(
                f"[red]error:[/red] unknown preset {preset!r}. "
                f"Known: {', '.join(sorted(PRESETS))}"
            )
            raise typer.Exit(code=2)
        resolved_preset = PRESETS[preset]
        ext = container or resolved_preset.container

    successes = 0
    failures = 0
    for proj_path in projects:
        project = Project.from_json(proj_path)
        dst = output_dir / f"{proj_path.stem}.{ext}"
        console.print(f"[dim]→[/dim] {proj_path} -> {dst}")
        try:
            cmd = render_project(
                project, dst, preset=resolved_preset, use_proxies=use_proxies,
            )
            _run(cmd, dry_run)
            successes += 1
        except (typer.Exit, FFmpegNotFoundError, RuntimeError) as e:
            failures += 1
            console.print(f"[red]error:[/red] {proj_path}: {e}")
            if not keep_going:
                console.print(f"[red]aborting[/red] after {failures} failure(s).")
                raise

    console.print(f"done: {successes} ok, {failures} failed.")


if __name__ == "__main__":  # pragma: no cover
    app()
