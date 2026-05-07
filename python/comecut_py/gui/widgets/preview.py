"""Center preview panel with HTML-parity footer controls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QByteArray, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal  # type: ignore
from PySide6.QtGui import (  # type: ignore
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...engine.audio_levels import AudioLevelStats, analyze_audio_levels, audio_clipping_warning

try:
    from PySide6.QtSvg import QSvgRenderer  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    QSvgRenderer = None

ICON_NORMAL = "#8c93a0"
ICON_ACTIVE = "#22d3c5"
PREVIEW_PLAY_SEEK_INTERVAL_MS = 45
PREVIEW_SCRUB_SEEK_INTERVAL_MS = 70
PREVIEW_METER_WINDOW_SECONDS = 12.0

_SYMBOL_RE = re.compile(
    r'<symbol\s+id="(?P<id>[^"]+)"(?P<attrs>[^>]*)>(?P<body>.*?)</symbol>',
    re.DOTALL,
)
_SYMBOL_CACHE: dict[str, tuple[str, str]] | None = None
_CONFIG_DIR = Path.home() / ".comecut_py"
_OCR_AREA_PATH = _CONFIG_DIR / "ocr_area.json"


def _fit_rect(outer: QRect, inner_w: int, inner_h: int) -> QRect:
    if outer.width() <= 0 or outer.height() <= 0 or inner_w <= 0 or inner_h <= 0:
        return QRect()
    scale = min(outer.width() / float(inner_w), outer.height() / float(inner_h))
    draw_w = max(1, int(round(inner_w * scale)))
    draw_h = max(1, int(round(inner_h * scale)))
    draw_x = outer.left() + (outer.width() - draw_w) // 2
    draw_y = outer.top() + (outer.height() - draw_h) // 2
    return QRect(draw_x, draw_y, draw_w, draw_h)


def compute_preview_rects(
    view_rect: QRect,
    *,
    image_size: tuple[int, int],
    canvas_size: tuple[int, int],
    transform_enabled: bool,
    clip_scale: float | None,
    clip_scale_x: float | None,
    clip_scale_y: float | None,
    pos_x: int | None,
    pos_y: int | None,
) -> tuple[QRect, QRect]:
    image_w = max(1, int(image_size[0]))
    image_h = max(1, int(image_size[1]))
    canvas_w = max(1, int(canvas_size[0]))
    canvas_h = max(1, int(canvas_size[1]))

    if not transform_enabled:
        fitted = _fit_rect(view_rect, image_w, image_h)
        return fitted, fitted

    project_rect = _fit_rect(view_rect, canvas_w, canvas_h)
    base_rect = _fit_rect(project_rect, image_w, image_h)
    if base_rect.isEmpty():
        return project_rect, project_rect

    has_axis_scale = clip_scale_x is not None or clip_scale_y is not None
    if not has_axis_scale and clip_scale is None and pos_x is None and pos_y is None:
        return project_rect, base_rect

    uniform_scale = 1.0 if clip_scale is None else max(0.01, min(5.0, float(clip_scale)))
    if has_axis_scale:
        sx = clip_scale_x
        sy = clip_scale_y
        if sx is None:
            sx = sy if sy is not None else uniform_scale
        if sy is None:
            sy = sx if sx is not None else uniform_scale
        scale_x = max(0.01, min(5.0, float(sx)))
        scale_y = max(0.01, min(5.0, float(sy)))
    else:
        scale_x = uniform_scale
        scale_y = uniform_scale

    draw_w = max(1, int(round(base_rect.width() * scale_x)))
    draw_h = max(1, int(round(base_rect.height() * scale_y)))

    if pos_x is None and pos_y is None:
        center_x = project_rect.center().x()
        center_y = project_rect.center().y()
    else:
        px = 0.0 if pos_x is None else float(pos_x)
        py = 0.0 if pos_y is None else float(pos_y)
        # Map project coordinates (relative to center) to preview widget coordinates
        center_x = project_rect.center().x() + int(round((px / canvas_w) * project_rect.width()))
        center_y = project_rect.center().y() - int(round((py / canvas_h) * project_rect.height()))

    draw_x = int(round(center_x - (draw_w / 2.0)))
    draw_y = int(round(center_y - (draw_h / 2.0)))
    video_rect = QRect(draw_x, draw_y, draw_w, draw_h)

    if video_rect.width() < project_rect.width():
        video_rect.moveLeft(
            max(project_rect.left(), min(video_rect.left(), project_rect.right() - video_rect.width() + 1))
        )
    if video_rect.height() < project_rect.height():
        video_rect.moveTop(
            max(project_rect.top(), min(video_rect.top(), project_rect.bottom() - video_rect.height() + 1))
        )
    return project_rect, video_rect


def _inset_rect_by_ratio(rect: QRect, ratio: float) -> QRect:
    if rect.isEmpty():
        return QRect()
    r = max(0.0, min(0.45, float(ratio)))
    dx = int(round(rect.width() * r))
    dy = int(round(rect.height() * r))
    return rect.adjusted(dx, dy, -dx, -dy)


def preview_safe_area_rects(project_rect: QRect) -> tuple[QRect, QRect]:
    """Return action-safe and title-safe rectangles for the preview canvas."""
    return _inset_rect_by_ratio(project_rect, 0.05), _inset_rect_by_ratio(project_rect, 0.10)


# ---------------------------------------------------------------------------
# Custom video canvas with subtitle overlay
# ---------------------------------------------------------------------------

class _VideoCanvas(QWidget):
    """Renders QVideoFrames via QPainter so we can draw subtitle text on top."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._current_frame: QVideoFrame | None = None
        self._current_image: QImage | None = None
        self._subtitle_main: str = ""
        self._subtitle_second: str = ""
        self._subtitle_pos_x: int | None = None
        self._subtitle_pos_y: int | None = None
        self._subtitle_font_size: int = 36
        self._project_canvas_size: tuple[int, int] = (1920, 1080)
        self._video_transform_enabled = False
        self._video_scale: float | None = None
        self._video_scale_x: float | None = None
        self._video_scale_y: float | None = None
        self._video_pos_x: int | None = None
        self._video_pos_y: int | None = None
        self._video_rotate: float | None = None

        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)

    @property
    def video_sink(self) -> QVideoSink:
        return self._sink

    def _on_frame(self, frame: QVideoFrame) -> None:
        self._current_frame = frame
        self._current_image = None  # invalidate cached image
        self.update()

    def set_subtitle(self, main: str, second: str) -> None:
        self._subtitle_main = main.strip()
        self._subtitle_second = second.strip()
        self.update()

    def set_subtitle_position(
        self,
        pos_x: int | None,
        pos_y: int | None,
        font_size: int,
        canvas_size: tuple[int, int],
    ) -> None:
        self._subtitle_pos_x = None if pos_x is None else int(pos_x)
        self._subtitle_pos_y = None if pos_y is None else int(pos_y)
        self._subtitle_font_size = max(8, int(font_size))
        canvas_w = max(1, int(canvas_size[0])) if len(canvas_size) > 0 else 1920
        canvas_h = max(1, int(canvas_size[1])) if len(canvas_size) > 1 else 1080
        self._project_canvas_size = (canvas_w, canvas_h)
        self.update()

    def set_video_transform(
        self,
        scale: float | None,
        pos_x: int | None,
        pos_y: int | None,
        rotate: float | None,
        canvas_size: tuple[int, int],
        scale_x: float | None = None,
        scale_y: float | None = None,
    ) -> None:
        canvas_w = max(1, int(canvas_size[0])) if len(canvas_size) > 0 else 1920
        canvas_h = max(1, int(canvas_size[1])) if len(canvas_size) > 1 else 1080
        self._project_canvas_size = (canvas_w, canvas_h)
        self._video_transform_enabled = True
        self._video_scale = None if scale is None else float(scale)
        self._video_scale_x = None if scale_x is None else float(scale_x)
        self._video_scale_y = None if scale_y is None else float(scale_y)
        self._video_pos_x = None if pos_x is None else int(pos_x)
        self._video_pos_y = None if pos_y is None else int(pos_y)
        self._video_rotate = None if rotate is None else float(rotate)
        self.update()

    def clear_video_transform(self) -> None:
        self._video_transform_enabled = False
        self._video_scale = None
        self._video_scale_x = None
        self._video_scale_y = None
        self._video_pos_x = None
        self._video_pos_y = None
        self._video_rotate = None
        self.update()

    def clear_frame(self) -> None:
        self._current_frame = None
        self._current_image = None
        self._subtitle_main = ""
        self._subtitle_second = ""
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self._video_rect = QRect()
        self._project_rect = QRect()
        # Draw video frame
        img = self._get_image()
        if img is not None and not img.isNull():
            project_rect, video_rect = compute_preview_rects(
                self.rect(),
                image_size=(img.width(), img.height()),
                canvas_size=self._project_canvas_size,
                transform_enabled=self._video_transform_enabled,
                clip_scale=self._video_scale,
                clip_scale_x=self._video_scale_x,
                clip_scale_y=self._video_scale_y,
                pos_x=self._video_pos_x,
                pos_y=self._video_pos_y,
            )
            self._project_rect = project_rect if not project_rect.isEmpty() else self.rect()
            self._video_rect = video_rect if not video_rect.isEmpty() else self._project_rect
            
            # Draw the black canvas background only where the project_rect is
            painter.fillRect(self._project_rect, QColor("#000000"))
            
            painter.save()
            if self._video_rotate:
                # Rotate around center of video_rect
                center = self._video_rect.center()
                painter.translate(center)
                painter.rotate(self._video_rotate)
                painter.translate(-center)
            
            painter.drawImage(self._video_rect, img)
            painter.restore()

            self._draw_canvas_guides(painter)
            
            if self._subtitle_main or self._subtitle_second:
                self._draw_subtitles(painter, self._project_rect)
        else:
            self._project_rect = self.rect()
            self._video_rect = self.rect()
            self._draw_canvas_guides(painter)
            # No frame - draw subtitle bar only if needed
            if self._subtitle_main or self._subtitle_second:
                self._draw_subtitles(painter, self._project_rect)

        painter.end()

    @property
    def video_rect(self) -> QRect:
        return getattr(self, "_video_rect", self.rect())

    @property
    def project_rect(self) -> QRect:
        return getattr(self, "_project_rect", self.rect())

    def _get_image(self) -> QImage | None:
        if self._current_frame is None:
            return None
        if self._current_image is not None:
            return self._current_image
        frame = self._current_frame
        if not frame.isValid():
            return None
        img = frame.toImage()
        if img.isNull():
            return None
        # Convert to a format QPainter handles well
        self._current_image = img.convertToFormat(QImage.Format.Format_RGB32)
        return self._current_image

    def _draw_canvas_guides(self, painter: QPainter) -> None:
        if not self._video_transform_enabled:
            return
        project_rect = self.project_rect
        if project_rect.isEmpty() or project_rect.width() <= 2 or project_rect.height() <= 2:
            return

        action_safe, title_safe = preview_safe_area_rects(project_rect)
        center = project_rect.center()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        center_pen = QPen(QColor(255, 255, 255, 72), 1)
        center_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(center_pen)
        painter.drawLine(center.x(), project_rect.top(), center.x(), project_rect.bottom())
        painter.drawLine(project_rect.left(), center.y(), project_rect.right(), center.y())

        action_pen = QPen(QColor(34, 211, 197, 62), 1)
        action_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(action_pen)
        painter.drawRect(action_safe)

        title_pen = QPen(QColor(255, 255, 255, 42), 1)
        title_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(title_pen)
        painter.drawRect(title_safe)

        painter.restore()

    def _subtitle_lines(self) -> list[str]:
        return [line for line in (self._subtitle_main, self._subtitle_second) if line]

    def _subtitle_layout(self, video_rect: QRect) -> tuple[list[str], QRect, QFont, int, int, int]:
        lines = self._subtitle_lines()
        if not lines:
            return [], QRect(), QFont("Arial", 0), 0, 0, 0

        canvas_w, canvas_h = self._project_canvas_size
        canvas_h = max(1, int(canvas_h))
        canvas_w = max(1, int(canvas_w))
        scale_y = video_rect.height() / canvas_h
        scale_x = video_rect.width() / canvas_w

        font_px = max(8, int(self._subtitle_font_size * scale_y))
        font = QFont("Arial", 0)
        font.setPixelSize(font_px)
        font.setBold(True)

        fm = QFontMetrics(font)
        line_h = fm.height()
        padding_x = int(font_px * 0.6)
        padding_y = int(font_px * 0.3)
        line_spacing = int(font_px * 0.2)
        total_h = len(lines) * line_h + (len(lines) - 1) * line_spacing + padding_y * 2
        max_line_w = max(fm.horizontalAdvance(l) for l in lines) if lines else 0
        block_w = max_line_w + padding_x * 2
        block_h = total_h

        if self._subtitle_pos_x is not None and self._subtitle_pos_y is not None:
            cx = video_rect.left() + int(self._subtitle_pos_x * scale_x)
            cy = video_rect.top() + int(self._subtitle_pos_y * scale_y)
            block_x = cx - block_w // 2
            block_y = cy - block_h // 2
        else:
            margin_bottom = int(video_rect.height() * 0.06)
            block_x = video_rect.left() + (video_rect.width() - block_w) // 2
            block_y = video_rect.bottom() - block_h - margin_bottom

        if block_w >= video_rect.width():
            block_w = video_rect.width()
            block_x = video_rect.left()
        else:
            block_x = max(video_rect.left(), min(block_x, video_rect.right() - block_w + 1))

        if block_h >= video_rect.height():
            block_h = video_rect.height()
            block_y = video_rect.top()
        else:
            block_y = max(video_rect.top(), min(block_y, video_rect.bottom() - block_h + 1))

        block_rect = QRect(int(block_x), int(block_y), int(block_w), int(block_h))
        return lines, block_rect, font, padding_x, padding_y, line_spacing

    def compute_subtitle_rect(self) -> QRect:
        lines, rect, _font, _px, _py, _ls = self._subtitle_layout(self.project_rect)
        if not lines:
            return QRect()
        return rect

    def subtitle_canvas_center(self) -> tuple[int, int]:
        rect = self.compute_subtitle_rect()
        if rect.isEmpty():
            w, h = self._project_canvas_size
            return w // 2, h // 2
        project_rect = self.project_rect
        if project_rect.width() <= 0 or project_rect.height() <= 0:
            w, h = self._project_canvas_size
            return w // 2, h // 2
        w, h = self._project_canvas_size
        scale_x = w / max(1, project_rect.width())
        scale_y = h / max(1, project_rect.height())
        cx = int((rect.center().x() - project_rect.left()) * scale_x)
        cy = int((rect.center().y() - project_rect.top()) * scale_y)
        return max(0, min(w, cx)), max(0, min(h, cy))

    def _draw_subtitles(self, painter: QPainter, video_rect: QRect) -> None:
        lines, block_rect, font, padding_x, padding_y, line_spacing = self._subtitle_layout(video_rect)
        if not lines:
            return

        painter.setFont(font)
        line_h = QFontMetrics(font).height()

        # Draw semi-transparent background pill
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(
            block_rect.x(),
            block_rect.y(),
            block_rect.width(),
            block_rect.height(),
            4,
            4,
        )
        painter.fillPath(path, QColor(0, 0, 0, 150))
        painter.restore()

        # Draw each line centred
        y = block_rect.y() + padding_y
        for line in lines:
            text_rect = QRect(
                block_rect.x() + padding_x,
                y,
                max(0, block_rect.width() - padding_x * 2),
                line_h,
            )
            # Stroke / shadow
            painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                shifted = text_rect.translated(dx, dy)
                painter.drawText(shifted, Qt.AlignmentFlag.AlignCenter, line)
            # Main text
            painter.setPen(QColor("#ffffff"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, line)
            y += line_h + line_spacing


class _SubtitleDragOverlay(QWidget):
    """Interactive subtitle drag/resize overlay on top of preview video."""

    position_changed = Signal(int, int)
    font_size_changed = Signal(int)
    drag_finished = Signal()

    def __init__(self, video_canvas: _VideoCanvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._canvas = video_canvas
        self._active = False
        self._hover = False
        self._dragging = False
        self._resizing = False
        self._resize_dir: str | None = None
        self._sub_rect = QRect()
        self._drag_start = QPoint()
        self._drag_anchor_center: tuple[int, int] = (0, 0)
        self._drag_start_font: int = 36
        self.hide()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active:
            self.show()
            self.raise_()
        else:
            self.hide()
            self._hover = False
            self._dragging = False
            self._resizing = False
            self._resize_dir = None
        self.update()

    def _sync_sub_rect(self) -> None:
        self._sub_rect = self._canvas.compute_subtitle_rect()

    def _get_resize_dir(self, pos: QPoint) -> str | None:
        rect = self._sub_rect
        if rect.isEmpty():
            return None
        margin = 10
        near_l = abs(pos.x() - rect.left()) <= margin
        near_r = abs(pos.x() - rect.right()) <= margin
        near_t = abs(pos.y() - rect.top()) <= margin
        near_b = abs(pos.y() - rect.bottom()) <= margin
        if near_t and near_l:
            return "tl"
        if near_t and near_r:
            return "tr"
        if near_b and near_l:
            return "bl"
        if near_b and near_r:
            return "br"
        if near_t:
            return "t"
        if near_b:
            return "b"
        if near_l:
            return "l"
        if near_r:
            return "r"
        return None

    def enterEvent(self, event) -> None:  # type: ignore[override]
        super().enterEvent(event)
        if not self._active:
            return
        self._hover = True
        self._sync_sub_rect()
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        super().leaveEvent(event)
        self._hover = False
        if not (self._dragging or self._resizing):
            self.unsetCursor()
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._active:
            return
        self._sync_sub_rect()
        rect = self._sub_rect
        if rect.isEmpty():
            return
        if not (self._hover or self._dragging or self._resizing):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = 70 if (self._dragging or self._resizing) else 40
        painter.setPen(QPen(QColor("#00E5FF"), 2.0))
        painter.setBrush(QColor(0, 229, 255, alpha))
        painter.drawRect(rect)

        hs = 8
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#00E5FF"))
        points = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomLeft(),
            rect.bottomRight(),
            QPoint(rect.center().x(), rect.top()),
            QPoint(rect.center().x(), rect.bottom()),
            QPoint(rect.left(), rect.center().y()),
            QPoint(rect.right(), rect.center().y()),
        ]
        for pt in points:
            painter.drawRect(pt.x() - hs // 2, pt.y() - hs // 2, hs, hs)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if not self._active or event.button() != Qt.MouseButton.LeftButton:
            return
        self._sync_sub_rect()
        if self._sub_rect.isEmpty():
            return
        resize_dir = self._get_resize_dir(event.pos())
        if resize_dir is not None:
            self._resizing = True
            self._resize_dir = resize_dir
            self._drag_start = event.pos()
            self._drag_start_font = int(self._canvas._subtitle_font_size)
            return
        if self._sub_rect.contains(event.pos()):
            self._dragging = True
            self._drag_start = event.pos()
            self._drag_anchor_center = self._canvas.subtitle_canvas_center()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        super().mouseMoveEvent(event)
        if not self._active:
            return
        self._sync_sub_rect()

        if not (self._dragging or self._resizing):
            resize_dir = self._get_resize_dir(event.pos())
            if resize_dir in ("tl", "br"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif resize_dir in ("tr", "bl"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif resize_dir in ("t", "b"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif resize_dir in ("l", "r"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self._sub_rect.contains(event.pos()):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            return

        video_rect = self._canvas.video_rect
        canvas_w, canvas_h = self._canvas._project_canvas_size
        if video_rect.width() <= 0 or video_rect.height() <= 0:
            return

        if self._dragging:
            delta = event.pos() - self._drag_start
            dx_canvas = int(delta.x() * canvas_w / video_rect.width())
            dy_canvas = int(delta.y() * canvas_h / video_rect.height())
            new_x = self._drag_anchor_center[0] + dx_canvas
            new_y = self._drag_anchor_center[1] + dy_canvas
            new_x = max(0, min(canvas_w, new_x))
            new_y = max(0, min(canvas_h, new_y))
            self.position_changed.emit(new_x, new_y)
            self.update()
            return

        if self._resizing:
            delta = event.pos() - self._drag_start
            dir_ = self._resize_dir or ""
            signed = 0
            if "t" in dir_:
                signed -= delta.y()
            if "b" in dir_:
                signed += delta.y()
            if "l" in dir_:
                signed -= delta.x()
            if "r" in dir_:
                signed += delta.x()
            new_size = max(8, min(300, self._drag_start_font + int(signed * 0.5)))
            self.font_size_changed.emit(new_size)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        was_active = self._dragging or self._resizing
        self._dragging = False
        self._resizing = False
        self._resize_dir = None
        if was_active:
            self.drag_finished.emit()
        self.update()


class _TransformOverlay(QWidget):
    """Interactive video resize/rotate/drag overlay."""

    transform_changed = Signal(float, int, int, float)  # scale, x, y, rotate
    drag_finished = Signal()

    def __init__(self, video_canvas: _VideoCanvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._canvas = video_canvas
        self._active = False
        self._hover = False
        self._dragging = False
        self._resizing = False
        self._rotating = False
        self._handle_dir: str | None = None
        
        self._drag_start_pos = QPoint()
        self._drag_start_scale = 1.0
        self._drag_start_pos_x = 0
        self._drag_start_pos_y = 0
        self._drag_start_rotate = 0.0
        self._drag_start_angle = 0.0
        
        self.hide()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if self._active:
            self.show()
            self.raise_()
        else:
            self.hide()
            self._dragging = False
            self._resizing = False
            self._rotating = False
        self.update()

    def _get_handle(self, pos: QPoint) -> str | None:
        rect = self._canvas.video_rect
        if rect.isEmpty():
            return None
        
        # We need to account for rotation when checking handles
        # For now, let's assume no rotation for handle detection, or use a simpler approach
        # A better way is to un-rotate the mouse point
        rot = self._canvas._video_rotate or 0.0
        if rot != 0:
            transform = QTransform()
            center = rect.center()
            transform.translate(center.x(), center.y())
            transform.rotate(-rot)
            transform.translate(-center.x(), -center.y())
            local_pos = transform.map(pos)
        else:
            local_pos = pos

        margin = 12
        # Check rotation handle (bottom center circle)
        rot_handle_y = rect.bottom() + 30
        rot_handle_rect = QRect(rect.center().x() - 15, rot_handle_y - 15, 30, 30)
        # We check the rotation handle in screen space because it's usually fixed relative to the box
        # Actually, let's keep it simple: if rotation is 0, local_pos is enough.
        # If rotated, we still check relative to the box.
        
        if QRect(rect.center().x() - 12, rect.bottom() + 18, 24, 24).contains(local_pos):
            return "rotate"

        near_l = abs(local_pos.x() - rect.left()) <= margin
        near_r = abs(local_pos.x() - rect.right()) <= margin
        near_t = abs(local_pos.y() - rect.top()) <= margin
        near_b = abs(local_pos.y() - rect.bottom()) <= margin

        if near_t and near_l: return "tl"
        if near_t and near_r: return "tr"
        if near_b and near_l: return "bl"
        if near_b and near_r: return "br"
        
        if rect.contains(local_pos):
            return "move"
            
        return None

    def enterEvent(self, event) -> None:
        if self._active:
            self._hover = True
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        if not (self._dragging or self._resizing or self._rotating):
            self.unsetCursor()
        self.update()

    def paintEvent(self, event) -> None:
        if not self._active: return
        rect = self._canvas.video_rect
        if rect.isEmpty(): return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rot = self._canvas._video_rotate or 0.0
        painter.save()
        if rot != 0:
            center = rect.center()
            painter.translate(center)
            painter.rotate(rot)
            painter.translate(-center)
            
        # Draw bounding box
        painter.setPen(QPen(QColor("#22d3c5"), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        
        # Draw corner handles (circles)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#22d3c5"), 1))
        r = 5
        for pt in [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()]:
            painter.drawEllipse(pt, r, r)
            
        # Draw rotation handle line and icon
        painter.setPen(QPen(QColor("#22d3c5"), 1))
        painter.drawLine(rect.center().x(), rect.bottom(), rect.center().x(), rect.bottom() + 18)
        
        painter.setBrush(QColor("#1a1d23"))
        painter.drawEllipse(rect.center().x() - 10, rect.bottom() + 18, 20, 20)
        
        # Rotation icon (mini arrow circle)
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.drawArc(rect.center().x() - 6, rect.bottom() + 12 + 10, 12, 12, 45 * 16, 270 * 16)
        
        painter.restore()

    def mousePressEvent(self, event) -> None:
        if not self._active or event.button() != Qt.MouseButton.LeftButton: return
        
        self._handle_dir = self._get_handle(event.pos())
        if not self._handle_dir: return
        
        self._drag_start_pos = event.pos()
        self._drag_start_scale = (
            self._canvas._video_scale
            or self._canvas._video_scale_x
            or self._canvas._video_scale_y
            or 1.0
        )
        self._drag_start_pos_x = self._canvas._video_pos_x or 0
        self._drag_start_pos_y = self._canvas._video_pos_y or 0
        self._drag_start_rotate = self._canvas._video_rotate or 0.0
        
        if self._handle_dir == "rotate":
            self._rotating = True
            center = self._canvas.video_rect.center()
            diff = event.pos() - center
            self._drag_start_angle = math.degrees(math.atan2(diff.y(), diff.x()))
        elif self._handle_dir in ("tl", "tr", "bl", "br"):
            self._resizing = True
        elif self._handle_dir == "move":
            self._dragging = True

    def mouseMoveEvent(self, event) -> None:
        if not self._active: return
        
        if not (self._dragging or self._resizing or self._rotating):
            handle = self._get_handle(event.pos())
            if handle in ("tl", "br"): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif handle in ("tr", "bl"): self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif handle == "move": self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif handle == "rotate": self.setCursor(Qt.CursorShape.PointingHandCursor)
            else: self.unsetCursor()
            return

        rect = self._canvas.video_rect
        canvas_w, canvas_h = self._canvas._project_canvas_size
        
        if self._dragging:
            delta = event.pos() - self._drag_start_pos
            # Project space movement
            dx = delta.x() * canvas_w / self._canvas.project_rect.width()
            dy = delta.y() * canvas_h / self._canvas.project_rect.height()
            
            new_x = int(self._drag_start_pos_x + dx)
            new_y = int(self._drag_start_pos_y - dy)
            
            # Snap to center (within 20 pixels in project space)
            if abs(new_x) < 20: new_x = 0
            if abs(new_y) < 20: new_y = 0
            
            self.transform_changed.emit(
                self._drag_start_scale,
                new_x,
                new_y,
                self._drag_start_rotate
            )
        
        elif self._resizing:
            # Simple scale by distance from center
            center = rect.center()
            dist_start = math.hypot(self._drag_start_pos.x() - center.x(), self._drag_start_pos.y() - center.y())
            dist_now = math.hypot(event.pos().x() - center.x(), event.pos().y() - center.y())
            
            if dist_start > 0:
                new_scale = self._drag_start_scale * (dist_now / dist_start)
                
                # Snap to 1.0 (within 3% threshold)
                if 0.97 <= new_scale <= 1.03:
                    new_scale = 1.0
                
                new_scale = max(0.01, min(5.0, new_scale))
                self.transform_changed.emit(
                    new_scale,
                    self._drag_start_pos_x,
                    self._drag_start_pos_y,
                    self._drag_start_rotate
                )
                
        elif self._rotating:
            center = rect.center()
            diff = event.pos() - center
            current_angle = math.degrees(math.atan2(diff.y(), diff.x()))
            angle_delta = current_angle - self._drag_start_angle
            new_rot = (self._drag_start_rotate + angle_delta) % 360
            if new_rot > 180: new_rot -= 360
            
            # Snap to common angles (0, 90, 180, -90) within 2.0 degree threshold
            for snap_angle in [0, 90, 180, -90, -180]:
                if abs(new_rot - snap_angle) < 2.0:
                    new_rot = float(snap_angle)
                    break
            
            self.transform_changed.emit(
                self._drag_start_scale,
                self._drag_start_pos_x,
                self._drag_start_pos_y,
                new_rot
            )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            was_active = self._dragging or self._resizing or self._rotating
            self._dragging = False
            self._resizing = False
            self._rotating = False
            if was_active:
                self.drag_finished.emit()
        self.update()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PreviewFullscreenWindow(QWidget):
    request_close = Signal()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.request_close.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.request_close.emit()
        event.accept()


def _fmt_time(ms: int) -> str:
    """Format milliseconds as HH:MM:SS.cc (centiseconds)."""
    if ms < 0:
        ms = 0
    cs = (ms % 1000) // 10
    s_total = ms // 1000
    h, rem = divmod(s_total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{cs:02d}"


def _fmt_dbfs(value: float) -> str:
    if not math.isfinite(value):
        return "-inf dBFS"
    return f"{value:.1f} dBFS"


def format_audio_meter_summary(label: str, stats: AudioLevelStats | None) -> tuple[str, str, bool]:
    """Return (short text, detailed text, warning) for preview meter UI."""
    if stats is None or stats.total_samples <= 0:
        return f"{label}: no audio", f"{label}: no analyzable audio in this window.", False

    warning = audio_clipping_warning(stats)
    short = f"{label}: Pk {_fmt_dbfs(stats.peak_dbfs)}"
    detail = (
        f"{label}\n"
        f"Peak: {_fmt_dbfs(stats.peak_dbfs)}\n"
        f"RMS: {_fmt_dbfs(stats.rms_dbfs)}\n"
        f"Clipped samples: {stats.clipped_samples} "
        f"({stats.clipped_ratio * 100.0:.3f}%)"
    )
    if warning:
        detail += f"\nWarning: {warning}"
    return short, detail, warning is not None


def _load_preview_symbols() -> dict[str, tuple[str, str]]:
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
        sid = m.group("id")
        if sid.startswith("icon-editor-preview-"):
            symbols[sid] = (m.group("attrs"), m.group("body"))
    _SYMBOL_CACHE = symbols
    return symbols


def _preview_icon(symbol_id: str, *, color: str = ICON_NORMAL, size: int = 16) -> QIcon:
    if QSvgRenderer is None:
        return QIcon()
    symbol = _load_preview_symbols().get(symbol_id)
    if symbol is None:
        return QIcon()
    attrs, body = symbol
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


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class PreviewPanel(QWidget):
    position_changed = Signal(int)  # current playhead in milliseconds
    playpause_requested = Signal()
    playback_state_changed = Signal(bool)
    media_ended = Signal()
    ocr_area_selected = Signal(float, float, float, float)  # y1, y2, x1, x2 (0.0-1.0)
    ocr_cancelled = Signal()
    transform_changed = Signal(float, int, int, float)  # scale, x, y, rotate
    transform_finished = Signal()
    _meter_result_ready = Signal(int, object)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("PREVIEW")
        header.setObjectName("sectionHeader")
        header.setFixedHeight(48)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(8)
        self._body_layout = body

        # Video container (plain QFrame - no native child)
        self._video_container = QFrame()
        self._video_container.setObjectName("panel")
        self._video_container.setStyleSheet(
            "background: #1a1d23; border-radius: 2px; border: none;"
        )
        container_layout = QVBoxLayout(self._video_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        self._video_home_layout = container_layout

        # Custom canvas - renders video + subtitle in one QPainter pass
        self._video = _VideoCanvas()
        container_layout.addWidget(self._video)
        self._sub_overlay = _SubtitleDragOverlay(self._video, self._video)
        self._sub_overlay.setGeometry(self._video.rect())
        self._sub_overlay.hide()

        self._transform_overlay = _TransformOverlay(self._video, self._video)
        self._transform_overlay.setGeometry(self._video.rect())
        self._transform_overlay.hide()
        self._transform_overlay.transform_changed.connect(self.transform_changed)
        self._transform_overlay.drag_finished.connect(self.transform_finished)

        body.addWidget(self._video_container, stretch=1)

        # OCR selection overlay (hidden by default)
        from .ocr_selector_overlay import OcrSelectorOverlay  # type: ignore
        self._ocr_overlay = OcrSelectorOverlay(self._video_container)
        self._ocr_overlay.hide()
        self._ocr_overlay.area_selected.connect(self._on_ocr_area_selected)
        self._ocr_overlay.cancelled.connect(self._on_ocr_cancelled)
        self._ocr_video_area: tuple[float, float, float, float] | None = self._load_saved_ocr_video_area()

        # ---- Footer ----
        footer = QFrame()
        footer.setObjectName("panel")
        footer.setFixedHeight(44)
        footer.setStyleSheet("background: transparent; border: none;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 0, 10, 0)
        footer_layout.setSpacing(8)

        self._time_lbl = QLabel("00:00:00.00 / 00:00:00.00")
        self._time_lbl.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 11px; "
            "color: #8c93a0;"
        )
        footer_layout.addWidget(self._time_lbl)

        footer_layout.addStretch(1)

        self._play_btn = QToolButton()
        self._play_btn.setObjectName("iconBtn")
        self._play_btn.setFixedSize(28, 28)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.clicked.connect(self.playpause_requested.emit)
        footer_layout.addWidget(self._play_btn)

        footer_layout.addStretch(1)

        right_controls = QWidget()
        right_layout = QHBoxLayout(right_controls)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._meter_btn = QToolButton()
        self._meter_btn.setObjectName("iconBtn")
        self._meter_btn.setFixedSize(26, 26)
        self._meter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._meter_btn.setToolTip("Preview meter")
        self._meter_btn.clicked.connect(self._request_meter_analysis)
        right_layout.addWidget(self._meter_btn)

        self._meter_badge = QLabel("")
        self._meter_badge.setVisible(False)
        self._meter_badge.setMinimumWidth(92)
        self._meter_badge.setStyleSheet(
            """
            QLabel {
                background: #111318;
                border: 1px solid #27303a;
                border-radius: 4px;
                color: #a7f3d0;
                font-size: 10px;
                padding: 3px 6px;
            }
            """
        )
        right_layout.addWidget(self._meter_badge)

        self._aspect = QComboBox()
        self._aspect.addItems(["16:9", "9:16", "1:1", "4:3", "21:9"])
        self._aspect.setCurrentText("16:9")
        self._aspect.setFixedWidth(82)
        self._aspect.setStyleSheet(
            """
            QComboBox {
                background: #111318;
                border: 1px solid #2a2f38;
                border-radius: 4px;
                color: #e6e8ec;
                font-size: 11px;
                padding: 2px 8px;
            }
            QComboBox::drop-down { border: none; width: 16px; }
            """
        )
        right_layout.addWidget(self._aspect)

        self._full_btn = QToolButton()
        self._full_btn.setObjectName("iconBtn")
        self._full_btn.setFixedSize(26, 26)
        self._full_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._full_btn.clicked.connect(self._toggle_fullscreen)
        right_layout.addWidget(self._full_btn)

        footer_layout.addWidget(right_controls)
        self._footer = footer
        body.addWidget(footer)
        layout.addLayout(body)

        self._fullscreen_window: _PreviewFullscreenWindow | None = None
        self._fullscreen_video_host: QFrame | None = None
        self._fullscreen_footer_shell: QFrame | None = None

        # Media player - uses QVideoSink instead of QVideoWidget
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setVideoSink(self._video.video_sink)
        self._player.setAudioOutput(self._audio)
        self._timeline_audio_player = QMediaPlayer(self)
        self._timeline_audio = QAudioOutput(self)
        self._timeline_audio_player.setAudioOutput(self._timeline_audio)
        try:
            self._timeline_audio_player.setPitchCompensation(True)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._timeline_audio_source_path: str | None = None
        self._timeline_audio_source_key: str | None = None
        self._timeline_audio_last_seek_ms: int = -1
        self._timeline_audio_last_seek_ts: float = 0.0
        self._timeline_audio_should_play = False
        self._media_source_path: str | None = None
        self._timeline_play_available = False
        self._timeline_playing_override: bool | None = None
        self._meter_token = 0
        self._meter_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="preview-meter",
        )

        self._duration_ms = 0
        self._timeline_time_display_enabled = False
        self._timeline_current_ms = 0
        self._timeline_total_ms = 0
        self._pending_seek_ms: int | None = None
        self._last_seek_ms: int = -1
        self._last_seek_flush_ts: float = 0.0
        self._seek_on_load_ms: int | None = None
        self._pending_play_on_load = False
        self._pending_play_seek_ms: int | None = None
        self._prime_seek_ms: int | None = None
        self._prime_prev_muted: bool | None = None
        self._seek_flush = QTimer(self)
        self._seek_flush.setSingleShot(True)
        self._seek_flush.timeout.connect(self._flush_pending_seek)
        self._prime_timer = QTimer(self)
        self._prime_timer.setSingleShot(True)
        self._prime_timer.timeout.connect(self._finish_prime_frame)
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._timeline_audio_player.playbackStateChanged.connect(
            self._on_timeline_audio_playback_state_changed
        )
        self._meter_result_ready.connect(self._on_meter_result_ready)

        self._apply_footer_icons()
        self._sync_play_icon()

    # ---- icons ----

    def _apply_footer_icons(self) -> None:
        self._apply_icon(
            self._meter_btn,
            "icon-editor-preview-meter",
            color=ICON_ACTIVE,
            size=16,
            fallback="[]",
        )
        self._apply_icon(
            self._full_btn,
            "icon-editor-preview-fullscreen",
            color=ICON_NORMAL,
            size=15,
            fallback="[]",
        )

    @staticmethod
    def _apply_icon(
        btn: QToolButton,
        symbol_id: str,
        *,
        color: str,
        size: int,
        fallback: str = "",
    ) -> None:
        icon = _preview_icon(symbol_id, color=color, size=size)
        if icon.isNull():
            btn.setText(fallback)
            btn.setIcon(QIcon())
            return
        btn.setText("")
        btn.setIcon(icon)
        btn.setIconSize(QSize(size, size))

    def _sync_play_icon(self) -> None:
        has_source = not self._player.source().isEmpty()
        can_play = has_source or bool(self._timeline_play_available)
        self._play_btn.setEnabled(can_play)
        if can_play:
            self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self._play_btn.setCursor(Qt.CursorShape.ArrowCursor)

        if self._timeline_playing_override is None:
            is_playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        else:
            is_playing = bool(self._timeline_playing_override)
        symbol = "icon-editor-preview-pause" if is_playing else "icon-editor-preview-play"
        fallback = "||" if is_playing else ">"
        
        self._apply_icon(
            self._play_btn,
            symbol,
            color=ICON_NORMAL,
            size=16,
            fallback=fallback,
        )

    def set_timeline_play_available(self, available: bool) -> None:
        self._timeline_play_available = bool(available)
        self._sync_play_icon()

    def set_timeline_playing_override(self, playing: bool | None) -> None:
        self._timeline_playing_override = None if playing is None else bool(playing)
        self._sync_play_icon()

    def set_timeline_time_display(self, current_ms: int, total_ms: int) -> None:
        try:
            current_i = int(current_ms)
        except Exception:
            current_i = 0
        try:
            total_i = int(total_ms)
        except Exception:
            total_i = 0
        current_i = max(0, current_i)
        total_i = max(0, total_i)
        if total_i > 0:
            current_i = min(current_i, total_i)
        self._timeline_time_display_enabled = True
        self._timeline_current_ms = current_i
        self._timeline_total_ms = total_i
        self._update_time(current_i)

    def clear_timeline_time_display(self) -> None:
        self._timeline_time_display_enabled = False
        self._update_time(self._player.position())

    # ---- playback control ----

    def load(self, path: Path | str) -> None:
        self._cancel_prime_frame(keep_playing=False)
        if self._seek_flush.isActive():
            self._seek_flush.stop()
        self._pending_seek_ms = None
        self._last_seek_ms = -1
        self._seek_on_load_ms = 0
        self._pending_play_on_load = False
        self._pending_play_seek_ms = None
        self._duration_ms = 0
        self._media_source_path = str(path)
        self._clear_meter_status()
        self._player.pause()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self.seek(0)
        self._sync_play_icon()

    def clear(self) -> None:
        self._cancel_prime_frame(keep_playing=False)
        if self._seek_flush.isActive():
            self._seek_flush.stop()
        self._pending_seek_ms = None
        self._seek_on_load_ms = None
        self._pending_play_on_load = False
        self._pending_play_seek_ms = None
        self._last_seek_ms = -1
        self._duration_ms = 0
        self._media_source_path = None
        self._clear_meter_status()
        self._player.stop()
        self._player.setSource(QUrl())
        self.clear_timeline_audio()
        self._video.clear_frame()
        self._video.clear_video_transform()
        self._update_time(0)
        self._sync_play_icon()

    def clear_video_preview(self) -> None:
        """Clear only the main preview video/audio source, keeping timeline audio alive."""
        self._cancel_prime_frame(keep_playing=False)
        if self._seek_flush.isActive():
            self._seek_flush.stop()
        self._pending_seek_ms = None
        self._seek_on_load_ms = None
        self._pending_play_on_load = False
        self._pending_play_seek_ms = None
        self._last_seek_ms = -1
        self._duration_ms = 0
        self._media_source_path = None
        self._clear_meter_status()
        self._player.stop()
        self._player.setSource(QUrl())
        self._video.clear_frame()
        self._video.clear_video_transform()
        self._sync_play_icon()

    def _normalize_seek_ms(self, ms: int) -> int:
        try:
            ms_i = int(ms)
        except Exception:
            ms_i = 0
        if ms_i < 0:
            ms_i = 0
        if self._duration_ms > 0:
            ms_i = min(ms_i, self._duration_ms)
        return ms_i

    def seek(self, ms: int, *, throttle: bool = False) -> None:
        """Seek preview playback to a specific position (milliseconds)."""
        ms_i = self._normalize_seek_ms(ms)
        is_playing = (
            self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        if not throttle and not is_playing:
            if self._seek_flush.isActive():
                self._seek_flush.stop()
            self._pending_seek_ms = None
            if ms_i != self._last_seek_ms:
                self._last_seek_ms = ms_i
                self._last_seek_flush_ts = monotonic()
                self._player.setPosition(ms_i)
            return

        self._pending_seek_ms = ms_i
        interval_ms = (
            PREVIEW_PLAY_SEEK_INTERVAL_MS if is_playing else PREVIEW_SCRUB_SEEK_INTERVAL_MS
        )
        if throttle:
            now = monotonic()
            elapsed_ms = (now - self._last_seek_flush_ts) * 1000.0
            if self._last_seek_flush_ts <= 0.0 or elapsed_ms >= interval_ms:
                if self._seek_flush.isActive():
                    self._seek_flush.stop()
                self._flush_pending_seek()
                return
            if not self._seek_flush.isActive():
                self._seek_flush.start(max(1, int(interval_ms - elapsed_ms)))
            return

        if not self._seek_flush.isActive():
            self._seek_flush.start(interval_ms)

    def force_seek(self, ms: int) -> None:
        """Immediately seek the main player, even while it is playing."""
        ms_i = self._normalize_seek_ms(ms)
        if self._seek_flush.isActive():
            self._seek_flush.stop()
        self._pending_seek_ms = None
        self._last_seek_ms = ms_i
        self._last_seek_flush_ts = monotonic()
        self._player.setPosition(ms_i)

    def load_seek_play(self, path: Path | str, ms: int, *, rate: float = 1.0) -> None:
        """Load a source, then seek and play after Qt reports it is ready."""
        path_s = str(path)
        same_source = self._media_source_path == path_s and not self._player.source().isEmpty()
        ready_statuses = (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )
        source_ready = same_source and self._player.mediaStatus() in ready_statuses
        if source_ready:
            ms_i = self._normalize_seek_ms(ms)
        else:
            try:
                ms_i = int(ms)
            except Exception:
                ms_i = 0
            ms_i = max(0, ms_i)

        self.set_playback_rate(rate)
        self._pending_play_on_load = True
        self._pending_play_seek_ms = ms_i

        if source_ready:
            self._pending_play_on_load = False
            self._pending_play_seek_ms = None
            self._cancel_prime_frame(keep_playing=True)
            if self._seek_flush.isActive():
                self._seek_flush.stop()
            self._pending_seek_ms = None
            self._seek_on_load_ms = None
            self.force_seek(ms_i)
            self._player.play()
            self._sync_play_icon()
            return

        if same_source:
            self._cancel_prime_frame(keep_playing=False)
            if self._seek_flush.isActive():
                self._seek_flush.stop()
            self._pending_seek_ms = None
            self._seek_on_load_ms = None
            self._sync_play_icon()
            return

        self._cancel_prime_frame(keep_playing=False)
        if self._seek_flush.isActive():
            self._seek_flush.stop()
        self._pending_seek_ms = None
        self._last_seek_ms = -1
        self._seek_on_load_ms = None
        self._duration_ms = 0
        self._media_source_path = path_s
        self._clear_meter_status()
        self._player.pause()
        self._player.setSource(QUrl.fromLocalFile(path_s))
        self._sync_play_icon()

    def _flush_pending_seek(self) -> None:
        if self._pending_seek_ms is None:
            return
        ms_i = self._pending_seek_ms
        self._pending_seek_ms = None
        if ms_i == self._last_seek_ms:
            return
        self._last_seek_ms = ms_i
        self._last_seek_flush_ts = monotonic()
        self._player.setPosition(ms_i)

    def _toggle_play(self) -> None:
        if self._prime_timer.isActive():
            self._cancel_prime_frame(keep_playing=True)
            self._sync_play_icon()
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()
        self._sync_play_icon()

    def toggle_play_pause(self) -> None:
        self._toggle_play()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def main_player_is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def main_player_position_ms(self) -> int:
        return int(self._player.position())

    def set_audio_muted(self, muted: bool) -> None:
        self._audio.setMuted(bool(muted))

    def set_audio_gain(self, gain: float) -> None:
        """Set preview output gain in linear space (0..1 for Qt backend)."""
        try:
            value = float(gain)
        except Exception:
            value = 1.0
        value = max(0.0, min(1.0, value))
        self._audio.setVolume(value)

    def set_playback_rate(self, rate: float) -> None:
        """Set QMediaPlayer playback rate with defensive clamping."""
        try:
            value = float(rate)
        except Exception:
            value = 1.0
        value = max(0.1, min(10.0, value))
        if abs(float(self._player.playbackRate()) - value) > 1e-9:
            self._player.setPlaybackRate(value)

    def sync_timeline_audio(
        self,
        path: Path | str,
        ms: int,
        *,
        playback_rate: float = 1.0,
        gain: float = 1.0,
        muted: bool = False,
        playing: bool = False,
        force_seek: bool = False,
    ) -> None:
        path_obj = Path(path)
        raw_path_str = str(path_obj)
        raw_path_key = raw_path_str.casefold()
        if self._timeline_audio_source_path == raw_path_str:
            path_str = raw_path_str
            path_key = self._timeline_audio_source_key or raw_path_key
        elif self._timeline_audio_source_key == raw_path_key:
            path_str = self._timeline_audio_source_path or raw_path_str
            path_key = raw_path_key
        else:
            try:
                path_str = str(path_obj.resolve())
            except Exception:
                path_str = raw_path_str
            path_key = path_str.casefold()
        is_mp3_source = Path(path_str).suffix.lower() == ".mp3"
        source_changed = self._timeline_audio_source_key != path_key
        if source_changed:
            self._timeline_audio_player.pause()
            self._timeline_audio_player.setSource(QUrl.fromLocalFile(path_str))
            self._timeline_audio_source_path = path_str
            self._timeline_audio_source_key = path_key
            self._timeline_audio_last_seek_ms = -1
            self._timeline_audio_last_seek_ts = 0.0
            force_seek = True

        try:
            rate = float(playback_rate)
        except Exception:
            rate = 1.0
        rate = max(0.1, min(10.0, rate))
        if abs(float(self._timeline_audio_player.playbackRate()) - rate) > 1e-9:
            self._timeline_audio_player.setPlaybackRate(rate)

        try:
            volume = float(gain)
        except Exception:
            volume = 1.0
        volume = max(0.0, min(1.0, volume))
        self._timeline_audio.setMuted(bool(muted))
        self._timeline_audio.setVolume(volume)

        try:
            ms_i = max(0, int(ms))
        except Exception:
            ms_i = 0

        should_play = playing and not muted
        self._timeline_audio_should_play = bool(should_play)
        is_playing = (
            self._timeline_audio_player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )
        current = int(self._timeline_audio_player.position())
        drift_limit_ms = 900 if playing else 80
        if abs(rate - 1.0) > 1e-3:
            drift_limit_ms = 1200 if playing else 80
        if playing and not force_seek and not source_changed and is_mp3_source:
            # MP3 timestamp reporting can be jittery during live sync; avoid
            # aggressive re-seeks that can cause audible looping.
            drift_limit_ms = max(drift_limit_ms, 2400)
        should_seek = (
            force_seek
            or self._timeline_audio_last_seek_ms < 0
            or abs(current - ms_i) > drift_limit_ms
        )
        if (
            should_seek
            and playing
            and not force_seek
            and not source_changed
            and is_mp3_source
            and should_play
            and is_playing
        ):
            # During steady MP3 playback, repeated setPosition calls can
            # re-trigger decoder skip/discard paths and produce audible loops.
            should_seek = False
        if should_seek and playing and not force_seek and not source_changed:
            now = monotonic()
            elapsed_ms = (now - self._timeline_audio_last_seek_ts) * 1000.0
            min_interval_ms = 700.0 if is_mp3_source else 350.0
            if elapsed_ms >= 0.0 and elapsed_ms < min_interval_ms:
                should_seek = False
        if (
            should_seek
            and is_mp3_source
            and should_play
            and not force_seek
            and not source_changed
            and not is_playing
            and self._timeline_audio_last_seek_ms >= 0
            and abs(current - ms_i) < 5000
        ):
            # While backend transitions into playback, repeated MP3 seeks can
            # retrigger timestamp correction and create audible loop artifacts.
            should_seek = False
        if should_seek:
            self._timeline_audio_player.setPosition(ms_i)
            self._timeline_audio_last_seek_ms = ms_i
            self._timeline_audio_last_seek_ts = monotonic()

        if should_play and not is_playing:
            self._timeline_audio_player.play()
        elif not should_play and is_playing:
            self._timeline_audio_player.pause()

    def clear_timeline_audio(self) -> None:
        self._timeline_audio_should_play = False
        self._timeline_audio_player.pause()
        self._timeline_audio_player.setSource(QUrl())
        self._timeline_audio_source_path = None
        self._timeline_audio_source_key = None
        self._timeline_audio_last_seek_ms = -1
        self._timeline_audio_last_seek_ts = 0.0

    def _meter_sources(self) -> list[tuple[str, str, float]]:
        sources: list[tuple[str, str, float]] = []
        if self._media_source_path:
            sources.append(
                (
                    "Main preview",
                    self._media_source_path,
                    max(0.0, float(self._player.position()) / 1000.0),
                )
            )
        if (
            self._timeline_audio_source_path
            and self._timeline_audio_source_path != self._media_source_path
        ):
            sources.append(
                (
                    "Timeline audio",
                    self._timeline_audio_source_path,
                    max(0.0, float(self._timeline_audio_player.position()) / 1000.0),
                )
            )
        return sources

    def _set_meter_status(self, text: str, detail: str, *, warning: bool = False) -> None:
        self._meter_badge.setText(text)
        self._meter_badge.setToolTip(detail)
        self._meter_badge.setVisible(True)
        self._meter_btn.setToolTip(detail)
        color = "#fecaca" if warning else "#a7f3d0"
        border = "#7f1d1d" if warning else "#27303a"
        self._meter_badge.setStyleSheet(
            f"""
            QLabel {{
                background: #111318;
                border: 1px solid {border};
                border-radius: 4px;
                color: {color};
                font-size: 10px;
                padding: 3px 6px;
            }}
            """
        )

    def _clear_meter_status(self) -> None:
        if not hasattr(self, "_meter_badge"):
            return
        self._meter_badge.setVisible(False)
        self._meter_badge.setText("")
        self._meter_badge.setToolTip("")
        self._meter_btn.setToolTip("Preview meter")

    def _request_meter_analysis(self) -> None:
        sources = self._meter_sources()
        if not sources:
            self._set_meter_status("No source", "Load a preview source before using the meter.")
            return

        self._meter_token += 1
        token = self._meter_token
        self._set_meter_status(
            "Analyzing...",
            f"Analyzing {PREVIEW_METER_WINDOW_SECONDS:.0f}s around the current playhead.",
        )

        def _job() -> None:
            result: list[tuple[str, float, AudioLevelStats | None]] = []
            for label, path, start in sources:
                try:
                    stats = analyze_audio_levels(
                        path,
                        start=start,
                        duration=PREVIEW_METER_WINDOW_SECONDS,
                        timeout=20.0,
                    )
                except Exception:
                    stats = None
                result.append((label, start, stats))
            try:
                self._meter_result_ready.emit(token, result)
            except RuntimeError:
                return

        self._meter_executor.submit(_job)

    def _on_meter_result_ready(self, token: int, payload: object) -> None:
        if token != self._meter_token or not isinstance(payload, list):
            return
        details: list[str] = []
        short_items: list[str] = []
        has_warning = False
        analyzed_any = False
        for item in payload:
            if not isinstance(item, tuple) or len(item) != 3:
                continue
            label, start, stats = item
            label_s = f"{label} @{float(start):.1f}s"
            short, detail, warning = format_audio_meter_summary(
                label_s,
                stats if isinstance(stats, AudioLevelStats) else None,
            )
            analyzed_any = analyzed_any or isinstance(stats, AudioLevelStats)
            details.append(detail)
            short_items.append(short)
            has_warning = has_warning or warning

        if not details:
            self._set_meter_status("No audio", "No analyzable audio found.")
            return

        if has_warning:
            short_text = "CLIPPING"
        elif analyzed_any and short_items:
            short_text = short_items[0].split(": ", 1)[-1]
        else:
            short_text = "No audio"
        self._set_meter_status(short_text, "\n\n".join(details), warning=has_warning)

    def play(self) -> None:
        self._cancel_prime_frame(keep_playing=True)
        self._player.play()
        self._sync_play_icon()

    def pause(self) -> None:
        self._cancel_prime_frame(keep_playing=False)
        self._player.pause()
        self._sync_play_icon()

    # ---- fullscreen ----

    def _toggle_fullscreen(self) -> None:
        if self._fullscreen_window is not None:
            self._leave_fullscreen()
            return
        self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        if self._fullscreen_window is not None:
            return
        win = _PreviewFullscreenWindow(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        win.setObjectName("previewFullscreenWindow")
        win.setStyleSheet("background: #1a1d23;")
        win.request_close.connect(self._leave_fullscreen)

        root = QVBoxLayout(win)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch(1)
        close_btn = QToolButton()
        close_btn.setFixedSize(34, 34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setText("\u00D7")
        close_btn.setStyleSheet(
            """
            QToolButton {
                background: rgba(255,255,255,0.09);
                color: #d0d5de;
                border: none;
                border-radius: 17px;
                font-size: 20px;
                font-weight: 500;
            }
            QToolButton:hover {
                background: rgba(255,255,255,0.16);
            }
            """
        )
        close_btn.clicked.connect(self._leave_fullscreen)
        top_row.addWidget(close_btn)
        root.addLayout(top_row)

        self._fullscreen_video_host = QFrame()
        self._fullscreen_video_host.setStyleSheet(
            "background: #000; border: 1px solid #2a2f38; border-radius: 6px;"
        )
        fs_video_layout = QVBoxLayout(self._fullscreen_video_host)
        fs_video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_home_layout.removeWidget(self._video)
        self._video.setParent(None)
        fs_video_layout.addWidget(self._video)
        self._sync_sub_overlay_geometry()
        root.addWidget(self._fullscreen_video_host, stretch=1)

        self._fullscreen_footer_shell = QFrame()
        self._fullscreen_footer_shell.setStyleSheet(
            "background: #111318; border: 1px solid #2a2f38; border-radius: 20px;"
        )
        fs_footer_layout = QVBoxLayout(self._fullscreen_footer_shell)
        fs_footer_layout.setContentsMargins(8, 0, 8, 0)
        fs_footer_layout.setSpacing(0)
        self._body_layout.removeWidget(self._footer)
        self._footer.setParent(None)
        fs_footer_layout.addWidget(self._footer)
        root.addWidget(self._fullscreen_footer_shell, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._fullscreen_window = win
        win.showFullScreen()
        win.raise_()
        win.activateWindow()

    def _leave_fullscreen(self) -> None:
        if self._fullscreen_window is None:
            return
        if self._fullscreen_video_host is not None and self._fullscreen_video_host.layout() is not None:
            self._fullscreen_video_host.layout().removeWidget(self._video)
        if self._fullscreen_footer_shell is not None and self._fullscreen_footer_shell.layout() is not None:
            self._fullscreen_footer_shell.layout().removeWidget(self._footer)

        self._video.setParent(self._video_container)
        self._video_home_layout.addWidget(self._video)
        self._sync_sub_overlay_geometry()
        self._footer.setParent(self)
        self._body_layout.addWidget(self._footer)

        win = self._fullscreen_window
        self._fullscreen_window = None
        self._fullscreen_video_host = None
        self._fullscreen_footer_shell = None
        win.hide()
        win.deleteLater()

    # ---- player callbacks ----

    def _on_playback_state_changed(self, _state: QMediaPlayer.PlaybackState) -> None:
        self._sync_play_icon()
        self.playback_state_changed.emit(
            self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    def _on_timeline_audio_playback_state_changed(
        self, state: QMediaPlayer.PlaybackState
    ) -> None:
        # Some backends can transiently auto-resume after source updates.
        # Timeline audio must only play when explicitly requested by timeline clock.
        if (
            state == QMediaPlayer.PlaybackState.PlayingState
            and not self._timeline_audio_should_play
        ):
            self._timeline_audio_player.pause()

    def _on_duration(self, d: int) -> None:
        self._duration_ms = d
        self._update_time(self._player.position())

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.media_ended.emit()
            return
        if status not in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            return
        if self._pending_play_on_load:
            ms = self._pending_play_seek_ms or 0
            self._pending_play_on_load = False
            self._pending_play_seek_ms = None
            self._seek_on_load_ms = None
            self._cancel_prime_frame(keep_playing=True)
            self.seek(ms)
            self._player.play()
            self._sync_play_icon()
            return
        if self._seek_on_load_ms is None:
            return
        ms = self._seek_on_load_ms
        self._seek_on_load_ms = None
        self.seek(ms)
        self._start_prime_frame(ms)

    def _start_prime_frame(self, ms: int) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        self._cancel_prime_frame(keep_playing=False)
        self._prime_seek_ms = max(0, int(ms))
        try:
            self._prime_prev_muted = bool(self._audio.isMuted())
            self._audio.setMuted(True)
        except Exception:
            self._prime_prev_muted = None
        self._player.play()
        self._prime_timer.start(90)

    def _cancel_prime_frame(self, *, keep_playing: bool) -> None:
        if self._prime_timer.isActive():
            self._prime_timer.stop()
        has_prime = self._prime_seek_ms is not None
        self._prime_seek_ms = None
        if self._prime_prev_muted is not None:
            try:
                self._audio.setMuted(self._prime_prev_muted)
            except Exception:
                pass
        self._prime_prev_muted = None
        if has_prime and not keep_playing:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()

    def _finish_prime_frame(self) -> None:
        ms = self._prime_seek_ms
        self._cancel_prime_frame(keep_playing=False)
        if ms is None:
            return
        self.seek(ms)

    def _on_position(self, pos: int) -> None:
        self._last_seek_ms = int(pos)
        self._update_time(pos)
        self.position_changed.emit(pos)

    def set_subtitle(self, main: str, second: str) -> None:
        """Push subtitle text to the video canvas overlay."""
        self._video.set_subtitle(main, second)

    def set_subtitle_position(
        self,
        *,
        pos_x: int | None,
        pos_y: int | None,
        font_size: int,
        canvas_size: tuple[int, int],
    ) -> None:
        self._video.set_subtitle_position(pos_x, pos_y, font_size, canvas_size)
        self._sync_sub_overlay_geometry()

    def set_video_transform(
        self,
        *,
        scale: float | None,
        scale_x: float | None = None,
        scale_y: float | None = None,
        pos_x: int | None,
        pos_y: int | None,
        rotate: float | None = 0.0,
        canvas_size: tuple[int, int],
    ) -> None:
        self._video.set_video_transform(
            scale,
            pos_x,
            pos_y,
            rotate,
            canvas_size,
            scale_x=scale_x,
            scale_y=scale_y,
        )
        self._transform_overlay.setGeometry(self._video.rect())
        self.update()

    def set_transform_overlay_active(self, active: bool) -> None:
        self._transform_overlay.setGeometry(self._video.rect())
        self._transform_overlay.set_active(active)

    def clear_video_transform(self) -> None:
        self._video.clear_video_transform()
        self._transform_overlay.set_active(False)
        self.update()

    def set_subtitle_overlay_active(self, active: bool) -> None:
        self._sub_overlay.set_active(bool(active))
        self._sync_sub_overlay_geometry()

    def _sync_sub_overlay_geometry(self) -> None:
        if not hasattr(self, "_sub_overlay"):
            return
        self._sub_overlay.setGeometry(self._video.rect())
        if self._sub_overlay.isVisible():
            self._sub_overlay.raise_()

    # ---- OCR selection methods ----

    @staticmethod
    def _default_ocr_video_area() -> tuple[float, float, float, float]:
        # Match SubtitleExtractor defaults: Y/H/X/W = 0.78/0.21/0.05/0.90
        y = 0.78
        h = 0.21
        x = 0.05
        w = 0.90
        return y, min(1.0, y + h), x, min(1.0, x + w)

    def _load_saved_ocr_video_area(self) -> tuple[float, float, float, float]:
        default = self._default_ocr_video_area()
        try:
            raw = json.loads(_OCR_AREA_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return default
            if all(k in raw for k in ("y", "h", "x", "w")):
                y = float(raw.get("y", default[0]))
                h = float(raw.get("h", default[1] - default[0]))
                x = float(raw.get("x", default[2]))
                w = float(raw.get("w", default[3] - default[2]))
                return self._normalize_ocr_area((y, y + h, x, x + w))
            if all(k in raw for k in ("y1", "y2", "x1", "x2")):
                return self._normalize_ocr_area(
                    (
                        float(raw.get("y1", default[0])),
                        float(raw.get("y2", default[1])),
                        float(raw.get("x1", default[2])),
                        float(raw.get("x2", default[3])),
                    )
                )
        except Exception:
            pass
        return default

    def _save_ocr_video_area(self, area: tuple[float, float, float, float]) -> None:
        y1, y2, x1, x2 = self._normalize_ocr_area(area)
        payload = {
            "y": y1,
            "h": max(0.0, y2 - y1),
            "x": x1,
            "w": max(0.0, x2 - x1),
            "y1": y1,
            "y2": y2,
            "x1": x1,
            "x2": x2,
        }
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _OCR_AREA_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            # Do not break OCR flow if filesystem is unavailable.
            return

    @staticmethod
    def _normalize_ocr_area(
        area: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        y1, y2, x1, x2 = area
        ny1 = max(0.0, min(1.0, float(y1)))
        ny2 = max(0.0, min(1.0, float(y2)))
        nx1 = max(0.0, min(1.0, float(x1)))
        nx2 = max(0.0, min(1.0, float(x2)))
        if ny2 < ny1:
            ny1, ny2 = ny2, ny1
        if nx2 < nx1:
            nx1, nx2 = nx2, nx1
        return ny1, ny2, nx1, nx2

    def _overlay_area_to_video_area(
        self,
        area: tuple[float, float, float, float] | None = None,
    ) -> tuple[float, float, float, float]:
        y1, y2, x1, x2 = area if area is not None else self._ocr_overlay.get_area()
        y1, y2, x1, x2 = self._normalize_ocr_area((y1, y2, x1, x2))

        w_container = float(self._video_container.width())
        h_container = float(self._video_container.height())
        if w_container <= 0.0 or h_container <= 0.0:
            return y1, y2, x1, x2

        canvas_pos = self._video.mapTo(self._video_container, self._video.rect().topLeft())
        canvas_x = float(canvas_pos.x())
        canvas_y = float(canvas_pos.y())
        vid_rect = self._video.video_rect
        vr_x = float(vid_rect.x())
        vr_y = float(vid_rect.y())
        vr_w = float(vid_rect.width())
        vr_h = float(vid_rect.height())
        if vr_w <= 1.0 or vr_h <= 1.0:
            return y1, y2, x1, x2

        px1 = x1 * w_container - canvas_x
        px2 = x2 * w_container - canvas_x
        py1 = y1 * h_container - canvas_y
        py2 = y2 * h_container - canvas_y

        vx1 = (px1 - vr_x) / vr_w
        vx2 = (px2 - vr_x) / vr_w
        vy1 = (py1 - vr_y) / vr_h
        vy2 = (py2 - vr_y) / vr_h
        return self._normalize_ocr_area((vy1, vy2, vx1, vx2))

    def _video_area_to_overlay_area(
        self,
        area: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        vy1, vy2, vx1, vx2 = self._normalize_ocr_area(area)

        w_container = float(self._video_container.width())
        h_container = float(self._video_container.height())
        if w_container <= 0.0 or h_container <= 0.0:
            return vy1, vy2, vx1, vx2

        canvas_pos = self._video.mapTo(self._video_container, self._video.rect().topLeft())
        canvas_x = float(canvas_pos.x())
        canvas_y = float(canvas_pos.y())
        vid_rect = self._video.video_rect
        vr_x = float(vid_rect.x())
        vr_y = float(vid_rect.y())
        vr_w = float(vid_rect.width())
        vr_h = float(vid_rect.height())
        if vr_w <= 1.0 or vr_h <= 1.0:
            return vy1, vy2, vx1, vx2

        px1 = canvas_x + vr_x + vx1 * vr_w
        px2 = canvas_x + vr_x + vx2 * vr_w
        py1 = canvas_y + vr_y + vy1 * vr_h
        py2 = canvas_y + vr_y + vy2 * vr_h

        ox1 = px1 / w_container
        ox2 = px2 / w_container
        oy1 = py1 / h_container
        oy2 = py2 / h_container
        return self._normalize_ocr_area((oy1, oy2, ox1, ox2))

    def _reflow_ocr_overlay_to_current_video(self) -> None:
        if not hasattr(self, "_ocr_overlay"):
            return
        self._ocr_overlay.setGeometry(self._video_container.rect())
        if not self._ocr_overlay.is_active:
            return
        if self._ocr_video_area is None:
            self._ocr_video_area = self._overlay_area_to_video_area()
        oy1, oy2, ox1, ox2 = self._video_area_to_overlay_area(self._ocr_video_area)
        self._ocr_overlay.set_area(oy1, oy2, ox1, ox2)

    def start_ocr_selection(self) -> None:
        """Bật chế độ chọn vùng OCR - hiện overlay trên video."""
        self._ocr_overlay.setGeometry(self._video_container.rect())
        if self._ocr_video_area is None:
            self._ocr_video_area = self._overlay_area_to_video_area()
        oy1, oy2, ox1, ox2 = self._video_area_to_overlay_area(self._ocr_video_area)
        self._ocr_overlay.set_area(oy1, oy2, ox1, ox2)
        self._ocr_overlay.start_selection()
        self._ocr_overlay.raise_()
        self._ocr_overlay.setFocus()
        QTimer.singleShot(0, self._reflow_ocr_overlay_to_current_video)

    def stop_ocr_selection(self) -> None:
        """Tắt chế độ chọn vùng OCR."""
        self._ocr_overlay.stop_selection()

    def get_ocr_area(self) -> tuple[float, float, float, float]:
        """Lấy vùng chọn OCR hiện tại theo tọa độ video thực (không gồm letterbox)."""
        self._ocr_video_area = self._overlay_area_to_video_area()
        self._save_ocr_video_area(self._ocr_video_area)
        return self._ocr_video_area

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_sub_overlay_geometry()
        if hasattr(self, "_transform_overlay"):
            self._transform_overlay.setGeometry(self._video.rect())
        if hasattr(self, "_ocr_overlay"):
            self._ocr_overlay.setGeometry(self._video_container.rect())
            if self._ocr_overlay.is_active:
                QTimer.singleShot(0, self._reflow_ocr_overlay_to_current_video)
                QTimer.singleShot(40, self._reflow_ocr_overlay_to_current_video)

    def _on_ocr_area_selected(self, y1: float, y2: float, x1: float, x2: float) -> None:
        area = self._overlay_area_to_video_area((y1, y2, x1, x2))
        self._ocr_video_area = area
        self._save_ocr_video_area(area)
        self.ocr_area_selected.emit(*area)

    def _on_ocr_cancelled(self) -> None:
        self.ocr_cancelled.emit()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self._meter_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        super().closeEvent(event)

    def _update_time(self, pos: int) -> None:
        if self._timeline_time_display_enabled:
            cur = _fmt_time(self._timeline_current_ms)
            total = _fmt_time(self._timeline_total_ms)
        else:
            cur = _fmt_time(pos)
            total = _fmt_time(self._duration_ms)
        self._time_lbl.setText(
            f'<span style="color:{ICON_ACTIVE}">{cur}</span> '
            f'<span style="color:#8c93a0">/ {total}</span>'
        )


__all__ = ["PreviewPanel", "format_audio_meter_summary"]
