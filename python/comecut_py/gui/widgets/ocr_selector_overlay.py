"""OCR Selector Overlay - lớp chọn vùng phụ đề trực tiếp trên Preview."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal  # type: ignore
from PySide6.QtGui import QColor, QCursor, QPainter, QPen  # type: ignore
from PySide6.QtWidgets import QWidget  # type: ignore


class OcrSelectorOverlay(QWidget):
    """
    Widget trong suốt đặt chồng lên Preview, cho phép người dùng
    điều chỉnh vùng chứa phụ đề (mặc định đã có sẵn).
    
    Hỗ trợ:
    - Di chuyển toàn bộ vùng chọn.
    - Thay đổi kích thước qua các cạnh và góc.
    """

    area_selected = Signal(float, float, float, float)   # y1, y2, x1, x2 (0.0-1.0)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        
        # Vùng chọn mặc định (tỉ lệ 0.0 - 1.0)
        # Y: 0.7 -> 0.9 (20% ở dưới)
        # X: 0.1 -> 0.9 (80% ở giữa)
        self._y1, self._y2 = 0.7, 0.9
        self._x1, self._x2 = 0.1, 0.9
        
        self._active = False
        self._drag_mode = None  # None, 'move', 'n', 's', 'e', 'w'
        self._last_mouse_pos: QPoint | None = None
        self._drag_start_rect: tuple[float, float, float, float] | None = None # y1, y2, x1, x2
        
        self._handle_size = 10  # Kích thước vùng cảm ứng ở cạnh

    def set_area(self, y1: float, y2: float, x1: float, x2: float) -> None:
        """Set OCR selection rect in normalized coordinates (0..1)."""
        ny1 = max(0.0, min(1.0, float(y1)))
        ny2 = max(0.0, min(1.0, float(y2)))
        nx1 = max(0.0, min(1.0, float(x1)))
        nx2 = max(0.0, min(1.0, float(x2)))
        if ny2 < ny1:
            ny1, ny2 = ny2, ny1
        if nx2 < nx1:
            nx1, nx2 = nx2, nx1

        min_size = 0.02
        if (ny2 - ny1) < min_size:
            if ny1 + min_size <= 1.0:
                ny2 = ny1 + min_size
            else:
                ny1 = max(0.0, ny2 - min_size)
        if (nx2 - nx1) < min_size:
            if nx1 + min_size <= 1.0:
                nx2 = nx1 + min_size
            else:
                nx1 = max(0.0, nx2 - min_size)

        self._y1, self._y2, self._x1, self._x2 = ny1, ny2, nx1, nx2
        self.update()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_selection(self) -> None:
        """Bật chế độ chọn vùng - hiện overlay với vùng mặc định."""
        self._active = True
        self.show()
        self.raise_()
        self.update()

    def stop_selection(self) -> None:
        """Tắt chế độ chọn vùng."""
        self._active = False
        self._drag_mode = None
        self.hide()
        self.update()

    @property
    def is_active(self) -> bool:
        return self._active

    def get_area(self) -> tuple[float, float, float, float]:
        """Trả về vùng chọn hiện tại (y1, y2, x1, x2)."""
        return self._y1, self._y2, self._x1, self._x2

    # ------------------------------------------------------------------
    # Coordinate Conversion
    # ------------------------------------------------------------------

    def _get_pixel_rect(self) -> QRect:
        """Chuyển tỉ lệ sang pixel trên widget hiện tại."""
        w = self.width()
        h = self.height()
        return QRect(
            int(self._x1 * w),
            int(self._y1 * h),
            int((self._x2 - self._x1) * w),
            int((self._y2 - self._y1) * h)
        )
    def _get_handle_at(self, pos: QPoint) -> str | None:
        """Xác định chuột đang ở handle nào hoặc ở giữa."""
        rect = self._get_pixel_rect()
        if not rect.isValid():
            return None
            
        m = self._handle_size
        x, y = pos.x(), pos.y()
        
        # Ưu tiên các cạnh trước
        if abs(y - rect.top()) <= m and rect.left() <= x <= rect.right(): return 'n'
        if abs(y - rect.bottom()) <= m and rect.left() <= x <= rect.right(): return 's'
        if abs(x - rect.left()) <= m and rect.top() <= y <= rect.bottom(): return 'w'
        if abs(x - rect.right()) <= m and rect.top() <= y <= rect.bottom(): return 'e'
        
        # Kiểm tra bên trong
        if rect.contains(pos):
            return 'move'
            
        return None

    def _update_cursor(self, handle: str | None) -> None:
        cursors = {
            'move': Qt.CursorShape.SizeAllCursor,
            'n': Qt.CursorShape.SizeVerCursor,
            's': Qt.CursorShape.SizeVerCursor,
            'w': Qt.CursorShape.SizeHorCursor,
            'e': Qt.CursorShape.SizeHorCursor,
        }
        self.setCursor(QCursor(cursors.get(handle, Qt.CursorShape.ArrowCursor)))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._active:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._get_handle_at(event.pos())
            if handle:
                self._drag_mode = handle
                self._last_mouse_pos = event.pos()
                self._drag_start_rect = (self._y1, self._y2, self._x1, self._x2)
                self.grabMouse()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if not self._active:
            return
            
        if self._drag_mode and self._drag_start_rect:
            w_widget, h_widget = self.width(), self.height()
            if w_widget <= 0 or h_widget <= 0:
                return
                
            delta = event.pos() - self._last_mouse_pos
            dx = delta.x() / w_widget
            dy = delta.y() / h_widget
            
            s_y1, s_y2, s_x1, s_x2 = self._drag_start_rect
            
            if self._drag_mode == 'move':
                # Đảm bảo không ra ngoài
                new_x1 = max(0.0, min(1.0 - (s_x2 - s_x1), s_x1 + dx))
                new_y1 = max(0.0, min(1.0 - (s_y2 - s_y1), s_y1 + dy))
                self._x2 = new_x1 + (s_x2 - s_x1)
                self._x1 = new_x1
                self._y2 = new_y1 + (s_y2 - s_y1)
                self._y1 = new_y1
            elif self._drag_mode == 'n':
                self._y1 = max(0.0, min(s_y2 - 0.02, s_y1 + dy))
            elif self._drag_mode == 's':
                self._y2 = max(s_y1 + 0.02, min(1.0, s_y2 + dy))
            elif self._drag_mode == 'w':
                self._x1 = max(0.0, min(s_x2 - 0.02, s_x1 + dx))
            elif self._drag_mode == 'e':
                self._x2 = max(s_x1 + 0.02, min(1.0, s_x2 + dx))
            
            self.update()
            # Tự động phát tín hiệu cập nhật (nếu cần sync ngay)
            # self.area_selected.emit(self._y1, self._y2, self._x1, self._x2)
        else:
            # Cập nhật cursor khi di chuyển chuột qua các vùng
            handle = self._get_handle_at(event.pos())
            self._update_cursor(handle)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_mode:
            self._drag_mode = None
            self._drag_start_rect = None
            self.releaseMouse()
            self.area_selected.emit(self._y1, self._y2, self._x1, self._x2)
            self.update()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.stop_selection()
            self.cancelled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.area_selected.emit(self._y1, self._y2, self._x1, self._x2)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._get_pixel_rect()
        if rect.isValid():
            # Vẽ viền Xanh lá (Green) giống SubtitleExtractor
            # Độ dày 3px
            pen = QPen(QColor("#00ff00"), 3, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)

        painter.end()
