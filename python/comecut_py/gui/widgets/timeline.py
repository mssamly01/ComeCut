"""Bottom panel Ã¢â‚¬â€ a ``QGraphicsView``-based timeline.
"""

from __future__ import annotations

import re
import math
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QByteArray, QPoint, QPointF, QRectF, QSize, Qt, QSignalBlocker, QTimer, Signal  # type: ignore
from PySide6.QtGui import (  # type: ignore
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPalette,
    QPolygonF,
    QPixmap,
)
from PySide6.QtWidgets import (  # type: ignore
    QFrame,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QMenu,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtSvg import QSvgRenderer  # type: ignore
except Exception:  # pragma: no cover - optional dependency on some runtimes
    QSvgRenderer = None

from ...core.audio_mixer import (
    AUDIO_ROLE_LABELS,
    set_track_role,
    set_track_volume,
    track_output_gain,
)
from ...core.ffmpeg_cmd import get_video_duration
from ...core.project import Clip, Project, Track
from ...core.transitions import (
    COMMON_TRANSITION_KINDS,
    DEFAULT_TRANSITION_DURATION,
    adjacent_pair_from_clips,
    find_transition,
    normalize_track_transitions,
    reindex_transitions_after_clip_delete,
    remove_track_transition,
    set_track_transition,
    transition_duration_limit,
)
from ..preview_timeline import clip_fade_multiplier_at_local_time

_RESOLVED_PATH_CACHE: dict[str, str] = {}
_IS_FILE_CACHE: dict[str, bool] = {}


def _resolved_source_str(source: str | Path) -> str:
    raw = str(source or "")
    if not raw:
        return ""
    cached = _RESOLVED_PATH_CACHE.get(raw)
    if cached is not None:
        return cached
    try:
        resolved = str(Path(raw).resolve())
    except Exception:
        resolved = raw
    _RESOLVED_PATH_CACHE[raw] = resolved
    return resolved


def _cached_is_file(source: str | Path) -> bool:
    raw = str(source or "")
    if not raw:
        return False
    cached = _IS_FILE_CACHE.get(raw)
    if cached is not None:
        return cached
    try:
        is_file = Path(raw).is_file()
    except Exception:
        is_file = False
    _IS_FILE_CACHE[raw] = is_file
    return is_file


BASE_PIXELS_PER_SECOND = 50.0
PIXELS_PER_SECOND = BASE_PIXELS_PER_SECOND
TRACK_HEIGHT = 64.0
LANE_GAP = 8.0
RULER_HEIGHT = 30.0
TRACK_EDGE_PADDING = 24.0
TRACK_HEADER_WIDTH = 128
TIMELINE_BG_COLOR = "#111318"
MAIN_TRACK_HEIGHT_FACTOR = 1.1
AUDIO_TRACK_HEIGHT_FACTOR = 0.7
TEXT_TRACK_HEIGHT_FACTOR = 0.35
MEDIA_MIME_TYPE = "application/x-comecut-media-path"
ZOOM_MIN = 1
ZOOM_MAX = 400
ICON_NORMAL = "#8c93a0"
ICON_ACTIVE = "#22d3c5"
SNAP_TOLERANCE_PX = 5.0
SCRUB_SEEK_INTERVAL_MS = 120
SCRUB_PLAYHEAD_REFRESH_INTERVAL_MS = 80
LONG_MEDIA_CACHE_THRESHOLD_SECONDS = 30.0
VISIBLE_CACHE_PREFETCH_VIEWPORTS = 1.0
MEDIA_CACHE_IDLE_DELAY_MS = 250
MEDIA_CACHE_PROGRESSIVE_DELAY_MS = 350
MEDIA_CACHE_PROGRESSIVE_BATCH_SIZE = 4
MEDIA_CACHE_PROGRESSIVE_WAVE_RANGE_SECONDS = 300.0
MAX_PROGRESSIVE_WAVEFORM_INFLIGHT = 4
MAX_FILMSTRIP_CHUNKS_INFLIGHT = 64
MAX_FILMSTRIP_CHUNKS_INFLIGHT_PER_SOURCE = 8
MAX_THUMB_PATH_CACHE_ITEMS = 512
MAX_STRIP_PIXMAP_CACHE_ITEMS = 128
MAX_CHUNK_PIXMAP_CACHE_ITEMS = 256
MAX_WAVEFORM_PEAKS_CACHE_ITEMS = 4096
MAX_WAVEFORM_RANGE_CACHE_ITEMS = 8192
SCENE_INDEX_CLIP_THRESHOLD = 800
FILMSTRIP_FRAMES = 24
FILMSTRIP_TILE_WIDTH = 120
FILMSTRIP_HEIGHT_BUCKET = 16
TIMELINE_USE_TILED_FILMSTRIP = True
FILMSTRIP_TILE_W = 96
FILMSTRIP_TILE_H = 54
FILMSTRIP_TILES_PER_CHUNK = 60
FILMSTRIP_DENSE_PX_PER_SECOND = 48.0
FILMSTRIP_SUBSECOND_PX_PER_SECOND = 112.0
FILMSTRIP_ULTRA_DENSE_PX_PER_SECOND = 224.0
FILMSTRIP_TARGET_THUMB_SPACING_PX = 56.0
FILMSTRIP_SAMPLE_STEPS_SECONDS = (
    1,
    2,
    3,
    5,
    10,
    15,
    30,
    60,
    120,
    300,
    600,
    900,
    1800,
)
WAVEFORM_PEAKS_FAST = 256
WAVEFORM_PEAKS_RESOLUTION = 2048
WAVEFORM_UPGRADE_DELAY_MS = 200
WAVEFORM_USE_POLYGON = True
TIMELINE_USE_OPENGL_VIEWPORT = False
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
SUBTITLE_EXTS = {".srt", ".vtt", ".lrc", ".ass", ".ssa", ".txt"}
TABLE_CAPTION_FONT_PT = 10
TIMELINE_CLIP_LABEL_FONT_PT = 8
MEDIA_CLIP_HEADER_HEIGHT = 20.0
MEDIA_CLIP_WAVEFORM_HEIGHT = 24.0
MEDIA_CLIP_HEADER_RATIO = 0.30
MEDIA_CLIP_FILMSTRIP_RATIO = 0.40
MEDIA_CLIP_WAVEFORM_RATIO = 0.30
VIDEO_CLIP_BASE_COLOR = "#0e5f6a"
VIDEO_CLIP_HEADER_COLOR = QColor(7, 85, 95, 210)
VIDEO_CLIP_WAVE_BG = QColor(5, 96, 99, 225)
VIDEO_CLIP_WAVE_BAR = "#16c7c9"
AUDIO_CLIP_BASE_COLOR = "#1f5ea8"
AUDIO_CLIP_HEADER_COLOR = QColor(23, 77, 145, 215)
AUDIO_CLIP_WAVE_BG = QColor(16, 60, 118, 225)
AUDIO_CLIP_WAVE_BAR = "#21b6ff"
VOLUME_LINE_DB_SPAN = 24.0
VOLUME_LINE_HIT_PX = 7.0
FADE_HANDLE_RADIUS_PX = 3.6
FADE_HANDLE_HIT_PX = 8.0
FADE_HANDLE_AUDIO_TOP_OFFSET_PX = 7.0
TRIM_HANDLE_HIT_PX = 7.0
MIN_TRIM_TIMELINE_DURATION_SECONDS = 1.0 / 30.0
TRANSITION_KIND_LABELS = {
    "fade": "Fade",
    "dissolve": "Dissolve",
    "wipeleft": "Wipe Left",
    "wiperight": "Wipe Right",
    "slideleft": "Slide Left",
    "slideright": "Slide Right",
}

_SYMBOL_RE = re.compile(
    r'<symbol\s+id="(?P<id>[^"]+)"(?P<attrs>[^>]*)>(?P<body>.*?)</symbol>',
    re.DOTALL,
)
_SYMBOL_CACHE: dict[str, tuple[str, str]] | None = None
_OPENGL_ICON_PATH_D = (
    "M0 38.413h36.121v144.713H20.416v-13.012h-6.418v-37.155h6.418v-27.013h-6.418V68.792h6.418V54.118H0zm233.039 49.274V169.6c0 6.938-5.624 12.566-12.563 12.566h-.013v12.46h-80.221v-12.46h-7.612v12.46H52.409v-12.46h-7.034V75.125h175.101c6.939 0 12.563 5.624 12.563 12.562M62.52 181.542h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm2.466-52.737h-9.988v3.925h5.559v1.943q-3.226 3.77-7.229 3.77-1.75 0-3.245-.72a8 8 0 0 1-2.584-1.962q-1.09-1.244-1.711-2.935-.621-1.69-.621-3.634 0-1.866.563-3.537a9.6 9.6 0 0 1 1.594-2.954 7.5 7.5 0 0 1 2.488-2.021q1.457-.738 3.206-.738 2.214 0 4.101 1.088 1.884 1.089 2.934 3.148l4.004-2.954q-1.4-2.76-4.179-4.392t-6.665-1.633q-2.877 0-5.324 1.107a13.6 13.6 0 0 0-4.256 2.993 13.9 13.9 0 0 0-2.838 4.392q-1.03 2.507-1.029 5.344 0 2.993 1.029 5.577 1.03 2.586 2.799 4.489a12.9 12.9 0 0 0 4.158 2.993q2.39 1.089 5.111 1.088 4.391 0 7.695-3.304v3.109h4.43v-14.182zm5.534 52.737h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm1.591-66.146H93.572v27.595h5.363v-11.427h10.961v-4.353h-10.96v-7.112h13.176v-4.703zm6.409 66.146h-4v9h4zm8 0h-4v9h4zm1.876-52.154 9.833-13.992h-5.791l-6.84 10.261-6.88-10.261h-5.829l9.833 13.992-9.522 13.602h5.83l6.568-9.872 6.529 9.872h5.791zm21.958 52.154h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm8 0h-4v9h4zm3.373-50.847c0-19.328-15.67-35-35-35s-35 15.672-35 35 15.67 35 35 35 35-15.673 35-35m-16.152.557c.861-.464 1.723-.924 2.57-1.381l2.471-1.408c.804-.46 1.583-.902 2.313-1.36q.084-.05.167-.104a26.58 26.58 0 0 0-9.268-16.713c-.068.092-.14.192-.212.288q-.462.637-1.028 1.413l-1.296 1.679c-.452.6-.964 1.22-1.493 1.864-.53.647-1.078 1.314-1.634 1.996a663 663 0 0 0-1.761 2.023q-.003 0-.007.007l.125-2.003c.057-.957.072-1.93.109-2.903l.093-2.914.012-2.847c.006-.927.01-1.824-.021-2.684 0-.07-.003-.13-.005-.198a26.5 26.5 0 0 0-9.984-1.941c-3.208 0-6.281.567-9.13 1.604l.15.337.71 1.6c.249.606.52 1.263.805 1.96.294.692.576 1.444.868 2.224l.908 2.411.873 2.538.005.012-1.675-1.112c-.798-.526-1.631-1.027-2.458-1.547-.83-.513-1.661-1.029-2.478-1.536-.838-.487-1.661-.969-2.459-1.434a69 69 0 0 0-2.333-1.323c-.059-.032-.112-.06-.17-.094-5.087 3.977-8.688 9.76-9.843 16.386q.174.019.356.035l1.739.187c.65.086 1.354.182 2.1.284.745.089 1.538.224 2.361.36.824.137 1.678.275 2.543.419l2.632.513h.012l-1.799.896c-.855.428-1.703.899-2.567 1.354-.861.463-1.723.923-2.57 1.38-.842.479-1.671.951-2.471 1.411a65 65 0 0 0-2.481 1.46 26.58 26.58 0 0 0 9.269 16.714l.212-.289 1.028-1.413 1.296-1.677c.452-.602.964-1.222 1.493-1.864l1.634-1.994c.581-.665 1.17-1.345 1.761-2.023l.007-.009-.124 2.003c-.058.957-.074 1.928-.11 2.903l-.094 2.914-.011 2.846a66 66 0 0 0 .02 2.684c.001.069.004.131.004.197a26.5 26.5 0 0 0 9.985 1.942c3.208 0 6.281-.566 9.129-1.605-.049-.108-.097-.223-.149-.337l-.71-1.598-.804-1.959a56 56 0 0 1-.868-2.225c-.295-.784-.601-1.593-.908-2.413l-.874-2.536-.004-.013c.55.368 1.106.735 1.674 1.113.797.524 1.631 1.025 2.458 1.545l2.478 1.538c.838.487 1.661.969 2.458 1.434.8.465 1.573.918 2.333 1.321.06.034.113.062.17.095 5.088-3.978 8.688-9.758 9.844-16.385a12 12 0 0 0-.356-.036l-1.739-.185c-.65-.088-1.355-.183-2.1-.287-.746-.087-1.538-.221-2.361-.357-.824-.137-1.678-.276-2.543-.42l-2.632-.513h-.012l1.798-.898c.856-.425 1.705-.898 2.569-1.352"
)

_TRACK_TYPE_ICON_SVG = {
    "video": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        '<path d="M0 3v14h20V3zm1 1h18v12H1zm1 1v1h1V5zm15 0v1h1V5zM7 6.117v7.766l.758-.453L13.473 10zm1 1.768L11.525 10 8 12.115zM2 8v1h1V8zm15 0v1h1V8zM2 11v1h1v-1zm15 0v1h1v-1zM2 14v1h1v-1zm15 0v1h1v-1z" fill="{color}" stroke="none"/>'
        "</svg>"
    ),
    "text": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -1 20 20">'
        '<g fill="none" stroke="{color}" stroke-linecap="round" stroke-linejoin="round" stroke-width="2">'
        '<path d="M19 9V7h-8v2"/>'
        '<path d="M1 3V1h10v2m4 4v10m-2 0h4M6 1v16m-2 0h4"/>'
        "</g></svg>"
    ),
    "audio": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        '<path d="M9.772 4.28c.56-.144 1.097.246 1.206.814.1.517-.263 1.004-.771 1.14A7 7 0 1 0 19 12.9c.009-.5.4-.945.895-1 .603-.067 1.112.371 1.106.977L21 13q0 .16-.006.32a1 1 0 0 1 0 .164l-.008.122a9 9 0 0 1-9.172 8.392A9 9 0 0 1 9.772 4.28" fill="{color}"/>'
        '<path d="M15.93 13.753a4.001 4.001 0 1 1-6.758-3.581A4 4 0 0 1 12 9c.75 0 1.3.16 2 .53 0 0 .15.09.25.17-.1-.35-.228-1.296-.25-1.7a59 59 0 0 1-.025-2.035V2.96c0-.52.432-.94.965-.94q.155 0 .305.048l4.572 1.689c.446.145.597.23.745.353q.222.183.33.446c.073.176.108.342.108.801v1.16c0 .518-.443.94-.975.94a1 1 0 0 1-.305-.049l-1.379-.447-.151-.05c-.437-.14-.618-.2-.788-.26a6 6 0 0 1-.514-.207 4 4 0 0 1-.213-.107c-.098-.05-.237-.124-.521-.263L16 6l.011 7q0 .383-.082.753z" fill="{color}"/>'
        "</svg>"
    ),
}


def _load_timeline_symbols() -> dict[str, tuple[str, str]]:
    global _SYMBOL_CACHE
    if _SYMBOL_CACHE is not None:
        return _SYMBOL_CACHE
    symbols: dict[str, tuple[str, str]] = {}
    icon_sheet = Path(__file__).resolve().parents[4] / "index.html"
    try:
        raw = icon_sheet.read_text(encoding="utf-8")
    except OSError:
        _SYMBOL_CACHE = symbols
        return symbols
    for m in _SYMBOL_RE.finditer(raw):
        symbol_id = m.group("id")
        if symbol_id.startswith("icon-editor-timeline-"):
            symbols[symbol_id] = (m.group("attrs"), m.group("body"))
    _SYMBOL_CACHE = symbols
    return symbols


