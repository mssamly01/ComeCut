"""Ken Burns effect — animated zoom and pan over a still image.

Wraps ffmpeg's ``zoompan`` filter so a single image is rendered into a video
clip of the requested duration with a linear zoom interpolation from
``start_zoom`` to ``end_zoom``. Optional focal-point arguments let the zoom
also translate across the frame (hence "pan").
"""

from __future__ import annotations

from pathlib import Path

from ..core.ffmpeg_cmd import FFmpegCommand


def zoompan_image(
    src: str | Path,
    dst: str | Path,
    *,
    duration: float,
    start_zoom: float = 1.0,
    end_zoom: float = 1.2,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    focus_x: str = "iw/2-(iw/zoom/2)",
    focus_y: str = "ih/2-(ih/zoom/2)",
) -> FFmpegCommand:
    """Build a ``zoompan`` command that turns ``src`` into a ``duration``-s clip.

    ``focus_x`` / ``focus_y`` are ffmpeg expressions. The defaults keep the
    zoom anchored at the image centre; passing e.g. ``focus_x='0'`` pans in
    from the left edge.

    The output is a silent MP4; compose it with a project render or concat it
    with audio elsewhere if you need sound.
    """
    if duration <= 0:
        raise ValueError(f"duration must be > 0 (got {duration})")
    if start_zoom <= 0 or end_zoom <= 0:
        raise ValueError("zooms must be > 0")

    nframes = max(1, round(duration * fps))
    # Linear interpolation: z(n) = start + (end-start) * n/(nframes-1).
    # ``on`` is the zoompan filter's built-in "output frame index" variable.
    if nframes == 1:
        z_expr = f"{start_zoom}"
    else:
        z_expr = (
            f"{start_zoom}+({end_zoom}-{start_zoom})*on/{nframes - 1}"
        )

    cmd = FFmpegCommand()
    # ``-loop 1`` decodes the still image as a looping video stream;
    # ``-t duration`` on the *output* side clips the result to the intended
    # length. Pre-upscaling the input by 4x keeps the zoompan output sharp
    # (zoompan samples pixel-accurate; without the upscale the output looks
    # jaggy at zoom > 1.0).
    #
    # Note: ``d=1`` — not ``d=nframes`` — because zoompan's ``d`` is "output
    # frames PER input frame" and ``-loop 1`` feeds one input frame per
    # second by default. With ``d=1`` the zoom interpolation drives one
    # output frame per input frame and the total frame count is controlled
    # by the output-side ``-t``.
    cmd.add_input(str(src), "-loop", "1", "-framerate", f"{fps}")
    cmd.set_filter_complex(
        f"[0:v]scale=iw*4:ih*4,"
        f"zoompan=z='{z_expr}':x='{focus_x}':y='{focus_y}':"
        f"d=1:s={width}x{height}:fps={fps}[vo]"
    )
    cmd.map("[vo]")
    cmd.out(str(dst), "-t", f"{duration}", "-r", f"{fps}", "-pix_fmt", "yuv420p")
    return cmd


__all__ = ["zoompan_image"]
