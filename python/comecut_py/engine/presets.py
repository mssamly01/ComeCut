"""Named export presets for :func:`render_project`.

Each preset describes the *output* — codec, bitrate/CRF, container, audio
format, and (optionally) a canvas override. Presets are applied in
``render_project`` after the composition graph is built: the video signal
is scaled + padded to the preset's target resolution, and the output args
(``-c:v``/``-c:a``/``-b:v``/``-crf``/...) are swapped in to replace the
default libx264/CRF-20/AAC pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExportPreset:
    """A named export target.

    Attributes
    ----------
    name : str
        Key under which the preset is registered in :data:`PRESETS`.
    width, height : int or None
        Output resolution. ``None`` means "inherit project canvas".
    fps : float or None
        Frame rate to force on the output. ``None`` inherits the project.
    vcodec : str
        ffmpeg video codec ID (``libx264``, ``libvpx-vp9``, ``gif``, ...).
    acodec : str or None
        ffmpeg audio codec ID, or ``None`` for video-only containers like
        GIF.
    crf : int or None
        CRF for quality-targeted encodes. Mutually exclusive with
        ``video_bitrate`` in practice; CRF is preferred for single-pass
        and ``video_bitrate`` for two-pass.
    video_bitrate : str or None
        Target video bitrate (e.g. ``"8M"``) — used when the caller opts
        into two-pass encoding.
    audio_bitrate : str or None
        Audio bitrate for ``acodec`` (e.g. ``"192k"``).
    x264_preset : str or None
        x264 ``-preset`` argument (``ultrafast``...``veryslow``).
    profile : str or None
        Codec profile (``high``, ``main``, ...).
    pix_fmt : str
        Output pixel format. ``yuv420p`` for broad compatibility.
    container : str
        File extension hint — callers use this to default ``dst`` if no
        suffix is provided.
    extra_args : tuple[str, ...]
        Any additional ffmpeg output args appended verbatim (e.g.
        ``("-movflags", "+faststart")``).
    """

    name: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    vcodec: str = "libx264"
    acodec: str | None = "aac"
    crf: int | None = 20
    video_bitrate: str | None = None
    audio_bitrate: str | None = "192k"
    x264_preset: str | None = "medium"
    profile: str | None = None
    pix_fmt: str = "yuv420p"
    container: str = "mp4"
    extra_args: tuple[str, ...] = field(default_factory=tuple)


PRESETS: dict[str, ExportPreset] = {
    # YouTube recommends up to 12 Mb/s 1080p30, CRF 18 comfortably beats
    # that visually at modest bitrates. Profile High + faststart lets the
    # browser start playing before the whole file lands.
    "youtube-1080p": ExportPreset(
        name="youtube-1080p",
        width=1920, height=1080, fps=30.0,
        crf=18, x264_preset="slow", profile="high",
        audio_bitrate="192k",
        extra_args=("-movflags", "+faststart"),
    ),
    "youtube-4k": ExportPreset(
        name="youtube-4k",
        width=3840, height=2160, fps=30.0,
        crf=18, x264_preset="slow", profile="high",
        audio_bitrate="192k",
        extra_args=("-movflags", "+faststart"),
    ),
    # Instagram Reels + TikTok: 9:16 1080x1920, ~30 fps. Same encoder
    # settings — the platforms re-encode on upload anyway.
    "reels": ExportPreset(
        name="reels",
        width=1080, height=1920, fps=30.0,
        crf=20, x264_preset="medium", profile="high",
        audio_bitrate="128k",
        extra_args=("-movflags", "+faststart"),
    ),
    "tiktok": ExportPreset(
        name="tiktok",
        width=1080, height=1920, fps=30.0,
        crf=20, x264_preset="medium", profile="high",
        audio_bitrate="128k",
        extra_args=("-movflags", "+faststart"),
    ),
    # Twitter/X: max 140 s, 512 MB, 1280x720 30fps for best compatibility.
    # Main profile + AAC LC is what the uploader accepts without
    # transcoding.
    "twitter": ExportPreset(
        name="twitter",
        width=1280, height=720, fps=30.0,
        crf=23, x264_preset="medium", profile="main",
        audio_bitrate="128k",
        extra_args=("-movflags", "+faststart"),
    ),
    # GIF: no audio, palettegen is applied separately in the renderer
    # path; this preset just carries size + fps + container.
    "gif": ExportPreset(
        name="gif",
        width=480, height=None, fps=15.0,
        vcodec="gif", acodec=None,
        crf=None, x264_preset=None, profile=None,
        audio_bitrate=None,
        pix_fmt="pal8",
        container="gif",
    ),
    # WebM: VP9 + Opus. CRF 30 is VP9's sweet spot for "near-lossless".
    "webm": ExportPreset(
        name="webm",
        width=1920, height=1080, fps=30.0,
        vcodec="libvpx-vp9", acodec="libopus",
        crf=30, x264_preset=None, profile=None,
        audio_bitrate="96k",
        pix_fmt="yuv420p",
        container="webm",
    ),
}


def preset_output_args(
    preset: ExportPreset,
    *,
    pass_number: int | None = None,
    pass_log_prefix: str | None = None,
) -> list[str]:
    """Build the ``-c:v``/``-c:a``/``-b:v``/``-crf``/... tail of args for a preset.

    ``pass_number`` and ``pass_log_prefix`` wire in ffmpeg's two-pass log
    file; pass ``1`` for the analyse pass and ``2`` for the encode pass.
    """
    args: list[str] = ["-c:v", preset.vcodec]
    if preset.x264_preset:
        args += ["-preset", preset.x264_preset]
    if preset.profile:
        args += ["-profile:v", preset.profile]
    # Two-pass requires a bitrate target; CRF is ignored in that mode.
    if pass_number is not None and preset.video_bitrate:
        args += ["-b:v", preset.video_bitrate]
        args += ["-pass", str(pass_number)]
        if pass_log_prefix:
            args += ["-passlogfile", pass_log_prefix]
    elif preset.crf is not None:
        args += ["-crf", str(preset.crf)]
    elif preset.video_bitrate:
        args += ["-b:v", preset.video_bitrate]
    if preset.pix_fmt:
        args += ["-pix_fmt", preset.pix_fmt]
    if preset.fps is not None:
        args += ["-r", str(preset.fps)]
    if preset.acodec:
        args += ["-c:a", preset.acodec]
        if preset.audio_bitrate:
            args += ["-b:a", preset.audio_bitrate]
    else:
        # No audio codec → strip audio entirely from the output.
        args += ["-an"]
    args.extend(preset.extra_args)
    return args


__all__ = ["PRESETS", "ExportPreset", "preset_output_args"]