def _timeline_icon(symbol_id: str, color: str = ICON_NORMAL, size: int = 16) -> QIcon:
    if QSvgRenderer is None:
        return QIcon()
    symbol = _load_timeline_symbols().get(symbol_id)
    if symbol is None:
        return QIcon()
    attrs, body = symbol
    # Keep the symbol geometry and reuse exact SVG paths from the HTML sprite.
    svg = f'<svg xmlns="http://www.w3.org/2000/svg"{attrs}>{body}</svg>'.replace(
        "currentColor", color
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def _clip_timeline_end(clip: Clip) -> float | None:
    dur = clip.timeline_duration
    if dur is None:
        return None
    return float(clip.start) + float(dur)


def ripple_shift_later_clips(
    track: Track,
    *,
    anchor_seconds: float,
    delta_seconds: float,
    exclude_clip: Clip | None = None,
) -> bool:
    """Shift clips at/after an edit point by ``delta_seconds`` on one track."""
    if abs(float(delta_seconds)) <= 1e-6:
        return False
    changed = False
    anchor = float(anchor_seconds)
    for clip in track.clips:
        if exclude_clip is not None and clip is exclude_clip:
            continue
        if float(clip.start) + 1e-6 < anchor:
            continue
        new_start = max(0.0, float(clip.start) + float(delta_seconds))
        if abs(new_start - float(clip.start)) > 1e-6:
            clip.start = new_start
            changed = True
    if changed:
        track.clips.sort(key=lambda c: c.start)
    return changed


def trim_clip_edge(
    track: Track,
    clip: Clip,
    edge: str,
    target_seconds: float,
    *,
    ripple: bool = False,
    min_duration_seconds: float = MIN_TRIM_TIMELINE_DURATION_SECONDS,
) -> tuple[bool, float]:
    """Trim one clip edge and optionally ripple clips after the right edge.

    Returns ``(changed, ripple_delta_seconds)``. The ripple delta is non-zero
    only for right-edge ripple trim so callers/tests can inspect the edit.
    """
    if clip not in track.clips:
        return False, 0.0
    edge_n = (edge or "").strip().lower()
    if edge_n not in {"left", "right"}:
        return False, 0.0
    if clip.out_point is None:
        return False, 0.0

    speed = max(1e-6, float(clip.speed or 1.0))
    original_start = float(clip.start)
    original_in = float(clip.in_point)
    original_out = float(clip.out_point)
    original_duration = float(clip.timeline_duration or 0.0)
    if original_duration <= 1e-6 or original_out <= original_in:
        return False, 0.0

    min_duration = max(1e-6, float(min_duration_seconds))
    min_source_span = min_duration * speed
    original_end = original_start + original_duration
    target = max(0.0, float(target_seconds))
    changed = False
    ripple_delta = 0.0

    if edge_n == "left":
        min_start = max(0.0, original_start - (original_in / speed))
        max_start = original_end - min_duration
        if max_start < min_start:
            max_start = min_start
        new_start = max(min_start, min(max_start, target))
        new_in = original_in + ((new_start - original_start) * speed)
        new_in = max(0.0, min(original_out - min_source_span, new_in))
        if abs(new_start - original_start) > 1e-6:
            clip.start = new_start
            changed = True
        if abs(new_in - original_in) > 1e-6:
            clip.in_point = new_in
            changed = True
    else:
        min_end = original_start + min_duration
        new_end = max(min_end, target)
        new_out = original_in + ((new_end - original_start) * speed)
        if new_out < original_in + min_source_span:
            new_out = original_in + min_source_span
            new_end = original_start + min_duration
        if abs(new_out - original_out) > 1e-6:
            clip.out_point = new_out
            changed = True
            if ripple:
                ripple_delta = new_end - original_end
                ripple_shift_later_clips(
                    track,
                    anchor_seconds=original_end,
                    delta_seconds=ripple_delta,
                    exclude_clip=clip,
                )

    if changed:
        track.clips.sort(key=lambda c: c.start)
    return changed, ripple_delta


def ripple_delete_clips_from_track(track: Track, selected_ids: set[int]) -> bool:
    """Delete selected clips and close the timeline gap on one track."""
    if not selected_ids:
        return False
    old_clips = list(track.clips)
    old_transitions = list(track.transitions)
    removed_indices = {
        idx for idx, clip in enumerate(old_clips) if id(clip) in selected_ids
    }
    removed = [clip for clip in track.clips if id(clip) in selected_ids]
    if not removed:
        return False
    removed.sort(key=lambda c: float(c.start))
    remaining = [clip for clip in track.clips if id(clip) not in selected_ids]
    for clip in remaining:
        shift = 0.0
        clip_start = float(clip.start)
        for deleted in removed:
            if clip_start + 1e-6 >= float(deleted.start):
                shift += float(deleted.timeline_duration or 0.0)
        if shift > 0.0:
            clip.start = max(0.0, clip_start - shift)
    track.clips = sorted(remaining, key=lambda c: c.start)
    reindex_transitions_after_clip_delete(
        track,
        removed_indices,
        old_transitions,
        old_clip_count=len(old_clips),
    )
    return True


def timeline_snap_times(project: Project, *, exclude_clip: Clip | None = None) -> list[float]:
    """Return clip edge + beat marker snap anchors in timeline seconds."""
    times: set[float] = {0.0}
    for track in project.tracks:
        for clip in track.clips:
            if exclude_clip is not None and clip is exclude_clip:
                continue
            dur = clip.timeline_duration
            if dur is None or dur <= 0.0:
                continue
            start = max(0.0, float(clip.start))
            times.add(round(start, 6))
            times.add(round(start + float(dur), 6))
    for marker in getattr(project, "beat_markers", []):
        try:
            time_s = float(marker.time)
        except Exception:
            continue
        if time_s >= 0.0:
            times.add(round(time_s, 6))
    return sorted(times)


def _custom_hover_scrub_icon(active: bool = False, size: int = 24) -> QIcon:
    """Programmatic Hover Scrub icon from editor_app.py."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Use comecut colors (Neon for active, Dim for inactive)
    color = QColor(ICON_ACTIVE if active else ICON_NORMAL)

    # Scale coordinates from 24x24 base
    s = size / 24.0

    # 1. Playhead vertical line
    painter.setPen(QPen(color, 2 * s))
    painter.drawLine(int(10 * s), int(4 * s), int(10 * s), int(20 * s))

    # 2. Bracket (left side)
    painter.setPen(QPen(color, 2 * s))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(
        [
            QPointF(8 * s, 8 * s),
            QPointF(4 * s, 8 * s),
            QPointF(4 * s, 16 * s),
            QPointF(8 * s, 16 * s),
        ]
    )

    # 3. Mouse cursor (right side)
    path = QPainterPath()
    path.moveTo(14 * s, 10 * s)
    path.lineTo(14 * s, 20 * s)
    path.lineTo(16 * s, 17 * s)
    path.lineTo(19 * s, 21 * s)
    path.lineTo(21 * s, 20 * s)
    path.lineTo(18 * s, 16 * s)
    path.lineTo(22 * s, 16 * s)
    path.closeSubpath()

    painter.setBrush(QColor("#FFFFFF"))
    painter.setPen(QPen(color, 1 * s))
    painter.drawPath(path)

    painter.end()
    return QIcon(pixmap)


def _custom_opengl_icon(active: bool = False, size: int = 18) -> QIcon:
    """Dedicated OpenGL toggle icon provided by user, tinted to app state."""
    if QSvgRenderer is None:
        return QIcon()
    color = ICON_ACTIVE if active else ICON_NORMAL
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 233.039 233.039">'
        '<path fill="none" d="M0 0h233.039v233.039H0z"/>'
        f'<path fill="{color}" d="{_OPENGL_ICON_PATH_D}"/>'
        "</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def _custom_track_type_icon(kind: str, color: str = "#4a505c", size: int = 14) -> QIcon:
    """Render custom track-type icon (video/text/audio) from inline SVG."""
    if QSvgRenderer is None:
        return QIcon()
    key = (kind or "video").strip().lower()
    svg_tpl = _TRACK_TYPE_ICON_SVG.get(key, _TRACK_TYPE_ICON_SVG["video"])
    svg = svg_tpl.format(color=color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def _format_timestamp(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_ruler_label(seconds: float, major_tick_seconds: float) -> str:
    if major_tick_seconds < 1.0:
        total_tenths = int(round(seconds * 10))
        mins = total_tenths // 600
        sec_tenths = total_tenths % 600
        sec = sec_tenths // 10
        tenth = sec_tenths % 10
        return f"{mins:02d}:{sec:02d}.{tenth}"
    return _format_timestamp(seconds)


def _downsample_peaks(peaks: list[float], target: int) -> list[float]:
    """Max-pool waveform peaks to the number of bars needed for the current zoom."""
    n = len(peaks)
    if target >= n or n == 0:
        return list(peaks)
    target = max(1, int(target))
    bucket = n / float(target)
    out: list[float] = []
    for i in range(target):
        start = int(i * bucket)
        end = int((i + 1) * bucket)
        if end <= start:
            end = start + 1
        if end > n:
            end = n
        out.append(max(peaks[start:end]))
    return out


def waveform_peaks_for_clip_source_range(
    peaks: list[float],
    clip: Clip,
    source_duration_seconds: float,
) -> list[float]:
    """Return only the waveform peaks covered by the clip's source in/out range."""
    if not peaks:
        return peaks

    try:
        source_duration = float(source_duration_seconds)
    except Exception:
        source_duration = 0.0
    if source_duration <= 1e-6:
        return list(reversed(peaks)) if bool(getattr(clip, "reverse", False)) else list(peaks)

    try:
        in_point = max(0.0, float(getattr(clip, "in_point", 0.0) or 0.0))
    except Exception:
        in_point = 0.0
    try:
        raw_out = getattr(clip, "out_point", None)
        out_point = float(raw_out) if raw_out is not None else source_duration
    except Exception:
        out_point = source_duration

    out_point = max(in_point, min(source_duration, out_point))
    in_point = min(in_point, source_duration)
    if out_point <= in_point + 1e-6:
        return []

    n = len(peaks)
    start_idx = int(math.floor((in_point / source_duration) * n))
    end_idx = int(math.ceil((out_point / source_duration) * n))
    start_idx = max(0, min(n - 1, start_idx))
    end_idx = max(start_idx + 1, min(n, end_idx))
    sliced = list(peaks[start_idx:end_idx])
    if bool(getattr(clip, "reverse", False)):
        sliced.reverse()
    return sliced


def _filmstrip_sample_step_seconds(px_per_src_sec: float) -> int:
    """Choose how many source seconds one visible thumbnail should represent."""
    if px_per_src_sec >= FILMSTRIP_DENSE_PX_PER_SECOND:
        return 1
    raw_step = FILMSTRIP_TARGET_THUMB_SPACING_PX / max(1e-6, float(px_per_src_sec))
    for step in FILMSTRIP_SAMPLE_STEPS_SECONDS:
        if step >= raw_step:
            return int(step)
    return max(1, int(raw_step + 0.999))


def _filmstrip_samples_per_second(px_per_src_sec: float) -> int:
    """Choose denser chunk samples once one-second tiles would be stretched."""
    px = max(0.0, float(px_per_src_sec))
    if px >= FILMSTRIP_ULTRA_DENSE_PX_PER_SECOND:
        return 4
    if px >= FILMSTRIP_SUBSECOND_PX_PER_SECOND:
        return 2
    return 1


from ...engine.thumbnails import (
    extract_filmstrip_chunk,
    render_filmstrip_png,
)
from ...engine.waveform import extract_waveform_peaks, extract_waveform_peaks_range


def _format_clip_duration_smpte(seconds: float, fps: float = 24.0) -> str:
    """Format clip duration as HH:MM:SS:FF."""
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    frames = int(round((s - int(s)) * fps)) % max(1, int(fps))
    return f"{h:02d}:{m:02d}:{sec:02d}:{frames:02d}"


def _clip_section_heights(total_height: float) -> tuple[float, float, float]:
    """Split clip height into header / filmstrip / waveform by 30/40/30 ratio."""
    h = max(0.0, float(total_height))
    if h <= 0.0:
        return 0.0, 0.0, 0.0
    header_h = h * MEDIA_CLIP_HEADER_RATIO
    filmstrip_h = h * MEDIA_CLIP_FILMSTRIP_RATIO
    waveform_h = max(0.0, h - header_h - filmstrip_h)
    return header_h, filmstrip_h, waveform_h


def _linear_to_db(gain: float) -> float:
    if gain <= 1e-6:
        return -60.0
    return 20.0 * math.log10(gain)


def _db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def fade_handle_center_y(*, wave_top: float, wave_height: float, audio_style: bool) -> float:
    top = float(wave_top)
    height = max(0.0, float(wave_height))
    if audio_style:
        return top + FADE_HANDLE_AUDIO_TOP_OFFSET_PX
    return top + (height * 0.5)


def fade_zone_x_positions(
    *,
    left: float,
    right: float,
    duration_seconds: float,
    fade_in_seconds: float,
    fade_out_seconds: float,
) -> tuple[float, float]:
    x_left = float(left)
    x_right = float(right)
    if x_right < x_left:
        x_left, x_right = x_right, x_left
    dur = max(0.0, float(duration_seconds))
    if dur <= 1e-9 or x_right <= x_left:
        return x_left, x_right
    fade_in = max(0.0, min(dur, float(fade_in_seconds)))
    fade_out = max(0.0, min(dur, float(fade_out_seconds)))
    span = x_right - x_left
    x_in = x_left + (fade_in / dur) * span
    x_out = x_right - (fade_out / dur) * span
    x_in = max(x_left, min(x_right, x_in))
    x_out = max(x_left, min(x_right, x_out))
    if x_out < x_in:
        mid = (x_in + x_out) * 0.5
        return mid, mid
    return x_in, x_out


def apply_fade_endpoint_zero(
    peaks: list[float],
    *,
    fade_in_seconds: float,
    fade_out_seconds: float,
) -> list[float]:
    if not peaks:
        return peaks
    out = [max(0.0, float(v)) for v in peaks]
    if fade_in_seconds > 1e-6:
        out[0] = 0.0
        if len(out) > 1:
            out[1] = 0.0
    if fade_out_seconds > 1e-6:
        out[-1] = 0.0
        if len(out) > 1:
            out[-2] = 0.0
    return out


class ClipRect(QGraphicsRectItem):
    def __init__(
        self,
        clip: Clip,
        lane_y: float,
        lane_height: float,
        color: QColor,
        panel: TimelinePanel,
        track_kind: str = "video",
        *,
        locked: bool = False,
        muted: bool = False,
        hidden: bool = False,
    ) -> None:
        duration = clip.timeline_duration or 5.0
        w = panel.seconds_to_pixels(duration)
        super().__init__(QRectF(0, 0, w, lane_height))
        self.clip = clip
        self._lane_y = lane_y
        self._panel = panel
        self._pixmap: QPixmap | None = None
        self._pixmap_path: Path | None = None
        self._drag_y = lane_y
        self._drag_origin_start = clip.start
        self._drag_origin_track_idx = -1
        self._drag_happened = False
        self._press_scene_x = 0.0
        self._press_scene_y = 0.0
        self._volume_dragging = False
        self._volume_drag_changed = False
        self._volume_line_hover = False
        self._fade_dragging: str | None = None
        self._fade_drag_changed = False
        self._fade_handle_hover: str | None = None
        self._trim_dragging: str | None = None
        self._trim_drag_changed = False
        self._trim_drag_ripple = False
        self._trim_handle_hover: str | None = None
        self._trim_origin_duration = float(clip.timeline_duration or 0.0)
        self._trim_origin_end = float(clip.start) + self._trim_origin_duration
        self._updating_layout = False
        self._is_text_clip = bool(getattr(clip, "is_text_clip", False))
        self._track_kind = (track_kind or "video").strip().lower()
        self._is_audio_clip = self._track_kind == "audio"
        self._decode_source_key = self._current_decode_source_key()
        self._content_signature = self._make_content_signature(clip, self._track_kind)
        self._is_missing = not self._is_text_clip and not _cached_is_file(clip.source)
        
        self.setPos(panel.seconds_to_pixels(clip.start), lane_y)
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#1a1d23"), 1))
        self._sync_cache_mode()
        self._locked = bool(locked)
        self._muted = bool(muted)
        self._hidden = bool(hidden)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not locked)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not locked)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setAcceptHoverEvents(True)
        # Hide clip hover tooltip on timeline items (path/text popup disabled by user request).
        self.setToolTip("")

    def _sync_cache_mode(self) -> None:
        if TIMELINE_USE_TILED_FILMSTRIP and not self._is_text_clip and not self._is_audio_clip:
            self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        else:
            self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    @staticmethod
    def _make_content_signature(clip: Clip, track_kind: str) -> tuple:
        return (
            track_kind,
            str(getattr(clip, "source", "") or ""),
            float(getattr(clip, "start", 0.0) or 0.0),
            float(getattr(clip, "timeline_duration", 0.0) or 0.0),
            float(getattr(clip, "in_point", 0.0) or 0.0),
            float(getattr(clip, "out_point", 0.0) or 0.0),
            str(getattr(clip, "proxy", "") or ""),
            str(getattr(clip, "text_main", "") or ""),
            str(getattr(clip, "text_second", "") or ""),
        )

    def _current_decode_source_key(self) -> str:
        try:
            return _resolved_source_str(self._panel._clip_decode_source(self.clip))
        except Exception:
            return str(getattr(self.clip, "source", "") or "")

    def invalidate_filmstrip(self) -> None:
        self._pixmap = None
        self._pixmap_path = None
        self.update()

    def update_from_layout(
        self,
        *,
        clip: Clip,
        lane_y: float,
        lane_height: float,
        color: QColor,
        track_kind: str,
        locked: bool,
        muted: bool = False,
        hidden: bool = False,
    ) -> None:
        """Update this timeline item in place instead of recreating it."""
        new_track_kind = (track_kind or "video").strip().lower()
        changed = False
        if self.clip is not clip:
            self.clip = clip
            changed = True

        new_is_text = bool(getattr(clip, "is_text_clip", False))
        new_is_audio = new_track_kind == "audio"
        if (
            self._track_kind != new_track_kind
            or self._is_text_clip != new_is_text
            or self._is_audio_clip != new_is_audio
        ):
            self._track_kind = new_track_kind
            self._is_text_clip = new_is_text
            self._is_audio_clip = new_is_audio
            self._sync_cache_mode()
            self.invalidate_filmstrip()
            changed = True

        new_decode_source = self._current_decode_source_key()
        if new_decode_source != self._decode_source_key:
            self._decode_source_key = new_decode_source
            self.invalidate_filmstrip()
            changed = True

        new_signature = self._make_content_signature(clip, self._track_kind)
        if new_signature != self._content_signature:
            self._content_signature = new_signature
            changed = True

        new_is_missing = not self._is_text_clip and not _cached_is_file(clip.source)
        if new_is_missing != self._is_missing:
            self._is_missing = new_is_missing
            changed = True

        if self.brush().color() != color:
            self.setBrush(QBrush(color))
            changed = True

        start_x = self._panel.seconds_to_pixels(float(clip.start))
        new_y = float(lane_y)
        new_w = max(1.0, self._panel.seconds_to_pixels(float(clip.timeline_duration or 5.0)))
        new_h = max(1.0, float(lane_height))

        pos = self.pos()
        if abs(pos.x() - start_x) > 0.5 or abs(pos.y() - new_y) > 0.5:
            self._updating_layout = True
            try:
                self.setPos(start_x, new_y)
            finally:
                self._updating_layout = False
            changed = True

        rect = self.rect()
        height_changed = abs(rect.height() - new_h) > 0.5
        if abs(rect.width() - new_w) > 0.5 or height_changed:
            self.setRect(0, 0, new_w, new_h)
            if height_changed:
                self.invalidate_filmstrip()
            changed = True

        self._lane_y = new_y
        if not self._drag_happened:
            self._drag_y = new_y

        self.update_track_state(locked=locked, muted=muted, hidden=hidden)
        # Keep clip hover tooltip disabled after every layout refresh.
        self.setToolTip("")
        if changed:
            self.update()

    def update_track_state(self, *, locked: bool, muted: bool, hidden: bool) -> None:
        new_locked = bool(locked)
        new_muted = bool(muted)
        new_hidden = bool(hidden)
        if (
            new_locked == self._locked
            and new_muted == self._muted
            and new_hidden == self._hidden
        ):
            return
        self._locked = new_locked
        self._muted = new_muted
        self._hidden = new_hidden
        if new_locked:
            self.setSelected(False)
            self._set_volume_line_hover(False)
            self._set_fade_handle_hover(None)
            self._set_trim_handle_hover(None)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not new_locked)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not new_locked)
        self.update()

    def _volume_wave_rect(self) -> QRectF | None:
        rect = self.rect()
        if self._is_text_clip or rect.height() < 40.0:
            return None
        header_h, filmstrip_h, waveform_h = _clip_section_heights(rect.height())
        if self._is_audio_clip:
            top = rect.top() + header_h
            h = max(0.0, rect.height() - header_h)
        else:
            top = rect.top() + header_h + filmstrip_h
            h = max(0.0, waveform_h)
        if h <= 2.0:
            return None
        return QRectF(
            rect.left(),
            top,
            rect.width(),
            h,
        )

    def _volume_line_y(self, wave_rect: QRectF) -> float:
        gain = max(0.0, float(getattr(self.clip, "volume", 1.0) or 0.0))
        if gain <= 1e-6:
            norm = 0.95
        else:
            db = max(-VOLUME_LINE_DB_SPAN, min(VOLUME_LINE_DB_SPAN, _linear_to_db(gain)))
            norm = 0.5 - ((db / (2.0 * VOLUME_LINE_DB_SPAN)) * 0.9)
            norm = max(0.05, min(0.95, norm))
        return float(wave_rect.top()) + (norm * float(wave_rect.height()))

    def _set_volume_from_wave_y(self, y: float, wave_rect: QRectF) -> bool:
        h = max(1.0, float(wave_rect.height()))
        top = float(wave_rect.top())
        norm = (float(y) - top) / h
        norm = max(0.05, min(0.95, norm))
        if norm >= 0.949:
            new_gain = 0.0
        else:
            db = (0.5 - norm) * ((2.0 * VOLUME_LINE_DB_SPAN) / 0.9)
            new_gain = max(0.0, min(10.0, _db_to_linear(db)))
        old_gain = float(getattr(self.clip, "volume", 1.0) or 0.0)
        if abs(new_gain - old_gain) <= 1e-5:
            return False
        self.clip.volume = new_gain
        return True

    def _fade_handle_points(self, wave_rect: QRectF) -> tuple[QPointF, QPointF]:
        y = fade_handle_center_y(
            wave_top=float(wave_rect.top()),
            wave_height=float(wave_rect.height()),
            audio_style=self._is_audio_clip,
        )
        left = float(wave_rect.left()) + FADE_HANDLE_RADIUS_PX
        right = float(wave_rect.right()) - FADE_HANDLE_RADIUS_PX
        fade_in, fade_out, dur = self._fade_durations_seconds()
        x_in, x_out = fade_zone_x_positions(
            left=left,
            right=right,
            duration_seconds=dur,
            fade_in_seconds=fade_in,
            fade_out_seconds=fade_out,
        )
        return QPointF(x_in, y), QPointF(x_out, y)

    def _fade_durations_seconds(self) -> tuple[float, float, float]:
        dur = max(0.0, float(self.clip.timeline_duration or 0.0))
        if dur <= 1e-9:
            return 0.0, 0.0, 0.0
        afx = self.clip.audio_effects
        fade_in = max(0.0, min(dur, float(getattr(afx, "fade_in", 0.0) or 0.0)))
        fade_out = max(0.0, min(dur, float(getattr(afx, "fade_out", 0.0) or 0.0)))
        return fade_in, fade_out, dur

    def _set_fade_from_wave_x(self, which: str, x: float, wave_rect: QRectF) -> bool:
        which_n = (which or "").strip().lower()
        if which_n not in {"in", "out"}:
            return False
        dur = max(0.0, float(self.clip.timeline_duration or 0.0))
        if dur <= 1e-6:
            return False
        left = float(wave_rect.left()) + FADE_HANDLE_RADIUS_PX
        right = float(wave_rect.right()) - FADE_HANDLE_RADIUS_PX
        width = max(1e-6, right - left)
        x_c = max(left, min(right, float(x)))
        afx = self.clip.audio_effects
        if which_n == "in":
            new_fade = ((x_c - left) / width) * dur
            new_fade = max(0.0, min(dur, new_fade))
            old = float(getattr(afx, "fade_in", 0.0) or 0.0)
            if abs(old - new_fade) <= 1e-4:
                return False
            afx.fade_in = new_fade
            return True

        new_fade = ((right - x_c) / width) * dur
        new_fade = max(0.0, min(dur, new_fade))
        old = float(getattr(afx, "fade_out", 0.0) or 0.0)
        if abs(old - new_fade) <= 1e-4:
            return False
        afx.fade_out = new_fade
        return True

    def _apply_waveform_fade_envelope(self, peaks: list[float]) -> list[float]:
        if not peaks:
            return peaks

        dur = max(0.0, float(self.clip.timeline_duration or 0.0))
        if dur <= 1e-6:
            return peaks

        afx = self.clip.audio_effects
        if (
            float(getattr(afx, "fade_in", 0.0) or 0.0) <= 0.0
            and float(getattr(afx, "fade_out", 0.0) or 0.0) <= 0.0
        ):
            return peaks

        denom = float(max(1, len(peaks) - 1))
        return [
            max(0.0, float(peak))
            * clip_fade_multiplier_at_local_time(
                self.clip,
                (float(i) / denom) * dur,
                duration_seconds=dur,
            )
            for i, peak in enumerate(peaks)
        ]

    def _hit_fade_handle(self, pos: QPointF) -> str | None:
        if self._is_text_clip or self._locked:
            return None
        wave_rect = self._volume_wave_rect()
        if wave_rect is None:
            return None
        p_in, p_out = self._fade_handle_points(wave_rect)
        hx = FADE_HANDLE_HIT_PX
        hy = FADE_HANDLE_HIT_PX
        in_rect = QRectF(
            float(p_in.x()) - hx,
            float(p_in.y()) - hy,
            hx * 2.0,
            hy * 2.0,
        )
        if in_rect.contains(pos):
            return "in"
        out_rect = QRectF(
            float(p_out.x()) - hx,
            float(p_out.y()) - hy,
            hx * 2.0,
            hy * 2.0,
        )
        if out_rect.contains(pos):
            return "out"
        return None

    def _hit_volume_line(self, pos: QPointF) -> bool:
        if self._is_text_clip or self._locked:
            return False
        wave_rect = self._volume_wave_rect()
        if wave_rect is None:
            return False
        if not wave_rect.adjusted(0.0, -VOLUME_LINE_HIT_PX, 0.0, VOLUME_LINE_HIT_PX).contains(pos):
            return False
        y = self._volume_line_y(wave_rect)
        return abs(float(pos.y()) - y) <= VOLUME_LINE_HIT_PX

    def _hit_trim_handle(self, pos: QPointF) -> str | None:
        if self._locked:
            return None
        rect = self.rect()
        if rect.width() <= 2.0 or rect.height() <= 2.0:
            return None
        if not rect.adjusted(-2.0, -2.0, 2.0, 2.0).contains(pos):
            return None
        hit_w = min(max(4.0, TRIM_HANDLE_HIT_PX), max(4.0, rect.width() * 0.35))
        left_dist = abs(float(pos.x()) - float(rect.left()))
        right_dist = abs(float(rect.right()) - float(pos.x()))
        if left_dist <= hit_w and left_dist <= right_dist:
            return "left"
        if right_dist <= hit_w:
            return "right"
        return None

    def _sync_interaction_cursor(self) -> None:
        if self._trim_dragging is not None or self._trim_handle_hover is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if self._fade_dragging is not None or self._fade_handle_hover is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if self._volume_dragging or self._volume_line_hover:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            return
        self.unsetCursor()

    def _set_volume_line_hover(self, active: bool) -> None:
        new_active = bool(active) and not self._is_text_clip and not self._locked
        if new_active != self._volume_line_hover:
            self._volume_line_hover = new_active
            self.update()
        self._sync_interaction_cursor()

    def _set_fade_handle_hover(self, which: str | None) -> None:
        if self._is_text_clip or self._locked:
            which = None
        which_n = (which or "").strip().lower()
        if which_n not in {"in", "out"}:
            which_n = None
        if which_n != self._fade_handle_hover:
            self._fade_handle_hover = which_n
            self.update()
        self._sync_interaction_cursor()

    def _set_trim_handle_hover(self, which: str | None) -> None:
        if self._locked:
            which = None
        which_n = (which or "").strip().lower()
        if which_n not in {"left", "right"}:
            which_n = None
        if which_n != self._trim_handle_hover:
            self._trim_handle_hover = which_n
            self.update()
        self._sync_interaction_cursor()

    def _draw_volume_line(self, painter: QPainter, wave_rect: QRectF) -> None:
        y = self._volume_line_y(wave_rect)
        line_color = QColor("#5f84a6") if self._is_audio_clip else QColor("#5e8d7f")
        if self._muted:
            line_color = QColor("#6a7481")
        if self._volume_line_hover and not self._volume_dragging:
            line_color = QColor("#9ddcff")
        if self._volume_dragging:
            line_color = QColor("#d7f4ff")
        line_w = 0.9
        if self._volume_line_hover:
            line_w = 1.1
        if self._volume_dragging:
            line_w = 1.25
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(line_color, line_w))
        x0 = float(wave_rect.left()) + 4.0
        x1 = float(wave_rect.right()) - 4.0
        painter.drawLine(
            QPointF(x0, y),
            QPointF(x1, y),
        )
        dot_color = QColor("#d7f4ff") if self._volume_dragging else line_color
        painter.setPen(QPen(dot_color, 0.8))
        painter.setBrush(QBrush(dot_color))
        dot_r = 1.7 if self._volume_line_hover else 1.5
        painter.drawEllipse(QPointF(x0, y), dot_r, dot_r)
        painter.drawEllipse(QPointF(x1, y), dot_r, dot_r)
        painter.restore()

    def _waveform_fade_clip_path(self, wave_rect: QRectF) -> QPainterPath | None:
        if self._is_text_clip:
            return None
        fade_in, fade_out, _ = self._fade_durations_seconds()
        if fade_in <= 1e-4 and fade_out <= 1e-4:
            return None
        x0 = float(wave_rect.left())
        x1 = float(wave_rect.right())
        if x1 <= x0 + 0.5:
            return None
        baseline_y = float(wave_rect.bottom()) - 1.0
        top_y = float(wave_rect.top())
        p_in, p_out = self._fade_handle_points(wave_rect)
        apex_in_x = max(x0, min(x1, float(p_in.x())))
        apex_out_x = max(x0, min(x1, float(p_out.x())))
        apex_in_y = max(top_y + 0.5, min(baseline_y - 0.5, float(p_in.y())))
        apex_out_y = max(top_y + 0.5, min(baseline_y - 0.5, float(p_out.y())))

        cut_path = QPainterPath()
        if fade_in > 1e-4 and apex_in_x > x0 + 0.5:
            span = max(1.0, apex_in_x - x0)
            path_in = QPainterPath()
            path_in.moveTo(x0, top_y)
            path_in.lineTo(apex_in_x, top_y)
            path_in.lineTo(apex_in_x, apex_in_y)
            path_in.cubicTo(
                QPointF(x0 + (span * 0.72), apex_in_y + ((baseline_y - apex_in_y) * 0.10)),
                QPointF(x0 + (span * 0.24), baseline_y),
                QPointF(x0, baseline_y),
            )
            path_in.closeSubpath()
            cut_path.addPath(path_in)
        if fade_out > 1e-4 and apex_out_x < x1 - 0.5:
            span = max(1.0, x1 - apex_out_x)
            path_out = QPainterPath()
            path_out.moveTo(apex_out_x, top_y)
            path_out.lineTo(x1, top_y)
            path_out.lineTo(x1, baseline_y)
            path_out.cubicTo(
                QPointF(x1 - (span * 0.24), baseline_y),
                QPointF(x1 - (span * 0.72), apex_out_y + ((baseline_y - apex_out_y) * 0.10)),
                QPointF(apex_out_x, apex_out_y),
            )
            path_out.closeSubpath()
            cut_path.addPath(path_out)
        if cut_path.isEmpty():
            return None

        visible = QPainterPath()
        visible.addRect(wave_rect)
        return visible.subtracted(cut_path)

    def _draw_fade_handles(self, painter: QPainter, wave_rect: QRectF) -> None:
        if self._is_text_clip:
            return
        p_in, p_out = self._fade_handle_points(wave_rect)
        base = QColor("#dbe7f2")
        if self._muted:
            base = QColor("#9aa4b2")
        in_color = QColor(base)
        out_color = QColor(base)
        if self._fade_handle_hover == "in" and self._fade_dragging is None:
            in_color = QColor("#ffffff")
        if self._fade_handle_hover == "out" and self._fade_dragging is None:
            out_color = QColor("#ffffff")
        if self._fade_dragging == "in":
            in_color = QColor("#ffffff")
        if self._fade_dragging == "out":
            out_color = QColor("#ffffff")

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        in_r = FADE_HANDLE_RADIUS_PX + (0.7 if (self._fade_handle_hover == "in" or self._fade_dragging == "in") else 0.0)
        out_r = FADE_HANDLE_RADIUS_PX + (0.7 if (self._fade_handle_hover == "out" or self._fade_dragging == "out") else 0.0)
        painter.setPen(QPen(QColor(14, 24, 36, 170), 0.8))
        painter.setBrush(QBrush(in_color))
        painter.drawEllipse(p_in, in_r, in_r)
        painter.setBrush(QBrush(out_color))
        painter.drawEllipse(p_out, out_r, out_r)
        painter.restore()

    def _draw_trim_handles(self, painter: QPainter, rect: QRectF) -> None:
        if self._locked:
            return
        if not (self.isSelected() or self._trim_handle_hover or self._trim_dragging):
            return
        strip_w = min(TRIM_HANDLE_HIT_PX, max(2.0, rect.width() * 0.5))
        if strip_w <= 0.0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        base = QColor(255, 255, 255, 42)
        active = QColor("#ffffff")
        active.setAlpha(120)
        line = QColor("#ffffff")
        line.setAlpha(170)
        for edge in ("left", "right"):
            is_active = self._trim_handle_hover == edge or self._trim_dragging == edge
            x = rect.left() if edge == "left" else rect.right() - strip_w
            handle_rect = QRectF(x, rect.top() + 1.0, strip_w, max(0.0, rect.height() - 2.0))
            painter.fillRect(handle_rect, active if is_active else base)
            if is_active:
                line_x = handle_rect.left() if edge == "left" else handle_rect.right()
                painter.setPen(QPen(line, 1.0))
                painter.drawLine(QPointF(line_x, rect.top() + 4.0), QPointF(line_x, rect.bottom() - 4.0))
        painter.restore()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        has_capcut_layout = (not self._is_text_clip) and rect.height() >= 40.0
        header_h = 0.0
        filmstrip_h = rect.height()
        waveform_h = 0.0
        if has_capcut_layout:
            header_h, filmstrip_h, waveform_h = _clip_section_heights(rect.height())
            film_rect = QRectF(
                rect.left(),
                rect.top() + header_h,
                rect.width(),
                max(0.0, filmstrip_h),
            )
        else:
            film_rect = rect

        painter.setClipPath(path)
        if self._is_text_clip:
            base = QColor("#b56b58")
            painter.fillPath(path, QBrush(base))
            painter.fillRect(rect, QColor(0, 0, 0, 12))
        else:
            base_color = QColor(AUDIO_CLIP_BASE_COLOR if self._is_audio_clip else VIDEO_CLIP_BASE_COLOR)
            painter.fillRect(rect, base_color)
            if self._is_audio_clip:
                painter.fillRect(film_rect, QBrush(self.brush().color()))
            else:
                painter.fillRect(film_rect, base_color)
                if TIMELINE_USE_TILED_FILMSTRIP:
                    self._draw_filmstrip_tiles(painter, film_rect)
                else:
                    self._draw_filmstrip_single_strip(painter, film_rect)
                painter.fillRect(film_rect, QColor(0, 0, 0, 50))

            if has_capcut_layout:
                wave_rect = self._volume_wave_rect()
                if wave_rect is not None:
                    wave_bg = AUDIO_CLIP_WAVE_BG if self._is_audio_clip else VIDEO_CLIP_WAVE_BG
                    if self._muted:
                        wave_bg = QColor(35, 45, 52, 210)
                    painter.fillRect(wave_rect, wave_bg)
                    media_kind = "audio" if self._is_audio_clip else "video"
                    visible_wave = self._panel.request_visible_waveform_peaks_async(
                        self.clip,
                        num_peaks=WAVEFORM_PEAKS_RESOLUTION,
                        media_kind=media_kind,
                    )
                    local_start = 0.0
                    local_end = float(getattr(self.clip, "timeline_duration", 0.0) or 0.0)
                    draw_rect = wave_rect
                    if visible_wave is not None:
                        peaks_full, local_start, local_end = visible_wave
                        timeline_dur = max(1e-6, float(getattr(self.clip, "timeline_duration", 0.0) or 0.0))
                        x0 = wave_rect.left() + wave_rect.width() * (local_start / timeline_dur)
                        x1 = wave_rect.left() + wave_rect.width() * (local_end / timeline_dur)
                        draw_rect = QRectF(
                            x0,
                            wave_rect.top(),
                            max(1.0, x1 - x0),
                            wave_rect.height(),
                        )
                    else:
                        peaks_full = self._panel.request_waveform_peaks_async(
                            self.clip,
                            num_peaks=WAVEFORM_PEAKS_RESOLUTION,
                            media_kind=media_kind,
                        )
                        if peaks_full:
                            source_duration = self._panel._waveform_source_duration_seconds(self.clip)
                            peaks_full = waveform_peaks_for_clip_source_range(
                                peaks_full,
                                self.clip,
                                source_duration,
                            )
                    if peaks_full:
                        bar_count = max(8, int(draw_rect.width() / 3.0))
                        peaks = (
                            peaks_full
                            if bar_count >= len(peaks_full)
                            else _downsample_peaks(peaks_full, bar_count)
                        )
                        fade_in, fade_out, _ = self._fade_durations_seconds()
                        if visible_wave is not None:
                            timeline_dur = max(
                                1e-6,
                                float(getattr(self.clip, "timeline_duration", 0.0) or 0.0),
                            )
                            fade_in = max(0.0, fade_in - local_start)
                            fade_out = max(0.0, fade_out - max(0.0, timeline_dur - local_end))
                        peaks = apply_fade_endpoint_zero(
                            peaks,
                            fade_in_seconds=fade_in,
                            fade_out_seconds=fade_out,
                        )
                        wave_gain = max(0.0, float(getattr(self.clip, "volume", 1.0) or 0.0))
                        draw_waveform = (
                            self._draw_waveform_polygon
                            if WAVEFORM_USE_POLYGON
                            else self._draw_waveform_bars
                        )
                        clip_path = self._waveform_fade_clip_path(wave_rect)
                        if clip_path is not None:
                            painter.save()
                            painter.setClipPath(clip_path, Qt.ClipOperation.IntersectClip)
                        try:
                            draw_waveform(
                                painter,
                                draw_rect,
                                peaks,
                                audio_style=self._is_audio_clip,
                                muted=self._muted,
                                gain_mult=wave_gain,
                            )
                        finally:
                            if clip_path is not None:
                                painter.restore()
                    self._draw_volume_line(painter, wave_rect)
                    self._draw_fade_handles(painter, wave_rect)

                header_rect = QRectF(rect.left(), rect.top(), rect.width(), header_h)
                header_color = AUDIO_CLIP_HEADER_COLOR if self._is_audio_clip else VIDEO_CLIP_HEADER_COLOR
                if self._muted:
                    header_color = QColor(header_color)
                    header_color.setAlpha(150)
                painter.fillRect(header_rect, header_color)

        painter.setClipping(False)
        if self._hidden:
            painter.save()
            painter.setClipPath(path)
            painter.fillPath(path, QBrush(QColor(0, 0, 0, 118)))
            painter.fillPath(path, QBrush(QColor(34, 211, 197, 20)))
            painter.restore()

        if self._locked:
            painter.save()
            painter.setClipPath(path)
            painter.fillPath(path, QBrush(QColor(0, 0, 0, 70)))
            painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
            spacing = 10.0
            x = rect.left() - rect.height()
            while x < rect.right():
                painter.drawLine(
                    QPointF(x, rect.bottom()),
                    QPointF(x + rect.height(), rect.top()),
                )
                x += spacing
            painter.restore()

        if self.isSelected():
            painter.setPen(QPen(QColor("#ffffff"), 3))
        elif self._locked:
            painter.setPen(QPen(QColor(255, 255, 255, 62), 1.2))
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawPath(path)
        self._draw_trim_handles(painter, rect)

        # Speed-issue overlay tint (used by caption filter "TÃ¡Â»â€˜c Ã„â€˜Ã¡Â»â„¢ Ã„â€˜Ã¡Â»Âc")
        issue_ids = getattr(self._panel, "_speed_issue_clip_ids", set())
        if id(self.clip) in issue_ids:
            painter.setBrush(QColor(255, 82, 82, 60))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#E57373"), 1.5 if self.isSelected() else 1))
            painter.drawRoundedRect(rect, 4, 4)

        if self._is_missing:
            painter.save()
            painter.setClipPath(path)
            # Red warning overlay
            painter.fillRect(rect, QColor(239, 68, 68, 80))
            # "Media Offline" text
            painter.setPen(QColor("#ffffff"))
            font_missing = QFont("Inter", 10, QFont.Weight.Bold)
            painter.setFont(font_missing)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Media Offline")
            painter.restore()

        painter.setClipPath(path)
        label_pt = TABLE_CAPTION_FONT_PT if self._is_text_clip else TIMELINE_CLIP_LABEL_FONT_PT
        font = QFont("Inter", label_pt, QFont.Weight.Medium)
        painter.setFont(font)
        fm = QFontMetrics(font)
        if self._is_text_clip:
            painter.setPen(QColor("#ffffff"))
            if rect.width() >= 28.0:
                main = (self.clip.text_main or "").strip()
                second = (self.clip.text_second or "").strip()
                if second:
                    label = f"{main} | {second}" if main else second
                else:
                    label = main or "Text"
                label = label.replace("\n", " ").replace("\r", " ")
                text_rect = rect.adjusted(8, 4, -8, -4)
                label = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(text_rect.width()))
                painter.drawText(
                    text_rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    label,
                )
        elif has_capcut_layout:
            painter.setPen(QColor("#e6e9ef"))
            header_rect = QRectF(rect.left(), rect.top(), rect.width(), header_h)
            filename = Path(self.clip.source).name
            duration_text = _format_clip_duration_smpte(float(self.clip.timeline_duration or 0.0))
            header_text = f"{filename}  {duration_text}"
            header_text_elided = fm.elidedText(
                header_text,
                Qt.TextElideMode.ElideRight,
                max(0, int(header_rect.width() - 12)),
            )
            painter.drawText(
                header_rect.adjusted(6, 0, -6, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                header_text_elided,
            )
        else:
            painter.setPen(QColor("#ffffff"))
            label = Path(self.clip.source).name
            title = fm.elidedText(label, Qt.TextElideMode.ElideRight, int(rect.width() - 16))
            painter.drawText(
                rect.adjusted(8, 4, -8, -4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                title,
            )

    def _draw_filmstrip_single_strip(
        self,
        painter: QPainter,
        film_rect: QRectF,
    ) -> bool:
        """Legacy fixed-strip renderer kept as a fast rollback path."""
        if self._pixmap is None:
            strip_w = FILMSTRIP_FRAMES * FILMSTRIP_TILE_WIDTH
            raw_h = int(max(16.0, film_rect.height()))
            strip_h = max(
                16,
                ((raw_h + FILMSTRIP_HEIGHT_BUCKET - 1) // FILMSTRIP_HEIGHT_BUCKET)
                * FILMSTRIP_HEIGHT_BUCKET,
            )
            strip_path = self._panel.request_filmstrip_async(
                self.clip,
                strip_width=strip_w,
                strip_height=strip_h,
                frames=FILMSTRIP_FRAMES,
            )
            if strip_path:
                pix = self._panel.cached_strip_pixmap(strip_path)
                if pix is not None:
                    self._pixmap = pix
                    self._pixmap_path = strip_path

        if self._pixmap is None:
            return False
        painter.drawPixmap(film_rect.toRect(), self._pixmap)
        return True

    def _draw_filmstrip_tiles(
        self,
        painter: QPainter,
        film_rect: QRectF,
        exposed_rect: QRectF | None = None,
    ) -> bool:
        """Draw zoom-aware, source-time filmstrip chunks."""
        clip = self.clip
        in_point = float(getattr(clip, "in_point", 0.0) or 0.0)
        timeline_dur = float(getattr(clip, "timeline_duration", 0.0) or 0.0)
        speed = max(1e-6, float(getattr(clip, "speed", 1.0) or 1.0))
        source_span = float(getattr(clip, "source_duration", 0.0) or 0.0)
        if source_span <= 0.0 and timeline_dur > 0.0:
            source_span = timeline_dur * speed
        if source_span <= 0.0 or film_rect.width() <= 0.0 or film_rect.height() <= 0.0:
            return False

        src_start = in_point
        src_end = in_point + source_span
        px_per_src_sec = film_rect.width() / source_span

        try:
            visible_tl_start, visible_tl_end = self._panel._visible_timeline_seconds()
            clip_start = float(getattr(clip, "start", 0.0) or 0.0)
            visible_local_start = max(0.0, visible_tl_start - clip_start)
            visible_local_end = min(timeline_dur, visible_tl_end - clip_start)
            if visible_local_end < visible_local_start:
                visible_local_start = 0.0
                visible_local_end = timeline_dur
            visible_src_start = src_start + visible_local_start * speed
            visible_src_end = src_start + visible_local_end * speed
        except Exception:
            visible_src_start = src_start
            visible_src_end = src_end

        visible_src_start = max(src_start, visible_src_start - 1.0)
        visible_src_end = min(src_end, visible_src_end + 1.0)

        chunk_size = max(1, int(FILMSTRIP_TILES_PER_CHUNK))
        samples_per_second = _filmstrip_samples_per_second(px_per_src_sec)
        tile_duration = 1.0 / float(max(1, samples_per_second))
        sample_step_seconds = _filmstrip_sample_step_seconds(px_per_src_sec)
        drawn_anything = False

        if sample_step_seconds > 1:
            first_sample_idx = max(
                0,
                int((visible_src_start - src_start) // sample_step_seconds) - 1,
            )
            last_sample_idx = max(
                first_sample_idx,
                int((visible_src_end - src_start) // sample_step_seconds) + 1,
            )
            for sample_idx in range(first_sample_idx, last_sample_idx + 1):
                seg_start = src_start + float(sample_idx * sample_step_seconds)
                seg_end = min(
                    src_end,
                    src_start + float((sample_idx + 1) * sample_step_seconds),
                )
                if seg_end < visible_src_start:
                    continue
                if seg_start > visible_src_end:
                    break

                dst_src_start = max(seg_start, visible_src_start, src_start)
                dst_src_end = min(seg_end, visible_src_end, src_end)
                if dst_src_end <= dst_src_start:
                    continue

                sample_src = min(
                    max(seg_start, src_start),
                    max(src_start, src_end - 1e-6),
                )
                sample_number = max(0, int(math.floor(sample_src / tile_duration)))
                chunk_idx = int(sample_number // chunk_size)
                tile_idx = int(sample_number % chunk_size)
                pix = self._panel.request_filmstrip_chunk_async(
                    clip,
                    chunk_idx,
                    samples_per_second=samples_per_second,
                )
                if pix is None:
                    continue

                dst_x = film_rect.left() + (dst_src_start - src_start) * px_per_src_sec
                dst_w = max(1.0, (dst_src_end - dst_src_start) * px_per_src_sec + 0.5)
                if dst_x > film_rect.right() or dst_x + dst_w < film_rect.left():
                    continue

                src_rect = QRectF(
                    float(tile_idx * FILMSTRIP_TILE_W),
                    0.0,
                    float(FILMSTRIP_TILE_W),
                    float(FILMSTRIP_TILE_H),
                )
                dst_rect = QRectF(dst_x, film_rect.top(), dst_w, film_rect.height())
                painter.drawPixmap(dst_rect, pix, src_rect)
                drawn_anything = True

            return drawn_anything

        first_sample = max(0, int(math.floor(visible_src_start / tile_duration)))
        last_visible_src = max(visible_src_start, visible_src_end - 1e-6)
        last_sample = max(first_sample, int(math.floor(last_visible_src / tile_duration)))
        first_chunk = int(first_sample // chunk_size)
        last_chunk = max(first_chunk, int(last_sample // chunk_size))
        for chunk_idx in range(first_chunk, last_chunk + 1):
            pix = self._panel.request_filmstrip_chunk_async(
                clip,
                chunk_idx,
                samples_per_second=samples_per_second,
            )
            if pix is None:
                continue
            for tile_idx in range(chunk_size):
                tile_sample_idx = chunk_idx * chunk_size + tile_idx
                tile_src_start = float(tile_sample_idx) * tile_duration
                tile_src_end = tile_src_start + tile_duration
                if tile_src_end < visible_src_start:
                    continue
                if tile_src_start > visible_src_end:
                    break

                seg_start = max(tile_src_start, src_start)
                seg_end = min(tile_src_end, src_end)
                if seg_end <= seg_start:
                    continue

                dst_x = film_rect.left() + (seg_start - src_start) * px_per_src_sec
                dst_w = max(1.0, (seg_end - seg_start) * px_per_src_sec + 0.5)
                if dst_x > film_rect.right() or dst_x + dst_w < film_rect.left():
                    continue

                src_x = (tile_idx * FILMSTRIP_TILE_W) + (
                    (seg_start - tile_src_start) * FILMSTRIP_TILE_W
                )
                src_w = max(1.0, (seg_end - seg_start) * FILMSTRIP_TILE_W)
                src_rect = QRectF(src_x, 0.0, src_w, float(FILMSTRIP_TILE_H))
                dst_rect = QRectF(dst_x, film_rect.top(), dst_w, film_rect.height())
                painter.drawPixmap(dst_rect, pix, src_rect)
                drawn_anything = True

        return drawn_anything

    def _draw_waveform_polygon(
        self,
        painter: QPainter,
        wave_rect: QRectF,
        peaks: list[float],
        *,
        audio_style: bool = False,
        muted: bool = False,
        gain_mult: float = 1.0,
    ) -> None:
        if len(peaks) < 2 or wave_rect.width() <= 0.0 or wave_rect.height() <= 0.0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        wave_color = AUDIO_CLIP_WAVE_BAR if audio_style else VIDEO_CLIP_WAVE_BAR
        if muted:
            wave_color = "#5c6872"
        painter.setBrush(QBrush(QColor(wave_color)))

        n = len(peaks)
        left = float(wave_rect.left())
        width = float(wave_rect.width())
        step = width / float(max(1, n - 1))
        baseline_y = float(wave_rect.bottom() - 1.0)
        max_wave_h = max(2.0, float(wave_rect.height()) - 2.0)

        top_points: list[QPointF] = []
        bottom_points: list[QPointF] = []
        gain = max(0.0, min(2.5, float(gain_mult)))
        for i, peak in enumerate(peaks):
            amp = max(0.0, min(1.0, float(peak) * 1.8 * gain))
            wave_h = max(1.0, amp * max_wave_h)
            x = left + (step * i)
            top_points.append(QPointF(x, baseline_y - wave_h))
            bottom_points.append(QPointF(x, baseline_y))

        polygon = QPolygonF(top_points + list(reversed(bottom_points)))
        painter.drawPolygon(polygon)
        painter.restore()

    def _draw_waveform_bars(
        self,
        painter: QPainter,
        wave_rect: QRectF,
        peaks: list[float],
        *,
        audio_style: bool = False,
        muted: bool = False,
        gain_mult: float = 1.0,
    ) -> None:
        if not peaks or wave_rect.width() <= 0.0 or wave_rect.height() <= 0.0:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        bar_color = AUDIO_CLIP_WAVE_BAR if audio_style else VIDEO_CLIP_WAVE_BAR
        if muted:
            bar_color = "#5c6872"
        painter.setBrush(QBrush(QColor(bar_color)))
        n = len(peaks)
        slot_w = wave_rect.width() / float(n)
        bar_w = max(1.0, min(2.0, slot_w - 1.0))
        if audio_style:
            baseline_y = float(wave_rect.bottom() - 1.0)
            max_wave_h = max(2.0, float(wave_rect.height()) - 2.0)
        else:
            center_y = wave_rect.center().y()
            max_half_h = max(2.0, wave_rect.height() * 0.42)
        gain = max(0.0, min(2.5, float(gain_mult)))
        x = wave_rect.left()
        for peak in peaks:
            amp = max(0.0, min(1.0, float(peak) * 1.8 * gain))
            h = max(1.0, amp * (max_wave_h if audio_style else max_half_h))
            bar_x = x + max(0.0, (slot_w - bar_w) * 0.5)
            if audio_style:
                painter.drawRect(QRectF(bar_x, baseline_y - h, bar_w, h))
            else:
                painter.drawRect(QRectF(bar_x, center_y - h, bar_w, h * 2.0))
            x += slot_w
        painter.restore()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._updating_layout:
                return value
            if self._trim_dragging is not None:
                return self.pos()
            x = max(0.0, float(value.x()))
            start_sec = self._panel.pixels_to_seconds(x)
            snapped_sec = self._panel.apply_clip_snap(self.clip, start_sec)
            self.clip.start = snapped_sec
            self._drag_y = float(value.y())
            value.setX(self._panel.seconds_to_pixels(snapped_sec))
            self._panel._update_live_link_follow(
                self.clip,
                origin_start=float(self._drag_origin_start),
                parent_start=snapped_sec,
                parent_scene_y=float(value.y()),
                parent_lane_y=float(self._lane_y),
            )
        return super().itemChange(change, value)

    def _apply_trim_geometry_from_clip(self) -> None:
        width = max(1.0, self._panel.seconds_to_pixels(float(self.clip.timeline_duration or 5.0)))
        self._updating_layout = True
        try:
            self.setPos(self._panel.seconds_to_pixels(float(self.clip.start)), self._lane_y)
            self.setRect(0, 0, width, self.rect().height())
        finally:
            self._updating_layout = False
        self._content_signature = self._make_content_signature(self.clip, self._track_kind)
        self.update()

    def _set_trim_edge_from_scene_x(self, edge: str, scene_x: float) -> bool:
        loc = self._panel._find_clip_location(self.clip)
        if loc is None:
            return False
        track, _, _ = loc
        if self._panel._is_track_locked(track):
            return False
        target = self._panel.pixels_to_seconds(scene_x)
        target = self._panel.apply_trim_snap(self.clip, edge, target)
        changed, _ = trim_clip_edge(track, self.clip, edge, target, ripple=False)
        if changed:
            self._apply_trim_geometry_from_clip()
        return changed

    def mouseReleaseEvent(self, event):
        if self._trim_dragging is not None and event.button() == Qt.MouseButton.LeftButton:
            edge = self._trim_dragging
            changed = bool(self._trim_drag_changed)
            ripple = bool(self._trim_drag_ripple and edge == "right")
            ripple_anchor = float(self._trim_origin_end)
            current_end = _clip_timeline_end(self.clip)
            ripple_delta = 0.0
            if current_end is not None:
                ripple_delta = float(current_end) - float(self._trim_origin_end)
            self._trim_dragging = None
            self._trim_drag_changed = False
            self._trim_drag_ripple = False
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self._locked)
            self.setZValue(0)
            self.setSelected(True)
            self._set_trim_handle_hover(self._hit_trim_handle(event.pos()))
            if changed:
                clip = self.clip
                QTimer.singleShot(
                    0,
                    lambda c=clip, rp=ripple, anchor=ripple_anchor, delta=ripple_delta, panel=self._panel: panel.handle_clip_trim_change(
                        c,
                        ripple=rp,
                        ripple_anchor_seconds=anchor,
                        ripple_delta_seconds=delta,
                    ),
                )
            event.accept()
            return
        if self._fade_dragging is not None and event.button() == Qt.MouseButton.LeftButton:
            self._fade_dragging = None
            self.setZValue(0)
            self.setSelected(True)
            if self._fade_drag_changed:
                self._fade_drag_changed = False
                self._panel.handle_clip_fade_change(self.clip)
            self._set_fade_handle_hover(self._hit_fade_handle(event.pos()))
            self._set_volume_line_hover(self._hit_volume_line(event.pos()))
            event.accept()
            return
        if self._volume_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._volume_dragging = False
            self.setZValue(0)
            self.setSelected(True)
            if self._volume_drag_changed:
                self._volume_drag_changed = False
                self._panel.handle_clip_volume_change(self.clip)
            self._set_volume_line_hover(self._hit_volume_line(event.pos()))
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            self.setZValue(0)
            return
        # Clicking to select should not trigger timeline mutation/rebuild.
        if not self._drag_happened:
            self.setZValue(0)
            self._panel._clear_live_link_follow()
            return
        # Only treat as a drop when position/lane actually changed.
        time_moved = abs(float(self.clip.start) - float(self._drag_origin_start)) > 1e-4
        lane_moved = abs(float(self._drag_y) - float(self._lane_y)) > 2.0
        if not (time_moved or lane_moved):
            self.setZValue(0)
            self.setSelected(True)
            self._panel._clear_live_link_follow()
            return
        # Defer model/scene mutation until Qt finishes release handling.
        # This avoids deleting the active QGraphicsItem while native code is
        # still unwinding the mouse event.
        clip = self.clip
        dragged_y = self._drag_y
        drag_origin_start = self._drag_origin_start
        self.setZValue(0)
        QTimer.singleShot(
            0,
            lambda c=clip, y=dragged_y, origin=drag_origin_start, panel=self._panel: panel.handle_clip_release_by_clip(
                c, y, origin
            ),
        )

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        # HTML-like behavior: single click always selects this clip.
        mods = event.modifiers()
        additive = bool(
            mods
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.ShiftModifier
            )
        )
        if not additive and self.scene() is not None:
            self.scene().clearSelection()
        self.setSelected(True)
        wave_rect = self._volume_wave_rect()
        if wave_rect is not None:
            fade_hit = self._hit_fade_handle(event.pos())
            if fade_hit is not None:
                self._panel.user_pause_requested.emit()
                self._fade_dragging = fade_hit
                self._fade_drag_changed = False
                self._drag_happened = False
                self.setZValue(2002)
                self._set_fade_handle_hover(fade_hit)
                self._set_volume_line_hover(False)
                if self._set_fade_from_wave_x(fade_hit, float(event.pos().x()), wave_rect):
                    self._fade_drag_changed = True
                self.update()
                event.accept()
                return
        if wave_rect is not None and self._hit_volume_line(event.pos()):
            self._panel.user_pause_requested.emit()
            self._volume_dragging = True
            self._volume_drag_changed = False
            self._drag_happened = False
            self.setZValue(2002)
            self._fade_dragging = None
            self._set_volume_line_hover(True)
            if self._set_volume_from_wave_y(float(event.pos().y()), wave_rect):
                self._volume_drag_changed = True
            self.update()
            event.accept()
            return
        trim_hit = self._hit_trim_handle(event.pos())
        if trim_hit is not None:
            self._panel.user_pause_requested.emit()
            self._trim_dragging = trim_hit
            self._trim_drag_changed = False
            self._trim_drag_ripple = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._trim_origin_duration = float(self.clip.timeline_duration or 0.0)
            self._trim_origin_end = float(self.clip.start) + self._trim_origin_duration
            self._drag_happened = False
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            self.setZValue(2002)
            self._set_trim_handle_hover(trim_hit)
            self._set_fade_handle_hover(None)
            self._set_volume_line_hover(False)
            if self._set_trim_edge_from_scene_x(trim_hit, float(event.scenePos().x())):
                self._trim_drag_changed = True
            event.accept()
            return
        self._drag_origin_start = self.clip.start
        src_idx = self._panel._track_index_for_clip(self.clip)
        self._drag_origin_track_idx = -1 if src_idx is None else src_idx
        self._panel._begin_live_link_follow(
            self.clip,
            origin_start=float(self._drag_origin_start),
        )
        self._drag_happened = False
        sp = event.scenePos()
        self._press_scene_x = float(sp.x())
        self._press_scene_y = float(sp.y())
        # Keep the dragged clip visually above overlapping clips while moving.
        self.setZValue(2002)
        super().mousePressEvent(event)
        # Qt can toggle Ctrl/Shift-clicked items after our manual selection.
        # Re-assert selection so multi-select actions like Link see every clip.
        self.setSelected(True)

    def mouseMoveEvent(self, event):
        if self._fade_dragging is not None:
            wave_rect = self._volume_wave_rect()
            if wave_rect is not None and self._set_fade_from_wave_x(
                self._fade_dragging,
                float(event.pos().x()),
                wave_rect,
            ):
                self._fade_drag_changed = True
                self.update()
            self._set_fade_handle_hover(self._fade_dragging)
            event.accept()
            return
        if self._volume_dragging:
            wave_rect = self._volume_wave_rect()
            if wave_rect is not None and self._set_volume_from_wave_y(float(event.pos().y()), wave_rect):
                self._volume_drag_changed = True
                self.update()
            event.accept()
            return
        if self._trim_dragging is not None:
            self._trim_drag_ripple = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._set_trim_edge_from_scene_x(self._trim_dragging, float(event.scenePos().x())):
                self._trim_drag_changed = True
            self._set_trim_handle_hover(self._trim_dragging)
            event.accept()
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        sp = event.scenePos()
        dx = abs(float(sp.x()) - self._press_scene_x)
        dy = abs(float(sp.y()) - self._press_scene_y)
        if dx > 4.0 or dy > 4.0:
            if not self._drag_happened:
                self._panel.user_pause_requested.emit()
            self._drag_happened = True
        super().mouseMoveEvent(event)

    def hoverMoveEvent(self, event) -> None:
        if not self._volume_dragging and self._fade_dragging is None and self._trim_dragging is None:
            fade_hit = self._hit_fade_handle(event.pos())
            self._set_fade_handle_hover(fade_hit)
            if fade_hit is None:
                volume_hit = self._hit_volume_line(event.pos())
                self._set_volume_line_hover(volume_hit)
                self._set_trim_handle_hover(None if volume_hit else self._hit_trim_handle(event.pos()))
            else:
                self._set_volume_line_hover(False)
                self._set_trim_handle_hover(None)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._set_fade_handle_hover(None)
        self._set_volume_line_hover(False)
        self._set_trim_handle_hover(None)
        super().hoverLeaveEvent(event)

    def contextMenuEvent(self, event):
        self.setSelected(True)
        self._panel.open_clip_context_menu(self.clip, event.screenPos())
        event.accept()


class TimelineScene(QGraphicsScene):
    """Paint cheap ruler overlays without adding tick items to the scene."""

    def __init__(self, panel, parent=None) -> None:
        super().__init__(parent)
        self._panel = panel

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        panel = self._panel
        if panel is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        visible_left = float(rect.left())
        visible_right = float(rect.right())
        if visible_right < visible_left:
            visible_left, visible_right = visible_right, visible_left
        visible_width = max(1.0, visible_right - visible_left)
        try:
            viewport_rect = panel._view.mapToScene(
                panel._view.viewport().rect()
            ).boundingRect()
            ruler_y = max(0.0, float(viewport_rect.top()))
        except Exception:
            ruler_y = max(0.0, float(rect.top()))
        ruler_bottom = ruler_y + RULER_HEIGHT

        painter.fillRect(
            QRectF(visible_left, ruler_y, visible_width, RULER_HEIGHT),
            QBrush(QColor("#1a1d23")),
        )
        painter.setPen(QPen(QColor("#2a2f38"), 1))
        painter.drawLine(
            QPointF(visible_left, ruler_bottom),
            QPointF(visible_right, ruler_bottom),
        )

        major_tick = panel._major_tick_seconds(panel._pixels_per_second)
        minor_tick = max(1e-6, major_tick / 5.0)
        sec_start = panel.pixels_to_seconds(max(0.0, visible_left))
        sec_end = panel.pixels_to_seconds(max(0.0, visible_right))
        i_start = max(0, int(sec_start / minor_tick) - 1)
        i_end = int(sec_end / minor_tick) + 2
        major_pen = QPen(QColor("#525969"), 1)
        minor_pen = QPen(QColor("#363b46"), 1)
        font = QFont("Inter", 8, QFont.Weight.Medium)
        painter.setFont(font)
        for i in range(i_start, i_end):
            sec = i * minor_tick
            if sec < 0.0:
                continue
            x = panel.seconds_to_pixels(sec)
            if (i % 5) == 0:
                painter.setPen(major_pen)
                painter.drawLine(QPointF(x, ruler_y + 8.0), QPointF(x, ruler_bottom))
                painter.setPen(QColor("#8c93a0"))
                painter.drawText(
                    QPointF(x + 4.0, ruler_y + 14.0),
                    _format_ruler_label(sec, major_tick),
                )
            else:
                painter.setPen(minor_pen)
                painter.drawLine(QPointF(x, ruler_y + 18.0), QPointF(x, ruler_bottom))

        # Foreground is painted above scene items, so draw the playhead handle
        # here to keep it visible after the ruler background is painted.
        x = panel.seconds_to_pixels(panel._playhead_seconds)
        if visible_left - 12.0 <= x <= visible_right + 12.0:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            playhead_color = QColor("#22d3c5")
            painter.setPen(QPen(playhead_color, 1))
            painter.drawLine(QPointF(x, ruler_bottom), QPointF(x, max(rect.bottom(), self.height())))
            painter.drawLine(QPointF(x, ruler_y), QPointF(x, ruler_bottom))
            handle_path = QPainterPath()
            handle_path.moveTo(x, ruler_y)
            handle_path.lineTo(x + 6.0, ruler_y + 8.0)
            handle_path.lineTo(x, ruler_y + 16.0)
            handle_path.lineTo(x - 6.0, ruler_y + 8.0)
            handle_path.closeSubpath()
            painter.fillPath(handle_path, QBrush(playhead_color))

        painter.restore()


class TimelineView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, panel: TimelinePanel) -> None:
        super().__init__(scene)
        self._panel = panel
        self._rubber_selecting = False
        self._scrubbing_playhead = False
        self._using_opengl_viewport = False
        self.setBackgroundBrush(QBrush(QColor(TIMELINE_BG_COLOR)))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.set_opengl_viewport_enabled(TIMELINE_USE_OPENGL_VIEWPORT)
        self.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing,
            True,
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.horizontalScrollBar().setStyleSheet(
            """
            QScrollBar:horizontal {
                border: none;
                background: transparent;
                height: 18px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #4a4a4a;
                min-width: 72px;
                border-radius: 2px;
                margin: 6px 0px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #6a6a6a;
            }
            QScrollBar::handle:horizontal:pressed {
                background: #858585;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width: 0px;
                height: 0px;
            }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            """
        )
        self.verticalScrollBar().setStyleSheet(
            """
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 14px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #4a4a4a;
                min-height: 48px;
                border-radius: 2px;
                margin: 0px 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6a6a6a;
            }
            QScrollBar::handle:vertical:pressed {
                background: #858585;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                width: 0px;
                height: 0px;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Enable box-select only when dragging on empty timeline space,
        # so single-click on a clip still selects it reliably.
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        # Needed for hover scrub (mouse move without pressed buttons).
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def is_opengl_viewport_enabled(self) -> bool:
        return bool(self._using_opengl_viewport)

    @staticmethod
    def _apply_dark_viewport_background(viewport: QWidget) -> None:
        palette = viewport.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(TIMELINE_BG_COLOR))
        viewport.setPalette(palette)
        viewport.setAutoFillBackground(True)
        viewport.setStyleSheet(f"background: {TIMELINE_BG_COLOR}; border: none;")
        viewport.setMouseTracking(True)

    def set_opengl_viewport_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        if enabled == self._using_opengl_viewport:
            return True
        if enabled:
            try:
                from PySide6.QtGui import QSurfaceFormat  # type: ignore
                from PySide6.QtOpenGLWidgets import QOpenGLWidget  # type: ignore

                viewport = QOpenGLWidget(self)
                fmt = QSurfaceFormat()
                fmt.setSwapInterval(0)
                viewport.setFormat(fmt)
            except Exception:
                return False
        else:
            viewport = QWidget(self)

        self._apply_dark_viewport_background(viewport)
        self.setViewport(viewport)
        self._using_opengl_viewport = enabled
        self.setBackgroundBrush(QBrush(QColor(TIMELINE_BG_COLOR)))
        update_mode = (
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
            if enabled
            else QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self.setViewportUpdateMode(update_mode)
        self.setAcceptDrops(True)
        self._apply_dark_viewport_background(self.viewport())
        scene = self.scene()
        if scene is not None:
            scene.setBackgroundBrush(QBrush(QColor(TIMELINE_BG_COLOR)))
            scene.invalidate(scene.sceneRect(), QGraphicsScene.SceneLayer.AllLayers)
        self.resetCachedContent()
        self.viewport().update()
        self.update()
        return True

    @staticmethod
    def _extract_path(event_mime) -> Path | None:
        if event_mime.hasFormat(MEDIA_MIME_TYPE):
            raw = bytes(event_mime.data(MEDIA_MIME_TYPE)).decode("utf-8", errors="ignore").strip()
            if raw:
                return Path(raw)
        if event_mime.hasUrls():
            for url in event_mime.urls():
                if url.isLocalFile():
                    return Path(url.toLocalFile())
        text = event_mime.text().strip()
        if text:
            return Path(text)
        return None

    @staticmethod
    def _drop_point(event) -> QPoint:
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            super().wheelEvent(event)
            return

        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            view_x = event.position().x() if hasattr(event, "position") else float(event.pos().x())
            scene_x = self.mapToScene(self._drop_point(event)).x()
            self._panel.zoom_by_wheel(delta, scene_x, view_x)
            event.accept()
            return

        if mods & Qt.KeyboardModifier.AltModifier:
            self._panel.scroll_horizontal_by(delta)
            event.accept()
            return

        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._panel.ripple_delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._panel._set_pointer_active(True)
            scene_pt = self.mapToScene(event.pos())
            if float(event.pos().y()) <= float(RULER_HEIGHT):
                self._panel.user_pause_requested.emit()
                self._scrubbing_playhead = True
                self._panel._begin_playhead_scrub()
                self._rubber_selecting = False
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                self._panel._scrub_playhead_to_scene_x(float(scene_pt.x()), emit_seek=True)
                event.accept()
                return
            item = self.itemAt(event.pos())
            if item is None:
                self._rubber_selecting = True
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            else:
                self._rubber_selecting = False
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._scrubbing_playhead and (event.buttons() & Qt.MouseButton.LeftButton):
            scene_pt = self.mapToScene(event.pos())
            self._panel._scrub_playhead_to_scene_x(float(scene_pt.x()), emit_seek=True)
            event.accept()
            return
        if (
            self._panel.is_hover_scrub_enabled()
            and not (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            scene_pt = self.mapToScene(event.pos())
            if float(scene_pt.x()) >= 0.0:
                self._panel._scrub_playhead_to_scene_x(float(scene_pt.x()), emit_seek=True)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_scrubbing = bool(
            event.button() == Qt.MouseButton.LeftButton and self._scrubbing_playhead
        )
        if was_scrubbing:
            scene_pt = self.mapToScene(event.pos())
            # Ensure final scrub position is emitted on release.
            self._panel._scrub_playhead_to_scene_x(float(scene_pt.x()), emit_seek=True)
            self._panel._end_playhead_scrub()
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._panel._set_pointer_active(False)
            self._scrubbing_playhead = False
        if self._rubber_selecting:
            self._rubber_selecting = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        path = self._extract_path(event.mimeData())
        if path is not None:
            self._panel.begin_external_drag_preview(path)
            event.acceptProposedAction()
            return
        self._panel.end_external_drag_preview()
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        path = self._extract_path(event.mimeData())
        if path is not None:
            self._panel.update_external_drag_preview(path)
            event.acceptProposedAction()
            return
        self._panel.end_external_drag_preview()
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._panel.end_external_drag_preview()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._extract_path(event.mimeData())
        if path is None:
            self._panel.end_external_drag_preview()
            event.ignore()
            return
        accepted = self._panel.handle_external_media_drop(path, self._drop_point(event))
        self._panel.end_external_drag_preview()
        if accepted:
            event.acceptProposedAction()
        else:
            event.ignore()


class TrackHeader(QWidget):
    """Left-side header for a timeline track."""

    def __init__(
        self,
        name: str,
        kind: str,
        *,
        locked: bool = False,
        hidden: bool = False,
        muted: bool = False,
        volume: float = 1.0,
        role: str = "other",
        lane_height: float = TRACK_HEIGHT,
        background_color: QColor | str = "#16181d",
        on_toggle_lock: Callable[[], None] | None = None,
        on_toggle_hidden: Callable[[], None] | None = None,
        on_toggle_mute: Callable[[], None] | None = None,
        on_volume_changed: Callable[[float, bool], None] | None = None,
        on_role_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.setFixedWidth(TRACK_HEADER_WIDTH)
        self.setFixedHeight(int(max(20.0, lane_height)))
        self.setToolTip(name)
        self._background_color = QColor(background_color)
        # HTML parity: controls stay on the header while the lane remains.
        self.setStyleSheet(
            """
            QLabel { border: none; background: transparent; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        def _icon_label(symbol_id: str, fallback: str = "*", size: int = 12) -> QLabel:
            lbl = QLabel(fallback, self)
            lbl.setStyleSheet("color: #4a505c; font-size: 10px;")
            icon = _timeline_icon(symbol_id, color="#4a505c", size=size)
            if not icon.isNull():
                lbl.setText("")
                lbl.setPixmap(icon.pixmap(size, size))
            return lbl

        def _icon_button(
            symbol_id: str,
            tip: str,
            slot: Callable[[], None] | None,
            *,
            active: bool = False,
            fallback: str = "",
            size: int = 14,
        ) -> QToolButton:
            btn = QToolButton(self)
            btn.setToolTip(tip)
            btn.setFixedSize(22, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("trackActive", "true" if active else "false")
            btn.setStyleSheet(
                """
                QToolButton {
                    border: none;
                    border-radius: 5px;
                    background: transparent;
                    color: #929292;
                    padding: 4px 0 3px 0;
                }
                QToolButton:hover {
                    color: #d8d8d8;
                    background: #000000;
                }
                QToolButton:pressed {
                    padding-left: 1px;
                    padding-top: 5px;
                }
                QToolButton[trackActive="true"] {
                    color: #00bfc9;
                    background: #030303;
                }
                QToolTip {
                    color: #dce6f2;
                    background: #11161f;
                    border: 1px solid #2a2f38;
                    padding: 4px 6px;
                }
                """
            )
            normal_icon = _timeline_icon(
                symbol_id,
                color="#00bfc9" if active else "#929292",
                size=size,
            )
            if normal_icon.isNull():
                btn.setText(fallback)
            else:
                hover_icon = _timeline_icon(
                    symbol_id,
                    color="#00bfc9" if active else "#d8d8d8",
                    size=size,
                )
                icon = QIcon()
                icon.addPixmap(normal_icon.pixmap(size, size), QIcon.Mode.Normal)
                if not hover_icon.isNull():
                    icon.addPixmap(hover_icon.pixmap(size, size), QIcon.Mode.Active)
                btn.setText("")
                btn.setIcon(icon)
                btn.setIconSize(QSize(size, size))
            if slot is not None:
                btn.clicked.connect(lambda _checked=False, cb=slot: cb())
            return btn

        icons_layout = QHBoxLayout()
        icons_layout.setContentsMargins(0, 0, 0, 0)
        icons_layout.setSpacing(6)
        lock_icon = "icon-editor-timeline-tracks-lock-off" if locked else "icon-editor-timeline-tracks-lock"
        eye_icon = "icon-editor-timeline-tracks-eye-off" if hidden else "icon-editor-timeline-tracks-eye"
        audio_icon = "icon-editor-timeline-tracks-audio-off" if muted else "icon-editor-timeline-tracks-audio"
        # Dedicated icon per track type (video/text/audio), same spacing rhythm as action icons.
        type_fallback = {"video": "M", "text": "T", "audio": "A"}.get((kind or "").strip().lower(), "M")
        track_type_icon = QLabel(type_fallback, self)
        track_type_icon.setFixedSize(22, 22)
        track_type_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        track_type_icon.setStyleSheet("color: #4a505c; font-size: 10px; border: none; background: transparent;")
        type_icon = _custom_track_type_icon(kind, color="#4a505c", size=14)
        if not type_icon.isNull():
            track_type_icon.setText("")
            track_type_icon.setPixmap(type_icon.pixmap(14, 14))
        icons_layout.addWidget(track_type_icon)
        icons_layout.addWidget(
            _icon_button(
                lock_icon,
                "Má»Ÿ khÃ³a track" if locked else "KhÃ³a track",
                on_toggle_lock,
                active=locked,
                fallback="L",
            )
        )
        icons_layout.addWidget(
            _icon_button(
                eye_icon,
                "Hiá»‡n track" if hidden else "áº¨n track",
                on_toggle_hidden,
                active=hidden,
                fallback="E",
            )
        )
        icons_layout.addWidget(
            _icon_button(
                audio_icon,
                "Báº­t Ã¢m thanh track" if muted else "Táº¯t Ã¢m thanh track",
                on_toggle_mute,
                active=muted,
                fallback="A",
            )
        )
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)
        top_row.addLayout(icons_layout)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        if (kind or "").strip().lower() == "audio" and lane_height >= 46:
            mixer_row = QHBoxLayout()
            mixer_row.setContentsMargins(0, 0, 0, 0)
            mixer_row.setSpacing(5)
            vol = QSlider(Qt.Orientation.Horizontal, self)
            vol.setRange(0, 200)
            vol.setFixedHeight(16)
            vol.setToolTip("Track volume")
            vol.setValue(max(0, min(200, int(round(float(volume) * 100.0)))))
            vol.setStyleSheet(
                """
                QSlider::groove:horizontal {
                    height: 3px;
                    background: #252b34;
                    border-radius: 2px;
                }
                QSlider::sub-page:horizontal {
                    background: #22d3c5;
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    width: 9px;
                    margin: -4px 0;
                    border-radius: 4px;
                    background: #d7fbf7;
                }
                """
            )
            if on_volume_changed is not None:
                vol.valueChanged.connect(
                    lambda v, slider=vol, cb=on_volume_changed: cb(
                        max(0.0, float(v) / 100.0),
                        not slider.isSliderDown(),
                    )
                )
                vol.sliderReleased.connect(
                    lambda slider=vol, cb=on_volume_changed: cb(
                        max(0.0, float(slider.value()) / 100.0),
                        True,
                    )
                )
            mixer_row.addWidget(vol, 1)

            role_box = QComboBox(self)
            role_box.setFixedWidth(58)
            role_box.setToolTip("Audio role")
            for role_id, label in AUDIO_ROLE_LABELS.items():
                role_box.addItem(label, role_id)
            role_index = role_box.findData((role or "other").strip().lower())
            role_box.setCurrentIndex(role_index if role_index >= 0 else role_box.findData("other"))
            role_box.setStyleSheet(
                """
                QComboBox {
                    background: #111318;
                    border: 1px solid #2a2f38;
                    border-radius: 4px;
                    color: #cfd5df;
                    font-size: 9px;
                    padding-left: 4px;
                }
                QComboBox::drop-down { border: none; width: 10px; }
                """
            )
            if on_role_changed is not None:
                role_box.currentIndexChanged.connect(
                    lambda _idx, box=role_box, cb=on_role_changed: cb(
                        str(box.currentData() or "other")
                    )
                )
            mixer_row.addWidget(role_box)
            layout.addLayout(mixer_row)
        else:
            layout.addStretch(1)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background_color)
        painter.setPen(QPen(QColor("#2a2f38"), 1))
        painter.drawLine(0, 0, self.width(), 0)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        painter.end()
        super().paintEvent(event)

class TimelinePanel(QWidget):
    selection_changed = Signal(object)
    subtitle_edit_translate_requested = Signal(object)
    subtitle_batch_translate_requested = Signal(object)
    _thumbnail_ready = Signal(object, object)
    _filmstrip_chunk_ready = Signal(object, object)
    _waveform_peaks_ready = Signal(object, object)
    playpause_requested = Signal()
    seek_requested = Signal(float)  # playhead seek request (seconds)
    undo_requested = Signal()
    redo_requested = Signal()
    save_requested = Signal()
    media_drop_requested = Signal(str, float, int, bool)
    project_mutated = Signal()
    user_pause_requested = Signal()

    def __init__(self, project: Project) -> None:
        super().__init__()
        self._project = project
        self._timeline_end_cache: float | None = None
        self._playhead_seconds: float = 0.0
        self._playhead_item = None
        self._playhead_handle = None
        self._zoom_percent = 100
        self._pixels_per_second = BASE_PIXELS_PER_SECOND
        self._zoom_anchor_seconds: float | None = None
        self._zoom_anchor_view_x: float | None = None
        self._is_playing = False
        self._snapping_enabled = True
        self._main_track_magnet_enabled = True
        self._linked_selection_enabled = True
        self._suppress_linked_selection = False
        self._live_link_parent_runtime_id: int | None = None
        self._live_link_parent_origin_start = 0.0
        self._live_link_follow_snapshot: dict[int, tuple[Clip, float, str, float]] = {}
        self._hover_scrub_enabled = False
        self._use_opengl_viewport = TIMELINE_USE_OPENGL_VIEWPORT
        self._empty_drop_preview_visible = False
        self._refresh_scheduled = False
        self._pointer_active = False
        self._pending_pointer_refresh = False
        self._is_playhead_scrubbing = False
        self._scrub_last_emit_ts = 0.0
        self._scrub_last_visual_refresh_ts = 0.0
        self._scrub_pending_seconds: float | None = None
        self._last_seek_request_was_scrub = False
        self._scrub_emit_timer = QTimer(self)
        self._scrub_emit_timer.setSingleShot(True)
        self._scrub_emit_timer.timeout.connect(self._flush_pending_scrub_seek)
        self._speed_issue_clip_ids: set[int] = set()
        self._thumb_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-thumb")
        self._wave_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-wave")
        self._thumb_cache: dict[tuple[str, int, int, int, int], Path | None] = {}
        self._thumb_inflight: set[tuple[str, int, int, int, int]] = set()
        self._strip_pixmap_cache: dict[str, QPixmap] = {}
        self._chunk_pixmap_cache: dict[tuple[str, int, int, int, int, int], QPixmap | None] = {}
        self._chunk_inflight: set[tuple[str, int, int, int, int, int]] = set()
        self._wave_peaks_cache: dict[tuple[str, int, int], list[float] | None] = {}
        self._wave_peaks_inflight: set[tuple[str, int, int]] = set()
        self._wave_range_peaks_cache: dict[tuple[str, int, int, int], list[float] | None] = {}
        self._wave_range_peaks_inflight: set[tuple[str, int, int, int]] = set()
        self._wave_upgrade_pending: set[tuple[str, int, int]] = set()
        self._wave_source_duration_cache: dict[str, float] = {}
        self._progressive_media_cache_tasks: deque[tuple] = deque()
        self._progressive_media_cache_task_keys: set[tuple] = set()
        self._media_cache_generation = 0
        self._media_cache_idle_timer = QTimer(self)
        self._media_cache_idle_timer.setSingleShot(True)
        self._media_cache_idle_timer.timeout.connect(self._on_media_cache_idle)
        self._pending_track_volume_commits: set[int] = set()
        self._thumbnail_ready.connect(self._on_thumbnail_ready)
        self._filmstrip_chunk_ready.connect(self._on_filmstrip_chunk_ready)
        self._waveform_peaks_ready.connect(self._on_waveform_peaks_ready)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.toolbar = self._build_transport()
        main_layout.addWidget(self.toolbar)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        self.sidebar = QWidget()
        self.sidebar.setObjectName("TimelineSidebar")
        self.sidebar.setFixedWidth(TRACK_HEADER_WIDTH)
        self.sidebar.setStyleSheet(
            f"QWidget#TimelineSidebar {{ background: {TIMELINE_BG_COLOR}; border: none; border-right: 1px solid #2a2f38; }}"
        )
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_layout.setSpacing(0)
        
        ruler_header = QWidget()
        ruler_header.setObjectName("TimelineRulerHeader")
        ruler_header.setFixedHeight(int(RULER_HEIGHT))
        ruler_header.setStyleSheet("QWidget#TimelineRulerHeader { background: #1a1d23; border-right: 1px solid #2a2f38; border-bottom: 1px solid #2a2f38; }")
        self.sidebar_layout.addWidget(ruler_header)
        
        self.headers_viewport = QWidget()
        self.headers_viewport.setObjectName("TimelineHeadersViewport")
        self.headers_viewport.setStyleSheet(
            f"QWidget#TimelineHeadersViewport {{ background: {TIMELINE_BG_COLOR}; border: none; border-right: 1px solid #2a2f38; }}"
        )
        self.sidebar_layout.addWidget(self.headers_viewport, 1)

        self.headers_list = QWidget(self.headers_viewport)
        self.headers_list.setObjectName("TimelineHeadersList")
        self.headers_list.setStyleSheet(
            f"QWidget#TimelineHeadersList {{ background: {TIMELINE_BG_COLOR}; border: none; border-right: 1px solid #2a2f38; }}"
        )
        self.headers_list_layout = QVBoxLayout(self.headers_list)
        self.headers_list_layout.setContentsMargins(0, 0, 0, 0)
        self.headers_list_layout.setSpacing(LANE_GAP)
        
        content_layout.addWidget(self.sidebar)

        self._scene = TimelineScene(self, self)
        self._scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self._scene.setBackgroundBrush(QBrush(QColor(TIMELINE_BG_COLOR)))
        self._clip_items_by_id: dict[int, ClipRect] = {}
        self._clip_items_by_source: dict[str, list[ClipRect]] = {}
        self._last_emitted_selection_key: tuple[int, ...] | None = None
        self._transient_scene_items: list[QGraphicsItem] = []
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._view = TimelineView(self._scene, self)
        self._view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._view.setStyleSheet(f"background: {TIMELINE_BG_COLOR}; border: none;")
        self._view.verticalScrollBar().valueChanged.connect(self._sync_header_scroll)
        content_layout.addWidget(self._view)
        
        main_layout.addWidget(content)
        self._ensure_unique_clip_ids()
        self.refresh()

    def _schedule_refresh(self) -> None:
        if self._pointer_active:
            self._pending_pointer_refresh = True
            return
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True

        def _do() -> None:
            self._refresh_scheduled = False
            self.refresh()

        QTimer.singleShot(0, _do)

    def schedule_refresh(self) -> None:
        self._schedule_refresh()

    def _set_pointer_active(self, active: bool) -> None:
        was_active = bool(self._pointer_active)
        self._pointer_active = bool(active)
        if was_active and not self._pointer_active:
            for item in getattr(self, "_clip_items_by_id", {}).values():
                if (
                    isinstance(item, ClipRect)
                    and not getattr(item, "_is_text_clip", False)
                    and not getattr(item, "_is_audio_clip", False)
                    and self._clip_intersects_visible_timeline(item.clip)
                ):
                    item.update()
            if hasattr(self, "_view"):
                self._view.viewport().update()
            self._bump_media_cache_idle()
        if self._pointer_active or not self._pending_pointer_refresh:
            return
        self._pending_pointer_refresh = False
        self._schedule_refresh()

    def _bump_media_cache_idle(self) -> None:
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            return
        try:
            self._media_cache_idle_timer.start(MEDIA_CACHE_IDLE_DELAY_MS)
        except RuntimeError:
            return

    def _schedule_progressive_media_cache(self) -> None:
        if not self._progressive_media_cache_tasks:
            return
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            return
        try:
            if not self._media_cache_idle_timer.isActive():
                self._media_cache_idle_timer.start(MEDIA_CACHE_PROGRESSIVE_DELAY_MS)
        except RuntimeError:
            return

    def _on_media_cache_idle(self) -> None:
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            self._bump_media_cache_idle()
            return
        visible_items = [
            item
            for item in getattr(self, "_clip_items_by_id", {}).values()
            if isinstance(item, ClipRect)
            and not getattr(item, "_is_text_clip", False)
            and self._clip_intersects_visible_timeline(item.clip)
        ]
        for item in visible_items:
            item.update()
        if visible_items and hasattr(self, "_view"):
            self._view.viewport().update()
        self._process_progressive_media_cache()

    def _build_transport(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet("background: #1a1d23; border-bottom: 1px solid #2a2f38;")
        bar.setFixedHeight(40)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(4)

        title = QLabel("TIMELINE")
        title.setStyleSheet(
            "font-weight: 800; color: #8c93a0; font-size: 11px; margin-right: 8px;"
        )
        h.addWidget(title)

        self._btn_undo = self._make_toolbar_button(
            "icon-editor-timeline-undo", "HoÃ n tÃ¡c", self.undo_requested.emit, fallback="U"
        )
        h.addWidget(self._btn_undo)

        self._btn_redo = self._make_toolbar_button(
            "icon-editor-timeline-redo", "LÃ m láº¡i", self.redo_requested.emit, fallback=""
        )
        h.addWidget(self._btn_redo)

        self._btn_delete = self._make_toolbar_button(
            "icon-editor-timeline-delete", "XÃ³a", self.ripple_delete_selected, fallback="D"
        )
        h.addWidget(self._btn_delete)

        self._btn_split = self._make_toolbar_button(
            "icon-editor-timeline-split", "Cáº¯t", self.split_at_playhead, fallback=""
        )
        h.addWidget(self._btn_split)

        self._btn_save = self._make_toolbar_button(
            "icon-editor-timeline-save", "LÆ°u", self.save_requested.emit, fallback="SV"
        )
        h.addWidget(self._btn_save)

        h.addStretch(1)

        self._btn_snap = self._make_toolbar_button(
            "icon-editor-timeline-snapping",
            "Báº¯t dÃ­nh",
            self._toggle_snapping,
            checkable=True,
            checked=self._snapping_enabled,
            fallback="SN",
        )
        h.addWidget(self._btn_snap)

        self._btn_main_magnet = self._make_toolbar_button(
            "icon-editor-timeline-main-magnet",
            "Hút vào đoạn chính",
            self._toggle_main_track_magnet,
            checkable=True,
            checked=self._main_track_magnet_enabled,
            fallback="MG",
        )
        h.addWidget(self._btn_main_magnet)

        self._btn_link = self._make_toolbar_button(
            "icon-editor-timeline-link",
            "Liên kết/Bỏ liên kết clip đã chọn",
            self._toggle_link_selected_clips,
            checkable=True,
            checked=False,
            fallback="LK",
        )
        h.addWidget(self._btn_link)

        self._btn_hover_scrub = self._make_toolbar_button(
            "icon-editor-timeline-hoverscrub",
            "DÃ­nh playhead theo chuá»™t (S)",
            self._toggle_hover_scrub,
            checkable=True,
            checked=self._hover_scrub_enabled,
            fallback="HS",
        )
        self._btn_hover_scrub.setToolTip("Báº­t/Táº¯t dÃ­nh Playhead vÃ o chuá»™t (Hover Scrub) - phÃ­m táº¯t: S")
        h.addWidget(self._btn_hover_scrub)

        self._btn_opengl = self._make_toolbar_button(
            "icon-editor-timeline-opengl",
            "OpenGL cho timeline",
            self._toggle_opengl_viewport,
            checkable=True,
            checked=self._use_opengl_viewport,
            fallback="GL",
        )
        self._btn_opengl.setToolTip("Báº­t/Táº¯t OpenGL cho timeline (thá»­ nghiá»‡m GPU paint)")
        h.addWidget(self._btn_opengl)

        zoom_divider = QFrame()
        zoom_divider.setFrameShape(QFrame.Shape.VLine)
        zoom_divider.setStyleSheet("color: #2a2f38;")
        h.addWidget(zoom_divider)

        self._btn_zoom_out = self._make_toolbar_button(
            "icon-editor-timeline-zoommin",
            "Thu nhá» timeline",
            lambda: self._nudge_zoom(-10),
            fallback="-",
        )
        h.addWidget(self._btn_zoom_out)

        self._zoom = QSlider(Qt.Orientation.Horizontal)
        self._zoom.setRange(ZOOM_MIN, ZOOM_MAX)
        self._zoom.setValue(100)
        self._zoom.setFixedWidth(92)
        self._zoom.setStyleSheet(
            """
            QSlider { background: transparent; border: none; }
            QSlider::groove:horizontal { background: #2a2f38; height: 2px; border-radius: 1px; }
            QSlider::sub-page:horizontal { background: #22d3c5; height: 2px; border-radius: 1px; }
            QSlider::handle:horizontal { background: #22d3c5; width: 10px; height: 10px; margin: -4px 0; border-radius: 5px; }
            """
        )
        self._zoom.valueChanged.connect(self._on_zoom_changed)
        h.addWidget(self._zoom)

        self._btn_zoom_in = self._make_toolbar_button(
            "icon-editor-timeline-zoommax",
            "PhÃ³ng to timeline",
            lambda: self._nudge_zoom(10),
            fallback="+",
        )
        h.addWidget(self._btn_zoom_in)
        self._refresh_toggle_icons()
        return bar

    def _make_toolbar_button(
        self,
        symbol_id: str,
        tip: str,
        slot=None,
        *,
        checkable: bool = False,
        checked: bool = False,
        fallback: str = "",
    ) -> QToolButton:
        btn = QToolButton()
        btn.setToolTip(tip)
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            """
            QToolButton {
                border: none;
                border-radius: 4px;
                background: transparent;
                color: #8c93a0;
                font-size: 11px;
            }
            QToolButton:hover { background: #2a2f38; }
            QToolButton:checked { background: rgba(34, 211, 197, 0.16); }
            QToolButton:disabled {
                color: #4a505c;
                background: transparent;
            }
            QToolTip {
                color: #dce6f2;
                background: #11161f;
                border: 1px solid #2a2f38;
                padding: 4px 6px;
            }
            """
        )
        btn.setCheckable(checkable)
        btn.setChecked(checked)
        btn.setProperty("symbol_id", symbol_id)
        btn.setProperty("fallback_text", fallback)
        if slot is not None:
            if checkable:
                btn.toggled.connect(lambda _checked, cb=slot: cb())
            else:
                btn.clicked.connect(lambda _checked=False, cb=slot: cb())
        self._apply_button_icon(btn, active=checked)
        return btn

    def _apply_button_icon(self, btn: QToolButton, *, active: bool) -> None:
        symbol_id = str(btn.property("symbol_id"))
        fallback = str(btn.property("fallback_text") or "")
        icon_size = 14

        # Use custom drawn icon for parity with editor_app.py
        if symbol_id == "icon-editor-timeline-hoverscrub":
            icon = _custom_hover_scrub_icon(active=active, size=18)
            icon_size = 18
        elif symbol_id == "icon-editor-timeline-opengl":
            icon = _custom_opengl_icon(active=active, size=18)
            icon_size = 18
        else:
            icon = _timeline_icon(
                symbol_id, ICON_ACTIVE if active else ICON_NORMAL, size=14
            )
        if icon.isNull():
            btn.setIcon(QIcon())
            btn.setText(fallback)
            return
        btn.setText("")
        btn.setIcon(icon)
        btn.setIconSize(QSize(icon_size, icon_size))

    def _refresh_play_icon(self) -> None:
        btn = getattr(self, "_btn_play", None)
        if btn is None:
            return
        is_playing = getattr(self, "_is_playing", False)
        symbol_id = "icon-editor-timeline-pause" if is_playing else "icon-editor-timeline-play"
        fallback = "||" if is_playing else ">"
        btn.setProperty("symbol_id", symbol_id)
        btn.setProperty("fallback_text", fallback)
        self._apply_button_icon(btn, active=is_playing)
        # Disable play button if timeline is empty
        has_clips = any(len(track.clips) > 0 for track in self._project.tracks)
        btn.setEnabled(has_clips)
    def _refresh_toggle_icons(self) -> None:
        self._apply_button_icon(self._btn_snap, active=self._snapping_enabled)
        if hasattr(self, "_btn_main_magnet"):
            self._apply_button_icon(
                self._btn_main_magnet, active=self._main_track_magnet_enabled
            )
        if hasattr(self, "_btn_link"):
            has_linked = False
            selected_count = 0
            if hasattr(self, "_scene"):
                selected = self.selected_clips()
                selected_count = len(selected)
                has_linked = any(
                    getattr(clip, "link_group_id", None)
                    for clip in selected
                )
            active = bool(self._linked_selection_enabled or has_linked)
            blocker = QSignalBlocker(self._btn_link)
            try:
                self._btn_link.setChecked(active)
            finally:
                del blocker
            self._btn_link.setEnabled(True)
            if selected_count >= 2:
                tip = "LiÃªn káº¿t/Bá» liÃªn káº¿t clip Ä‘Ã£ chá»n"
            else:
                state = "Báº¬T" if self._linked_selection_enabled else "Táº®T"
                tip = f"Linked Selection: {state} (chọn 2+ clip để tạo liên kết)"
            self._btn_link.setToolTip(tip)
            self._apply_button_icon(self._btn_link, active=active)
        if hasattr(self, "_btn_hover_scrub"):
            self._apply_button_icon(
                self._btn_hover_scrub, active=self._hover_scrub_enabled
            )
        if hasattr(self, "_btn_opengl"):
            self._apply_button_icon(
                self._btn_opengl, active=self._use_opengl_viewport
            )

    def set_history_state(self, *, can_undo: bool, can_redo: bool) -> None:
        self._btn_undo.setEnabled(bool(can_undo))
        self._btn_redo.setEnabled(bool(can_redo))
        self._apply_button_icon(self._btn_undo, active=bool(can_undo))
        self._apply_button_icon(self._btn_redo, active=bool(can_redo))

    def _on_playpause_clicked(self) -> None:
        self._is_playing = not self._is_playing
        self.playpause_requested.emit()

    def set_playing_state(self, playing: bool) -> None:
        was_playing = self._is_playing
        self._is_playing = bool(playing)
        if was_playing and not self._is_playing:
            self._bump_media_cache_idle()
            self._set_pointer_active(False)
            self._refresh_playhead()

    def set_speed_issue_clip_ids(self, ids: set[int]) -> None:
        new_ids = set(ids) if ids else set()
        if new_ids == self._speed_issue_clip_ids:
            return
        old_ids = self._speed_issue_clip_ids
        affected = old_ids ^ new_ids
        self._speed_issue_clip_ids = new_ids
        if not hasattr(self, "_scene") or self._scene is None:
            return
        for item in self._scene.items():
            if isinstance(item, ClipRect) and id(item.clip) in affected:
                item.update()

    def _toggle_snapping(self) -> None:
        self._set_snapping_enabled(self._btn_snap.isChecked())

    def _toggle_auto_track_magnet(self) -> None:
        # Backward-compatible alias for older toolbar wiring/tests.
        self._toggle_snapping()

    def _set_snapping_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._snapping_enabled = enabled
        if hasattr(self, "_btn_snap"):
            blocker_snap = QSignalBlocker(self._btn_snap)
            try:
                self._btn_snap.setChecked(enabled)
            finally:
                del blocker_snap
        self._refresh_toggle_icons()

    def is_snapping_enabled(self) -> bool:
        return bool(self._snapping_enabled)

    def is_main_track_magnet_enabled(self) -> bool:
        return bool(self._main_track_magnet_enabled)

    def _toggle_main_track_magnet(self) -> None:
        self._set_main_track_magnet_enabled(self._btn_main_magnet.isChecked())

    def _set_main_track_magnet_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._main_track_magnet_enabled = enabled
        if hasattr(self, "_btn_main_magnet"):
            blocker = QSignalBlocker(self._btn_main_magnet)
            try:
                self._btn_main_magnet.setChecked(enabled)
            finally:
                del blocker
        changed = self.normalize_main_track_magnetic() if enabled else False
        self._refresh_toggle_icons()
        if changed:
            self.refresh()
            self.project_mutated.emit()

    def _toggle_link_selected_clips(self) -> None:
        selected = self.selected_clips()
        if not selected:
            self._linked_selection_enabled = bool(self._btn_link.isChecked())
            self._refresh_toggle_icons()
            return
        self._ensure_unique_clip_ids()

        linked_groups = {
            str(getattr(clip, "link_group_id", "") or "")
            for clip in selected
            if getattr(clip, "link_group_id", None)
        }
        has_linked = bool(linked_groups) or any(
            getattr(clip, "linked_parent_id", None) for clip in selected
        )
        if has_linked:
            targets = self._expanded_linked_clips(selected)
            for clip in targets:
                self._clear_link_fields(clip)
            self.refresh()
            self.select_clips(targets)
            self.project_mutated.emit()
            return

        if len(selected) < 2:
            self._linked_selection_enabled = bool(self._btn_link.isChecked())
            self._refresh_toggle_icons()
            return
        parent = self._choose_link_parent(selected)
        if parent is None:
            return
        self._linked_selection_enabled = True
        group_id = uuid4().hex
        parent.link_group_id = group_id
        parent.linked_parent_id = None
        parent.linked_offset = 0.0
        for clip in selected:
            clip.link_group_id = group_id
            if clip is parent:
                continue
            clip.linked_parent_id = parent.clip_id
            clip.linked_offset = float(clip.start) - float(parent.start)
        self.refresh()
        self.select_clips(selected)
        self.project_mutated.emit()

    def _toggle_hover_scrub(self) -> None:
        self._hover_scrub_enabled = self._btn_hover_scrub.isChecked()
        if not self._hover_scrub_enabled:
            self._view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._refresh_toggle_icons()

    def _toggle_opengl_viewport(self) -> None:
        self._set_opengl_viewport_enabled(self._btn_opengl.isChecked())

    def _set_opengl_viewport_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        ok = self._view.set_opengl_viewport_enabled(enabled)
        self._use_opengl_viewport = bool(enabled and ok)
        if hasattr(self, "_btn_opengl"):
            blocker = QSignalBlocker(self._btn_opengl)
            try:
                self._btn_opengl.setChecked(self._use_opengl_viewport)
            finally:
                del blocker
            if enabled and not ok:
                tip = "OpenGL timeline: khÃ´ng kháº£ dá»¥ng"
            else:
                tip = f"OpenGL timeline: {'Báº¬T' if self._use_opengl_viewport else 'Táº®T'}"
            self._btn_opengl.setToolTip(tip)
        self._refresh_toggle_icons()
        self._schedule_refresh()

    def is_hover_scrub_enabled(self) -> bool:
        return bool(self._hover_scrub_enabled)

    def _nudge_zoom(self, delta: int) -> None:
        self._zoom.setValue(max(ZOOM_MIN, min(ZOOM_MAX, self._zoom.value() + delta)))

    def apply_clip_snap(self, moving_clip: Clip, start_seconds: float) -> float:
        raw_start = max(0.0, float(start_seconds))
        if not self._snapping_enabled:
            return raw_start

        # Ported from editor_app.py::handle_drag
        # Priority:
        # 1) snap start/end to playhead
        # 2) snap start->other.end OR end->other.start
        clip_duration = max(0.0, float(moving_clip.timeline_duration or 0.0))
        raw_end = raw_start + clip_duration
        snap_t = self._snap_tolerance_seconds()

        # Priority 1: playhead
        playhead = max(0.0, float(self._playhead_seconds))
        start_to_playhead = abs(raw_start - playhead)
        if start_to_playhead <= snap_t:
            return playhead
        if clip_duration > 0.0 and abs(raw_end - playhead) <= snap_t:
            return max(0.0, playhead - clip_duration)

        # Priority 2: other clip edges across all tracks (global snapping)
        best_start = raw_start
        best_dist = float("inf")
        for edge in self._iter_snap_edges(exclude_clip=moving_clip):
            dist_start = abs(raw_start - edge)
            if dist_start <= snap_t and dist_start < best_dist:
                best_dist = dist_start
                best_start = edge
            if clip_duration > 0.0:
                dist_end = abs(raw_end - edge)
                if dist_end <= snap_t and dist_end < best_dist:
                    best_dist = dist_end
                    best_start = max(0.0, edge - clip_duration)
        return best_start

    def apply_trim_snap(self, moving_clip: Clip, edge: str, edge_seconds: float) -> float:
        raw_edge = max(0.0, float(edge_seconds))
        if not self._snapping_enabled:
            return raw_edge
        edge_n = (edge or "").strip().lower()
        if edge_n not in {"left", "right"}:
            return raw_edge
        snap_t = self._snap_tolerance_seconds()
        candidates = [0.0, max(0.0, float(self._playhead_seconds))]
        candidates.extend(self._iter_snap_edges(exclude_clip=moving_clip))
        snapped = raw_edge
        best_dist = snap_t + 1.0
        for cand in candidates:
            dist = abs(raw_edge - cand)
            if dist <= snap_t and dist < best_dist:
                snapped = cand
                best_dist = dist
        return snapped

    def _snap_tolerance_seconds(self) -> float:
        return SNAP_TOLERANCE_PX / max(1.0, self._pixels_per_second)

    def _iter_snap_edges(self, *, exclude_clip: Clip | None = None):
        yield from timeline_snap_times(self._project, exclude_clip=exclude_clip)

    def _snap_playhead_time(self, raw_seconds: float) -> float:
        # Ported from editor_app.py::handle_scrub
        # Snap playhead to nearest clip edge across all tracks when magnet is enabled.
        t = max(0.0, raw_seconds)
        if not self._snapping_enabled:
            return t
        snap_t = self._snap_tolerance_seconds()
        best_dist = float("inf")
        snapped = t
        for edge in self._iter_snap_edges():
            dist = abs(t - edge)
            if dist < snap_t and dist < best_dist:
                best_dist = dist
                snapped = edge
        return snapped

    def _snap_start(
        self,
        start_seconds: float,
        *,
        clip_duration: float | None = None,
        moving_clip: Clip | None = None,
    ) -> float:
        start_seconds = max(0.0, start_seconds)
        if not self._snapping_enabled:
            return start_seconds

        threshold_seconds = self._snap_tolerance_seconds()
        duration = max(0.0, float(clip_duration or 0.0))
        end_seconds = start_seconds + duration

        # Keep 00:00 as a stable snap anchor for external imports.
        candidates = [0.0, max(0.0, float(self._playhead_seconds))]
        candidates.extend(self._iter_snap_edges(exclude_clip=moving_clip))

        snapped = start_seconds
        best_delta = threshold_seconds + 1.0
        for cand in candidates:
            delta = abs(cand - start_seconds)
            if delta <= threshold_seconds and delta < best_delta:
                snapped = cand
                best_delta = delta
            if duration > 0.0:
                end_delta = abs(cand - end_seconds)
                if end_delta <= threshold_seconds and end_delta < best_delta:
                    snapped = max(0.0, cand - duration)
                    best_delta = end_delta
        return snapped

    @staticmethod
    def _media_kind_for_path(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in AUDIO_EXTS:
            return "audio"
        if ext in SUBTITLE_EXTS:
            return "text"
        return "video"

    def _timeline_has_clips(self) -> bool:
        for track in self._project.tracks:
            if track.clips:
                return True
        return False

    def _track_count_for_kind(self, kind: str) -> int:
        return sum(
            1
            for track in self._project.tracks
            if track.kind == kind
            and not (kind == "video" and self._is_main_track(track))
        )

    def _clip_count_for_kind(self, kind: str) -> int:
        return sum(
            len(track.clips)
            for track in self._project.tracks
            if track.kind == kind
        )

    def _can_create_track_for_clip(
        self,
        kind: str,
        clip: Clip,
        source_track: Track,
    ) -> bool:
        max_tracks = max(1, self._clip_count_for_kind(kind))
        if self._track_count_for_kind(kind) < max_tracks:
            return True
        if self._is_main_track(source_track):
            return False
        return clip in source_track.clips and len(source_track.clips) == 1

    def _new_track_name_for_kind(self, kind: str) -> str:
        label = {"audio": "Audio", "text": "Text", "video": "Video"}.get(
            kind,
            kind.title(),
        )
        return f"{label} {self._track_count_for_kind(kind) + 1}"

    def _update_empty_drop_preview_state(self, *, dragging_media_kind: str | None) -> None:
        should_show = (
            dragging_media_kind == "video"
            and not self._timeline_has_clips()
        )
        if should_show == self._empty_drop_preview_visible:
            return
        self._empty_drop_preview_visible = should_show
        # Defer refresh to avoid clearing scene during drag/drop event processing
        QTimer.singleShot(0, self.refresh)

    def begin_external_drag_preview(self, path: Path) -> None:
        self._update_empty_drop_preview_state(
            dragging_media_kind=self._media_kind_for_path(path)
        )

    def update_external_drag_preview(self, path: Path) -> None:
        self._update_empty_drop_preview_state(
            dragging_media_kind=self._media_kind_for_path(path)
        )

    def end_external_drag_preview(self) -> None:
        if not self._empty_drop_preview_visible:
            return
        self._empty_drop_preview_visible = False
        # Defer refresh to avoid clearing scene during drag/drop event processing
        QTimer.singleShot(0, self.refresh)

    def _scene_duration_seconds(self) -> float:
        has_any_clips = any(bool(track.clips) for track in self._project.tracks)
        if not has_any_clips:
            # Empty project should fit current viewport (no phantom horizontal scroll).
            return 0.0
        timeline_end = max(self._timeline_end_seconds(), self._playhead_seconds)
        if timeline_end <= 0.0:
            return 60.0
        # Follow media length once clips exist (CapCut-like first-drop behavior).
        return max(8.0, timeline_end + 5.0)

    def _timeline_end_seconds(self) -> float:
        cached = self._timeline_end_cache
        if cached is not None:
            return cached
        try:
            end = max(0.0, float(self._project.duration))
        except Exception:
            end = 0.0
        self._timeline_end_cache = end
        return end

    def _clamp_playhead_seconds(self, seconds: float) -> float:
        try:
            s = max(0.0, float(seconds))
        except Exception:
            s = 0.0
        end = self._timeline_end_seconds()
        if end > 0.0:
            return min(s, end)
        return 0.0

    def _visible_scene_right(self) -> float:
        viewport_w = float(self._view.viewport().width())
        if viewport_w <= 0.0:
            viewport_w = float(self._view.width())
        scroll_left = float(self._view.horizontalScrollBar().value())
        return max(0.0, scroll_left + max(0.0, viewport_w))

    @staticmethod
    def _main_track_index_in_tracks(tracks: list[Track]) -> int | None:
        for i, track in enumerate(tracks):
            if track.kind == "video" and track.name.strip().lower() == "main":
                return i
        for i, track in enumerate(tracks):
            if track.kind == "video":
                return i
        return None

    def _main_track_index(self) -> int | None:
        return self._main_track_index_in_tracks(self._project.tracks)

    @staticmethod
    def _is_track_locked(track: Track) -> bool:
        return bool(getattr(track, "locked", False))

    @staticmethod
    def _is_track_hidden(track: Track) -> bool:
        return bool(getattr(track, "hidden", False))

    @staticmethod
    def _is_track_muted(track: Track) -> bool:
        return bool(getattr(track, "muted", False))

    def _track_lane_color(self, track: Track, *, is_main_lane: bool) -> QColor:
        lane_color = QColor("#16181d")
        if self._is_track_hidden(track):
            lane_color = QColor("#202a2a")
        if self._empty_drop_preview_visible and is_main_lane:
            lane_color = QColor("#60656f")
        return lane_color

    def _nearest_unlocked_track_index(self, kind: str, anchor_idx: int) -> int | None:
        best_idx: int | None = None
        best_dist: int | None = None
        for idx, track in enumerate(self._project.tracks):
            if track.kind != kind or self._is_track_locked(track):
                continue
            dist = abs(idx - anchor_idx)
            if best_idx is None or best_dist is None or dist < best_dist:
                best_idx = idx
                best_dist = dist
        return best_idx

    def _constrain_insert_index_for_kind(self, kind: str, insert_idx: int) -> int:
        safe_idx = max(0, min(int(insert_idx), len(self._project.tracks)))
        main_idx = self._main_track_index()
        if main_idx is None:
            return safe_idx
        if kind == "audio":
            return max(main_idx + 1, safe_idx)
        if kind in {"text", "video"}:
            return min(main_idx, safe_idx)
        return safe_idx

    def _drop_target_for_kind_zone(
        self,
        kind: str,
        idx: int,
        insert_new_track: bool,
    ) -> tuple[int, bool]:
        main_idx = self._main_track_index()
        if main_idx is None:
            if insert_new_track:
                return self._constrain_insert_index_for_kind(kind, idx), True
            return idx, False

        if insert_new_track:
            return self._constrain_insert_index_for_kind(kind, idx), True

        if kind == "audio":
            if (
                main_idx < idx < len(self._project.tracks)
                and self._project.tracks[idx].kind == "audio"
                and not self._is_track_locked(self._project.tracks[idx])
            ):
                return idx, False
            anchor = max(main_idx + 1, idx)
            alt_idx = self._nearest_unlocked_track_index("audio", anchor)
            if alt_idx is not None and alt_idx > main_idx:
                return alt_idx, False
            return main_idx + 1, True

        if kind in {"text", "video"}:
            if (
                0 <= idx < len(self._project.tracks)
                and self._project.tracks[idx].kind == kind
                and not self._is_track_locked(self._project.tracks[idx])
                and idx <= main_idx
            ):
                return idx, False
            anchor = min(main_idx, max(0, idx))
            alt_idx = self._nearest_unlocked_track_index(kind, anchor)
            if alt_idx is not None and alt_idx <= main_idx:
                return alt_idx, False
            return main_idx, True

        return idx, False

    def _track_height_for(self, track: Track, idx: int, main_idx: int | None) -> float:
        if track.kind == "text":
            return max(20.0, TRACK_HEIGHT * TEXT_TRACK_HEIGHT_FACTOR)
        if track.kind == "audio":
            return max(40.0, TRACK_HEIGHT * AUDIO_TRACK_HEIGHT_FACTOR)
        if main_idx is not None and idx == main_idx and track.kind == "video":
            return TRACK_HEIGHT * MAIN_TRACK_HEIGHT_FACTOR
        return TRACK_HEIGHT

    def _track_layout_data(
        self,
        tracks: list[Track] | None = None,
    ) -> tuple[list[Track], list[float], list[float], int | None]:
        tracks_list = tracks if tracks is not None else self._project.tracks
        if not tracks_list:
            tracks_list = [Track(name="Main", kind="video")]

        main_idx = self._main_track_index_in_tracks(tracks_list)
        heights = [
            self._track_height_for(track, idx, main_idx)
            for idx, track in enumerate(tracks_list)
        ]
        viewport_h = self._timeline_viewport_height()
        content_h = max(0.0, viewport_h - RULER_HEIGHT)
        padding = TRACK_EDGE_PADDING if tracks_list else 0.0
        usable_h = max(0.0, content_h - padding * 2.0)
        top_limit = RULER_HEIGHT + padding
        total_h = sum(heights) + max(0, len(heights) - 1) * LANE_GAP

        if total_h >= usable_h:
            first_track_y = top_limit
        elif main_idx is None:
            first_track_y = top_limit + max(0.0, (usable_h - total_h) / 2.0)
        else:
            main_h = heights[main_idx]
            main_top = top_limit + (usable_h - main_h) / 2.0
            before_h = sum(heights[:main_idx]) + main_idx * LANE_GAP
            first_track_y = main_top - before_h
            max_first_y = RULER_HEIGHT + max(0.0, content_h - padding - total_h)
            first_track_y = max(top_limit, min(first_track_y, max_first_y))

        tops: list[float] = []
        y = first_track_y
        for h in heights:
            tops.append(y)
            y += h + LANE_GAP
        return tracks_list, tops, heights, main_idx

    def _track_index_for_clip(self, clip: Clip) -> int | None:
        for idx, track in enumerate(self._project.tracks):
            if clip in track.clips:
                return idx
        return None

    def _selected_clip_items(self) -> list[ClipRect]:
        return [it for it in self._scene.selectedItems() if isinstance(it, ClipRect)]

    def _find_clip_location(self, clip: Clip) -> tuple[Track, int, int] | None:
        for track_idx, track in enumerate(self._project.tracks):
            for clip_idx, track_clip in enumerate(track.clips):
                if track_clip is clip:
                    return track, track_idx, clip_idx
        return None

    def _all_timeline_clips(self) -> list[Clip]:
        return [clip for track in self._project.tracks for clip in track.clips]

    def _ensure_unique_clip_ids(self) -> bool:
        changed = False
        seen: set[str] = set()
        for clip in self._all_timeline_clips():
            clip_id = str(getattr(clip, "clip_id", "") or "").strip()
            if not clip_id or clip_id in seen:
                clip.clip_id = uuid4().hex
                clip_id = str(clip.clip_id)
                changed = True
            seen.add(clip_id)
        return changed

    def _find_clip_by_clip_id(self, clip_id: str | None) -> Clip | None:
        if not clip_id:
            return None
        target = str(clip_id)
        for clip in self._all_timeline_clips():
            if str(getattr(clip, "clip_id", "")) == target:
                return clip
        return None

    def _main_track(self) -> Track | None:
        main_idx = self._main_track_index()
        if main_idx is None or main_idx < 0 or main_idx >= len(self._project.tracks):
            return None
        return self._project.tracks[main_idx]

    def _is_main_track(self, track: Track) -> bool:
        main = self._main_track()
        return main is track and track.kind == "video"

    def _is_main_video_clip(self, clip: Clip) -> bool:
        loc = self._find_clip_location(clip)
        return loc is not None and self._is_main_track(loc[0])

    def _clips_for_link_group(self, group_id: str | None) -> list[Clip]:
        if not group_id:
            return []
        gid = str(group_id)
        return [
            clip
            for clip in self._all_timeline_clips()
            if str(getattr(clip, "link_group_id", "") or "") == gid
        ]

    def _choose_link_parent(self, clips: list[Clip]) -> Clip | None:
        if not clips:
            return None
        for clip in clips:
            if self._is_main_video_clip(clip):
                return clip
        for clip in clips:
            loc = self._find_clip_location(clip)
            if loc is not None and loc[0].kind == "video":
                return clip
        return min(clips, key=lambda c: (float(c.start), str(getattr(c, "clip_id", ""))))

    def _link_parent_for_clip(self, clip: Clip) -> Clip | None:
        parent = self._find_clip_by_clip_id(getattr(clip, "linked_parent_id", None))
        if parent is not None:
            return parent
        group = self._clips_for_link_group(getattr(clip, "link_group_id", None))
        if not group:
            return clip
        group_ids = {str(getattr(c, "clip_id", "")) for c in group}
        for candidate in group:
            parent_id = str(getattr(candidate, "linked_parent_id", "") or "")
            if not parent_id or parent_id not in group_ids:
                return candidate
        return self._choose_link_parent(group)

    def _expanded_linked_clips(self, clips: list[Clip]) -> list[Clip]:
        ordered: list[Clip] = []
        seen: set[int] = set()

        def add(clip: Clip) -> None:
            if id(clip) not in seen:
                ordered.append(clip)
                seen.add(id(clip))

        for clip in clips:
            add(clip)
            group_id = getattr(clip, "link_group_id", None)
            if group_id:
                for linked in self._clips_for_link_group(str(group_id)):
                    add(linked)
        return ordered

    def _sync_linked_children_to_parent(
        self,
        parent: Clip,
        *,
        skip_main_track: bool = False,
    ) -> bool:
        changed = False
        parent_id = str(getattr(parent, "clip_id", "") or "")
        if not parent_id:
            return False
        for child in self._all_timeline_clips():
            if child is parent:
                continue
            if str(getattr(child, "linked_parent_id", "") or "") != parent_id:
                continue
            if skip_main_track and self._is_main_video_clip(child):
                continue
            desired = max(0.0, float(parent.start) + float(getattr(child, "linked_offset", 0.0) or 0.0))
            if abs(float(child.start) - desired) > 1e-6:
                child.start = desired
                changed = True
        return changed

    def _sync_linked_after_clip_move(self, clip: Clip) -> bool:
        group_id = getattr(clip, "link_group_id", None)
        if group_id and self._linked_selection_enabled:
            parent = self._link_parent_for_clip(clip)
            if parent is None:
                return False
            if parent is not clip:
                desired_parent_start = max(
                    0.0,
                    float(clip.start) - float(getattr(clip, "linked_offset", 0.0) or 0.0),
                )
                if abs(float(parent.start) - desired_parent_start) > 1e-6:
                    parent.start = desired_parent_start
            return self._sync_linked_children_to_parent(parent)

        if getattr(clip, "linked_parent_id", None):
            parent = self._find_clip_by_clip_id(getattr(clip, "linked_parent_id", None))
            if parent is not None:
                clip.linked_offset = float(clip.start) - float(parent.start)
                return True
            clip.linked_parent_id = None
            clip.linked_offset = 0.0
            return True

        return self._sync_linked_children_to_parent(clip)

    def _clip_overlaps_range(self, clip: Clip, start: float, end: float) -> bool:
        duration = max(0.0, float(clip.timeline_duration or 0.0))
        if duration <= 0.0:
            return False
        clip_start = float(clip.start)
        clip_end = clip_start + duration
        return clip_start < end and clip_end > start

    def _begin_live_link_follow(self, parent: Clip, *, origin_start: float) -> None:
        self._live_link_parent_runtime_id = id(parent)
        self._live_link_parent_origin_start = max(0.0, float(origin_start))
        self._live_link_follow_snapshot = {}
        if not self._linked_selection_enabled:
            return

        parent_duration = max(0.0, float(parent.timeline_duration or 0.0))
        parent_old_end = self._live_link_parent_origin_start + parent_duration
        parent_id = str(getattr(parent, "clip_id", "") or "")
        parent_group_id = str(getattr(parent, "link_group_id", "") or "")
        for child in self._all_timeline_clips():
            if child is parent:
                continue
            child_loc = self._find_clip_location(child)
            if child_loc is None:
                continue
            child_track, _, _ = child_loc
            if self._is_track_locked(child_track):
                continue

            mode: str | None = None
            if (
                parent_id
                and str(getattr(child, "linked_parent_id", "") or "") == parent_id
            ):
                mode = "linked_offset"
            elif (
                parent_group_id
                and str(getattr(child, "link_group_id", "") or "") == parent_group_id
            ):
                mode = "delta"
            elif (
                self._is_main_video_clip(parent)
                and not self._is_main_track(child_track)
                and not getattr(child, "link_group_id", None)
                and not getattr(child, "linked_parent_id", None)
                and self._clip_overlaps_range(
                    child,
                    self._live_link_parent_origin_start,
                    parent_old_end,
                )
            ):
                mode = "delta"

            if mode is not None:
                item = self._clip_items_by_id.get(id(child))
                child_lane_y = float(item._lane_y) if item is not None else 0.0
                self._live_link_follow_snapshot[id(child)] = (
                    child,
                    float(child.start),
                    mode,
                    child_lane_y,
                )

    def _clear_live_link_follow(self) -> None:
        self._live_link_parent_runtime_id = None
        self._live_link_parent_origin_start = 0.0
        self._live_link_follow_snapshot = {}

    def _move_clip_item_live(self, clip: Clip, *, visual_y: float | None = None) -> None:
        item = self._clip_items_by_id.get(id(clip))
        if item is None:
            return
        item._updating_layout = True
        try:
            item.setPos(
                self.seconds_to_pixels(float(clip.start)),
                item._lane_y if visual_y is None else float(visual_y),
            )
        finally:
            item._updating_layout = False
        item.update()

    def _update_live_link_follow(
        self,
        parent: Clip,
        *,
        origin_start: float,
        parent_start: float,
        parent_scene_y: float | None = None,
        parent_lane_y: float | None = None,
    ) -> bool:
        if self._live_link_parent_runtime_id != id(parent):
            self._begin_live_link_follow(parent, origin_start=origin_start)
        if self._live_link_parent_runtime_id != id(parent):
            return False
        if not self._live_link_follow_snapshot:
            return False

        new_parent_start = max(0.0, float(parent_start))
        delta = new_parent_start - self._live_link_parent_origin_start
        visual_y_delta = 0.0
        if parent_scene_y is not None and parent_lane_y is not None:
            visual_y_delta = float(parent_scene_y) - float(parent_lane_y)
        changed = False
        for child, child_origin_start, mode, child_lane_y in list(self._live_link_follow_snapshot.values()):
            if self._find_clip_location(child) is None:
                continue
            if mode == "linked_offset":
                desired = max(
                    0.0,
                    new_parent_start + float(getattr(child, "linked_offset", 0.0) or 0.0),
                )
            else:
                desired = max(0.0, child_origin_start + delta)
            moved_x = abs(float(child.start) - desired) > 1e-6
            child.start = desired
            self._move_clip_item_live(child, visual_y=child_lane_y + visual_y_delta)
            changed = changed or moved_x or abs(visual_y_delta) > 1e-6
        return changed

    def _sync_overlap_children_after_parent_move(
        self,
        parent: Clip,
        *,
        origin_start: float | None,
    ) -> bool:
        """Move unlinked clips that visually live under a moved Main clip.

        This keeps LK useful as a mode: users can turn it on first, then drag
        the main media and have overlapping audio/text/effect clips follow.
        Explicit link groups still take priority and are skipped here.
        """
        if not self._linked_selection_enabled or not self._is_main_video_clip(parent):
            return False
        if origin_start is None:
            return False
        try:
            old_start = max(0.0, float(origin_start))
            new_start = max(0.0, float(parent.start))
        except Exception:
            return False
        delta = new_start - old_start
        if abs(delta) <= 1e-6:
            return False
        parent_duration = max(0.0, float(parent.timeline_duration or 0.0))
        if parent_duration <= 0.0:
            return False
        old_end = old_start + parent_duration
        changed = False
        for child in self._all_timeline_clips():
            if child is parent:
                continue
            if getattr(child, "link_group_id", None) or getattr(child, "linked_parent_id", None):
                continue
            child_loc = self._find_clip_location(child)
            if child_loc is None:
                continue
            child_track, _, _ = child_loc
            if self._is_main_track(child_track) or self._is_track_locked(child_track):
                continue
            child_duration = max(0.0, float(child.timeline_duration or 0.0))
            if child_duration <= 0.0:
                continue
            child_start = float(child.start)
            child_end = child_start + child_duration
            overlaps_old_parent = child_start < old_end and child_end > old_start
            if not overlaps_old_parent:
                continue
            child.start = max(0.0, child_start + delta)
            changed = True
        return changed

    def _clear_link_fields(self, clip: Clip) -> None:
        clip.link_group_id = None
        clip.linked_parent_id = None
        clip.linked_offset = 0.0

    def _unlink_orphaned_children(self) -> bool:
        existing_ids = {
            str(getattr(clip, "clip_id", "") or "")
            for clip in self._all_timeline_clips()
        }
        changed = False
        for clip in self._all_timeline_clips():
            parent_id = str(getattr(clip, "linked_parent_id", "") or "")
            if parent_id and parent_id not in existing_ids:
                clip.linked_parent_id = None
                clip.linked_offset = 0.0
                changed = True
        return changed

    def normalize_main_track_magnetic(self) -> bool:
        if not self._main_track_magnet_enabled:
            return False
        track = self._main_track()
        if track is None or track.kind != "video" or not track.clips:
            return False

        changed = self._ensure_unique_clip_ids()
        track.clips.sort(key=lambda c: (float(c.start), str(getattr(c, "clip_id", ""))))
        cursor = 0.0
        for clip in track.clips:
            duration = max(0.0, float(clip.timeline_duration or 0.0))
            if duration <= 0.0:
                continue
            old_start = float(clip.start)
            if abs(old_start - cursor) > 1e-6:
                clip.start = cursor
                changed = True
                if self._sync_linked_children_to_parent(clip, skip_main_track=True):
                    changed = True
            cursor += duration
        track.clips.sort(key=lambda c: (float(c.start), str(getattr(c, "clip_id", ""))))
        normalize_track_transitions(track)
        return changed

    def _refresh_and_reselect(self, clip: Clip | None = None) -> None:
        self.refresh()
        if clip is None:
            return
        self.select_clip(clip)

    def select_clip(self, clip: Clip | None) -> None:
        self.select_clips([clip] if clip is not None else [])

    def selected_clips(self) -> list[Clip]:
        return [it.clip for it in self._selected_clip_items()]

    def select_clips(self, clips: list[Clip]) -> None:
        if self._linked_selection_enabled and not self._suppress_linked_selection:
            clips = self._expanded_linked_clips([c for c in clips if c is not None])
        clip_ids = {id(c) for c in clips}
        blocker = QSignalBlocker(self._scene)
        try:
            self._scene.clearSelection()
            if clip_ids:
                for clip_id in clip_ids:
                    item = self._clip_items_by_id.get(clip_id)
                    if isinstance(item, ClipRect):
                        item.setSelected(True)
        finally:
            del blocker
        if clip_ids:
            self._view.setFocus()
        self._refresh_toggle_icons()
        self._emit_current_selection()

    def _track_index_from_scene_y(self, scene_y: float) -> int:
        idx = self._nearest_track_index_by_scene_y(scene_y)
        if idx is None:
            return 0
        return idx

    def _track_scene_bounds(self, idx: int) -> tuple[float, float]:
        tracks, tops, heights, _ = self._track_layout_data(self._project.tracks)
        if not tracks:
            return RULER_HEIGHT, RULER_HEIGHT + TRACK_HEIGHT
        safe_idx = max(0, min(idx, len(tracks) - 1))
        top = tops[safe_idx]
        return top, top + heights[safe_idx]

    def _track_index_at_scene_y(self, scene_y: float) -> int | None:
        if not self._project.tracks:
            return None
        for idx in range(len(self._project.tracks)):
            top, bottom = self._track_scene_bounds(idx)
            if top <= scene_y <= bottom:
                return idx
        return None

    def _nearest_track_index_by_scene_y(self, scene_y: float) -> int | None:
        if not self._project.tracks:
            return None
        best_idx: int | None = None
        best_dist: float | None = None
        for idx in range(len(self._project.tracks)):
            top, bottom = self._track_scene_bounds(idx)
            center = (top + bottom) * 0.5
            dist = abs(scene_y - center)
            if best_dist is None or dist < best_dist:
                best_idx = idx
                best_dist = dist
        return best_idx

    def _internal_new_track_insert_index(
        self,
        kind: str,
        source_idx: int,
        dragged_y: float,
    ) -> int | None:
        if kind not in {"audio", "text", "video"}:
            return None

        direct_idx = self._track_index_at_scene_y(dragged_y)
        if direct_idx is None:
            nearest_idx = self._nearest_track_index_by_scene_y(dragged_y)
            if nearest_idx is None:
                return None
            top, bottom = self._track_scene_bounds(nearest_idx)
            center_y = (top + bottom) * 0.5
            proposed = nearest_idx if dragged_y < center_y else nearest_idx + 1
            return self._constrain_insert_index_for_kind(kind, proposed)

        if direct_idx < 0 or direct_idx >= len(self._project.tracks):
            return None
        top, bottom = self._track_scene_bounds(direct_idx)
        height = max(1.0, bottom - top)
        ratio = (dragged_y - top) / height
        direct_track = self._project.tracks[direct_idx]

        if direct_track.kind == kind:
            if ratio < 0.18:
                return self._constrain_insert_index_for_kind(kind, direct_idx)
            if ratio > 0.82:
                return self._constrain_insert_index_for_kind(kind, direct_idx + 1)
            return None

        if ratio < 0.25:
            return self._constrain_insert_index_for_kind(kind, direct_idx)
        if ratio > 0.75:
            return self._constrain_insert_index_for_kind(kind, direct_idx + 1)
        return None

    def _insert_track_for_dragged_clip(
        self,
        clip: Clip,
        source_idx: int,
        insert_idx: int,
    ) -> tuple[int, int, Track] | None:
        if source_idx < 0 or source_idx >= len(self._project.tracks):
            return None
        source_track = self._project.tracks[source_idx]
        kind = source_track.kind
        if not self._can_create_track_for_clip(kind, clip, source_track):
            return None

        safe_insert_idx = self._constrain_insert_index_for_kind(kind, insert_idx)
        new_track = Track(kind=kind, name=self._new_track_name_for_kind(kind))
        self._project.tracks.insert(safe_insert_idx, new_track)
        if safe_insert_idx <= source_idx:
            source_idx += 1
        source_track = self._project.tracks[source_idx]
        return source_idx, safe_insert_idx, source_track

    def _auto_clean_empty_tracks(self) -> None:
        main_idx = self._main_track_index()
        if main_idx is None:
            return
        kept: list[Track] = []
        for idx, track in enumerate(self._project.tracks):
            if idx == main_idx or track.clips:
                kept.append(track)
        self._project.tracks = kept

    @staticmethod
    def _resolve_non_overlapping_start(track: Track, moving_clip: Clip, desired_start: float) -> float:
        """Ensure a clip does not overlap any other clip on the same track.

        Behavior mirrors an HTML-like `isSpaceAvailable` fallback:
        if desired slot is occupied, push the clip to the right edge of blocking clips.
        """
        resolved = max(0.0, desired_start)
        duration = moving_clip.timeline_duration or 0.0
        if duration <= 0.0:
            return resolved

        others: list[Clip] = []
        for clip in track.clips:
            if clip is moving_clip:
                continue
            dur = clip.timeline_duration
            if dur is None or dur <= 0.0:
                continue
            others.append(clip)
        others.sort(key=lambda c: c.start)

        for clip in others:
            dur = clip.timeline_duration or 0.0
            clip_start = clip.start
            clip_end = clip_start + dur
            if resolved + duration <= clip_start:
                break
            if resolved < clip_end and resolved + duration > clip_start:
                resolved = clip_end

        return resolved

    def handle_clip_release(self, item: ClipRect, dragged_y: float) -> None:
        self.handle_clip_release_by_clip(
            item.clip,
            dragged_y,
            max(0.0, item._drag_origin_start),
        )

    def handle_clip_volume_change(self, clip: Clip) -> None:
        self._refresh_and_reselect(clip)
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def handle_clip_fade_change(self, clip: Clip) -> None:
        self._refresh_and_reselect(clip)
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def handle_clip_trim_change(
        self,
        clip: Clip,
        *,
        ripple: bool = False,
        ripple_anchor_seconds: float = 0.0,
        ripple_delta_seconds: float = 0.0,
    ) -> None:
        loc = self._find_clip_location(clip)
        if loc is None:
            self.refresh()
            return
        track, _, _ = loc
        if self._is_track_locked(track):
            self._refresh_and_reselect(clip)
            return
        if ripple and abs(float(ripple_delta_seconds)) > 1e-6:
            ripple_shift_later_clips(
                track,
                anchor_seconds=float(ripple_anchor_seconds),
                delta_seconds=float(ripple_delta_seconds),
                exclude_clip=clip,
            )
        track.clips.sort(key=lambda c: c.start)
        normalize_track_transitions(track)
        self._sync_linked_after_clip_move(clip)
        self.normalize_main_track_magnetic()
        self._refresh_and_reselect(clip)
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def handle_clip_release_by_clip(
        self,
        clip: Clip,
        dragged_y: float,
        drag_origin_start: float | None = None,
    ) -> None:
        source_idx = self._track_index_for_clip(clip)
        if source_idx is None or not self._project.tracks:
            self._clear_live_link_follow()
            self.refresh()
            return

        origin_start = (
            max(0.0, float(drag_origin_start))
            if drag_origin_start is not None
            else float(clip.start)
        )
        had_live_follow = self._live_link_parent_runtime_id == id(clip)
        source_track = self._project.tracks[source_idx]
        if self._is_track_locked(source_track):
            if drag_origin_start is not None:
                clip.start = max(0.0, drag_origin_start)
            self._clear_live_link_follow()
            self._refresh_and_reselect(clip)
            return
        kind = source_track.kind
        # Internal drag/drop should only switch tracks when the drop lands
        # inside a concrete track lane. Dropping in vertical gaps keeps source track.
        target_idx = source_idx
        direct_target_idx = self._track_index_at_scene_y(dragged_y)
        if direct_target_idx is not None:
            target_idx = direct_target_idx

        if kind in {"audio", "text", "video"}:
            insert_idx = self._internal_new_track_insert_index(
                kind,
                source_idx,
                dragged_y,
            )
            if insert_idx is not None:
                inserted = self._insert_track_for_dragged_clip(
                    clip,
                    source_idx,
                    insert_idx,
                )
                if inserted is not None:
                    source_idx, target_idx, source_track = inserted

        if target_idx < 0 or target_idx >= len(self._project.tracks):
            target_idx = source_idx
        elif self._project.tracks[target_idx].kind != kind:
            target_idx = source_idx

        if (
            target_idx != source_idx
            and 0 <= target_idx < len(self._project.tracks)
            and self._is_track_locked(self._project.tracks[target_idx])
        ):
            if drag_origin_start is not None:
                clip.start = max(0.0, drag_origin_start)
            self._clear_live_link_follow()
            self._refresh_and_reselect(clip)
            return

        if target_idx != source_idx:
            if clip in source_track.clips:
                source_track.clips.remove(clip)
            target_track = self._project.tracks[target_idx]
            target_track.clips.append(clip)
            target_track.clips.sort(key=lambda c: c.start)
            final_track = target_track
        else:
            final_track = source_track

        resolved_start = self._resolve_non_overlapping_start(
            final_track, clip, clip.start
        )
        if abs(resolved_start - clip.start) > 1e-6:
            clip.start = resolved_start
        self._sync_linked_after_clip_move(clip)
        for track in self._project.tracks:
            track.clips.sort(key=lambda c: c.start)
            normalize_track_transitions(track)
        self.normalize_main_track_magnetic()
        if had_live_follow:
            live_changed = self._update_live_link_follow(
                clip,
                origin_start=origin_start,
                parent_start=float(clip.start),
                parent_scene_y=None,
                parent_lane_y=None,
            )
        else:
            live_changed = self._sync_overlap_children_after_parent_move(
                clip,
                origin_start=origin_start,
            )
        if live_changed:
            for track in self._project.tracks:
                track.clips.sort(key=lambda c: c.start)
                normalize_track_transitions(track)
        self._clear_live_link_follow()

        # Ensure we always refresh to snap back if dropped in empty space.
        self._auto_clean_empty_tracks()
        self._refresh_and_reselect(clip)
        self.project_mutated.emit()

    def seconds_to_pixels(self, seconds: float) -> float:
        return max(0.0, seconds) * self._pixels_per_second

    def pixels_to_seconds(self, pixels: float) -> float:
        if self._pixels_per_second <= 0:
            return 0.0
        return max(0.0, pixels) / self._pixels_per_second

    @staticmethod
    def _major_tick_seconds(pixels_per_second: float) -> float:
        target_px = 120.0
        raw_seconds = target_px / max(1e-6, pixels_per_second)
        steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800]
        for step in steps:
            if step >= raw_seconds:
                return step
        return steps[-1]

    def _timeline_viewport_height(self) -> float:
        # Use panel geometry first (stable during parent resize), then fall back to
        # actual view sizes when available.
        panel_h = float(self.height() - self.toolbar.height())
        if panel_h > 100:
            return panel_h
        view_h = float(self._view.viewport().height())
        if view_h > 100:
            return view_h
        raw_h = float(self._view.height())
        if raw_h > 100:
            return raw_h
        return 400.0

    def _sync_header_scroll(self, value: int | None = None) -> None:
        if value is None:
            value = int(self._view.verticalScrollBar().value())
        self.headers_list.move(0, -max(0, int(value)))

    def scroll_horizontal_by(self, delta: int) -> None:
        bar = self._view.horizontalScrollBar()
        bar.setValue(bar.value() - int(delta))

    def scroll_to_start(self) -> None:
        bar = self._view.horizontalScrollBar()
        bar.setValue(bar.minimum())

    def auto_zoom_to_duration(self, duration_seconds: float) -> None:
        """Auto-fit timeline zoom so the given duration occupies the visible width."""
        try:
            duration = float(duration_seconds)
        except Exception:
            return
        if duration <= 0.0:
            return
        viewport_w = float(self._view.viewport().width())
        if viewport_w <= 0.0:
            viewport_w = float(self._view.width())
        if viewport_w <= 0.0:
            return
        target_pps = viewport_w / duration
        target_zoom = int(round((target_pps / BASE_PIXELS_PER_SECOND) * 100.0))
        target_zoom = max(ZOOM_MIN, min(ZOOM_MAX, target_zoom))
        if target_zoom != self._zoom.value():
            self._zoom.setValue(target_zoom)

    def zoom_by_wheel(self, delta: int, scene_x: float, view_x: float) -> None:
        direction = 1 if delta > 0 else -1
        step = max(1, int(abs(delta) / 120.0 * 10))
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom.value() + direction * step))
        if new_zoom == self._zoom.value():
            return
        self._zoom_anchor_seconds = self.pixels_to_seconds(scene_x)
        self._zoom_anchor_view_x = view_x
        self._zoom.setValue(new_zoom)

    def _on_zoom_changed(self, value: int) -> None:
        self._zoom_percent = value
        self._pixels_per_second = BASE_PIXELS_PER_SECOND * (value / 100.0)
        self.refresh()
        self._enqueue_progressive_media_cache_from_items()
        if self._zoom_anchor_seconds is None or self._zoom_anchor_view_x is None:
            return
        anchor_scene_x = self.seconds_to_pixels(self._zoom_anchor_seconds)
        scroll_target = int(anchor_scene_x - self._zoom_anchor_view_x)
        self._view.horizontalScrollBar().setValue(max(0, scroll_target))
        self._zoom_anchor_seconds = None
        self._zoom_anchor_view_x = None

    @staticmethod
    def _clip_decode_source(clip: Clip) -> str:
        proxy = str(getattr(clip, "proxy", "") or "").strip()
        if proxy and Path(proxy).exists():
            return proxy
        return str(clip.source)

    @staticmethod
    def _clip_has_ready_proxy(clip: Clip) -> bool:
        proxy = str(getattr(clip, "proxy", "") or "").strip()
        return bool(proxy and Path(proxy).exists())

    def _visible_timeline_seconds(self) -> tuple[float, float]:
        try:
            visible = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
            viewport_w = max(1.0, visible.width())
            prefetch = viewport_w * VISIBLE_CACHE_PREFETCH_VIEWPORTS
            left_px = max(0.0, visible.left() - prefetch)
            right_px = max(left_px, visible.right() + prefetch)
            return self.pixels_to_seconds(left_px), self.pixels_to_seconds(right_px)
        except Exception:
            return 0.0, self._scene_duration_seconds()

    def _clip_intersects_visible_timeline(self, clip: Clip) -> bool:
        dur = max(0.0, float(clip.timeline_duration or 0.0))
        if dur <= 0.0:
            return True
        visible_start, visible_end = self._visible_timeline_seconds()
        clip_start = max(0.0, float(clip.start))
        clip_end = clip_start + dur
        return clip_end >= visible_start and clip_start <= visible_end

    def _clip_visible_source_window(
        self,
        clip: Clip,
    ) -> tuple[float, float, float, float] | None:
        try:
            timeline_dur = max(0.0, float(getattr(clip, "timeline_duration", 0.0) or 0.0))
        except Exception:
            timeline_dur = 0.0
        if timeline_dur <= 1e-6:
            return None
        visible_start, visible_end = self._visible_timeline_seconds()
        try:
            clip_start = max(0.0, float(getattr(clip, "start", 0.0) or 0.0))
        except Exception:
            clip_start = 0.0
        local_start = max(0.0, visible_start - clip_start)
        local_end = min(timeline_dur, visible_end - clip_start)
        if local_end <= local_start + 1e-6:
            return None
        try:
            speed = max(1e-6, float(getattr(clip, "speed", 1.0) or 1.0))
        except Exception:
            speed = 1.0
        try:
            in_point = max(0.0, float(getattr(clip, "in_point", 0.0) or 0.0))
        except Exception:
            in_point = 0.0
        try:
            source_span = max(0.0, float(getattr(clip, "source_duration", 0.0) or 0.0))
        except Exception:
            source_span = 0.0
        if source_span <= 1e-6:
            source_span = timeline_dur * speed
        if source_span <= 1e-6:
            return None
        source_start_bound = in_point
        source_end_bound = in_point + source_span
        if bool(getattr(clip, "reverse", False)):
            source_start = source_end_bound - local_end * speed
            source_end = source_end_bound - local_start * speed
        else:
            source_start = in_point + local_start * speed
            source_end = in_point + local_end * speed
        source_start = max(source_start_bound, min(source_end_bound, source_start))
        source_end = max(source_start_bound, min(source_end_bound, source_end))
        if source_end <= source_start + 1e-6:
            return None
        return source_start, source_end, local_start, local_end

    def _allow_media_cache_request(self, clip: Clip, *, media_kind: str) -> bool:
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            self._bump_media_cache_idle()
            return False
        if not self._clip_intersects_visible_timeline(clip):
            return False
        try:
            dur = float(clip.source_duration or clip.timeline_duration or 0.0)
        except Exception:
            dur = 0.0
        is_long_video = (
            media_kind == "filmstrip"
            and dur >= LONG_MEDIA_CACHE_THRESHOLD_SECONDS
        )
        if is_long_video and not self._clip_has_ready_proxy(clip):
            return False
        return True

    def _cache_signal_key(self, key: object) -> tuple | None:
        if (
            isinstance(key, tuple)
            and len(key) == 2
            and isinstance(key[0], int)
            and isinstance(key[1], tuple)
        ):
            if int(key[0]) != int(self._media_cache_generation):
                return None
            return key[1]
        if isinstance(key, tuple):
            return key
        return None

    @staticmethod
    def _remember_cache_entry(
        cache: dict,
        key: object,
        value: object,
        max_items: int,
    ) -> object:
        try:
            del cache[key]
        except KeyError:
            pass
        cache[key] = value
        limit = max(1, int(max_items))
        while len(cache) > limit:
            try:
                oldest = next(iter(cache))
            except StopIteration:
                break
            cache.pop(oldest, None)
        return value

    def _reset_media_cache_generation(self) -> None:
        self._media_cache_generation += 1
        self._thumb_inflight.clear()
        self._chunk_inflight.clear()
        self._wave_peaks_inflight.clear()
        self._wave_range_peaks_inflight.clear()
        self._wave_upgrade_pending.clear()
        self._progressive_media_cache_tasks.clear()
        self._progressive_media_cache_task_keys.clear()
        self._wave_source_duration_cache.clear()

    @staticmethod
    def _filmstrip_key(
        clip: Clip,
        *,
        strip_width: int,
        strip_height: int,
        frames: int,
    ) -> tuple[str, int, int, int, int]:
        src = _resolved_source_str(TimelinePanel._clip_decode_source(clip))
        dur_ms = int(round(float(clip.source_duration or 0.0) * 1000.0))
        return (src, int(strip_width), int(strip_height), int(frames), dur_ms)

    @staticmethod
    def _filmstrip_key_from_source(
        source: str,
        *,
        strip_width: int,
        strip_height: int,
        frames: int,
        duration: float | None,
    ) -> tuple[str, int, int, int, int]:
        dur_ms = int(round(float(duration or 0.0) * 1000.0))
        return (
            _resolved_source_str(source),
            int(strip_width),
            int(strip_height),
            int(frames),
            dur_ms,
        )

    def _submit_filmstrip_extract(
        self,
        key: tuple[str, int, int, int, int],
        source: str,
        *,
        strip_width: int,
        strip_height: int,
        frames: int,
        duration: float | None,
    ) -> None:
        if key in self._thumb_cache or key in self._thumb_inflight:
            return
        self._thumb_inflight.add(key)
        generation = int(self._media_cache_generation)

        def _job() -> None:
            path = render_filmstrip_png(
                source,
                strip_width=strip_width,
                strip_height=strip_height,
                frames=frames,
                duration=duration,
            )
            try:
                self._thumbnail_ready.emit((generation, key), path)
            except RuntimeError:
                return

        self._thumb_executor.submit(_job)

    def request_filmstrip_async(
        self,
        clip: Clip,
        *,
        strip_width: int,
        strip_height: int,
        frames: int,
    ) -> Path | None:
        key = self._filmstrip_key(
            clip,
            strip_width=strip_width,
            strip_height=strip_height,
            frames=frames,
        )
        if key in self._thumb_cache:
            cached = self._thumb_cache[key]
            self._remember_cache_entry(
                self._thumb_cache,
                key,
                cached,
                MAX_THUMB_PATH_CACHE_ITEMS,
            )
            return cached
        if key in self._thumb_inflight:
            return None
        if not self._allow_media_cache_request(clip, media_kind="filmstrip"):
            return None

        self._submit_filmstrip_extract(
            key,
            self._clip_decode_source(clip),
            strip_width=strip_width,
            strip_height=strip_height,
            frames=frames,
            duration=clip.source_duration,
        )
        return None

    def _on_thumbnail_ready(self, key: object, path: object) -> None:
        key_t = self._cache_signal_key(key)
        if key_t is None:
            return
        self._thumb_inflight.discard(key_t)
        if isinstance(path, Path):
            resolved = path
        elif isinstance(path, str) and path.strip():
            resolved = Path(path)
        else:
            resolved = None
        self._remember_cache_entry(
            self._thumb_cache,
            key_t,
            resolved,
            MAX_THUMB_PATH_CACHE_ITEMS,
        )
        self._update_clip_items_for_cache_key(key_t, invalidate_filmstrip=False)
        self._schedule_progressive_media_cache()

    def cached_strip_pixmap(self, path: Path) -> QPixmap | None:
        cache_key = str(path)
        pix = self._strip_pixmap_cache.get(cache_key)
        if pix is not None and not pix.isNull():
            self._remember_cache_entry(
                self._strip_pixmap_cache,
                cache_key,
                pix,
                MAX_STRIP_PIXMAP_CACHE_ITEMS,
            )
            return pix
        loaded = QPixmap(cache_key)
        if loaded.isNull():
            return None
        self._remember_cache_entry(
            self._strip_pixmap_cache,
            cache_key,
            loaded,
            MAX_STRIP_PIXMAP_CACHE_ITEMS,
        )
        return loaded

    @staticmethod
    def _filmstrip_chunk_key(
        source: str,
        chunk_idx: int,
        *,
        samples_per_second: int = 1,
    ) -> tuple[str, int, int, int, int, int]:
        samples_key = max(1, int(samples_per_second))
        return (
            _resolved_source_str(source),
            int(chunk_idx),
            int(FILMSTRIP_TILE_W),
            int(FILMSTRIP_TILE_H),
            int(FILMSTRIP_TILES_PER_CHUNK),
            samples_key,
        )

    def _submit_filmstrip_chunk_extract(
        self,
        key: tuple[str, int, int, int, int, int],
        source: str,
        chunk_idx: int,
        *,
        samples_per_second: int = 1,
    ) -> None:
        if key in self._chunk_pixmap_cache or key in self._chunk_inflight:
            return
        if len(self._chunk_inflight) >= MAX_FILMSTRIP_CHUNKS_INFLIGHT:
            return
        source_key = str(key[0]) if key else _resolved_source_str(source)
        per_source = sum(1 for existing in self._chunk_inflight if existing and str(existing[0]) == source_key)
        if per_source >= MAX_FILMSTRIP_CHUNKS_INFLIGHT_PER_SOURCE:
            return
        self._chunk_inflight.add(key)
        generation = int(self._media_cache_generation)

        def _job() -> None:
            try:
                path = extract_filmstrip_chunk(
                    source,
                    chunk_idx,
                    tile_width=FILMSTRIP_TILE_W,
                    tile_height=FILMSTRIP_TILE_H,
                    tiles_per_chunk=FILMSTRIP_TILES_PER_CHUNK,
                    samples_per_second=max(1, int(samples_per_second)),
                )
            except Exception:
                path = None
            try:
                self._filmstrip_chunk_ready.emit((generation, key), path)
            except RuntimeError:
                return

        self._thumb_executor.submit(_job)

    def request_filmstrip_chunk_async(
        self,
        clip: Clip,
        chunk_idx: int,
        *,
        samples_per_second: int = 1,
    ) -> QPixmap | None:
        source = _resolved_source_str(self._clip_decode_source(clip))
        if not source:
            return None

        samples_per_second = max(1, int(samples_per_second))
        key = self._filmstrip_chunk_key(
            source,
            chunk_idx,
            samples_per_second=samples_per_second,
        )
        if key in self._chunk_pixmap_cache:
            pix = self._chunk_pixmap_cache[key]
            self._remember_cache_entry(
                self._chunk_pixmap_cache,
                key,
                pix,
                MAX_CHUNK_PIXMAP_CACHE_ITEMS,
            )
            return pix if pix is not None and not pix.isNull() else None
        if key in self._chunk_inflight:
            return None

        # Selection/drag blocks new extraction work, but already-cached chunks
        # must still paint. Otherwise clicking a clip can cache a blank filmstrip.
        if not self._allow_media_cache_request(clip, media_kind="filmstrip"):
            return None

        self._submit_filmstrip_chunk_extract(
            key,
            source,
            int(chunk_idx),
            samples_per_second=samples_per_second,
        )
        return None

    def _on_filmstrip_chunk_ready(self, key: object, path: object) -> None:
        key_t = self._cache_signal_key(key)
        if key_t is None:
            return
        self._chunk_inflight.discard(key_t)
        pix: QPixmap | None = None
        if isinstance(path, Path):
            loaded = QPixmap(str(path))
            if not loaded.isNull():
                pix = loaded
        elif isinstance(path, str) and path.strip():
            loaded = QPixmap(path)
            if not loaded.isNull():
                pix = loaded
        self._remember_cache_entry(
            self._chunk_pixmap_cache,
            key_t,
            pix,
            MAX_CHUNK_PIXMAP_CACHE_ITEMS,
        )
        self._update_clip_items_for_cache_key(key_t)
        self._schedule_progressive_media_cache()

    @staticmethod
    def _peaks_key(clip: Clip, num_peaks: int) -> tuple[str, int, int]:
        src = _resolved_source_str(TimelinePanel._clip_decode_source(clip))
        return TimelinePanel._peaks_key_from_source(src, num_peaks)

    @staticmethod
    def _peaks_key_from_source(
        source: str,
        num_peaks: int,
        duration_ms: int = 0,
    ) -> tuple[str, int, int]:
        return (str(source), int(num_peaks), int(duration_ms))

    @staticmethod
    def _range_peaks_key_from_source(
        source: str,
        start: float,
        duration: float,
        num_peaks: int,
    ) -> tuple[str, int, int, int]:
        start_ms = int(round(max(0.0, float(start)) * 1000.0))
        duration_ms = int(round(max(0.0, float(duration)) * 1000.0))
        return (_resolved_source_str(source), start_ms, duration_ms, int(num_peaks))

    def _waveform_source_duration_seconds(self, clip: Clip) -> float:
        source = _resolved_source_str(self._clip_decode_source(clip))

        cached = float(self._wave_source_duration_cache.get(source, 0.0) or 0.0)
        if cached > 1e-6:
            return cached

        upper_bound = 0.0
        for track in self._project.tracks:
            for item in track.clips:
                item_source = _resolved_source_str(self._clip_decode_source(item))
                if item_source != source:
                    continue
                try:
                    out_point = getattr(item, "out_point", None)
                    if out_point is not None:
                        upper_bound = max(upper_bound, float(out_point))
                except Exception:
                    pass
                try:
                    source_span = float(getattr(item, "source_duration", 0.0) or 0.0)
                    in_point = float(getattr(item, "in_point", 0.0) or 0.0)
                    upper_bound = max(upper_bound, in_point + source_span)
                except Exception:
                    pass

        duration = max(cached, upper_bound)
        if duration <= 1e-6:
            try:
                duration = float(clip.source_duration or clip.timeline_duration or 0.0)
            except Exception:
                duration = 0.0
        if duration > 1e-6:
            self._wave_source_duration_cache[source] = duration
        return duration

    def _submit_waveform_extract(
        self,
        key: tuple[str, int, int],
        source: str,
        num_peaks: int,
    ) -> None:
        if key in self._wave_peaks_cache or key in self._wave_peaks_inflight:
            return
        self._wave_peaks_inflight.add(key)
        generation = int(self._media_cache_generation)

        def _job() -> None:
            try:
                peaks = extract_waveform_peaks(source, num_peaks=num_peaks)
            except Exception:
                peaks = None
            try:
                self._waveform_peaks_ready.emit((generation, key), peaks)
            except RuntimeError:
                return

        self._wave_executor.submit(_job)

    def _submit_waveform_range_extract(
        self,
        key: tuple[str, int, int, int],
        source: str,
        *,
        start: float,
        duration: float,
        num_peaks: int,
    ) -> None:
        if key in self._wave_range_peaks_cache or key in self._wave_range_peaks_inflight:
            return
        self._wave_range_peaks_inflight.add(key)
        generation = int(self._media_cache_generation)

        def _job() -> None:
            try:
                peaks = extract_waveform_peaks_range(
                    source,
                    start=start,
                    duration=duration,
                    num_peaks=num_peaks,
                )
            except Exception:
                peaks = None
            try:
                self._waveform_peaks_ready.emit((generation, key), peaks)
            except RuntimeError:
                return

        self._wave_executor.submit(_job)

    def _schedule_waveform_upgrade(
        self,
        fast_key: tuple[str, int, int],
        *,
        target_peaks: int = WAVEFORM_PEAKS_RESOLUTION,
    ) -> None:
        if target_peaks <= WAVEFORM_PEAKS_FAST:
            return
        source = str(fast_key[0])
        duration_ms = int(fast_key[2])
        hi_key = self._peaks_key_from_source(source, target_peaks, duration_ms)
        if (
            hi_key in self._wave_peaks_cache
            or hi_key in self._wave_peaks_inflight
            or hi_key in self._wave_upgrade_pending
        ):
            return
        self._wave_upgrade_pending.add(hi_key)
        QTimer.singleShot(
            WAVEFORM_UPGRADE_DELAY_MS,
            lambda src=source, key=hi_key, peaks=target_peaks: self._kick_waveform_upgrade(
                src,
                key,
                peaks,
            ),
        )

    def _kick_waveform_upgrade(
        self,
        source: str,
        key: tuple[str, int, int],
        num_peaks: int,
    ) -> None:
        self._wave_upgrade_pending.discard(key)
        if key in self._wave_peaks_cache or key in self._wave_peaks_inflight:
            return
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            self._bump_media_cache_idle()
            return
        self._submit_waveform_extract(key, source, num_peaks)

    def request_waveform_peaks_async(
        self,
        clip: Clip,
        *,
        num_peaks: int = 256,
        media_kind: str = "video",
    ) -> list[float] | None:
        target_peaks = max(1, int(num_peaks))
        if target_peaks <= WAVEFORM_PEAKS_FAST:
            key = self._peaks_key(clip, target_peaks)
            if key in self._wave_peaks_cache:
                cached = self._wave_peaks_cache[key]
                self._remember_cache_entry(
                    self._wave_peaks_cache,
                    key,
                    cached,
                    MAX_WAVEFORM_PEAKS_CACHE_ITEMS,
                )
                return cached
            if key in self._wave_peaks_inflight:
                return None
            if not self._allow_media_cache_request(clip, media_kind=media_kind):
                return None
            self._submit_waveform_extract(key, self._clip_decode_source(clip), target_peaks)
            return None

        hi_key = self._peaks_key(clip, target_peaks)
        if hi_key in self._wave_peaks_cache:
            hi = self._wave_peaks_cache[hi_key]
            self._remember_cache_entry(
                self._wave_peaks_cache,
                hi_key,
                hi,
                MAX_WAVEFORM_PEAKS_CACHE_ITEMS,
            )
            if hi is not None:
                return hi

        fast_key = self._peaks_key(clip, WAVEFORM_PEAKS_FAST)
        if fast_key in self._wave_peaks_cache:
            fast = self._wave_peaks_cache[fast_key]
            self._remember_cache_entry(
                self._wave_peaks_cache,
                fast_key,
                fast,
                MAX_WAVEFORM_PEAKS_CACHE_ITEMS,
            )
            if fast is not None:
                self._schedule_waveform_upgrade(
                    fast_key,
                    target_peaks=target_peaks,
                )
            return fast

        if fast_key in self._wave_peaks_inflight:
            return None
        if not self._allow_media_cache_request(clip, media_kind=media_kind):
            return None
        self._submit_waveform_extract(
            fast_key,
            self._clip_decode_source(clip),
            WAVEFORM_PEAKS_FAST,
        )
        return None

    def request_waveform_peaks_range_async(
        self,
        clip: Clip,
        *,
        source_start: float,
        source_duration: float,
        num_peaks: int = 256,
        media_kind: str = "video",
    ) -> list[float] | None:
        target_peaks = max(1, int(num_peaks))
        if source_duration <= 1e-6:
            return None
        source = _resolved_source_str(self._clip_decode_source(clip))
        if not source:
            return None
        key = self._range_peaks_key_from_source(
            source,
            source_start,
            source_duration,
            target_peaks,
        )
        if key in self._wave_range_peaks_cache:
            cached = self._wave_range_peaks_cache[key]
            self._remember_cache_entry(
                self._wave_range_peaks_cache,
                key,
                cached,
                MAX_WAVEFORM_RANGE_CACHE_ITEMS,
            )
            return cached
        if key in self._wave_range_peaks_inflight:
            return None
        if not self._allow_media_cache_request(clip, media_kind=media_kind):
            return None
        self._submit_waveform_range_extract(
            key,
            source,
            start=source_start,
            duration=source_duration,
            num_peaks=target_peaks,
        )
        return None

    def request_visible_waveform_peaks_async(
        self,
        clip: Clip,
        *,
        num_peaks: int = 256,
        media_kind: str = "video",
    ) -> tuple[list[float], float, float] | None:
        target_peaks = max(1, int(num_peaks))
        try:
            duration = max(
                0.0,
                float(
                    getattr(clip, "source_duration", 0.0)
                    or getattr(clip, "timeline_duration", 0.0)
                    or 0.0
                ),
            )
        except Exception:
            duration = 0.0
        range_basis_duration = duration
        if media_kind == "video":
            try:
                range_basis_duration = max(
                    range_basis_duration,
                    float(self._waveform_source_duration_seconds(clip) or 0.0),
                )
            except Exception:
                pass
        if range_basis_duration < LONG_MEDIA_CACHE_THRESHOLD_SECONDS:
            return None
        window = self._clip_visible_source_window(clip)
        if window is None:
            return None
        source_start, source_end, local_start, local_end = window
        source = _resolved_source_str(self._clip_decode_source(clip))
        if not source:
            return None
        span = self._clip_source_time_span(clip)
        if span is None:
            return None
        span_start, span_end, speed = span
        chunk_specs = self._waveform_range_chunk_specs(
            source,
            span_start=span_start,
            span_end=span_end,
            request_start=source_start,
            request_end=source_end,
            num_peaks=target_peaks,
        )
        if not chunk_specs:
            return None

        ready_segments: list[tuple[float, float, list[float]]] = []
        can_submit = self._allow_media_cache_request(clip, media_kind=media_kind)
        for key, chunk_start, chunk_duration in chunk_specs:
            target_cached = key in self._wave_range_peaks_cache
            peaks = self._wave_range_peaks_cache.get(key)
            if peaks is None and target_peaks != WAVEFORM_PEAKS_FAST:
                fast_key = self._range_peaks_key_from_source(
                    source,
                    chunk_start,
                    chunk_duration,
                    WAVEFORM_PEAKS_FAST,
                )
                peaks = self._wave_range_peaks_cache.get(fast_key)
                if (
                    can_submit
                    and not target_cached
                    and key not in self._wave_range_peaks_inflight
                ):
                    self._submit_waveform_range_extract(
                        key,
                        source,
                        start=chunk_start,
                        duration=chunk_duration,
                        num_peaks=target_peaks,
                    )
            if peaks is None:
                if can_submit:
                    if target_peaks != WAVEFORM_PEAKS_FAST:
                        fast_key = self._range_peaks_key_from_source(
                            source,
                            chunk_start,
                            chunk_duration,
                            WAVEFORM_PEAKS_FAST,
                        )
                        if (
                            fast_key not in self._wave_range_peaks_cache
                            and fast_key not in self._wave_range_peaks_inflight
                        ):
                            self._submit_waveform_range_extract(
                                fast_key,
                                source,
                                start=chunk_start,
                                duration=chunk_duration,
                                num_peaks=WAVEFORM_PEAKS_FAST,
                            )
                    if (
                        not target_cached
                        and key not in self._wave_range_peaks_inflight
                    ):
                        self._submit_waveform_range_extract(
                            key,
                            source,
                            start=chunk_start,
                            duration=chunk_duration,
                            num_peaks=target_peaks,
                        )
                break
            ready_segments.append(
                (
                    float(chunk_start),
                    float(chunk_start + chunk_duration),
                    [float(value) for value in peaks],
                )
            )
        if not ready_segments:
            return None

        ready_source_start = ready_segments[0][0]
        ready_source_end = ready_segments[-1][1]
        visible_peaks: list[float] = []
        for _, _, segment_peaks in ready_segments:
            visible_peaks.extend(segment_peaks)
        if not visible_peaks:
            return None

        timeline_dur = max(
            1e-6,
            float(getattr(clip, "timeline_duration", 0.0) or 0.0),
        )
        if bool(getattr(clip, "reverse", False)):
            local_start = max(0.0, min(timeline_dur, (span_end - ready_source_end) / speed))
            local_end = max(0.0, min(timeline_dur, (span_end - ready_source_start) / speed))
        else:
            local_start = max(0.0, min(timeline_dur, (ready_source_start - span_start) / speed))
            local_end = max(0.0, min(timeline_dur, (ready_source_end - span_start) / speed))
        if bool(getattr(clip, "reverse", False)):
            visible_peaks.reverse()
        return visible_peaks, local_start, local_end

    def _on_waveform_peaks_ready(self, key: object, peaks: object) -> None:
        key_t = self._cache_signal_key(key)
        if key_t is None:
            return
        if len(key_t) == 4:
            self._wave_range_peaks_inflight.discard(key_t)
            if isinstance(peaks, list):
                cached_peaks = [float(x) for x in peaks]
            else:
                cached_peaks = None
            self._remember_cache_entry(
                self._wave_range_peaks_cache,
                key_t,
                cached_peaks,
                MAX_WAVEFORM_RANGE_CACHE_ITEMS,
            )
            self._update_clip_items_for_cache_key(key_t)
            self._schedule_progressive_media_cache()
            return

        self._wave_peaks_inflight.discard(key_t)
        if isinstance(peaks, list):
            cached_peaks = [float(x) for x in peaks]
        else:
            cached_peaks = None
        self._remember_cache_entry(
            self._wave_peaks_cache,
            key_t,
            cached_peaks,
            MAX_WAVEFORM_PEAKS_CACHE_ITEMS,
        )
        if (
            len(key_t) >= 3
            and int(key_t[1]) == WAVEFORM_PEAKS_FAST
            and isinstance(self._wave_peaks_cache.get(key_t), list)
        ):
            self._schedule_waveform_upgrade(key_t)
        self._update_clip_items_for_cache_key(key_t)
        self._schedule_progressive_media_cache()

    def prewarm_media(self, paths: list[Path | str]) -> None:
        """Warm timeline filmstrip/waveform caches before media is dropped."""
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists():
                continue
            ext = path.suffix.lower()
            if ext in SUBTITLE_EXTS:
                continue
            is_audio = ext in AUDIO_EXTS
            is_video = not is_audio
            source = _resolved_source_str(path)

            wave_key = self._peaks_key_from_source(source, WAVEFORM_PEAKS_FAST)
            self._submit_waveform_extract(
                wave_key,
                source,
                WAVEFORM_PEAKS_FAST,
            )

            if not is_video:
                continue

            if TIMELINE_USE_TILED_FILMSTRIP:
                chunk_key = self._filmstrip_chunk_key(source, 0)
                self._submit_filmstrip_chunk_extract(chunk_key, source, 0)
                continue

            strip_width = FILMSTRIP_FRAMES * FILMSTRIP_TILE_WIDTH
            main_track_h = MAIN_TRACK_HEIGHT_FACTOR * TRACK_HEIGHT
            _, main_filmstrip_h, _ = _clip_section_heights(main_track_h)
            raw_strip_height = max(
                16.0,
                main_filmstrip_h,
            )
            strip_height = max(
                16,
                int(
                    (
                        (int(raw_strip_height) + FILMSTRIP_HEIGHT_BUCKET - 1)
                        // FILMSTRIP_HEIGHT_BUCKET
                    )
                    * FILMSTRIP_HEIGHT_BUCKET
                ),
            )

            def _prewarm_video(
                src: str = source,
                sw: int = strip_width,
                sh: int = strip_height,
                generation: int = int(self._media_cache_generation),
            ) -> None:
                duration = get_video_duration(src)
                key = self._filmstrip_key_from_source(
                    src,
                    strip_width=sw,
                    strip_height=sh,
                    frames=FILMSTRIP_FRAMES,
                    duration=duration,
                )
                if key in self._thumb_cache or key in self._thumb_inflight:
                    return
                self._thumb_inflight.add(key)
                path_result = render_filmstrip_png(
                    src,
                    strip_width=sw,
                    strip_height=sh,
                    frames=FILMSTRIP_FRAMES,
                    duration=duration,
                )
                try:
                    self._thumbnail_ready.emit((generation, key), path_result)
                except RuntimeError:
                    return

            self._thumb_executor.submit(_prewarm_video)

    def _enqueue_progressive_media_cache_task(self, task: tuple) -> None:
        if len(task) < 2:
            return
        task_key = (task[0], task[1])
        if task_key in self._progressive_media_cache_task_keys:
            return
        self._progressive_media_cache_task_keys.add(task_key)
        self._progressive_media_cache_tasks.append(task)

    @staticmethod
    def _progressive_media_cache_task_priority(task: tuple) -> tuple[float, int, str]:
        marker = task[-1] if task else None
        if (
            isinstance(marker, tuple)
            and len(marker) >= 3
            and str(marker[0]) == "priority"
        ):
            try:
                return float(marker[1]), int(marker[2]), str(task[0])
            except Exception:
                pass
        return float("inf"), 99, str(task[0] if task else "")

    def _sort_progressive_media_cache_tasks(self) -> None:
        if len(self._progressive_media_cache_tasks) <= 1:
            return
        self._progressive_media_cache_tasks = deque(
            sorted(
                self._progressive_media_cache_tasks,
                key=self._progressive_media_cache_task_priority,
            )
        )

    def _clip_source_time_span(self, clip: Clip) -> tuple[float, float, float] | None:
        try:
            timeline_dur = max(
                0.0,
                float(getattr(clip, "timeline_duration", 0.0) or 0.0),
            )
        except Exception:
            timeline_dur = 0.0
        try:
            speed = max(1e-6, float(getattr(clip, "speed", 1.0) or 1.0))
        except Exception:
            speed = 1.0
        try:
            in_point = max(0.0, float(getattr(clip, "in_point", 0.0) or 0.0))
        except Exception:
            in_point = 0.0
        try:
            source_span = max(
                0.0,
                float(
                    getattr(clip, "source_duration", 0.0)
                    or timeline_dur * speed
                    or 0.0
                ),
            )
        except Exception:
            source_span = 0.0
        if source_span <= 1e-6:
            return None
        return in_point, in_point + source_span, speed

    def _waveform_range_chunk_specs(
        self,
        source: str,
        *,
        span_start: float,
        span_end: float,
        request_start: float,
        request_end: float,
        num_peaks: int,
    ) -> list[tuple[tuple[str, int, int, int], float, float]]:
        chunk_seconds = max(1.0, float(MEDIA_CACHE_PROGRESSIVE_WAVE_RANGE_SECONDS))
        span_start = max(0.0, float(span_start))
        span_end = max(span_start, float(span_end))
        request_start = max(span_start, min(span_end, float(request_start)))
        request_end = max(request_start, min(span_end, float(request_end)))
        if request_end <= request_start + 1e-6:
            return []

        first_chunk = max(0, int(math.floor((request_start - span_start) / chunk_seconds)))
        last_chunk = max(
            first_chunk,
            int(math.floor((max(request_start, request_end - 1e-6) - span_start) / chunk_seconds)),
        )
        specs: list[tuple[tuple[str, int, int, int], float, float]] = []
        for chunk_idx in range(first_chunk, last_chunk + 1):
            chunk_start = span_start + float(chunk_idx) * chunk_seconds
            chunk_end = min(span_end, chunk_start + chunk_seconds)
            duration = max(0.0, chunk_end - chunk_start)
            if duration <= 1e-6:
                continue
            key = self._range_peaks_key_from_source(
                source,
                chunk_start,
                duration,
                int(num_peaks),
            )
            specs.append((key, chunk_start, duration))
        return specs

    def _enqueue_progressive_media_cache_for_clip(self, clip: Clip) -> None:
        if not isinstance(clip, Clip):
            return
        if bool(getattr(clip, "is_text_clip", False)):
            return
        source_raw = self._clip_decode_source(clip)
        if not source_raw:
            return
        source = _resolved_source_str(source_raw)
        if not source:
            return
        span = self._clip_source_time_span(clip)
        if span is None:
            return
        source_start, source_end, speed = span
        source_duration = max(0.0, source_end - source_start)
        if source_duration <= 1e-6:
            return

        ext = Path(source).suffix.lower()
        is_audio = ext in AUDIO_EXTS
        range_basis_duration = source_duration
        if not is_audio:
            try:
                range_basis_duration = max(
                    range_basis_duration,
                    float(self._waveform_source_duration_seconds(clip) or 0.0),
                )
            except Exception:
                pass

        if range_basis_duration >= LONG_MEDIA_CACHE_THRESHOLD_SECONDS:
            peak_counts = (WAVEFORM_PEAKS_FAST, WAVEFORM_PEAKS_RESOLUTION)
            for num_peaks in peak_counts:
                chunk_specs = self._waveform_range_chunk_specs(
                    source,
                    span_start=source_start,
                    span_end=source_end,
                    request_start=source_start,
                    request_end=source_end,
                    num_peaks=num_peaks,
                )
                if bool(getattr(clip, "reverse", False)):
                    chunk_specs = list(reversed(chunk_specs))
                for key, range_start, range_duration in chunk_specs:
                    if bool(getattr(clip, "reverse", False)):
                        timeline_start = float(clip.start) + max(
                            0.0,
                            (source_end - (range_start + range_duration)) / max(1e-6, speed),
                        )
                    else:
                        timeline_start = float(clip.start) + max(
                            0.0,
                            (range_start - source_start) / max(1e-6, speed),
                        )
                    self._enqueue_progressive_media_cache_task(
                        (
                            "wave_range",
                            key,
                            source,
                            float(range_start),
                            float(range_duration),
                            int(num_peaks),
                            (
                                "priority",
                                timeline_start,
                                0 if num_peaks == WAVEFORM_PEAKS_FAST else 1,
                            ),
                        )
                    )
        else:
            key = self._peaks_key(clip, WAVEFORM_PEAKS_FAST)
            self._enqueue_progressive_media_cache_task(
                (
                    "wave",
                    key,
                    source,
                    WAVEFORM_PEAKS_FAST,
                    ("priority", float(clip.start), 0),
                )
            )
            hi_key = self._peaks_key(clip, WAVEFORM_PEAKS_RESOLUTION)
            self._enqueue_progressive_media_cache_task(
                (
                    "wave",
                    hi_key,
                    source,
                    WAVEFORM_PEAKS_RESOLUTION,
                    ("priority", float(clip.start), 1),
                )
            )

        if is_audio or not TIMELINE_USE_TILED_FILMSTRIP:
            return

        samples_per_second = _filmstrip_samples_per_second(
            float(self._pixels_per_second) / max(1e-6, speed)
        )
        chunk_duration = float(max(1, FILMSTRIP_TILES_PER_CHUNK)) / float(
            max(1, samples_per_second)
        )
        if chunk_duration <= 1e-6:
            return
        first_chunk = max(0, int(source_start // chunk_duration))
        last_chunk = max(
            first_chunk,
            int(max(source_start, source_end - 1e-6) // chunk_duration),
        )
        for chunk_idx in range(first_chunk, last_chunk + 1):
            key = self._filmstrip_chunk_key(
                source,
                chunk_idx,
                samples_per_second=samples_per_second,
            )
            self._enqueue_progressive_media_cache_task(
                (
                    "filmstrip_chunk",
                    key,
                    source,
                    int(chunk_idx),
                    int(samples_per_second),
                )
            )

    def _enqueue_progressive_media_cache_from_items(self) -> None:
        items = [
            item
            for item in getattr(self, "_clip_items_by_id", {}).values()
            if isinstance(item, ClipRect)
            and not getattr(item, "_is_text_clip", False)
        ]
        items.sort(key=lambda item: float(getattr(item.clip, "start", 0.0) or 0.0))
        before = len(self._progressive_media_cache_tasks)
        for item in items:
            self._enqueue_progressive_media_cache_for_clip(item.clip)
        if len(self._progressive_media_cache_tasks) > before:
            self._sort_progressive_media_cache_tasks()
            self._schedule_progressive_media_cache()

    def _submit_progressive_media_cache_task(self, task: tuple) -> bool:
        kind = str(task[0] if task else "")
        if kind == "filmstrip_chunk" and len(task) >= 5:
            key = task[1]
            source = str(task[2])
            chunk_idx = int(task[3])
            samples_per_second = max(1, int(task[4]))
            if key in self._chunk_pixmap_cache or key in self._chunk_inflight:
                return True
            if len(self._chunk_inflight) >= MAX_FILMSTRIP_CHUNKS_INFLIGHT:
                return False
            source_key = str(key[0]) if isinstance(key, tuple) and key else source
            per_source = sum(
                1
                for existing in self._chunk_inflight
                if existing and str(existing[0]) == source_key
            )
            if per_source >= MAX_FILMSTRIP_CHUNKS_INFLIGHT_PER_SOURCE:
                return False
            self._submit_filmstrip_chunk_extract(
                key,
                source,
                chunk_idx,
                samples_per_second=samples_per_second,
            )
            return True

        if kind == "wave_range" and len(task) >= 6:
            key = task[1]
            source = str(task[2])
            start = float(task[3])
            duration = float(task[4])
            num_peaks = int(task[5])
            if key in self._wave_range_peaks_cache or key in self._wave_range_peaks_inflight:
                return True
            if (
                len(self._wave_range_peaks_inflight) + len(self._wave_peaks_inflight)
                >= MAX_PROGRESSIVE_WAVEFORM_INFLIGHT
            ):
                return False
            self._submit_waveform_range_extract(
                key,
                source,
                start=start,
                duration=duration,
                num_peaks=num_peaks,
            )
            return True

        if kind == "wave" and len(task) >= 4:
            key = task[1]
            source = str(task[2])
            num_peaks = int(task[3])
            if key in self._wave_peaks_cache or key in self._wave_peaks_inflight:
                return True
            if (
                len(self._wave_range_peaks_inflight) + len(self._wave_peaks_inflight)
                >= MAX_PROGRESSIVE_WAVEFORM_INFLIGHT
            ):
                return False
            self._submit_waveform_extract(key, source, num_peaks)
            return True

        return True

    def _process_progressive_media_cache(self) -> None:
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            self._schedule_progressive_media_cache()
            return
        processed = 0
        while (
            self._progressive_media_cache_tasks
            and processed < MEDIA_CACHE_PROGRESSIVE_BATCH_SIZE
        ):
            task = self._progressive_media_cache_tasks[0]
            if not self._submit_progressive_media_cache_task(task):
                break
            self._progressive_media_cache_tasks.popleft()
            processed += 1
        if self._progressive_media_cache_tasks:
            self._schedule_progressive_media_cache()

    def _prewarm_clip_media_assets(self, clip: Clip) -> None:
        if bool(getattr(clip, "is_text_clip", False)):
            return
        source_raw = self._clip_decode_source(clip)
        if not source_raw:
            return
        if self._is_playing or self._is_playhead_scrubbing or self._pointer_active:
            self._bump_media_cache_idle()
            return
        if not self._clip_intersects_visible_timeline(clip):
            return
        source = _resolved_source_str(source_raw)
        ext = Path(source).suffix.lower()
        is_audio = ext in AUDIO_EXTS
        try:
            duration = float(
                getattr(clip, "source_duration", 0.0)
                or getattr(clip, "timeline_duration", 0.0)
                or 0.0
            )
        except Exception:
            duration = 0.0
        duration = max(0.0, duration)
        is_long = duration >= LONG_MEDIA_CACHE_THRESHOLD_SECONDS
        if is_long:
            window = self._clip_visible_source_window(clip)
            span = self._clip_source_time_span(clip)
            if window is not None and span is not None:
                source_start, source_end, _, _ = window
                span_start, span_end, _ = span
                for range_key, chunk_start, chunk_duration in self._waveform_range_chunk_specs(
                    source,
                    span_start=span_start,
                    span_end=span_end,
                    request_start=source_start,
                    request_end=source_end,
                    num_peaks=WAVEFORM_PEAKS_FAST,
                ):
                    self._submit_waveform_range_extract(
                        range_key,
                        source,
                        start=chunk_start,
                        duration=chunk_duration,
                        num_peaks=WAVEFORM_PEAKS_FAST,
                    )
        else:
            fast_key = self._peaks_key(clip, WAVEFORM_PEAKS_FAST)
            self._submit_waveform_extract(
                fast_key,
                source,
                WAVEFORM_PEAKS_FAST,
            )
            hi_key = self._peaks_key(clip, WAVEFORM_PEAKS_RESOLUTION)
            self._submit_waveform_extract(
                hi_key,
                source,
                WAVEFORM_PEAKS_RESOLUTION,
            )

        if is_audio:
            return
        if TIMELINE_USE_TILED_FILMSTRIP:
            src_duration = duration
            if src_duration <= 1e-6:
                return
            src_duration = max(0.0, src_duration)
            if src_duration <= 1e-6:
                return
            try:
                speed = max(1e-6, float(getattr(clip, "speed", 1.0) or 1.0))
            except Exception:
                speed = 1.0
            samples_per_second = _filmstrip_samples_per_second(
                float(self._pixels_per_second) / speed
            )
            chunk_duration = float(max(1, FILMSTRIP_TILES_PER_CHUNK)) / float(
                max(1, samples_per_second)
            )
            chunk_count = max(
                1,
                int(math.ceil(src_duration / chunk_duration)),
            )
            window = self._clip_visible_source_window(clip)
            if window is None:
                return
            source_start, source_end, _, _ = window
            first_chunk = max(0, int(source_start // chunk_duration))
            last_chunk = max(
                first_chunk,
                int(max(source_start, source_end - 1e-6) // chunk_duration),
            )
            last_chunk = min(chunk_count - 1, last_chunk)
            for chunk_idx in range(first_chunk, last_chunk + 1):
                key = self._filmstrip_chunk_key(
                    source,
                    chunk_idx,
                    samples_per_second=samples_per_second,
                )
                if samples_per_second == 1:
                    self._submit_filmstrip_chunk_extract(key, source, int(chunk_idx))
                else:
                    self._submit_filmstrip_chunk_extract(
                        key,
                        source,
                        int(chunk_idx),
                        samples_per_second=samples_per_second,
                    )
            return

        strip_width = FILMSTRIP_FRAMES * FILMSTRIP_TILE_WIDTH
        main_track_h = MAIN_TRACK_HEIGHT_FACTOR * TRACK_HEIGHT
        _, main_filmstrip_h, _ = _clip_section_heights(main_track_h)
        raw_strip_height = max(16.0, main_filmstrip_h)
        strip_height = max(
            16,
            int(
                (
                    (int(raw_strip_height) + FILMSTRIP_HEIGHT_BUCKET - 1)
                    // FILMSTRIP_HEIGHT_BUCKET
                )
                * FILMSTRIP_HEIGHT_BUCKET
            ),
        )
        if duration <= 1e-6:
            return
        if duration >= LONG_MEDIA_CACHE_THRESHOLD_SECONDS and not self._clip_has_ready_proxy(clip):
            return
        key = self._filmstrip_key_from_source(
            source,
            strip_width=strip_width,
            strip_height=strip_height,
            frames=FILMSTRIP_FRAMES,
            duration=duration,
        )
        self._submit_filmstrip_extract(
            key,
            source,
            strip_width=strip_width,
            strip_height=strip_height,
            frames=FILMSTRIP_FRAMES,
            duration=duration,
        )

    def prewarm_track_clips(self, clips: list[Clip]) -> None:
        """Eagerly preload timeline cache for clips already on tracks."""
        seen: set[tuple[str, int, str, int, int]] = set()
        progressive_clips: list[Clip] = []
        for clip in clips:
            if not isinstance(clip, Clip):
                continue
            if bool(getattr(clip, "is_text_clip", False)):
                continue
            source_raw = self._clip_decode_source(clip)
            if not source_raw:
                continue
            source = _resolved_source_str(source_raw)
            try:
                duration_ms = int(
                    round(
                        max(
                            0.0,
                            float(
                                getattr(clip, "source_duration", 0.0)
                                or getattr(clip, "timeline_duration", 0.0)
                                or 0.0
                            ),
                        )
                        * 1000.0
                    )
                )
            except Exception:
                duration_ms = 0
            try:
                in_point_ms = int(round(float(getattr(clip, "in_point", 0.0) or 0.0) * 1000.0))
            except Exception:
                in_point_ms = 0
            try:
                start_ms = int(round(float(getattr(clip, "start", 0.0) or 0.0) * 1000.0))
            except Exception:
                start_ms = 0
            signature = (source, duration_ms, str(clip.clip_type), in_point_ms, start_ms)
            if signature in seen:
                continue
            seen.add(signature)
            progressive_clips.append(clip)
            self._prewarm_clip_media_assets(clip)
        progressive_clips.sort(
            key=lambda item: float(getattr(item, "start", 0.0) or 0.0)
        )
        before = len(self._progressive_media_cache_tasks)
        for clip in progressive_clips:
            self._enqueue_progressive_media_cache_for_clip(clip)
        if len(self._progressive_media_cache_tasks) > before:
            self._sort_progressive_media_cache_tasks()
            self._schedule_progressive_media_cache()

    def _update_clip_items_for_cache_key(
        self,
        key: tuple,
        *,
        invalidate_filmstrip: bool = False,
    ) -> None:
        if not key:
            return
        source_key = str(key[0])
        bucket = getattr(self, "_clip_items_by_source", {}).get(source_key)
        if not bucket:
            return
        updated = False
        for item in list(bucket):
            if not self._clip_intersects_visible_timeline(item.clip):
                continue
            if invalidate_filmstrip:
                item.invalidate_filmstrip()
            else:
                item.update()
            updated = True
        if updated and hasattr(self, "_view"):
            self._view.viewport().update()

    def update_clip_visuals(self, clip: Clip) -> None:
        """Repaint a single clip item after cheap metadata/text changes."""
        item = self._clip_items_by_id.get(id(clip))
        if item is None:
            return
        item.update()
        if hasattr(self, "_view"):
            self._view.viewport().update()

    def _remove_transient_item(self, item: QGraphicsItem | None) -> None:
        if item is None:
            return
        self._transient_scene_items = [
            existing for existing in self._transient_scene_items if existing is not item
        ]
        try:
            if item.scene() is not None:
                self._scene.removeItem(item)
        except RuntimeError:
            pass

    def _clear_transient_items(self) -> None:
        for item in list(self._transient_scene_items):
            try:
                if item.scene() is not None:
                    self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._transient_scene_items.clear()
        self._playhead_item = None
        self._playhead_handle = None
        self._last_playhead_scene_x = None

    def _add_transient(self, item: QGraphicsItem) -> QGraphicsItem:
        self._transient_scene_items.append(item)
        return item

    def _index_clip_item(self, item: ClipRect) -> None:
        key = item._decode_source_key
        self._clip_items_by_source.setdefault(key, []).append(item)

    def _unindex_clip_item(self, item: ClipRect) -> None:
        key = item._decode_source_key
        bucket = self._clip_items_by_source.get(key)
        if not bucket:
            return
        try:
            bucket.remove(item)
        except ValueError:
            return
        if not bucket:
            self._clip_items_by_source.pop(key, None)

    def _reindex_clip_item(self, item: ClipRect, old_key: str, new_key: str) -> None:
        if old_key == new_key:
            return
        bucket = self._clip_items_by_source.get(old_key)
        if bucket:
            try:
                bucket.remove(item)
            except ValueError:
                pass
            if not bucket:
                self._clip_items_by_source.pop(old_key, None)
        self._clip_items_by_source.setdefault(new_key, []).append(item)

    def _clear_clip_items(self) -> None:
        for item in list(self._clip_items_by_id.values()):
            try:
                if item.scene() is not None:
                    self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._clip_items_by_id.clear()
        self._clip_items_by_source.clear()

    def _compute_clip_layout_data(
        self,
        tracks: list[Track],
        lane_tops: list[float],
        lane_heights: list[float],
    ) -> dict[int, tuple[Clip, float, float, QColor, bool, bool, bool, str]]:
        palette = {
            "video": QColor(VIDEO_CLIP_BASE_COLOR),
            "audio": QColor(AUDIO_CLIP_BASE_COLOR),
            "text": QColor("#0891b2"),
        }
        data: dict[int, tuple[Clip, float, float, QColor, bool, bool, bool, str]] = {}
        for i, track in enumerate(tracks):
            y_scene = lane_tops[i]
            lane_h = lane_heights[i]
            color = palette.get(track.kind, QColor("#4a505c"))
            locked = self._is_track_locked(track)
            muted = self._is_track_muted(track)
            hidden = self._is_track_hidden(track)
            for clip in track.clips:
                data[id(clip)] = (clip, y_scene, lane_h, color, locked, muted, hidden, track.kind)
        return data

    def refresh(self) -> None:
        self._timeline_end_cache = None
        selected_clips = [it.clip for it in self._selected_clip_items()]
        selected_ids = {id(clip) for clip in selected_clips}
        blocker = QSignalBlocker(self._scene)
        try:
            self._clear_transient_items()

            # Clear old header widgets safely (avoid stale layout items/pointers).
            while self.headers_list_layout.count() > 0:
                item = self.headers_list_layout.takeAt(0)
                if item is None:
                    continue
                w = item.widget()
                if w is not None:
                    w.deleteLater()
                del item

            tracks, lane_tops, lane_heights, main_idx = self._track_layout_data(
                self._project.tracks
            )
            clip_count = sum(len(track.clips) for track in tracks)
            target_index_method = (
                QGraphicsScene.ItemIndexMethod.BspTreeIndex
                if clip_count >= SCENE_INDEX_CLIP_THRESHOLD
                else QGraphicsScene.ItemIndexMethod.NoIndex
            )
            try:
                if self._scene.itemIndexMethod() != target_index_method:
                    self._scene.setItemIndexMethod(target_index_method)
            except Exception:
                pass

            viewport_h = self._timeline_viewport_height()
            scene_duration = self._scene_duration_seconds()
            duration_scene_w = self.seconds_to_pixels(scene_duration)
            viewport_scene_w = float(self._view.viewport().width())
            if viewport_scene_w <= 0.0:
                viewport_scene_w = float(self._view.width())
            # Drive timeline length by duration * zoom.
            # Keep a viewport-width minimum so lane background still fills screen,
            # but avoid phantom horizontal scrolling when content already fits.
            scene_w = max(200.0, duration_scene_w, max(0.0, viewport_scene_w))
            first_track_y = lane_tops[0] if lane_tops else RULER_HEIGHT
            self.headers_list_layout.setContentsMargins(
                0,
                int(max(0.0, first_track_y - RULER_HEIGHT)),
                0,
                int(TRACK_EDGE_PADDING),
            )

            clip_data = self._compute_clip_layout_data(tracks, lane_tops, lane_heights)
            existing_ids = set(self._clip_items_by_id.keys())
            new_ids = set(clip_data.keys())

            for i, track in enumerate(tracks):
                y_scene = lane_tops[i]
                lane_h = lane_heights[i]
                is_main_lane = (
                    (main_idx is None and i == 0)
                    or (main_idx is not None and i == main_idx)
                )
                lane_color = self._track_lane_color(track, is_main_lane=is_main_lane)
                if main_idx is not None and i == main_idx:
                    default_name = "Main"
                elif track.kind == "text":
                    default_name = f"Text {i+1}"
                elif track.kind == "audio":
                    default_name = f"Audio {i+1}"
                else:
                    default_name = f"Track {i+1}"
                header_name = track.name.strip() if track.name else default_name
                header = TrackHeader(
                    header_name,
                    track.kind,
                    locked=self._is_track_locked(track),
                    hidden=self._is_track_hidden(track),
                    muted=self._is_track_muted(track),
                    volume=track_output_gain(track),
                    role=str(getattr(track, "role", "other") or "other"),
                    lane_height=lane_h,
                    background_color=lane_color,
                    on_toggle_lock=lambda tr=track: self._toggle_track_lock(tr),
                    on_toggle_hidden=lambda tr=track: self._toggle_track_hidden(tr),
                    on_toggle_mute=lambda tr=track: self._toggle_track_mute(tr),
                    on_volume_changed=lambda value, commit, tr=track: self._set_track_volume(
                        tr,
                        value,
                        commit=commit,
                    ),
                    on_role_changed=lambda role, tr=track: self._set_track_role(tr, role),
                )
                self.headers_list_layout.addWidget(header)

                lane = self._scene.addRect(
                    0,
                    y_scene,
                    scene_w,
                    lane_h,
                    QPen(Qt.PenStyle.NoPen),
                    QBrush(lane_color),
                )
                lane.setZValue(-10)
                self._add_transient(lane)

                if self._is_track_locked(track):
                    lock_mask = self._scene.addRect(
                        0,
                        y_scene,
                        scene_w,
                        lane_h,
                        QPen(Qt.PenStyle.NoPen),
                        QBrush(QColor(0, 0, 0, 90), Qt.BrushStyle.Dense4Pattern),
                    )
                    lock_mask.setOpacity(0.55)
                    lock_mask.setZValue(-6)
                    self._add_transient(lock_mask)

                if is_main_lane and not track.clips:
                    guide_font = QFont("Inter", 8, QFont.Weight.Light)
                    txt = self._scene.addSimpleText("COME CUT. Ready to use for easy creation", guide_font)
                    txt.setBrush(QBrush(QColor("#4a505c")))
                    view_w = self._view.width() if self._view.width() > 100 else 800
                    txt.setPos(
                        (view_w - txt.boundingRect().width()) / 2.0,
                        y_scene + (lane_h - txt.boundingRect().height()) / 2.0,
                    )
                    txt.setZValue(-5)
                    self._add_transient(txt)

            for clip_id in existing_ids - new_ids:
                item = self._clip_items_by_id.pop(clip_id, None)
                if item is not None:
                    self._unindex_clip_item(item)
                    try:
                        if item.scene() is not None:
                            self._scene.removeItem(item)
                    except RuntimeError:
                        pass

            for clip_id in new_ids - existing_ids:
                clip, y_scene, lane_h, color, locked, muted, hidden, kind = clip_data[clip_id]
                item = ClipRect(
                    clip,
                    y_scene,
                    lane_h,
                    color,
                    self,
                    track_kind=kind,
                    locked=locked,
                    muted=muted,
                    hidden=hidden,
                )
                self._scene.addItem(item)
                self._clip_items_by_id[clip_id] = item
                self._index_clip_item(item)

            for clip_id in new_ids & existing_ids:
                clip, y_scene, lane_h, color, locked, muted, hidden, kind = clip_data[clip_id]
                item = self._clip_items_by_id[clip_id]
                old_key = item._decode_source_key
                item.update_from_layout(
                    clip=clip,
                    lane_y=y_scene,
                    lane_height=lane_h,
                    color=color,
                    track_kind=kind,
                    locked=locked,
                    muted=muted,
                    hidden=hidden,
                )
                self._reindex_clip_item(item, old_key, item._decode_source_key)

            content_bottom = (
                lane_tops[-1] + lane_heights[-1] + TRACK_EDGE_PADDING
                if lane_tops and lane_heights
                else RULER_HEIGHT + TRACK_EDGE_PADDING
            )
            scene_h = max(viewport_h, 200.0, content_bottom)
            self._scene.setSceneRect(0, 0, scene_w, scene_h)
            headers_h = max(0, int(math.ceil(scene_h - RULER_HEIGHT)))
            self.headers_list.setFixedWidth(TRACK_HEADER_WIDTH)
            self.headers_list.setFixedHeight(headers_h)
            self.headers_viewport.setMinimumHeight(0)
            self._sync_header_scroll()
            # Force horizontal scroll range to follow the new scene width.
            bar = self._view.horizontalScrollBar()
            scroll_overflow = scene_w - max(0.0, viewport_scene_w)
            # Tolerate tiny float drift so scrollbar truly locks when fitted.
            max_scroll = 0 if scroll_overflow <= 0.5 else max(0, int(scroll_overflow))
            bar.setRange(0, max_scroll)
            if bar.value() > max_scroll:
                bar.setValue(max_scroll)
            self._draw_ruler(scene_w)
            self._refresh_beat_markers()
            self._refresh_transitions(tracks, lane_tops, lane_heights)
            self._refresh_playhead()

            for clip_id, item in self._clip_items_by_id.items():
                item.setSelected(clip_id in selected_ids and not item._locked)
        finally:
            del blocker
        self._emit_current_selection_if_changed()

    def _draw_ruler(self, scene_w: float) -> None:
        visible = self._view.mapToScene(self._view.viewport().rect()).boundingRect()
        ruler_y = max(0.0, float(visible.top()))
        self._scene.invalidate(
            QRectF(0.0, ruler_y, max(1.0, scene_w), RULER_HEIGHT),
            QGraphicsScene.SceneLayer.ForegroundLayer,
        )

    def _refresh_beat_markers(self) -> None:
        scene_h = max(float(self._scene.height()), RULER_HEIGHT)
        pen = QPen(QColor("#eab308"), 1, Qt.PenStyle.DashLine)
        for marker in getattr(self._project, "beat_markers", []):
            try:
                seconds = max(0.0, float(marker.time))
            except Exception:
                continue
            x = self.seconds_to_pixels(seconds)
            line = self._add_transient(
                self._scene.addLine(x, RULER_HEIGHT, x, scene_h, pen)
            )
            line.setZValue(650)

    def _refresh_transitions(
        self,
        tracks: list[Track],
        lane_tops: list[float],
        lane_heights: list[float],
    ) -> None:
        badge_font = QFont("Inter", 7, QFont.Weight.DemiBold)
        for track_idx, track in enumerate(tracks):
            if track.kind not in {"video", "audio"}:
                continue
            if track_idx >= len(lane_tops) or track_idx >= len(lane_heights):
                continue
            lane_top = float(lane_tops[track_idx])
            lane_h = float(lane_heights[track_idx])
            for transition in track.transitions:
                from_index = int(transition.from_index)
                if int(transition.to_index) != from_index + 1:
                    continue
                if from_index < 0 or from_index + 1 >= len(track.clips):
                    continue
                if transition_duration_limit(track, from_index) <= 0.0:
                    continue
                left = track.clips[from_index]
                left_end = _clip_timeline_end(left)
                if left_end is None:
                    continue
                width = max(34.0, min(96.0, self.seconds_to_pixels(float(transition.duration)) * 2.0))
                height = 18.0
                x = self.seconds_to_pixels(left_end) - (width * 0.5)
                y = lane_top + max(4.0, (lane_h - height) * 0.5)
                rect = QRectF(x, y, width, height)
                path = QPainterPath()
                path.addRoundedRect(rect, 5.0, 5.0)
                badge = self._add_transient(
                    self._scene.addPath(
                        path,
                        QPen(QColor("#f8fafc"), 1.0),
                        QBrush(QColor(34, 211, 197, 190)),
                    )
                )
                badge.setZValue(620)
                label = TRANSITION_KIND_LABELS.get(
                    str(transition.kind),
                    str(transition.kind).title(),
                )
                text = self._add_transient(self._scene.addSimpleText(label, badge_font))
                text.setBrush(QBrush(QColor("#071317")))
                text_rect = text.boundingRect()
                text.setPos(
                    rect.center().x() - text_rect.width() * 0.5,
                    rect.center().y() - text_rect.height() * 0.5 - 0.5,
                )
                text.setZValue(621)

    def _refresh_playhead(self) -> None:
        old_x = getattr(self, "_last_playhead_scene_x", None)
        self._remove_transient_item(self._playhead_item)
        self._remove_transient_item(self._playhead_handle)
        x = self.seconds_to_pixels(self._playhead_seconds)
        self._last_playhead_scene_x = x
        self._playhead_item = None
        self._playhead_handle = None
        if old_x is None:
            dirty_left = x - 14.0
            dirty_width = 28.0
        else:
            dirty_left = min(float(old_x), x) - 14.0
            dirty_width = abs(float(old_x) - x) + 28.0
        self._scene.invalidate(
            QRectF(
                dirty_left,
                0.0,
                max(1.0, dirty_width),
                max(RULER_HEIGHT, self._scene.height()),
            ),
            QGraphicsScene.SceneLayer.ForegroundLayer,
        )

    def _on_selection_changed(self) -> None:
        if self._linked_selection_enabled and not self._suppress_linked_selection:
            selected = self.selected_clips()
            expanded = self._expanded_linked_clips(selected)
            if {id(c) for c in expanded} != {id(c) for c in selected}:
                self._suppress_linked_selection = True
                try:
                    self.select_clips(expanded)
                finally:
                    self._suppress_linked_selection = False
                return
        self._refresh_toggle_icons()
        self._emit_current_selection()

    def _emit_current_selection_if_changed(self) -> None:
        self._emit_current_selection()

    def _emit_current_selection(self) -> None:
        items = self._scene.selectedItems()
        selected_clips = [item.clip for item in items if isinstance(item, ClipRect)]
        clip = selected_clips[0] if selected_clips else None
        selection_key = tuple(sorted(id(selected) for selected in selected_clips))
        if selection_key == self._last_emitted_selection_key:
            return
        self._last_emitted_selection_key = selection_key
        self.selection_changed.emit(clip)

    def set_project(self, project: Project) -> None:
        self._clear_transient_items()
        self._clear_clip_items()
        self._last_emitted_selection_key = None
        self._reset_media_cache_generation()
        self._timeline_end_cache = None
        self._project = project
        self._ensure_unique_clip_ids()
        self.refresh()

    def closeEvent(self, event) -> None:
        try:
            self._thumb_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._wave_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        super().closeEvent(event)

    def set_playhead(self, seconds: float) -> None:
        self._playhead_seconds = self._clamp_playhead_seconds(seconds)
        self._refresh_playhead()

    def set_playhead_fast(self, seconds: float) -> None:
        self._playhead_seconds = self._clamp_playhead_seconds(seconds)

    def is_playhead_scrubbing(self) -> bool:
        return self._is_playhead_scrubbing

    def take_last_seek_request_was_scrub(self) -> bool:
        value = bool(self._last_seek_request_was_scrub)
        self._last_seek_request_was_scrub = False
        return value

    def _emit_seek_request(self, seconds: float, *, scrub: bool) -> None:
        self._last_seek_request_was_scrub = bool(scrub)
        self.seek_requested.emit(seconds)

    def _begin_playhead_scrub(self) -> None:
        self._is_playhead_scrubbing = True
        self._scrub_last_emit_ts = 0.0
        self._scrub_last_visual_refresh_ts = 0.0
        self._scrub_pending_seconds = None
        if self._scrub_emit_timer.isActive():
            self._scrub_emit_timer.stop()

    def _flush_pending_scrub_seek(self) -> None:
        if self._scrub_pending_seconds is None:
            return
        seconds = self._scrub_pending_seconds
        self._scrub_pending_seconds = None
        self._emit_seek_request(seconds, scrub=True)
        self._scrub_last_emit_ts = monotonic()

    def _end_playhead_scrub(self) -> None:
        if self._scrub_emit_timer.isActive():
            self._scrub_emit_timer.stop()
        self._is_playhead_scrubbing = False
        self._flush_pending_scrub_seek()
        self._bump_media_cache_idle()
        self._refresh_playhead()

    def _scrub_playhead_to_scene_x(self, scene_x: float, *, emit_seek: bool) -> None:
        seconds = max(0.0, self.pixels_to_seconds(scene_x))
        seconds = self._snap_playhead_time(seconds)
        scrub_like = self._is_playhead_scrubbing or self._hover_scrub_enabled
        if scrub_like:
            self.set_playhead_fast(seconds)
            visual_interval = SCRUB_PLAYHEAD_REFRESH_INTERVAL_MS / 1000.0
            now = monotonic()
            if (
                self._scrub_last_visual_refresh_ts <= 0.0
                or (now - self._scrub_last_visual_refresh_ts) >= visual_interval
            ):
                self._scrub_last_visual_refresh_ts = now
                self._refresh_playhead()
        else:
            self.set_playhead(seconds)
        seconds = float(self._playhead_seconds)
        if not emit_seek:
            return
        if not scrub_like:
            self._emit_seek_request(seconds, scrub=False)
            return

        interval = SCRUB_SEEK_INTERVAL_MS / 1000.0
        now = monotonic()
        if self._scrub_last_emit_ts <= 0.0 or (now - self._scrub_last_emit_ts) >= interval:
            self._emit_seek_request(seconds, scrub=True)
            self._scrub_last_emit_ts = now
            self._scrub_pending_seconds = None
            if self._scrub_emit_timer.isActive():
                self._scrub_emit_timer.stop()
            return

        self._scrub_pending_seconds = seconds
        remaining = max(1, int((interval - (now - self._scrub_last_emit_ts)) * 1000.0))
        if not self._scrub_emit_timer.isActive():
            self._scrub_emit_timer.start(remaining)

    def open_clip_context_menu(self, clip: Clip, screen_pos) -> None:
        loc = self._find_clip_location(clip)
        track = loc[0] if loc is not None else None
        menu = QMenu(self)
        is_text_clip = bool(getattr(clip, "is_text_clip", False))

        if track is not None and not is_text_clip:
            lock_label = "Unlock Track" if self._is_track_locked(track) else "Lock Track"
            act_lock = menu.addAction(lock_label)
            act_lock.triggered.connect(lambda checked=False, tr=track: self._toggle_track_lock(tr))
            menu.addSeparator()

        if is_text_clip:
            act_edit_trans = menu.addAction("Edit subtitle & trans")
            act_edit_trans.triggered.connect(
                lambda checked=False, c=clip: self.subtitle_edit_translate_requested.emit(c)
            )

            act_batch_trans = menu.addAction("Batch Translate Track")
            act_batch_trans.triggered.connect(
                lambda checked=False, c=clip: self.subtitle_batch_translate_requested.emit(c)
            )
            menu.addSeparator()

            act_delete = menu.addAction("Delete Selected")
            act_delete.triggered.connect(self.ripple_delete_selected)

            act_delete_left = menu.addAction("Delete Left Clips (Track)")
            act_delete_left.triggered.connect(self.delete_left_of_selected_clip)

            act_delete_right = menu.addAction("Delete Right Clips (Track)")
            act_delete_right.triggered.connect(self.delete_right_of_selected_clip)

            menu.exec(screen_pos)
            return

        act_delete = menu.addAction("Delete Selected")
        act_delete.triggered.connect(self.ripple_delete_selected)

        act_delete_left = menu.addAction("Delete Left Clips (Track)")
        act_delete_left.triggered.connect(self.delete_left_of_selected_clip)

        act_delete_right = menu.addAction("Delete Right Clips (Track)")
        act_delete_right.triggered.connect(self.delete_right_of_selected_clip)

        menu.addSeparator()
        act_split = menu.addAction("Split At Playhead")
        act_split.triggered.connect(self.split_at_playhead)

        menu.addSeparator()
        transition_target = self._transition_target_from_selection_or_clip(clip)
        add_transition_menu = menu.addMenu("Add Transition")
        add_transition_menu.setEnabled(transition_target is not None)
        for kind in COMMON_TRANSITION_KINDS:
            label = TRANSITION_KIND_LABELS.get(kind, str(kind).title())
            action = add_transition_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, k=kind, c=clip: self.add_transition_for_selection_or_clip(
                    c,
                    kind=k,
                )
            )
        remove_target = self._transition_remove_target_from_selection_or_clip(clip)
        act_remove_transition = menu.addAction("Remove Nearby Transition")
        act_remove_transition.setEnabled(remove_target is not None)
        act_remove_transition.triggered.connect(
            lambda checked=False, c=clip: self.remove_transition_for_selection_or_clip(c)
        )

        menu.exec(screen_pos)

    def _toggle_track_lock(self, track: Track) -> None:
        track.locked = not self._is_track_locked(track)
        self.refresh()
        self.project_mutated.emit()

    def _toggle_track_hidden(self, track: Track) -> None:
        track.hidden = not self._is_track_hidden(track)
        self.refresh()
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def _toggle_track_mute(self, track: Track) -> None:
        track.muted = not self._is_track_muted(track)
        self.refresh()
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def _set_track_volume(self, track: Track, volume: float, *, commit: bool) -> None:
        old = track_output_gain(track)
        new = set_track_volume(track, volume)
        changed = abs(new - old) > 1e-6
        track_id = id(track)
        if not commit:
            if changed:
                self._pending_track_volume_commits.add(track_id)
                self.seek_requested.emit(float(self._playhead_seconds))
            return

        had_pending = track_id in self._pending_track_volume_commits
        self._pending_track_volume_commits.discard(track_id)
        if not changed and not had_pending:
            return
        self.refresh()
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def _set_track_role(self, track: Track, role: str) -> None:
        old = str(getattr(track, "role", "other") or "other")
        new = set_track_role(track, role)
        if new == old:
            return
        self.refresh()
        self.project_mutated.emit()

    def handle_external_media_drop(self, path: Path, view_pos: QPoint) -> bool:
        if not self._project.tracks:
            return False
        scene_pos = self._view.mapToScene(view_pos)
        start = self.pixels_to_seconds(scene_pos.x())
        # Snap external drops to timeline anchors (00:00 + nearby clip edges),
        # matching CapCut-like behavior and avoiding tiny pixel-offset shifts.
        start = self._snap_start(start)
        # Extra guard for start-of-timeline drops:
        # users often drop visually at 00:00 with a small pixel offset.
        # If we are scrolled to timeline start and the drop is near zero,
        # clamp to exact 0 so subtitle timestamps stay identical to source.
        hbar = self._view.horizontalScrollBar()
        if (
            hbar.value() <= (hbar.minimum() + 1)
            and start <= max(0.5, SNAP_TOLERANCE_PX / max(1.0, self._pixels_per_second))
        ):
            start = 0.0

        tracks = self._project.tracks
        track_count = len(tracks)
        direct_idx = self._track_index_at_scene_y(scene_pos.y())
        nearest_idx = direct_idx
        if nearest_idx is None:
            nearest_idx = self._nearest_track_index_by_scene_y(scene_pos.y())
        if nearest_idx is None:
            return False
        idx = nearest_idx

        insert_new_track = False
        kind = self._media_kind_for_path(path)
        main_idx = self._main_track_index()

        if kind == "text":
            if direct_idx is not None and 0 <= direct_idx < len(self._project.tracks):
                direct_track = self._project.tracks[direct_idx]
                if direct_track.kind == "text" and not self._is_track_locked(direct_track):
                    idx = direct_idx
                else:
                    alt_idx = self._nearest_unlocked_track_index("text", direct_idx)
                    if alt_idx is not None:
                        idx = alt_idx
                    else:
                        idx = direct_idx
                        insert_new_track = True
            else:
                anchor = nearest_idx if nearest_idx is not None else 0
                alt_idx = self._nearest_unlocked_track_index("text", anchor)
                if alt_idx is not None:
                    idx = alt_idx
                else:
                    idx = anchor
                    insert_new_track = True
            idx, insert_new_track = self._drop_target_for_kind_zone(
                kind,
                idx,
                insert_new_track,
            )
            self.media_drop_requested.emit(str(path), start, idx, insert_new_track)
            return True

        # CapCut-like first-drop rule:
        # when timeline is empty, visual media (video/image) must land on Main,
        # never auto-create a new track.
        if kind == "video" and not self._timeline_has_clips() and main_idx is not None:
            if self._is_track_locked(self._project.tracks[main_idx]):
                alt_idx = self._nearest_unlocked_track_index(kind, main_idx)
                if alt_idx is not None:
                    idx = alt_idx
                else:
                    # No unlocked track available: allow creating one.
                    idx = main_idx
                    insert_new_track = True
            else:
                idx = main_idx
            self.media_drop_requested.emit(str(path), start, idx, insert_new_track)
            return True

        top, bottom = self._track_scene_bounds(idx)
        ratio = 0.5
        if bottom > top:
            ratio = (scene_pos.y() - top) / (bottom - top)

        # Match HTML external-drop behavior:
        # - if cursor is not on an exact track lane, use nearest track and prepare insert above/below
        # - if cursor is near lane top/bottom edge, prepare insert above/below
        if direct_idx is None:
            insert_new_track = True
            idx = idx if ratio < 0.5 else min(track_count, idx + 1)
        elif ratio < 0.25:
            insert_new_track = True
            idx = direct_idx
        elif ratio > 0.75:
            insert_new_track = True
            idx = min(track_count, direct_idx + 1)

        if kind == "video" and main_idx is not None:
            main_top, main_bottom = self._track_scene_bounds(main_idx)
            main_h = max(1.0, main_bottom - main_top)
            # Match HTML behavior: when dropping a video around main track,
            # only upward drag can request creating a new track.
            if (
                main_top - main_h * 0.5 <= scene_pos.y() <= main_top + main_h * 0.25
                and idx >= main_idx
            ):
                if main_idx > 0 and self._project.tracks[main_idx - 1].kind == "video":
                    idx = main_idx - 1
                    insert_new_track = False
                else:
                    idx = main_idx
                    insert_new_track = True
            elif scene_pos.y() >= main_bottom - main_h * 0.25 and idx == main_idx:
                insert_new_track = False

        if not insert_new_track and 0 <= idx < len(self._project.tracks) and self._is_track_locked(self._project.tracks[idx]):
            alt_idx = self._nearest_unlocked_track_index(kind, idx)
            if alt_idx is None:
                insert_new_track = True
            else:
                idx = alt_idx

        idx, insert_new_track = self._drop_target_for_kind_zone(
            kind,
            idx,
            insert_new_track,
        )

        self.media_drop_requested.emit(str(path), start, idx, insert_new_track)
        return True

    def split_at_playhead(self) -> None:
        self._cut_selected_clip()

    def delete_left_of_selected_clip(self) -> None:
        self._delete_side_clips("left")

    def delete_right_of_selected_clip(self) -> None:
        self._delete_side_clips("right")

    def _transition_pair_from_selection(self) -> tuple[Track, int] | None:
        selected = self.selected_clips()
        if len(selected) != 2:
            return None
        locs = [self._find_clip_location(clip) for clip in selected]
        if locs[0] is None or locs[1] is None:
            return None
        track = locs[0][0]
        if locs[1][0] is not track:
            return None
        if track.kind not in {"video", "audio"} or self._is_track_locked(track):
            return None
        from_index = adjacent_pair_from_clips(track, selected)
        if from_index is None:
            return None
        return track, from_index

    def _transition_target_from_selection_or_clip(self, clip: Clip) -> tuple[Track, int] | None:
        selected_pair = self._transition_pair_from_selection()
        if selected_pair is not None:
            track, from_index = selected_pair
            if transition_duration_limit(track, from_index) >= 0.05:
                return selected_pair
            return None
        loc = self._find_clip_location(clip)
        if loc is None:
            return None
        track, _, clip_idx = loc
        if track.kind not in {"video", "audio"} or self._is_track_locked(track):
            return None
        candidates = []
        if clip_idx < len(track.clips) - 1:
            candidates.append(clip_idx)
        if clip_idx > 0:
            candidates.append(clip_idx - 1)
        for from_index in candidates:
            if transition_duration_limit(track, from_index) >= 0.05:
                return track, from_index
        return None

    def _transition_remove_target_from_selection_or_clip(self, clip: Clip) -> tuple[Track, int] | None:
        selected_pair = self._transition_pair_from_selection()
        if selected_pair is not None:
            track, from_index = selected_pair
            return selected_pair if find_transition(track, from_index) is not None else None
        loc = self._find_clip_location(clip)
        if loc is None:
            return None
        track, _, clip_idx = loc
        if track.kind not in {"video", "audio"} or self._is_track_locked(track):
            return None
        for from_index in (clip_idx, clip_idx - 1):
            if from_index < 0:
                continue
            if find_transition(track, from_index) is not None:
                return track, from_index
        return None

    def add_transition_for_selection_or_clip(self, clip: Clip, *, kind: str = "fade") -> None:
        target = self._transition_target_from_selection_or_clip(clip)
        if target is None:
            return
        track, from_index = target
        try:
            set_track_transition(
                track,
                from_index,
                kind=kind,  # type: ignore[arg-type]
                duration=DEFAULT_TRANSITION_DURATION,
            )
        except ValueError:
            return
        pair = track.clips[from_index : from_index + 2]
        self.refresh()
        self.select_clips(pair)
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def remove_transition_for_selection_or_clip(self, clip: Clip) -> None:
        target = self._transition_remove_target_from_selection_or_clip(clip)
        if target is None:
            return
        track, from_index = target
        pair = track.clips[from_index : from_index + 2]
        if not remove_track_transition(track, from_index):
            return
        self.refresh()
        self.select_clips(pair)
        self.project_mutated.emit()
        self.seek_requested.emit(float(self._playhead_seconds))

    def _delete_side_clips(self, side: str) -> None:
        selected_items = self._selected_clip_items()
        if not selected_items:
            return
        selected = selected_items[-1].clip
        loc = self._find_clip_location(selected)
        if loc is None:
            return
        track, _, clip_idx = loc
        if self._is_track_locked(track):
            return
        old_clips = list(track.clips)
        old_transitions = list(track.transitions)
        if side == "left":
            if clip_idx <= 0:
                return
            removed_indices = set(range(0, clip_idx))
            del track.clips[:clip_idx]
        else:
            if clip_idx >= len(track.clips) - 1:
                return
            removed_indices = set(range(clip_idx + 1, len(old_clips)))
            del track.clips[clip_idx + 1 :]
        reindex_transitions_after_clip_delete(
            track,
            removed_indices,
            old_transitions,
            old_clip_count=len(old_clips),
        )
        self._unlink_orphaned_children()
        self.normalize_main_track_magnetic()
        self._auto_clean_empty_tracks()
        self._refresh_and_reselect(selected)
        self.project_mutated.emit()

    def _cut_selected_clip(self) -> None:
        selected_items = self._selected_clip_items()
        if not selected_items:
            return
        selected = selected_items[-1].clip
        loc = self._find_clip_location(selected)
        if loc is None:
            return
        track, _, clip_idx = loc
        if self._is_track_locked(track):
            return
        clip = track.clips[clip_idx]
        d = clip.timeline_duration
        t_sec = self._playhead_seconds
        if d is None or not (clip.start < t_sec < clip.start + d):
            return

        left_dur = t_sec - clip.start
        cut_out = clip.in_point + left_dur * clip.speed
        left = clip.model_copy(update={"out_point": cut_out})
        right = clip.model_copy(
            update={
                "clip_id": uuid4().hex,
                "in_point": cut_out,
                "start": t_sec,
                "link_group_id": None,
                "linked_parent_id": None,
                "linked_offset": 0.0,
            }
        )
        track.clips[clip_idx : clip_idx + 1] = [left, right]
        track.clips.sort(key=lambda c: c.start)
        normalize_track_transitions(track)
        self.normalize_main_track_magnetic()
        self._auto_clean_empty_tracks()
        self._refresh_and_reselect(right)
        self.project_mutated.emit()

    def ripple_delete_selected(self) -> None:
        selected = [it.clip for it in self._selected_clip_items()]
        if self._linked_selection_enabled:
            selected = self._expanded_linked_clips(selected)
        selected_ids = {id(clip) for clip in selected}
        if not selected_ids:
            return
        changed = False
        for track in self._project.tracks:
            if self._is_track_locked(track):
                continue
            if ripple_delete_clips_from_track(track, selected_ids):
                changed = True
        if not changed:
            return
        self._unlink_orphaned_children()
        self.normalize_main_track_magnetic()
        self._auto_clean_empty_tracks()
        self.refresh()
        self.project_mutated.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_refresh()

__all__ = ["TimelinePanel", "timeline_snap_times"]

