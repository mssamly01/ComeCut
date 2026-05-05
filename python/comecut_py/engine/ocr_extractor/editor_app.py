# editor/editor_app.py

# -*- coding: utf-8 -*-
import sys
import re
import os
import cv2
import pysrt
import numpy as np
import copy
import argparse
import threading
import time
import bisect
import gc
import psutil
from PIL import Image, ImageDraw, ImageFont

try:
    from skimage.metrics import structural_similarity as ssim
except ImportError:
    print("Cảnh báo: Thư viện 'scikit-image' chưa được cài đặt. Chức năng so sánh khung hình sẽ bị vô hiệu hóa.")
    print("Vui lòng chạy: pip install scikit-image")
    ssim = None

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QTextEdit, QLabel, QPushButton,
    QFileDialog, QStyle, QMessageBox, QScrollArea, QSlider, QProgressDialog,
    QLineEdit, QSizePolicy, QGridLayout, QDialog, QDialogButtonBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QPointF, QRect, QRectF, pyqtSignal, QThread, QMutex, QWaitCondition
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QFont, QCursor, QTextCharFormat, QTextCursor, QPainterPath, QFontMetrics, QPolygonF, QIcon, QFontDatabase

OCR_HIGHLIGHT_REGEX = (
    r"([^0-9\u4e00-\u9fff\uFF0C\u3002\uFF01\uFF1F\u3001\uFF1A\uFF1B\uFF08\uFF09\u300A\u300B\u201C\u201D\u2018\u2019.,!?()\[\]\-]+)"
    r"|(^[\s0-9]+$)"
    r"|(^[\s\uFF0C\u3002\uFF01\uFF1F\u3001\uFF1A\uFF1B\uFF08\uFF09\u300A\u300B\u201C\u201D\u2018\u2019.,!?()\[\]\-]+$)"
)
OCR_DIGITS_ONLY_REGEX = re.compile(r"[0-9\s]+")
OCR_INVALID_CHAR_REGEX = re.compile(r"[^0-9\u4e00-\u9fff\uFF0C\u3002\uFF01\uFF1F\u3001\uFF1A\uFF1B\uFF08\uFF09\u300A\u300B\u201C\u201D\u2018\u2019.,!?()\[\]\-]+")
OCR_MEANINGFUL_CHAR_REGEX = re.compile(r"[0-9A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

def normalize_whitespace(text):
    """Chuẩn hóa các loại dấu cách (NBSP, Full-width, Tab) về dấu cách chuẩn ASCII."""
    if not text:
        return ""
    # \xa0: Non-breaking space, \u3000: Ideographic space (tiếng Trung/Nhật)
    return text.replace('\xa0', ' ').replace('\u3000', ' ').replace('\t', ' ')

# --- BỘ KHUNG GIAO DIỆN (STYLESHEET) ---
APP_STYLESHEET = """
    /* Nền chính và màu chữ mặc định */
    QMainWindow, QWidget { 
        background-color: #121212; 
        color: #E0E0E0; 
        font-family: 'Segoe UI', Arial, sans-serif; 
    }
    
    QListWidget {
        background-color: #121212;
        border: none;
        outline: 0;
    }
    QListWidget::item { 
        background-color: transparent;
        border-bottom: 1px solid #222222; /* Đường kẻ mờ giữa các mục */
        border: 1px solid transparent; /* Border ẩn dể không bị giật khi select */
        margin: 0;
        padding: 5px;
        outline: 0;
    }
    QListWidget::item:hover {
        background-color: #1E1E1E; /* Nền xám nhạt khi di chuột qua */
    }
    QListWidget::item:selected { 
        background-color: #1A1A1A; /* Nền tối hơn cho dòng được chọn */
        border: 1px solid #00E5FF; /* Viền ngoài màu xanh (thay vì #1A1A1A) */
        border-bottom: 1px solid #00E5FF; /* Ép viền dưới phải có màu xanh */
        border-radius: 4px;
        outline: 0;
    }
    
    /* Nhãn ID và TextEdit trong list */
    #IdLabel {
        color: #555555;

        font-weight: bold;
        font-size: 13px;
        background: transparent;
    }
    #SubtitleTextEdit {
        background: transparent;
        border: none;
        color: #AAAAAA;
    }
    
    /* Trạng thái được chọn (Neon Blue) */
    QWidget[selected="true"] #IdLabel, 
    QWidget[selected="true"] #SubtitleTextEdit {
        color: #00E5FF !important;
    }

    /* Dòng đã sửa trong chế độ lọc OCR */
    QWidget[ocr_state="fixed"] #IdLabel,
    QWidget[ocr_state="fixed"] #SubtitleTextEdit {
        color: #6F6F6F;
    }
    QWidget[ocr_state="fixed"] #SubtitleTextEdit {
        background-color: rgba(255, 255, 255, 0.02);
    }

    /* Các nút inline (+ và Xóa) */
    .InlineButton {
        background: transparent;
        border: none;
        color: #444444;
        font-size: 16px;
        padding: 2px;
    }
    .InlineButton:hover {
        color: #00E5FF;
    }
    #DeleteButton:hover {
        color: #FF4D4D;
    }
    
    /* Ô chỉnh sửa text trong danh sách */
    QTextEdit { 
        background-color: transparent; 
        border: 1px solid transparent; 
        border-radius: 4px; 
        color: #FFFFFF; 
        padding-top: 2px;
        padding-bottom: 2px;
        padding-left: 6px;
        padding-right: 6px;
    }
    QTextEdit:focus {
        border: 1px solid transparent;
        background-color: transparent;
    }
    
    /* Ô tìm kiếm */
    QLineEdit {
        background-color: #252525;
        border: 1px solid #333333;
        border-radius: 4px;
        padding: 8px;
        color: #FFFFFF;
        font-size: 13px;
    }
    QLineEdit:focus {
        border: 1.5px solid #3A82F6;
    }
    
    /* Nhãn thời gian trong danh sách */
    #TimeLabel { 
        color: #999999; 
        font-size: 11px; 
        font-weight: bold; 
    }
    
    /* Màn hình video */
    #VideoLabel { 
        background-color: #000000; 
        border: 1px solid #333333;
    }
    
    /* Các nút bấm */
    QPushButton { 
        background-color: #2D2D2D; 
        color: #FFFFFF; 
        border: 1px solid #404040; 
        padding: 8px 16px; 
        border-radius: 6px; 
        font-weight: bold; 
    }
    QPushButton:hover { 
        background-color: #3D3D3D;
        border-color: #505050;
    }
    QPushButton:pressed { 
        background-color: #1A1A1A; 
    }
    QPushButton#PrimaryButton {
        background-color: #3A82F6;
        border: none;
    }
    QPushButton#PrimaryButton:hover {
        background-color: #2563EB;
    }
    
    /* Thanh chia layout */
    QSplitter::handle { 
        background-color: #252525; 
    }
    QSplitter::handle:hover { 
        background-color: #3A82F6; 
    }
    
    /* Thanh tiêu đề trên cùng */
    #Header { 
        background-color: #1E1E1E; 
        border-bottom: 1.5px solid #333333; 
    }
    
    /* Thanh cuộn timeline */
    QScrollArea { 
        border: none; 
        background-color: #121212;
    }
    
    /* Thanh trượt Zoom */
    QSlider::groove:horizontal { 
        border: 1px solid #333333; 
        background: #252525; 
        height: 6px; 
        border-radius: 3px; 
    }
    QSlider::handle:horizontal { 
        background: #FFFFFF; 
        border: 1px solid #333333; 
        width: 14px; 
        height: 14px;
        margin: -4px 0; 
        border-radius: 7px; 
    }

    /* Tùy chỉnh màu nền cho Timeline Widget */
    AdvancedTimelineWidget {
        background-color: #121212;
    }

    /* Các nút điều hướng tìm kiếm */
    .SearchButton {
        padding: 4px 8px;
        min-width: 30px;
    }

    /* Nút hành động hủy diệt (Xóa) */
    .DestructiveButton:hover {
        background-color: #5D2D2D;
        border-color: #FF4D4D;
        color: #FF4D4D;
    }

    /* Nhãn đếm kết quả tìm kiếm */
    #SearchCountLabel {
        color: #00E5FF;
        font-size: 11px;
        font-weight: bold;
        background-color: #1E1E1E;
        border-radius: 4px;
        padding: 2px 4px;
    }
"""

class SubtitleItem:
    def __init__(self, start_time, end_time, text, pos_x=0.5, pos_y=0.85, font_size=40):
        self.start_time = start_time
        self.end_time = end_time
        self.text = text
        self.pos_x = pos_x  # 0.0 - 1.0 (trái - phải)
        self.pos_y = pos_y  # 0.0 - 1.0 (trên - dưới)
        self.font_size = font_size
    def duration(self):
        return self.end_time - self.start_time

class DeleteInterjectionsDialog(QDialog):
    def __init__(self, parent, interjection_subs_with_stt):
        super().__init__(parent)
        self.setWindowTitle("Bộ Lọc Phụ Đề Cảm Thán")
        self.resize(500, 450)
        
        self.subs_with_stt = interjection_subs_with_stt
        self.parent_editor = parent
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        label = QLabel(f"Phát hiện <b>{len(interjection_subs_with_stt)}</b> dòng có khả năng là phụ đề rác (chỉ chứa từ cảm thán).<br>Vui lòng bỏ chọn những dòng bạn muốn giữ lại trước khi nhấn Xóa:")
        label.setWordWrap(True)
        label.setStyleSheet("color: #E0E0E0; margin-bottom: 5px;")
        layout.addWidget(label)
        
        # Checkbox Chọn tất cả
        self.cb_all = QCheckBox("Chọn tất cả để xóa")
        self.cb_all.setChecked(True)
        self.cb_all.setStyleSheet("font-weight: bold; margin-left: 5px; color: #FFF;")
        self.cb_all.stateChanged.connect(self.toggle_all)
        layout.addWidget(self.cb_all)
        
        # Danh sách QListWidget clone giao diện
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget { background-color: #121212; border: 1px solid #333333; border-radius: 6px; outline: 0; }
            QListWidget::item { border: 1px solid transparent; border-bottom: 1px solid #222222; padding: 7px; color: #AAAAAA; margin: 0; }
            QListWidget::item:hover { background-color: #1E1E1E; }
            QListWidget::item:selected { background-color: #1A1A1A; border: 1px solid #00E5FF; border-bottom: 1px solid #00E5FF; color: #00E5FF; border-radius: 4px; }
        """)
        
        for sub, stt_index in interjection_subs_with_stt:
            item = QListWidgetItem(f"Dòng {stt_index + 1}:  {sub.text}")
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, stt_index)
            self.list_widget.addItem(item)
            
        self.list_widget.itemClicked.connect(self.on_item_clicked)
        layout.addWidget(self.list_widget)
        
        # Nút xác nhận/hủy
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Xóa Các Dòng Đã Chọn")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
    def on_item_clicked(self, item):
        """Khi click vào dòng, tự động nhảy list chính tới đó"""
        stt_index = item.data(Qt.ItemDataRole.UserRole)
        if hasattr(self.parent_editor, 'subtitle_list'):
            self.parent_editor.subtitle_list.setCurrentRow(stt_index)
            
    def toggle_all(self, state):
        check_state = Qt.CheckState.Checked if state != 0 else Qt.CheckState.Unchecked
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(check_state)
            
    def get_selected_subs(self):
        selected = []
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).checkState() == Qt.CheckState.Checked:
                selected.append(self.subs_with_stt[i][0])
        return selected

class FindReplaceDialog(QDialog):
    """Hộp thoại Tìm kiếm và Thay thế hàng loạt phụ đề."""
    
    DIALOG_STYLESHEET = """
        QDialog {
            background-color: #1A1A1A;
            border: 1px solid #333333;
            border-radius: 10px;
        }
        QLabel#SectionTitle {
            color: #00E5FF;
            font-size: 15px;
            font-weight: bold;
        }
        QLabel#FieldLabel {
            color: #AAAAAA;
            font-size: 12px;
        }
        QLineEdit {
            background-color: #252525;
            border: 1px solid #333333;
            border-radius: 6px;
            padding: 8px 12px;
            color: #FFFFFF;
            font-size: 13px;
        }
        QLineEdit:focus {
            border: 1.5px solid #00E5FF;
        }
        QPushButton#ReplaceAllBtn {
            background-color: #00E5FF;
            color: #000000;
            border: none;
            border-radius: 6px;
            padding: 9px 20px;
            font-weight: bold;
            font-size: 13px;
        }
        QPushButton#ReplaceAllBtn:hover {
            background-color: #33ECFF;
        }
        QPushButton#ReplaceAllBtn:pressed {
            background-color: #00B8CC;
        }
        QPushButton#CancelBtn {
            background-color: #2D2D2D;
            color: #AAAAAA;
            border: 1px solid #404040;
            border-radius: 6px;
            padding: 9px 20px;
            font-size: 13px;
        }
        QPushButton#CancelBtn:hover {
            background-color: #3D3D3D;
            color: #FFFFFF;
        }
        QCheckBox {
            color: #AAAAAA;
            font-size: 12px;
        }
        QCheckBox::indicator {
            width: 14px;
            height: 14px;
            border-radius: 3px;
            border: 1px solid #555555;
            background-color: #252525;
        }
        QCheckBox::indicator:checked {
            background-color: #00E5FF;
            border-color: #00E5FF;
        }
    """
    
    def __init__(self, parent=None, initial_find_text=""):
        super().__init__(parent)
        self.setWindowTitle("Tìm kiếm & Thay thế")
        self.setFixedSize(420, 265)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(self.DIALOG_STYLESHEET)
        
        # Cho phép kéo di chuyển dialog
        self._drag_pos = None
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        
        # Container chính với bo góc
        container = QWidget()
        container.setObjectName("MainContainer")
        container.setStyleSheet("""
            QWidget#MainContainer {
                background-color: #1A1A1A; 
                border-radius: 10px; 
                border: 1px solid #333333;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(8)
        
        # Tiêu đề
        title_row = QHBoxLayout()
        title = QLabel("Tìm kiếm & Thay thế")
        title.setObjectName("SectionTitle")
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet("background: transparent; border: none; color: #555555; font-size: 14px;")
        btn_close.clicked.connect(self.reject)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(btn_close)
        layout.addLayout(title_row)
        
        # Ô Tìm
        lbl_find = QLabel("Tìm")
        lbl_find.setObjectName("FieldLabel")
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Nhập văn bản cần tìm...")
        self.find_input.setText(initial_find_text)
        layout.addWidget(lbl_find)
        layout.addWidget(self.find_input)
        
        # Ô Thay thế
        lbl_replace = QLabel("Thay thế bằng")
        lbl_replace.setObjectName("FieldLabel")
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Nhập văn bản thay thế...")
        layout.addWidget(lbl_replace)
        layout.addWidget(self.replace_input)
        
        # Tùy chọn phân biệt hoa thường
        self.cb_case_sensitive = QCheckBox("Phân biệt chữ hoa/thường")
        layout.addWidget(self.cb_case_sensitive)
        
        # Nút hành động
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_replace_all = QPushButton("Thay thế tất cả")
        self.btn_replace_all.setObjectName("ReplaceAllBtn")
        self.btn_replace_all.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setObjectName("CancelBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_replace_all)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)
        
        outer.addWidget(container)
        
        # Focus vào ô tìm kiếm khi mở
        QTimer.singleShot(50, lambda: self.find_input.setFocus())
        if initial_find_text:
            QTimer.singleShot(60, lambda: self.find_input.selectAll())
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
    
    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
    
    def mouseReleaseEvent(self, event):
        self._drag_pos = None
    
    def get_find_text(self):
        return self.find_input.text()
    
    def get_replace_text(self):
        return self.replace_input.text()
    
    def is_case_sensitive(self):
        return self.cb_case_sensitive.isChecked()


class SubtitleOverlayWidget(QWidget):
    # Phát tín hiệu khi vị trí hoặc kích thước thay đổi
    position_changed = pyqtSignal(float, float, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.active_sub = None
        self.is_dragging = False
        self.is_resizing = False
        self.drag_start_pos = QPoint()
        self.drag_start_font_size = 0
        self.sub_rect = QRect()
        self.resize_dir = None
        self.video_rect = QRect() # Vùng thực sự chứa video (không tính black bars)
        self.is_hovered = False

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()

    def set_active_sub(self, sub, video_rect):
        self.active_sub = sub
        self.video_rect = video_rect
        self.update()

    def get_sub_ui_rect(self):
        if not self.active_sub or self.video_rect.isEmpty():
            return QRect()
        
        # Lấy font family từ MainWindow
        main_win = self.window()
        font_family = getattr(main_win, 'font_family', "Segoe UI")
        
        # Font size tỉ lệ theo khung video
        font_size_ui = self.active_sub.font_size * (self.video_rect.height() / 1080.0)
        
        font = QFont(font_family)
        font.setPixelSize(int(font_size_ui))
        font.setBold(True)
        fm = QFontMetrics(font)
        
        text = self.active_sub.text if self.active_sub.text else " "
        
        # SỬ DỤNG boundingRect thay vì horizontalAdvance để lấy khung bao CHÍNH XÁC nhất (đặc biệt cho chữ Hán)
        # boundingRect trả về QRect bao quanh toàn bộ các nét vẽ của text
        text_bbox = fm.boundingRect(text)
        text_w = text_bbox.width()
        text_h = text_bbox.height()
        
        center_x = self.video_rect.left() + (self.video_rect.width() * self.active_sub.pos_x)
        text_bottom_y = self.video_rect.top() + (self.video_rect.height() * self.active_sub.pos_y)
        
        # TĂNG CƯỜNG PADDING (V7.0) 
        # Nới rộng vùng đệm để đảm bảo không bao giờ bị crop nét chữ
        padding_x = int(max(20, font_size_ui * 0.6)) 
        padding_y = int(max(15, font_size_ui * 0.4)) 
        
        return QRect(
            int(center_x - text_w/2 - padding_x), 
            int(text_bottom_y - text_h - padding_y), 
            int(text_w + padding_x * 2), 
            int(text_h + padding_y * 2)
        )

    def paintEvent(self, event):
        if not self.active_sub or self.video_rect.isEmpty():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        rect = self.get_sub_ui_rect()
        self.sub_rect = rect
        
        # 1. VẼ VĂN BẢN (LUÔN HIỂN THỊ)
        main_win = self.window()
        font_family = getattr(main_win, 'font_family', "Segoe UI")
        
        # Font size tỉ lệ theo khung video
        font_size_ui = self.active_sub.font_size * (self.video_rect.height() / 1080.0)
        font = QFont(font_family, int(font_size_ui))
        font.setBold(True)
        painter.setFont(font)
        
        text = self.active_sub.text if self.active_sub.text else ""
        
        # Vẽ bóng đổ nhẹ (Drop shadow) cho chữ
        # Dùng cờ TextDontClip để ép vẽ toàn bộ chữ kể cả khi rect bị lệch chuẩn
        draw_flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextDontClip
        
        painter.setPen(QColor(0, 0, 0, 180))
        painter.drawText(rect.adjusted(2, 2, 2, 2), draw_flags, text)
        
        # Vẽ chữ chính (Màu trắng hoặc Cyan)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, draw_flags, text)

        # 2. VẼ KHUNG VIỀN VÀ HANDLE (CHỈ HIỂN THỊ KHI HOVER/DRAG/RESIZE)
        if not (self.is_hovered or self.is_dragging or self.is_resizing):
            return
        
        # Vẽ khung bao quanh (Neon Blue) sắc nét
        pen = QPen(QColor("#00E5FF"), 2.0, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        
        # Vẽ màu nền mờ để báo hiệu vùng "hit area"
        alpha = 80 if (self.is_dragging or self.is_resizing) else 40
        painter.fillRect(rect, QColor(0, 229, 255, alpha))
        painter.drawRect(rect)
        
        # Tự động vẽ 8 đỉnh (neo resize)
        painter.setBrush(QColor("#00E5FF"))
        painter.setPen(Qt.PenStyle.NoPen)
        hs = 8 # Handle size
        centers = [
            rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight(),
            QPoint(rect.center().x(), rect.top()), QPoint(rect.center().x(), rect.bottom()),
            QPoint(rect.left(), rect.center().y()), QPoint(rect.right(), rect.center().y())
        ]
        for p in centers:
            painter.drawRect(p.x() - hs//2, p.y() - hs//2, hs, hs)

    def _get_resize_dir(self, pos):
        if self.sub_rect.isEmpty(): return None
        margin = 12
        r = self.sub_rect
        left = abs(pos.x() - r.left()) <= margin
        right = abs(pos.x() - r.right()) <= margin
        top = abs(pos.y() - r.top()) <= margin
        bottom = abs(pos.y() - r.bottom()) <= margin
        
        if top and left: return 'tl'
        if top and right: return 'tr'
        if bottom and left: return 'bl'
        if bottom and right: return 'br'
        if top: return 't'
        if bottom: return 'b'
        if left: return 'l'
        if right: return 'r'
        return None

    def mousePressEvent(self, event):
        if not self.active_sub: return
        
        dir = self._get_resize_dir(event.pos())
        if dir:
            self.is_resizing = True
            self.resize_dir = dir
            self.drag_start_pos = event.pos()
            self.drag_start_font_size = self.active_sub.font_size
        elif self.sub_rect.contains(event.pos()):
            self.is_dragging = True
            self.drag_start_pos = event.pos()

    def mouseMoveEvent(self, event):
        if not self.active_sub: return

        if self.is_dragging:
            delta = event.pos() - self.drag_start_pos
            self.drag_start_pos = event.pos()
            
            # Tính tỉ lệ gia tốc dựa trên tổng kích thước video (cách này tránh buffer delay của self.sub_rect)
            dx = delta.x() / self.video_rect.width()
            dy = delta.y() / self.video_rect.height()
            
            self.active_sub.pos_x = max(0.0, min(1.0, self.active_sub.pos_x + dx))
            self.active_sub.pos_y = max(0.0, min(1.0, self.active_sub.pos_y + dy))
            self.position_changed.emit(self.active_sub.pos_x, self.active_sub.pos_y, self.active_sub.font_size)
            self.update()
            
        elif self.is_resizing:
            delta = event.pos() - self.drag_start_pos
            
            # Tính toán scale dựa trên cạnh đang kéo
            scale_delta = 0
            if 't' in self.resize_dir: scale_delta -= delta.y()
            if 'b' in self.resize_dir: scale_delta += delta.y()
            if 'l' in self.resize_dir: scale_delta -= delta.x()
            if 'r' in self.resize_dir: scale_delta += delta.x()
            
            # Tăng giảm kích thước chữ theo lực kéo
            self.active_sub.font_size = max(10, min(300, self.drag_start_font_size + int(scale_delta * 0.5)))
            self.position_changed.emit(self.active_sub.pos_x, self.active_sub.pos_y, self.active_sub.font_size)
            self.update()
        else:
            dir = self._get_resize_dir(event.pos())
            if dir in ('tl', 'br'): self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif dir in ('tr', 'bl'): self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif dir in ('t', 'b'): self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif dir in ('l', 'r'): self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self.sub_rect.contains(event.pos()):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.is_resizing = False
        self.resize_dir = None

class SubtitleTextEdit(QTextEdit):
    focus_in_signal = pyqtSignal()
    
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_in_signal.emit()

class SubtitleListItemWidget(QWidget):
    text_changed_signal = pyqtSignal()
    delete_signal = pyqtSignal(object) # Trả về subtitle_item
    add_signal = pyqtSignal(object)    # Trả về subtitle_item (thêm sau item này)

    def __init__(self, subtitle_item, index, schedule_initial_adjust=True):
        super().__init__()
        self.item_data = subtitle_item
        self.current_search_text = ""
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 6, 15, 6); layout.setSpacing(15)
        
        # Cài đặt font chữ to và rõ hơn
        font = QFont()
        font.setPointSize(12) # Tăng kích thước font chữ lên 12pt
        
        # ID Label
        self.id_label = QLabel(f"{index}"); self.id_label.setObjectName("IdLabel")
        self.id_label.setFixedWidth(25)
        self.id_label.setFont(font)
        self.id_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        
        # Nội dung TextEdit (Dạng tối giản)
        self.text_edit = SubtitleTextEdit(self.item_data.text)
        self.text_edit.setObjectName("SubtitleTextEdit")
        self.text_edit.setFont(font)
        # Bật chế độ Word Wrap để xử lý dòng dài
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setFixedHeight(36)
        self.text_edit.textChanged.connect(self.on_text_changed)
        self.text_edit.focus_in_signal.connect(self.on_text_focused)
        
        # Tự động điều chỉnh chiều cao
        self.list_item = None
        self.text_edit.document().documentLayout().documentSizeChanged.connect(self.adjust_height)
        if schedule_initial_adjust:
            QTimer.singleShot(10, self.adjust_height) # Gọi ngay sau khi render xong (delay nhẹ để layout ổn định)
        
        # Nút hành động inline
        self.btn_add = QPushButton("+")
        self.btn_add.setProperty("class", "InlineButton")
        self.btn_add.setToolTip("Thêm phía sau")
        self.btn_add.clicked.connect(lambda: self.add_signal.emit(self.item_data))
        
        self.btn_delete = QPushButton("🗑")
        self.btn_delete.setProperty("class", "InlineButton")
        self.btn_delete.setObjectName("DeleteButton")
        self.btn_delete.setToolTip("Xóa dòng này")
        self.btn_delete.clicked.connect(lambda: self.delete_signal.emit(self.item_data))
        
        layout.addWidget(self.id_label)
        layout.addWidget(self.text_edit, 1)
        
        # Luôn căn giữa theo chiều dọc
        layout.setAlignment(self.btn_add, Qt.AlignmentFlag.AlignVCenter)
        layout.setAlignment(self.btn_delete, Qt.AlignmentFlag.AlignVCenter)
        
        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_delete)
        self.setLayout(layout)
    
    def on_text_focused(self):
        """Khi click vào text_edit, bắt buộc kích hoạt hành động chọn dòng cho list_widget cha."""
        self.adjust_height()
        if self.list_item and self.list_item.listWidget():
            list_widget = self.list_item.listWidget()
            try:
                # Ngăn list_widget chặn tín hiệu, đổi current item lập tức!
                list_widget.setCurrentItem(self.list_item)
            except Exception:
                pass

    def set_selected(self, selected):
        """Cập nhật trạng thái hiển thị khi được chọn."""
        if bool(self.property("selected")) == bool(selected):
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        for child in self.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)
        self.update()

    def set_ocr_state(self, state):
        """Cập nhật trạng thái hiển thị khi đang ở chế độ lọc OCR."""
        normalized_state = state if state else "normal"
        if self.property("ocr_state") == normalized_state:
            return
        self.setProperty("ocr_state", normalized_state)
        self.style().unpolish(self)
        self.style().polish(self)
        for child in self.findChildren(QWidget):
            child.style().unpolish(child)
            child.style().polish(child)
        self.update()
    
    def resizeEvent(self, event):
        """Khi widget thay đổi kích thước ngang, cần tính toán lại chiều cao do wrap line."""
        super().resizeEvent(event)
        self.adjust_height()

    def adjust_height(self):
        # Đảm bảo document layout nhận biết được chiều rộng thực tế của widget để wrap text chính xác
        self.text_edit.document().setTextWidth(self.text_edit.viewport().width())
        
        # Lấy chiều cao thực sự của toàn bộ nội dung trong document
        content_height = self.text_edit.document().size().height()
        
        # Thêm padding trên dưới để không bị scrollbar che khuất
        # Padding bao gồm: contents margins của QTextEdit + một chút vùng đệm (buffer)
        padding = 10
        new_height = int(content_height) + padding
        
        # Giới hạn chiều cao tối thiểu cho 1 dòng
        if new_height < 36:
            new_height = 36
        
        # Chỉ cập nhật nếu có sự thay đổi rõ ràng để tránh loop
        if abs(self.text_edit.height() - new_height) > 2:
            self.text_edit.setFixedHeight(new_height)
            if self.list_item:
                # Cập nhật sizeHint cho QListWidgetItem để ListWidget vẽ lại layout
                self.list_item.setSizeHint(self.sizeHint())

    def on_text_changed(self):
        new_text = self.text_edit.toPlainText()
        if self.item_data.text != new_text:
            self.item_data.text = new_text
            self.adjust_height()
            self.text_changed_signal.emit()

    def highlight_search_text(self, search_text, is_regex=False):
        """Bôi đen text tìm kiếm trong QTextEdit (hỗ trợ khoảng trắng hoặc regex)."""
        # Không strip để giữ nguyên khoảng trắng, chỉ lowercase
        self.current_search_text = search_text.lower() if search_text else ""
        
        # Block signals để tránh trigger textChanged
        self.text_edit.blockSignals(True)
        
        # Lưu vị trí con trỏ hiện tại
        cursor = self.text_edit.textCursor()
        current_position = cursor.position()
        
        # Xóa tất cả formatting cũ
        cursor.select(QTextCursor.SelectionType.Document)
        default_format = QTextCharFormat()
        cursor.setCharFormat(default_format)
        cursor.clearSelection()
        
        if not self.current_search_text:
            # Không có text để highlight, chỉ cần restore cursor
            cursor.setPosition(current_position)
            self.text_edit.setTextCursor(cursor)
            self.text_edit.blockSignals(False)
            return
        
        # Format cho text được highlight
        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor("#FFFF00"))  # Màu vàng
        highlight_format.setForeground(QColor("#000000"))  # Chữ đen
        
        if is_regex:
            # Sử dụng trực tiếp pattern regex truyền vào
            regex_pattern = self.current_search_text
        else:
            # CHUẨN HÓA TÌM KIẾM: Tạo regex hỗ trợ các loại dấu cách (ASCII, NBSP, Full-width)
            # Chuyển các ký tự đặc biệt trong search_text thành dạng text thường trong regex
            # ngoại trừ dấu cách sẽ biến thành pattern match tất cả loại space.
            escaped_search = re.escape(self.current_search_text)
            # Thay thế dấu cách đã thoát (\ ) hoặc chưa thoát bằng pattern match nhiều loại space
            regex_pattern = escaped_search.replace(r'\ ', r'[ \xa0\u3000]').replace(' ', r'[ \xa0\u3000]')
        
        # Lấy text hiện tại
        text = self.text_edit.toPlainText()
        text_lower = text.lower()
        
        try:
            for match in re.finditer(regex_pattern, text_lower):
                start_pos = match.start()
                end_pos = match.end()
                
                # Di chuyển cursor đến vị trí match và select text
                cursor.setPosition(start_pos)
                cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(highlight_format)
        except re.error:
            # Fallback về find() đơn giản nếu regex lỗi
            search_start = 0
            while True:
                pos = text_lower.find(self.current_search_text, search_start)
                if pos == -1:
                    break
                
                # Di chuyển cursor đến vị trí match và select text
                cursor.setPosition(pos)
                cursor.setPosition(pos + len(self.current_search_text), QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(highlight_format)
                
                search_start = pos + 1
        
        # Restore vị trí con trỏ
        cursor.setPosition(min(current_position, len(text)))
        cursor.clearSelection()
        self.text_edit.setTextCursor(cursor)
        
        self.text_edit.blockSignals(False)
    
    def clear_highlight(self):
        """Xóa tất cả highlight."""
        self.highlight_search_text("")

class AdvancedTimelineWidget(QWidget):
    time_changed = pyqtSignal(float)
    data_changed = pyqtSignal(bool)
    zoom_changed = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        # Tạo 3 track: track phụ trên (index 0), track chính (index 1), track phụ dưới (index 2)
        self.tracks = [[], [], []]
        self.main_track_index = 1
        self.video_duration = 1.0
        self.current_time = 0.0
        self.zoom = 1.0
        self.base_pixels_per_second = 50
        self.hover_scrub_enabled = False
        self.magnet_snap_enabled = True
        self.is_scrubbing = False
        self.active_snap_x = None # Tọa độ đường kẻ báo hiệu va chạm/bắt điểm
        
        # Dimensions
        self.ruler_height = 36   # Giảm nhẹ thước kẻ cho cân đối
        self.track_height = 32   # Giảm chiều cao track theo yêu cầu (gọn gàng hơn)
        self.track_spacing = 8
        self.padding_bottom = 15
        self.left_padding = 50
        self.right_padding = 100
        
        # Design Palette (OpenCut inspired)
        self.color_bg = QColor("#121212")
        self.color_ruler_bg = QColor("#1E1E1E")
        self.color_track_bg = QColor("#181818")
        self.color_separator = QColor("#2A2A2A")
        self.color_text_dim = QColor("#888888")
        self.color_text_bright = QColor("#E0E0E0")
        self.color_playhead = QColor("#FF4D4D")
        self.color_accent = QColor("#3A82F6")
        
        # Subtitle Block Colors
        self.track_colors = {
            0: QColor("#2E5046"),  # Phụ trên (Teal dim)
            1: QColor("#5DBAA0"),  # Chính (OpenCut Teal)
            2: QColor("#3D4B5C")   # Phụ dưới (Steel Blue)
        }
        
        self.selected_sub = None
        self.resizing_sub = None
        self.resize_edge = None
        self.dragging_sub = None
        self.drag_offset = QPoint()
        self.is_scrubbing = False
        self.ghost_rect = None
        self.drag_duration = 0.0
        self.ghost_track_idx = 0
        self.clicked_sub_info = None
        self.click_position = QPoint()
        self.reading_speed_issue_ids = set()
        self._resize_restore_playhead_time = None

    def get_pixels_per_second(self): return self.base_pixels_per_second * self.zoom
    def time_to_x(self, time): return self.left_padding + time * self.get_pixels_per_second()
    def x_to_time(self, x): return (x - self.left_padding) / self.get_pixels_per_second()

    def set_data(self, tracks, duration):
        # Đảm bảo luôn có đúng 3 track
        self.tracks = [[], [], []]
        
        if tracks and len(tracks) >= 3:
            # Nhận đúng thứ tự từ MainWindow
            self.tracks[0] = tracks[0]  # Track phụ trên
            self.tracks[1] = tracks[1]  # Track chính (giữa) - đây là nơi SRT được load vào
            self.tracks[2] = tracks[2]  # Track phụ dưới
        elif tracks and len(tracks) > 0:
            # Trường hợp đặc biệt: nếu chỉ có ít track
            if len(tracks) == 1:
                # Chỉ có 1 track từ SRT -> đặt vào track chính (index 1)
                self.tracks[1] = tracks[0]
            elif len(tracks) == 2:
                self.tracks[0] = tracks[0]
                self.tracks[1] = tracks[1]
        
        self.video_duration = duration if duration > 0 else 60.0
        self.update_widget_size(); self.update()

    def set_reading_speed_issue_ids(self, issue_ids):
        """Nhận danh sách subtitle vi phạm tốc độ đọc để tô nổi bật trên timeline."""
        new_ids = issue_ids if issue_ids is not None else set()
        if new_ids == self.reading_speed_issue_ids:
            return
        self.reading_speed_issue_ids = new_ids
        self.update()

    def set_zoom(self, zoom_level):
        self.zoom = max(0.1, zoom_level); self.update_widget_size(); self.update()

    def set_current_time(self, time):
        old_x = int(self.time_to_x(self.current_time))
        self.current_time = time
        new_x = int(self.time_to_x(time))
        # Chỉ invalidate vùng quanh playhead cũ và mới thay vì toàn bộ widget
        margin = 10
        dirty_rect = QRect(
            min(old_x, new_x) - margin, 0,
            abs(new_x - old_x) + 2 * margin, self.height()
        )
        self.update(dirty_rect)

    def update_widget_size(self):
        num_tracks = 3
        # Chiều rộng = Padding Trái + (Thời lượng * Pixels/Sec) + Padding Phải
        content_width = self.left_padding + (self.video_duration * self.get_pixels_per_second()) + self.right_padding
        content_height = self.ruler_height + num_tracks * (self.track_height + self.track_spacing) + self.padding_bottom
        self.setFixedSize(int(content_width), int(content_height))

    def get_sub_at_pos(self, pos):
        y_from_top = pos.y() - self.ruler_height
        track_idx = y_from_top // (self.track_height + self.track_spacing)
        
        if 0 <= track_idx < 3:
            for sub_idx, sub in enumerate(self.tracks[track_idx]):
                if self.get_sub_rect(sub, track_idx).contains(pos):
                    return sub, track_idx, sub_idx
        return None, -1, -1

    def get_sub_rect(self, sub, track_idx):
        x = self.time_to_x(sub.start_time)
        w = sub.duration() * self.get_pixels_per_second()
        y = self.ruler_height + track_idx * (self.track_height + self.track_spacing)
        return QRect(int(x), int(y), int(w), self.track_height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Lấy clip region từ event để chỉ vẽ vùng cần thiết
        clip_rect = event.rect()
        
        # 1. Vẽ nền chính
        painter.fillRect(clip_rect, self.color_bg)
        
        # 2. Vẽ nền cho các track
        for i in range(3):
            y = self.ruler_height + i * (self.track_height + self.track_spacing)
            track_bg_rect = QRect(clip_rect.left(), y, clip_rect.width(), self.track_height)
            painter.fillRect(track_bg_rect, self.color_track_bg)
        
        # 3. Vẽ đường kẻ và nhãn
        self.draw_track_separators(painter)
        self.draw_track_labels(painter)
        self.draw_ruler(painter)
        
        # 4. Vẽ các khối phụ đề (Tối ưu hóa: Frustum Culling)
        # Chỉ vẽ các khối phụ đề nằm trong vùng nhìn thấy để tăng tốc độ phản hồi
        scroll_area = self.parent().parent() if hasattr(self.parent(), 'parent') else None
        visible_start_time = 0
        visible_end_time = self.video_duration
        
        if isinstance(scroll_area, QScrollArea):
            scroll_x = scroll_area.horizontalScrollBar().value()
            view_w = scroll_area.viewport().width()
            visible_start_time = self.x_to_time(scroll_x)
            visible_end_time = self.x_to_time(scroll_x + view_w)

        for track_idx in range(3):
            for sub in self.tracks[track_idx]:
                # Culling: Bỏ qua nếu khối nằm hoàn toàn bên trái vùng nhìn thấy
                if sub.end_time < visible_start_time - 1.0: # Buffer 1s
                    continue
                # Culling: Dừng lại nếu khối bắt đầu hoàn toàn bên phải vùng nhìn thấy
                if sub.start_time > visible_end_time + 1.0: # Buffer 1s
                    break
                    
                is_selected = (sub == self.selected_sub)
                self.draw_sub_block(painter, sub, track_idx, is_selected)
        
        # 5. Vẽ ghost khi đang kéo
        if self.ghost_rect:
            painter.setBrush(QColor(58, 130, 246, 60))
            pen = QPen(self.color_accent, 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(QRectF(self.ghost_rect), 6, 6)
        
        # 6. Vẽ playhead (Đã tích hợp chỉ báo Snap vào màu sắc của Playhead)
        self.draw_playhead(painter)
    
    def draw_track_separators(self, painter):
        painter.setPen(QPen(self.color_separator, 1))
        # Đường kẻ trên cùng của track đầu tiên
        # painter.drawLine(0, self.ruler_height, self.width(), self.ruler_height)
        
        for track_idx in range(1, 4):
            y = self.ruler_height + track_idx * (self.track_height + self.track_spacing) - self.track_spacing // 2
            painter.drawLine(0, y, self.width(), y)
    
    def draw_track_labels(self, painter):
        painter.setPen(self.color_text_dim)
        font = QFont('Segoe UI', 8, QFont.Weight.Bold)
        painter.setFont(font)
        
        track_names = ["TRACK 1", "MAIN", "TRACK 2"]
        for track_idx in range(3):
            y = self.ruler_height + track_idx * (self.track_height + self.track_spacing) + self.track_height - 6
            painter.drawText(8, int(y), track_names[track_idx])
    
    def draw_ruler(self, painter):
        # Nền thước kẻ
        painter.fillRect(QRect(0, 0, self.width(), self.ruler_height), self.color_ruler_bg)
        painter.setPen(QPen(self.color_separator, 1))
        painter.drawLine(0, self.ruler_height, self.width(), self.ruler_height)
        
        pixels_per_second = self.get_pixels_per_second()
        # Tự động điều chỉnh khoảng cách vạch dựa trên Zoom
        if pixels_per_second > 100: interval = 0.5
        elif pixels_per_second > 40: interval = 1.0
        elif pixels_per_second > 10: interval = 5.0
        else: interval = 10.0
        
        painter.setPen(QPen(QColor("#444444"), 1))
        font = QFont('Segoe UI', 8)
        painter.setFont(font)
        
        # Lấy vùng hiển thị để culling - không vẽ vạch ngoài viewport (tối ưu video dài)
        scroll_area = self.parent().parent() if hasattr(self.parent(), 'parent') else None
        visible_x_start = 0
        visible_x_end = self.width()
        if isinstance(scroll_area, QScrollArea):
            visible_x_start = scroll_area.horizontalScrollBar().value() - 50
            visible_x_end = visible_x_start + scroll_area.viewport().width() + 50

        tick_interval = interval / 5
        # Tính vạch bắt đầu từ vùng visible thay vì từ 0 để tránh loop qua hàng nghìn vạch
        start_tick = max(0, int(self.x_to_time(visible_x_start) / tick_interval))
        end_tick = int(self.x_to_time(visible_x_end) / tick_interval) + 2
        end_tick = min(end_tick, int(self.video_duration / tick_interval) + 1)

        for i in range(start_tick, end_tick):
            t = i * tick_interval
            x = int(self.time_to_x(t))
            if i % 5 == 0:
                painter.setPen(QPen(QColor("#666666"), 1))
                painter.drawLine(x, self.ruler_height - 12, x, self.ruler_height)
                # Vẽ text thời gian
                painter.setPen(self.color_text_dim)
                time_str = f"{int(t//60):02}:{int(t%60):02}"
                if t % 1 != 0: time_str += f".{int((t%1)*10)}"
                painter.drawText(x + 4, self.ruler_height - 14, time_str)
            else:
                painter.setPen(QPen(QColor("#333333"), 1))
                painter.drawLine(x, self.ruler_height - 6, x, self.ruler_height)

    def draw_sub_block(self, painter, sub, track_idx, is_selected):
        sub_rect = self.get_sub_rect(sub, track_idx)
        if sub_rect.right() < 0 or sub_rect.left() > self.width(): return
        is_speed_issue = id(sub) in self.reading_speed_issue_ids
        
        # Color & Style
        base_color = self.track_colors.get(track_idx, self.color_accent)
        if is_selected:
            color = base_color.lighter(110)
            border_color = base_color.darker(120)
            text_color = QColor("#FFFFFF")
        else:
            color = base_color
            border_color = base_color.darker(120)
            text_color = QColor("#E0E0E0")
            if track_idx == 1: text_color = QColor("#000000") # Main track dùng chữ đen cho nổi

        # Vẽ body
        painter.setBrush(color)
        painter.setPen(QPen(border_color, 1.5 if is_selected else 1))
        radius = 6
        painter.drawRoundedRect(sub_rect, radius, radius)

        # Tô đỏ nhẹ các khối vi phạm tốc độ đọc để dễ nhận diện trực quan
        if is_speed_issue:
            painter.setBrush(QColor(255, 82, 82, 60 if is_selected else 45))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(sub_rect.adjusted(1, 1, -1, -1), radius, radius)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#E57373"), 1.5 if is_selected else 1))
            painter.drawRoundedRect(sub_rect, radius, radius)
        
        # Vẽ text
        painter.save()
        painter.setPen(text_color)
        painter.setFont(QFont('Segoe UI', 9, QFont.Weight.Medium if is_selected else QFont.Weight.Normal))
        clip_rect = sub_rect.adjusted(6, 0, -6, 0)
        painter.setClipRect(clip_rect)
        display_text = sub.text.replace('\n', ' ')
        painter.drawText(clip_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, display_text)
        painter.restore()
        
        if is_selected:
            # Resize Handles (Minimalist lines)
            painter.setPen(QPen(QColor("#00E5FF"), 2))
            h = sub_rect.height() // 3
            mid_y = sub_rect.center().y()
            painter.drawLine(sub_rect.left() + 3, mid_y - h//2, sub_rect.left() + 3, mid_y + h//2)
            painter.drawLine(sub_rect.right() - 3, mid_y - h//2, sub_rect.right() - 3, mid_y + h//2)

    def draw_playhead(self, painter):
        playhead_x = int(self.time_to_x(self.current_time))
        
        # Tích hợp Snap Indicator: Đổi màu sang Cyan khi có bắt điểm
        is_snapped = self.active_snap_x is not None
        current_color = QColor("#00E5FF") if is_snapped else self.color_playhead
        
        # Line
        painter.setPen(QPen(current_color, 1.5))
        painter.drawLine(playhead_x, 0, playhead_x, self.height())
        
        # Head (Inverted Pentagon/Diamond)
        head_w, head_h = 14, 18
        path = QPainterPath()
        path.moveTo(playhead_x - head_w//2, 0)
        path.lineTo(playhead_x + head_w//2, 0)
        path.lineTo(playhead_x + head_w//2, head_h - 6)
        path.lineTo(playhead_x, head_h)
        path.lineTo(playhead_x - head_w//2, head_h - 6)
        path.closeSubpath()
        
        painter.fillPath(path, current_color)
        painter.setPen(QPen(QColor(0,0,0,80), 1))
        painter.drawPath(path)

    def mouseDoubleClickEvent(self, event):
        sub, _, _ = self.get_sub_at_pos(event.pos())
        if sub: 
            self.selected_sub = sub  # Đặt làm subtitle được chọn
            self.time_changed.emit(sub.start_time)
            self.update()  # Cập nhật hiển thị

    def mousePressEvent(self, event):
        pos = event.pos()
        # Kiểm tra click vào thước kẻ hoặc vùng track để scrub
        if (QRect(0, 0, self.width(), self.ruler_height).contains(pos) or 
            pos.y() > self.ruler_height):  # Click vào bất kỳ vùng nào của track
            # Nếu không click vào phụ đề cụ thể, cho phép scrub
            sub, track_idx, sub_idx = self.get_sub_at_pos(pos)
            if not sub:  # Chỉ scrub khi không click vào phụ đề
                self.is_scrubbing = True
                self.time_changed.emit(max(0, self.x_to_time(pos.x())))
                return
        
        sub, track_idx, sub_idx = self.get_sub_at_pos(pos)
        old_selected = self.selected_sub
        self.selected_sub = sub
        
        # Nếu chọn subtitle mới, cập nhật selection trong danh sách
        if sub and sub != old_selected:
            # Phát tín hiệu để MainWindow cập nhật selection trong danh sách
            # Sử dụng cách tiếp cận thông qua parent hierarchy
            main_window = self.get_main_window()
            if main_window:
                main_window.update_selection_in_list(sub)
        
        if sub:
            sub_rect = self.get_sub_rect(sub, track_idx); handle_hitbox_width = 6
            if pos.x() < sub_rect.left() + handle_hitbox_width: self.resize_edge = 'left'
            elif pos.x() > sub_rect.right() - handle_hitbox_width: self.resize_edge = 'right'
            if self.resize_edge:
                self.resizing_sub = (sub, track_idx, sub_idx)
                self._resize_restore_playhead_time = self.current_time
            else:
                self.clicked_sub_info = (sub, track_idx, sub_idx)
                self.click_position = pos
                self.drag_duration = sub.duration()
        self.update()

    def get_main_window(self):
        """Tìm MainWindow từ hierarchy của widget"""
        widget = self.parent()
        while widget:
            if isinstance(widget, MainWindow):
                return widget
            widget = widget.parent()
        return None

    def mouseMoveEvent(self, event):
        pos = event.pos()
        is_interacting = False

        if self.is_scrubbing:
            self.handle_scrub(pos)
            is_interacting = True
        elif self.dragging_sub:
            self.handle_drag(pos)
            is_interacting = True
        elif self.resizing_sub:
            self.handle_resize(pos)
            # Khi resize, playhead tạm chạy theo chuột để người dùng đối chiếu với hardsub.
            self.handle_scrub(pos)
            is_interacting = True
        elif hasattr(self, 'clicked_sub_info') and self.clicked_sub_info:
            drag_threshold = 5
            if (pos - self.click_position).manhattanLength() > drag_threshold:
                sub, track_idx, sub_idx = self.clicked_sub_info
                sub_rect = self.get_sub_rect(sub, track_idx)
                self.dragging_sub = (sub, track_idx, sub_idx)
                self.drag_offset = self.click_position - sub_rect.topLeft()
                self.clicked_sub_info = None
                self.handle_drag(pos)
                is_interacting = True
            else:
                # Đang giữ chuột chờ đạt ngưỡng drag
                is_interacting = True
        else:
            sub, track_idx, _ = self.get_sub_at_pos(pos)
            if sub:
                sub_rect = self.get_sub_rect(sub, track_idx); handle_hitbox_width = 6
                if pos.x() < sub_rect.left() + handle_hitbox_width or pos.x() > sub_rect.right() - handle_hitbox_width:
                    self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
                else: self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            else: self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        # Chỉ chạy hover-scrub khi KHÔNG có tương tác kéo/resize đang diễn ra.
        if hasattr(self, 'hover_scrub_enabled') and self.hover_scrub_enabled:
            left_button_down = bool(event.buttons() & Qt.MouseButton.LeftButton)
            if (not left_button_down
                and not is_interacting
                and not getattr(self, 'clicked_sub_info', None)):
                self.handle_scrub(pos)

    def mouseReleaseEvent(self, event):
        changed = False
        restore_playhead_time = self._resize_restore_playhead_time if self.resizing_sub else None
        if self.dragging_sub and self.ghost_rect:
            sub_item, original_track_idx, _ = self.dragging_sub
            new_start_time = self.x_to_time(self.ghost_rect.x())
            sub_item.start_time = new_start_time
            sub_item.end_time = new_start_time + self.drag_duration
            target_track_idx = self.ghost_track_idx
            if target_track_idx != original_track_idx:
                self.tracks[original_track_idx].remove(sub_item)
                self.tracks[target_track_idx].append(sub_item)
                self.tracks[target_track_idx].sort(key=lambda s: s.start_time)
            changed = True
        elif self.resizing_sub:
            changed = True
            
        if changed: 
            self.data_changed.emit(True)
        
        self.is_scrubbing = False; self.resizing_sub = None; self.resize_edge = None
        self.dragging_sub = None; self.ghost_rect = None; self.ghost_track_idx = 0
        self.active_snap_x = None

        if restore_playhead_time is not None:
            self._resize_restore_playhead_time = None
            self.set_current_time(restore_playhead_time)
        else:
            self._resize_restore_playhead_time = None
        
        if hasattr(self, 'clicked_sub_info'):
            self.clicked_sub_info = None
            
        # Khi buông chuột, phát tín hiệu để MainWindow vẽ lại frame cuối ở chất lượng cao (Smooth Scale)
        self.time_changed.emit(self.current_time)
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Lưu vị trí của playhead trước khi zoom
            playhead_x = self.time_to_x(self.current_time)
            scroll_area = self.parent().parent()
            
            if isinstance(scroll_area, QScrollArea):
                viewport_width = scroll_area.viewport().width()
                
                # Thực hiện zoom
                delta = event.angleDelta().y()
                factor = 1.15 if delta > 0 else 1/1.15
                new_zoom = max(0.1, min(self.zoom * factor, 20.0))
                
                if new_zoom != self.zoom:
                    self.zoom = new_zoom
                    self.update_widget_size()
                    
                    # Tính toán vị trí cuộn mới để giữ playhead ở trung tâm
                    new_playhead_x = self.time_to_x(self.current_time)
                    center_offset = viewport_width // 2
                    new_scroll_value = max(0, new_playhead_x - center_offset)
                    scroll_area.horizontalScrollBar().setValue(int(new_scroll_value))
                    
                    self.update()
                    self.zoom_changed.emit(self.zoom)
            else:
                # Fallback nếu không tìm thấy scroll_area
                delta = event.angleDelta().y()
                factor = 1.15 if delta > 0 else 1/1.15
                new_zoom = max(0.1, min(self.zoom * factor, 20.0))
                if new_zoom != self.zoom:
                    self.zoom = new_zoom
                    self.update_widget_size()
                    self.update()
                    self.zoom_changed.emit(self.zoom)
        else: 
            event.ignore()

    def handle_scrub(self, pos):
        """Xử lý kéo thanh playhead, giới hạn trong vùng nhìn thấy"""
        # Tìm vùng nhìn thấy hiện tại từ ScrollArea
        min_x = 0
        max_x = self.width()
        
        # Lấy widget QScrollArea bao quanh
        scroll_area = None
        p = self.parent()
        while p:
            if isinstance(p, QScrollArea):
                scroll_area = p
                break
            p = p.parent()
            
        if scroll_area:
            # Vùng nhìn thấy = [giá trị thanh cuộn, giá trị + chiều rộng viewport]
            scroll_x = scroll_area.horizontalScrollBar().value()
            view_width = scroll_area.viewport().width()
            min_x = scroll_x
            max_x = scroll_x + view_width

        # Kẹp tọa độ x vào vùng nhìn thấy
        clamped_x = max(min_x, min(max_x, pos.x()))
        
        # Logic Bắt điểm (Magnet Snap)
        raw_time = max(0, min(self.video_duration, self.x_to_time(clamped_x)))
        snapped_time = raw_time
        
        if self.magnet_snap_enabled:
            # Giảm xuống 5px để độ khựng nhẹ nhàng và tinh tế nhất
            snap_threshold_px = 5 
            snap_threshold_time = snap_threshold_px / self.get_pixels_per_second()
            best_dist = float('inf')
            
            for track in self.tracks:
                for sub in track:
                    # Kiểm tra cả điểm đầu và điểm cuối
                    dist_start = abs(raw_time - sub.start_time)
                    dist_end = abs(raw_time - sub.end_time)
                    
                    if dist_start < snap_threshold_time and dist_start < best_dist:
                        best_dist = dist_start
                        snapped_time = sub.start_time
                        self.active_snap_x = self.time_to_x(sub.start_time)
                    if dist_end < snap_threshold_time and dist_end < best_dist:
                        best_dist = dist_end
                        snapped_time = sub.end_time
                        self.active_snap_x = self.time_to_x(sub.end_time)
        else:
            self.active_snap_x = None  # Đảm bảo không còn snap ma
        
        self.time_changed.emit(snapped_time)
    
    def can_place_subtitle_in_track(self, track, start_time, end_time, exclude_sub=None):
        epsilon = 0.001
        for sub in track:
            if sub is exclude_sub: continue
            if not (end_time <= sub.start_time + epsilon or start_time >= sub.end_time - epsilon): return False
        return True
    
    def find_suitable_track(self, start_time, end_time, preferred_track_idx=None, exclude_sub=None):
        # Ưu tiên track được chỉ định
        if preferred_track_idx is not None and 0 <= preferred_track_idx < 3:
            if self.can_place_subtitle_in_track(self.tracks[preferred_track_idx], start_time, end_time, exclude_sub):
                return preferred_track_idx
        
        # Tìm track khác có thể đặt được
        for track_idx in range(3):
            if self.can_place_subtitle_in_track(self.tracks[track_idx], start_time, end_time, exclude_sub):
                return track_idx
        
        # Nếu không có track nào phù hợp, trả về track chính
        return self.main_track_index

    def handle_drag(self, pos):
        if not self.dragging_sub: return
        sub, original_track_idx, _ = self.dragging_sub
        
        # 1. Tính toán thời gian gốc từ chuột
        scale = self.get_pixels_per_second()
        mouse_x = (pos - self.drag_offset).x()
        raw_start_time = max(0, min(self.video_duration - self.drag_duration, self.x_to_time(mouse_x)))
        raw_end_time = raw_start_time + self.drag_duration
        
        snapped_start_time = raw_start_time
        self.active_snap_x = None
        
        # Tìm giới hạn va chạm dựa trên vị trí mục tiêu hiện tại
        left_limit = 0.0
        right_limit = self.video_duration
        for other in self.tracks[original_track_idx]:
            if other is sub: continue
            # Nếu khối khác ở bên trái vị trí đang kéo tới (tính theo trung tâm để linh hoạt)
            if other.end_time <= raw_start_time + (self.drag_duration / 2):
                left_limit = max(left_limit, other.end_time)
            # Nếu khối khác ở bên phải vị trí đang kéo tới
            elif other.start_time >= raw_end_time - (self.drag_duration / 2):
                right_limit = min(right_limit, other.start_time)

        # 2. Xử lý Snapping (Playhead + Magnet)
        if self.magnet_snap_enabled:
            snap_px = 5 # Giảm vùng bắt dính xuống 5px (chạm mới hút)
            snap_t = snap_px / scale
            
            # Ưu tiên 1: Playhead
            if abs(raw_start_time - self.current_time) < snap_t:
                snapped_start_time = self.current_time
                self.active_snap_x = self.time_to_x(self.current_time)
            elif abs(raw_end_time - self.current_time) < snap_t:
                snapped_start_time = self.current_time - self.drag_duration
                self.active_snap_x = self.time_to_x(self.current_time)
            else:
                # Ưu tiên 2: Cạnh của các phụ đề khác (Trong phạm vi hút)
                for track in self.tracks:
                    for other in track:
                        if other is sub: continue
                        if abs(raw_start_time - other.end_time) < snap_t:
                            snapped_start_time = other.end_time
                            self.active_snap_x = self.time_to_x(other.end_time)
                            break
                        if abs(raw_end_time - other.start_time) < snap_t:
                            snapped_start_time = other.start_time - self.drag_duration
                            self.active_snap_x = self.time_to_x(other.start_time)
                            break
                    if self.active_snap_x is not None: break

        # 3. Ép va chạm cứng (Nếu vẫn xác định ở track cũ)
        clamped_start_time = max(left_limit, min(right_limit - self.drag_duration, snapped_start_time))
        
        # 4. Logic Nhảy Track thông minh
        y_from_top = pos.y() - self.ruler_height
        mouse_target_idx = max(0, min(y_from_top // (self.track_height + self.track_spacing), 2))
        
        # hysteresis_px: Khoảng cách "đẩy" tối thiểu để chấp nhận việc va chạm và tìm track mới
        hysteresis_px = 12 
        mouse_offset_px = abs(self.time_to_x(raw_start_time) - self.time_to_x(clamped_start_time))
        
        # QUAN TRỌNG: Nếu chuột đang đẩy vào vật cản, chúng ta dùng snapped_start_time (chưa bị clamp cứng)
        # để hỏi hệ thống xem có track nào khác ĐẶT ĐƯỢC ở vị trí này không.
        if mouse_target_idx == original_track_idx and mouse_offset_px < hysteresis_px:
            final_track_idx = original_track_idx
            final_start_time = clamped_start_time
            # Hiển thị Line Cyan nếu đang bị chặn (khựng)
            if clamped_start_time != snapped_start_time:
                self.active_snap_x = self.time_to_x(clamped_start_time if clamped_start_time == left_limit else right_limit)
        else:
            # Nếu đẩy đủ mạnh hoặc đổi track, tìm track phù hợp cho vị trí MOUSE (đã snap magnet)
            final_track_idx = self.find_suitable_track(snapped_start_time, snapped_start_time + self.drag_duration, preferred_track_idx=mouse_target_idx, exclude_sub=sub)
            final_start_time = snapped_start_time

        # Cập nhật Ghost
        ghost_y = self.ruler_height + final_track_idx * (self.track_height + self.track_spacing)
        ghost_w = self.drag_duration * scale
        self.ghost_rect = QRectF(self.time_to_x(final_start_time), ghost_y, ghost_w, self.track_height)
        self.ghost_track_idx = final_track_idx
        self.update()

    def handle_resize(self, pos):
        if not self.resizing_sub: return
        sub, track_idx, _ = self.resizing_sub 
        raw_time = max(0, min(self.video_duration, self.x_to_time(pos.x())))
        snapped_time = raw_time
        self.active_snap_x = None
        
        scale = self.get_pixels_per_second()
        snap_px = 5 # Chạm mới hút
        snap_t = snap_px / scale
        
        # 1. Snap vào Playhead (LUÔN HOẠT ĐỘNG theo yêu cầu người dùng)
        if abs(raw_time - self.current_time) < snap_t:
            snapped_time = self.current_time
            self.active_snap_x = self.time_to_x(self.current_time)
        
        # 2. Logic Magnet cho các phụ đề khác (Chỉ khi bật Magnet)
        if self.magnet_snap_enabled and self.active_snap_x is None:
            for t in self.tracks:
                for s in t:
                    if s is not sub:
                        if abs(raw_time - s.start_time) < snap_t:
                            snapped_time = s.start_time
                            self.active_snap_x = self.time_to_x(s.start_time)
                            break
                        if abs(raw_time - s.end_time) < snap_t:
                            snapped_time = s.end_time
                            self.active_snap_x = self.time_to_x(s.end_time)
                            break
                if self.active_snap_x is not None: break

        if self.resize_edge == 'left':
            left_boundary = 0.0
            for other_sub in self.tracks[track_idx]:
                if other_sub is not sub and other_sub.end_time < sub.end_time:
                    left_boundary = max(left_boundary, other_sub.end_time)
            # Khựng lại tại biên cố định nếu kéo quá (Collision)
            new_start_time = max(left_boundary, min(snapped_time, sub.end_time - 0.05))
            # Chỉ hiện line báo hiệu nếu CÓ bật Magnet
            if self.magnet_snap_enabled and new_start_time == left_boundary and snapped_time < left_boundary:
                self.active_snap_x = self.time_to_x(left_boundary)
            sub.start_time = new_start_time
            
        elif self.resize_edge == 'right':
            right_boundary = self.video_duration
            for other_sub in self.tracks[track_idx]:
                if other_sub is not sub and other_sub.start_time > sub.start_time:
                    right_boundary = min(right_boundary, other_sub.start_time)
            # Khựng lại tại biên cố định nếu kéo quá (Collision)
            new_end_time = min(right_boundary, max(snapped_time, sub.start_time + 0.05))
            # Chỉ hiện line báo hiệu nếu CÓ bật Magnet
            if self.magnet_snap_enabled and new_end_time == right_boundary and snapped_time > right_boundary:
                self.active_snap_x = self.time_to_x(right_boundary)
            sub.end_time = new_end_time
            
        self.update()

class VideoLoaderWorker(QThread):
    """Luồng xử lý đọc video ngầm để không gây lag giao diện chính"""
    frame_ready = pyqtSignal(QImage, float) # Trả về ảnh và thời gian
    
    def __init__(self, video_path):
        super().__init__()
        self.video_path = video_path
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self.pending_seek = None # Thời gian cần seek
        self.is_running = True
        self.target_size = None
        self.is_scrubbing = False

    def request_seek(self, time_sec, target_size, is_scrubbing):
        self.mutex.lock()
        self.pending_seek = time_sec
        self.target_size = target_size
        self.is_scrubbing = is_scrubbing
        self.condition.wakeOne()
        self.mutex.unlock()

    def stop(self):
        self.mutex.lock()
        self.is_running = False
        self.condition.wakeOne()
        self.mutex.unlock()
        self.wait()

    def run(self):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened(): return

        while self.is_running:
            self.mutex.lock()
            while self.is_running and self.pending_seek is None:
                # Đợi cho đến khi có yêu cầu mới
                self.condition.wait(self.mutex)
            
            if not self.is_running:
                self.mutex.unlock()
                break
            
            # Lấy yêu cầu - lấy yêu cầu MỚI NHẤT, bỏ qua các yêu cầu cũ (frame drop)
            seek_time = self.pending_seek
            target_size = self.target_size
            is_scrubbing = self.is_scrubbing
            self.pending_seek = None  # Reset để nhận yêu cầu tiếp theo
            self.mutex.unlock()
            
            # Nếu seek_time là -1, nghĩa là yêu cầu nạp khung hình KẾ TIẾP (Sequential)
            # Nếu seek_time >= 0, thực hiện set vị trí (Random Access)
            if seek_time >= 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, seek_time * 1000)
            
            ret, frame = cap.read()
            if ret:
                # Kiểm tra xem có yêu cầu MỚI HƠN đang chờ không (drop frame cũ)
                self.mutex.lock()
                has_newer = self.pending_seek is not None
                self.mutex.unlock()
                if has_newer:
                    continue  # Bỏ qua frame này, xử lý yêu cầu mới hơn ngay
                
                actual_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                
                # Downsampling
                if target_size and target_size.width() > 0:
                    fh, fw = frame.shape[:2]
                    ratio = min(target_size.width() / fw, target_size.height() / fh)
                    new_w, new_h = int(fw * ratio), int(fh * ratio)
                    
                    interp = cv2.INTER_NEAREST if is_scrubbing else cv2.INTER_AREA
                    small_frame = cv2.resize(frame, (new_w, new_h), interpolation=interp)
                    
                    rgb_image = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    img_data = rgb_image.data.tobytes()
                    q_img = QImage(img_data, w, h, w*ch, QImage.Format.Format_RGB888).copy()
                    
                    self.frame_ready.emit(q_img, actual_time)
        
        cap.release()

class MainWindow(QMainWindow):
    def __init__(self, initial_video_path=None, initial_srt_path=None):
        super().__init__()
        self.setWindowTitle("Trình chỉnh sửa phụ đề"); self.setGeometry(100, 100, 1440, 810)
        
        self.temp_srt_path = initial_srt_path
        self.has_unsaved_changes = False

        # Khởi tạo dữ liệu
        self.subtitle_tracks = [[], [], []]
        self.video_capture = None
        self.video_timer = QTimer(self); self.video_timer.timeout.connect(self.update_frame)
        self.video_duration = 0.0
        self.video_path = None
        self.font_path = self._find_system_font()
        
        # Nạp font vào hệ thống Qt để có thể sử dụng theo tên
        self.font_id = QFontDatabase.addApplicationFont(self.font_path)
        if self.font_id != -1:
            families = QFontDatabase.applicationFontFamilies(self.font_id)
            self.font_family = families[0] if families else "Segoe UI"
        else:
            self.font_family = "Segoe UI"
            
        # Tối ưu hóa hiệu năng
        self.font_cache = {}
        self.last_seek_time = 0.0
        self.seek_interval = 0.05  # Giới hạn ~20 FPS khi scrubbing (giảm tải decoder video dài)
        
        # Luồng xử lý video không đồng bộ
        self.video_worker = None
        
        # Trạng thái thời gian thực tế (Đồng hồ nội bộ)
        self.current_time = 0.0
        
        # Tối ưu hóa cho video dài
        self.memory_threshold = 75  # % memory usage threshold - phòng ngừa sớm hơn với video dài
        self.frame_cache = {}  # Cache cho frame đã xử lý
        self.cache_size_limit = 30  # Giảm xuống 30 để tránh tốn RAM với video dài 1-2 giờ
        self.processing_thread = None
        self.is_processing = False
        
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_steps = 50
        
        # Biến cho chức năng tìm kiếm
        self.search_results = []  # Danh sách các index của subtitle khớp với tìm kiếm
        self.current_search_index = -1  # Index hiện tại trong search_results
        self.is_ocr_filter_active = False # Flag cho chế độ lọc lỗi OCR
        self.is_speed_filter_active = False # Flag cho chế độ lọc tốc độ đọc
        self.is_duplicate_filter_active = False # Flag cho chế độ lọc phụ đề liền kề bị trùng

        # Chuẩn tốc độ đọc (ký tự/giây) theo yêu cầu
        self.min_reading_cps = 3.0
        self.max_reading_cps = 3.0
        self._reading_char_regex = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaffA-Za-z0-9]")
        self._reading_speed_cache_invalid = True
        self._reading_speed_issue_rows = []
        self._reading_speed_issue_ids = set()
        self._ocr_filter_snapshot_ids = None
        
        # Tối ưu hóa UI updates cho video dài
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._perform_delayed_update)
        self.subtitle_text_refresh_timer = QTimer(self)
        self.subtitle_text_refresh_timer.setSingleShot(True)
        self.subtitle_text_refresh_timer.timeout.connect(self._flush_text_edit_updates)
        self.large_list_mode_threshold = 1500
        self.large_list_batch_size = 120
        self.pending_update_reorganize = False
        self.is_updating_list = False
        self.subtitle_widgets_cache = {}  # Cache cho subtitle widgets
        self._sorted_subs_cache = None  # Cache cho sorted subtitles list
        self._cache_invalid = True  # Flag để biết khi nào cần refresh cache
        self._start_times_cache = None  # Cache list start_time để bisect nhanh O(log N)
        self._last_found_sub = None  # Cache temporal locality cho get_active_subtitle_item
        self.last_selected_idx = -1  # Cache index được chọn để tránh loop O(N)
        
        if not self.font_path: print("Cảnh báo: Không tìm thấy font hệ thống phù hợp. Sử dụng font mặc định.")
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget); main_layout.setContentsMargins(0, 0, 0, 0); main_layout.setSpacing(0)
        main_layout.addWidget(self.create_header_bar())
        workspace_layout = QVBoxLayout(); workspace_layout.setContentsMargins(0, 0, 0, 0); workspace_layout.setSpacing(0)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.create_left_panel())
        self.main_splitter.addWidget(self.create_right_panel())
        self.main_splitter.setSizes([450, 990])
        self.main_splitter.setStretchFactor(0, 0) # List stays fixed if possible
        self.main_splitter.setStretchFactor(1, 1) # Video takes all extra space
        
        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.addWidget(self.main_splitter)
        self.v_splitter.addWidget(self.create_bottom_panel())
        self.v_splitter.setSizes([600, 240])
        self.v_splitter.setStretchFactor(0, 1) # List and video shrink/grow
        self.v_splitter.setStretchFactor(1, 0) # Timeline height is stable
        
        workspace_layout.addWidget(self.v_splitter, 1)
        main_layout.addLayout(workspace_layout)
        
        # Khởi tạo thanh trạng thái
        self.statusBar().showMessage("Đã sẵn sàng")
        
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        if initial_video_path and os.path.exists(initial_video_path):
            self.load_video(path=initial_video_path)
        if initial_srt_path and os.path.exists(initial_srt_path):
            self.load_srt_file(path=initial_srt_path)
        
        self.save_state_for_undo()
        self.has_unsaved_changes = False
    
    def _check_memory_usage(self):
        """Kiểm tra sử dụng memory và giải phóng nếu cần."""
        try:
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > self.memory_threshold:
                # Giải phóng frame cache
                self._clear_frame_cache()
                gc.collect()
                # KHÔNG dùng time.sleep() vì block UI thread - chỉ set cờ
                return True
        except Exception as e:
            print(f"Lỗi khi kiểm tra memory: {e}")
        return False
    
    def _clear_frame_cache(self):
        """Giải phóng frame cache để tiết kiệm memory."""
        if len(self.frame_cache) > self.cache_size_limit:
            # Xóa một nửa cache cũ nhất
            keys_to_remove = list(self.frame_cache.keys())[:len(self.frame_cache)//2]
            for key in keys_to_remove:
                del self.frame_cache[key]
    
    def _get_cached_frame(self, frame_number):
        """Lấy frame từ cache hoặc load mới."""
        if frame_number in self.frame_cache:
            return self.frame_cache[frame_number]
        
        if self.video_capture and self.video_capture.isOpened():
            self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = self.video_capture.read()
            if ret:
                # Cache frame nếu cache chưa đầy
                if len(self.frame_cache) < self.cache_size_limit:
                    self.frame_cache[frame_number] = frame.copy()
                return frame
        
        return None

    def mark_change(self):
        """Tối ưu hóa: Invalidate cache khi có thay đổi."""
        self.has_unsaved_changes = True
        self._invalidate_cache()
    
    def _invalidate_cache(self):
        """Invalidate cache khi có thay đổi."""
        self._cache_invalid = True
        self._start_times_cache = None
        self._last_found_sub = None  # Reset temporal cache vì thứ tự có thể đổi
        self._reading_speed_cache_invalid = True

    def save_state_for_undo(self):
        try:
            current_state = copy.deepcopy(self.subtitle_tracks)
            if not self.undo_stack or self.undo_stack[-1] != current_state:
                self.undo_stack.append(current_state)
                if len(self.undo_stack) > self.max_undo_steps:
                    self.undo_stack.pop(0)
                self.redo_stack.clear()
        except Exception as e:
            print(f"Lỗi khi lưu trạng thái undo: {e}")
    
    def undo(self):
        if len(self.undo_stack) > 1:
            current_state = self.undo_stack.pop()
            self.redo_stack.append(current_state)
            previous_state = self.undo_stack[-1]
            self.subtitle_tracks = copy.deepcopy(previous_state)
            self.timeline.selected_sub = None
            self._invalidate_cache()
            self.update_all_views(reorganize=False)
            print("Đã hoàn tác")
    
    def redo(self):
        if self.redo_stack:
            next_state = self.redo_stack.pop()
            self.undo_stack.append(next_state)
            self.subtitle_tracks = copy.deepcopy(next_state)
            self.timeline.selected_sub = None
            self._invalidate_cache()
            self.update_all_views(reorganize=False)
            print("Đã làm lại")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play_pause()
            event.accept()
        elif event.key() == Qt.Key.Key_S and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            focused = QApplication.focusWidget()
            # Không chặn ký tự "s" khi người dùng đang gõ trong ô nhập liệu.
            if not isinstance(focused, (QTextEdit, QLineEdit)) and hasattr(self, 'btn_hover_scrub'):
                self.btn_hover_scrub.toggle()
                event.accept()
                return
            super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_A and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            focused = QApplication.focusWidget()
            # Không chặn ký tự "a" khi người dùng đang gõ trong ô nhập liệu.
            if not isinstance(focused, (QTextEdit, QLineEdit)):
                # Dùng chung logic với nút "Thêm" để tránh lệch hành vi:
                # nếu track hiện tại không đủ chỗ ở playhead thì chuyển sang track khác.
                self.add_subtitle()
                event.accept()
                return
            super().keyPressEvent(event)
        elif event.key() == Qt.Key.Key_Backspace:
            # Nhấn Backspace để xóa phụ đề đang chọn (nhanh, không cần xác nhận)
            if self.timeline.selected_sub:
                self.delete_subtitle_quick()
            event.accept()
        elif event.key() == Qt.Key.Key_F3:
            # F3: Tìm tiếp theo, Shift+F3: Tìm trước đó
            if event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                self.find_previous()
            else:
                self.find_next()
            event.accept()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo(); event.accept()
            elif event.key() == Qt.Key.Key_Y:
                self.redo(); event.accept()
            elif event.key() == Qt.Key.Key_S:
                # Ctrl+S: Lưu phụ đề (chế độ im lặng, hiện status bar)
                self.save_to_temp_file(silent=True)
                event.accept()
            elif event.key() == Qt.Key.Key_F:
                # Ctrl+F: Focus vào ô tìm kiếm
                self.search_input.setFocus()
                self.search_input.selectAll()
                event.accept()
            elif event.key() == Qt.Key.Key_H:
                # Ctrl+H: Mở hộp thoại Tìm kiếm & Thay thế
                self.show_find_replace_dialog()
                event.accept()
        else:
            super().keyPressEvent(event)

    def _find_system_font(self):
        font_paths = {
            "win32": ["C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/simsunb.ttf", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"],
            "darwin": ["/System/Library/Fonts/Supplemental/SimSun.ttf", "/System/Library/Fonts/PingFang.ttc"],
            "linux": ["/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc"]
        }
        fallback_fonts = ["C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Helvetica.dfont", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        os_fonts = font_paths.get(sys.platform, []) + fallback_fonts
        for path in os_fonts:
            if os.path.exists(path):
                print(f"Sử dụng font: {path}")
                return path
        print("Cảnh báo: Không tìm thấy font hệ thống phù hợp. Phụ đề có thể hiển thị lỗi.")
        return None

    def create_header_bar(self):
        header = QWidget(); header.setObjectName("Header"); header.setFixedHeight(50)
        layout = QHBoxLayout(header); layout.setContentsMargins(15, 0, 15, 0)
        title = QLabel("TRÌNH CHỈNH SỬA PHỤ ĐỀ CHUYÊN NGHIỆP - MULTI TRACK"); title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))

        self.btn_import_video = QPushButton("Thêm Video")
        self.btn_import_video.setToolTip("Mở video ngoài để chỉnh sửa trực tiếp")
        self.btn_import_video.clicked.connect(self.import_video_file)

        self.btn_import_srt = QPushButton("Thêm SRT")
        self.btn_import_srt.setToolTip("Mở file phụ đề SRT ngoài để chỉnh sửa trực tiếp")
        self.btn_import_srt.clicked.connect(self.import_srt_file)

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.btn_import_video)
        layout.addWidget(self.btn_import_srt)
        return header

    def import_video_file(self):
        """Mở hộp thoại để import video ngoài vào editor."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file video",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.ts *.mpeg *.mpg);;All Files (*)"
        )
        if not path:
            return

        if self.load_video(path=path):
            self.statusBar().showMessage(f"🎬 Đã mở video: {os.path.basename(path)}", 4000)

    def import_srt_file(self):
        """Mở hộp thoại để import SRT ngoài vào editor."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file phụ đề SRT",
            "",
            "Subtitle Files (*.srt);;All Files (*)"
        )
        if not path:
            return

        try:
            if self.load_srt_file(path=path):
                self.statusBar().showMessage(f"📝 Đã mở phụ đề: {os.path.basename(path)}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể import SRT:\n{e}")

    def _open_srt_with_fallback_encodings(self, path):
        """Đọc SRT với fallback encoding để tránh lỗi/crash khi file không phải UTF-8."""
        encodings = [
            "utf-8-sig",
            "utf-8",
            "utf-16",
            "utf-16-le",
            "utf-16-be",
            "cp1258",
            "cp1252",
            "latin-1",
        ]

        last_error = None
        for enc in encodings:
            try:
                subs = pysrt.open(path, encoding=enc)
                return subs, enc
            except Exception as e:
                last_error = e

        if last_error:
            raise last_error
        raise ValueError("Không thể đọc file SRT.")

    def create_left_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        panel.setMinimumWidth(200) # Chiều ngang tối thiểu hợp lý cho danh sách
        
        # Toolbar chính với nút thêm/xóa
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(10, 5, 10, 5)
        
        btn_add = QPushButton(" ➕ Thêm")
        btn_add.clicked.connect(self.add_subtitle)
        
        btn_del = QPushButton(" 🗑 Xóa")
        btn_del.setProperty("class", "DestructiveButton")
        btn_del.clicked.connect(self.delete_subtitle)
        
        toolbar.addWidget(btn_add)
        toolbar.addWidget(btn_del)
        toolbar.addStretch()
        
        # Thanh tìm kiếm
        search_bar = QHBoxLayout()
        search_bar.setContentsMargins(10, 0, 10, 5)
        search_bar.setSpacing(5)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm kiếm phụ đề...")
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.find_next)
        
        btn_find_prev = QPushButton("◀")
        btn_find_prev.setProperty("class", "SearchButton")
        btn_find_prev.setToolTip("Tìm trước (Shift+F3)")
        btn_find_prev.setFixedWidth(30)
        btn_find_prev.clicked.connect(self.find_previous)
        
        btn_find_next = QPushButton("▶")
        btn_find_next.setProperty("class", "SearchButton")
        btn_find_next.setToolTip("Tìm sau (F3 hoặc Enter)")
        btn_find_next.setFixedWidth(30)
        btn_find_next.clicked.connect(self.find_next)
        
        self.search_label = QLabel("0/0")
        self.search_label.setMinimumWidth(45)
        self.search_label.setObjectName("SearchCountLabel")
        self.search_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        btn_clear_search = QPushButton("✕")
        btn_clear_search.setProperty("class", "SearchButton")
        btn_clear_search.setToolTip("Xóa tìm kiếm")
        btn_clear_search.setFixedWidth(30)
        btn_clear_search.clicked.connect(self.clear_search)
        
        btn_replace = QPushButton("ab→")
        btn_replace.setToolTip("Tìm kiếm & Thay thế hàng loạt (Ctrl+H)")
        btn_replace.setFixedWidth(45)
        btn_replace.setStyleSheet("""
            QPushButton { 
                background-color: #1E3A4A; 
                color: #00E5FF; 
                border: 1px solid #00E5FF; 
                border-radius: 4px; 
                font-weight: bold; 
                font-size: 12px; 
                padding: 4px;
            }
            QPushButton:hover { 
                background-color: #00E5FF; 
                color: #121212; 
            }
        """)
        btn_replace.clicked.connect(self.show_find_replace_dialog)
        
        search_bar.addWidget(self.search_input)
        search_bar.addWidget(btn_find_prev)
        search_bar.addWidget(self.search_label)
        search_bar.addWidget(btn_find_next)
        search_bar.addWidget(btn_clear_search)
        search_bar.addWidget(btn_replace)
        
        self.subtitle_list = QListWidget()
        self.subtitle_list.currentRowChanged.connect(self.select_sub_from_list)
        self.subtitle_list.itemDoubleClicked.connect(self.on_subtitle_double_clicked)
        
        layout.addLayout(toolbar)
        layout.addLayout(search_bar)
        layout.addWidget(self.subtitle_list)
        return panel

    def create_right_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setContentsMargins(0,0,0,0)
        panel.setMinimumWidth(200)
        
        self.video_label = QLabel("Tải video để bắt đầu"); self.video_label.setObjectName("VideoLabel")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # FIX: Chặn QLabel tự tạo minimumSizeHint khổng lồ phụ thuộc vào Pixmap (gây lỗi loop layout window)
        self.video_label.setMinimumSize(1, 1)
        
        # Overlay là child TRỰC TIẾP của video_label để đảm bảo nó luôn nằm trên
        self.subtitle_overlay = SubtitleOverlayWidget(self.video_label)
        self.subtitle_overlay.position_changed.connect(self.on_subtitle_ui_changed)
        
        layout.addWidget(self.video_label, 1); return panel

    def resizeEvent(self, event):
        """Tự động scale lại video khi cửa sổ thay đổi kích thước"""
        super().resizeEvent(event)
        if hasattr(self, 'video_capture') and self.video_capture:
            # Chỉ update nếu không đang chơi để tránh quá tải
            if not self.video_timer.isActive():
                QTimer.singleShot(50, self.update_video_frame_preview)

    def update_video_frame_preview(self):
        """Cập nhật lại toàn bộ khung hình và UI Overlay theo kích thước mới nhất"""
        if not self.video_worker or not self.video_path: return
        current_time = self.current_time
        
        # Lấy kích thước hiện tại của vùng hiển thị
        target_size = self.video_label.size()
        if target_size.width() < 10 or target_size.height() < 10: return
        
        # QUAN TRỌNG: Yêu cầu Video Engine nạp lại frame với kích thước Scale mới
        # Điều này giải quyết triệt để lỗi video bị nhỏ khi phóng to cửa sổ
        is_scrubbing = self.timeline.is_scrubbing or getattr(self.timeline, 'hover_scrub_enabled', False)
        self.video_worker.request_seek(current_time, target_size, is_scrubbing)
        
        # Reset temporal cache để đảm bảo lấy active_sub mới nhất (text có thể đã thay đổi)
        self._last_found_sub = None
        active_sub = self.get_active_subtitle_item(current_time)
        if self.video_label.pixmap():
            self.update_overlay_geometry(self.video_label.pixmap(), target_size, active_sub)

    def on_subtitle_ui_changed(self, x, y, size):
        """Xử lý khi người dùng kéo thả phụ đề trên video, đồng bộ cho TOÀN BỘ phụ đề"""
        # Áp dụng chung một giao diện (kích thước, vị trí) cho tất cả các phụ đề hiện có
        for track in self.subtitle_tracks:
            for sub in track:
                sub.pos_x = x
                sub.pos_y = y
                sub.font_size = size
                
        # Phải set cờ báo hiệu project đã bị chỉnh sửa
        self.has_unsaved_changes = True
        
        # Buộc vẽ lại preview nhanh trên UI (video hiện tại đang tạm dừng)
        if hasattr(self, 'video_timer') and not self.video_timer.isActive():
            self.update_video_frame_preview()

    def filter_and_delete_interjections(self):
        """Lọc và xóa các dòng phụ đề chỉ chứa các từ cảm thán tiếng Trung"""
        # Bộ từ cảm thán mượn từ bản web index.html
        CHINESE_INTERJECTIONS = set("啊哦喔噢呃哎呀哇嘿呸嘘啧哼嗯喂咦哈吼嘻嘛呢吧吗啦哒哟嗷唔咕噜唏嗐咿啵呐呵嘀咯咳")
        
        def is_interjection(text):
            if not text: return False
            # Chỉ lấy các ký tự thuộc bảng chữ cái hoặc chữ Hán
            clean_chars = [c for c in text if c.isalpha() or '\u4e00' <= c <= '\u9fff']
            if not clean_chars: return False
            for c in clean_chars:
                if c not in CHINESE_INTERJECTIONS:
                    return False
            return True

        # Sinh danh sách kèm chỉ số STT tĩnh dựa trên thứ tự timeline
        all_subs = self._get_sorted_subs()
        interjection_subs_with_stt = []
        for i, sub in enumerate(all_subs):
            if is_interjection(sub.text):
                interjection_subs_with_stt.append((sub, i))
                
        if not interjection_subs_with_stt:
            QMessageBox.information(self, "Thông báo", "Tuyệt vời, không tìm thấy khối cảm thán rác tiếng Trung nào trong phụ đề!")
            return
            
        dialog = DeleteInterjectionsDialog(self, interjection_subs_with_stt)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_to_delete = dialog.get_selected_subs()
            if not selected_to_delete:
                return
                
            self.save_state_for_undo() # Backup state
            for track in self.subtitle_tracks:
                for sub in selected_to_delete:
                    if sub in track:
                        track.remove(sub)
            
            if self.timeline.selected_sub in selected_to_delete:
                self.timeline.selected_sub = None
                
            self.has_unsaved_changes = True
            self._invalidate_cache()
            self.update_all_views(reorganize=False, immediate=True)
            self.clear_search() # Làm mới lại search view
            QMessageBox.information(self, "Thành công", f"Đã hô biến {len(selected_to_delete)} dòng phụ đề cảm thán!")

    def filter_ocr_errors(self):
        """Lọc trực tiếp các dòng phụ đề chứa ký tự Latinh hoặc ký tự lạ do lỗi OCR."""
        all_subs = self._get_sorted_subs()
        # Snapshot danh sách lỗi OCR tại thời điểm bật filter để các dòng đã sửa không biến mất ngay.
        self._ocr_filter_snapshot_ids = {id(sub) for sub in all_subs if self._is_ocr_error_text(sub.text)}
        self.search_results = self._get_ocr_filter_live_results(all_subs)
                
        if self.search_results:
            self.is_ocr_filter_active = True
            self.is_speed_filter_active = False
            self.is_duplicate_filter_active = False
            # ... ô tìm kiếm ...
            self.search_input.blockSignals(True)
            self.search_input.setText("[Chế độ lọc: Lỗi OCR]")
            self.search_input.blockSignals(False)
            
            # Highlight: ký tự lạ, khối chỉ có số, hoặc khối chỉ có dấu câu
            self._apply_search_highlight(OCR_HIGHLIGHT_REGEX, is_regex=True)
            
            # Hiển thị snapshot ban đầu; các dòng đã sửa sẽ vẫn còn thấy trong danh sách.
            display_results = self._get_ocr_filter_snapshot_results(all_subs)
            for i in range(self.subtitle_list.count()):
                item = self.subtitle_list.item(i)
                if item:
                    item.setHidden(i not in display_results)
            self._update_ocr_filter_row_styles(all_subs)
            self.current_search_index = 0
            self.highlight_current_search_result()
            self.statusBar().showMessage(
                f"🔍 Tìm thấy {len(self.search_results)} lỗi OCR, giữ {len(display_results)} dòng trong danh sách.",
                5000
            )
        else:
            self.statusBar().showMessage("✅ Không phát hiện lỗi OCR trong danh sách phụ đề.", 5000)
            self.clear_search_results()

    def filter_reading_speed_issues(self):
        """Lọc các khối phụ đề có tốc độ đọc nhỏ hơn ngưỡng 3 ký tự/giây (thiếu ký tự do OCR)."""
        self._ocr_filter_snapshot_ids = None
        self._ensure_reading_speed_issue_cache()
        self.search_results = list(self._reading_speed_issue_rows)

        if self.search_results:
            self.is_speed_filter_active = True
            self.is_ocr_filter_active = False
            self.is_duplicate_filter_active = False

            self.search_input.blockSignals(True)
            self.search_input.setText(f"[Chế độ lọc: Tốc độ đọc < 3 ký tự/s]")
            self.search_input.blockSignals(False)

            self._apply_search_highlight("")
            self._update_ocr_filter_row_styles()

            for i in range(self.subtitle_list.count()):
                item = self.subtitle_list.item(i)
                if item:
                    item.setHidden(i not in self.search_results)

            self.current_search_index = 0
            self.highlight_current_search_result()
            self.statusBar().showMessage(
                f"⚠️ Tìm thấy {len(self.search_results)} khối phụ đề có tốc độ < 3 ký tự/s.",
                6000
            )
        else:
            self.statusBar().showMessage(
                f"✅ Không có khối phụ đề có tốc độ < 3 ký tự/s.",
                5000
            )
            self.clear_search_results()

    def filter_adjacent_duplicate_subtitles(self):
        """Lọc các dòng phụ đề liền kề có nội dung trùng nhau."""
        self._ocr_filter_snapshot_ids = None
        all_subs = self._get_sorted_subs()
        self.search_results = self._get_adjacent_duplicate_rows(all_subs)

        if self.search_results:
            self.is_duplicate_filter_active = True
            self.is_ocr_filter_active = False
            self.is_speed_filter_active = False

            self.search_input.blockSignals(True)
            self.search_input.setText("[Chế độ lọc: Trùng lặp liền kề]")
            self.search_input.blockSignals(False)

            self._apply_search_highlight("")
            self._update_ocr_filter_row_styles()

            for i in range(self.subtitle_list.count()):
                item = self.subtitle_list.item(i)
                if item:
                    item.setHidden(i not in self.search_results)

            self.current_search_index = 0
            self.highlight_current_search_result()
            self.statusBar().showMessage(
                f"🔁 Tìm thấy {len(self.search_results)} dòng nằm trong các cặp trùng lặp liền kề.",
                6000
            )
        else:
            self.statusBar().showMessage("✅ Không phát hiện phụ đề liền kề bị trùng.", 5000)
            self.clear_search_results()

    def get_magnet_snap_icon(self, active=True):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Màu xanh neon khi bật, màu xám khi tắt
        color = QColor("#121212") if active else QColor("#AAAAAA")
        painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        
        # Vẽ hình nam châm chữ U đơn giản
        path = QPainterPath()
        path.moveTo(6, 8)
        path.lineTo(6, 14)
        path.arcTo(6, 10, 12, 10, 180, 180) # Đáy cong
        path.lineTo(18, 8)
        
        painter.drawPath(path)
        painter.end()
        return QIcon(pixmap)

    def toggle_magnet_snap(self):
        enabled = not self.timeline.magnet_snap_enabled
        self.timeline.magnet_snap_enabled = enabled
        self.btn_magnet_snap.setIcon(self.get_magnet_snap_icon(active=enabled))
        
        # Tip hiển thị
        if enabled:
            self.btn_magnet_snap.setStyleSheet("background-color: #00E5FF; border-radius: 4px; padding: 4px;")
            self.btn_magnet_snap.setToolTip("Bật/Tắt Hút Playhead (Magnet): BẬT")
        else:
            self.btn_magnet_snap.setStyleSheet("padding: 4px;")
            self.btn_magnet_snap.setToolTip("Bật/Tắt Hút Playhead (Magnet): TẮT")

    def get_hover_scrub_icon(self, active=False):
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Màu xám nhạt khi tắt, màu đen khi bật (vì nền nút xanh)
        color = QColor("#121212") if active else QColor("#AAAAAA")
        
        # Vẽ thanh dọc Playhead
        painter.setPen(QPen(color, 2))
        painter.drawLine(10, 4, 10, 20)
        
        # Vẽ khung ngoặc vuông (bracket) bên trái
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF([QPointF(8, 8), QPointF(4, 8), QPointF(4, 16), QPointF(8, 16)]))
        
        # Vẽ con trỏ chuột bên phải
        path = QPainterPath()
        path.moveTo(14, 10)
        path.lineTo(14, 20)
        path.lineTo(16, 17)
        path.lineTo(19, 21)
        path.lineTo(21, 20)
        path.lineTo(18, 16)
        path.lineTo(22, 16)
        path.closeSubpath()
        
        # Chuột trắng viền màu color
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(QPen(color, 1))
        painter.drawPath(path)
        
        painter.end()
        return QIcon(pixmap)

    def toggle_hover_scrub(self, checked):
        """Xử lý bật tắt dính playhead vào chuột"""
        if hasattr(self, 'timeline'):
            self.timeline.hover_scrub_enabled = checked
            if checked:
                self.btn_hover_scrub.setIcon(self.get_hover_scrub_icon(active=True))
                self.btn_hover_scrub.setStyleSheet("background-color: #00E5FF; border-radius: 4px; padding: 4px;")
            else:
                self.btn_hover_scrub.setIcon(self.get_hover_scrub_icon(active=False))
                self.btn_hover_scrub.setStyleSheet("padding: 4px;")
                # Giữ playhead tại vị trí chuột hiện tại khi tắt hover-scrub,
                # tránh bị nhảy ngược về thời điểm cũ.
                locked_time = self.timeline.current_time
                self.current_time = locked_time
                if hasattr(self, 'video_worker') and self.video_worker:
                    self.seek_video(locked_time, force=True)

    def _on_timeline_hscroll_changed(self, _value):
        """Giữ playhead dính theo chuột khi cuộn ngang timeline (vd: Alt + wheel)."""
        if not (hasattr(self, 'timeline') and hasattr(self, 'timeline_scroll')):
            return
        if not getattr(self.timeline, 'hover_scrub_enabled', False):
            return

        # Tránh can thiệp khi đang tương tác kéo/resize trong timeline
        if getattr(self.timeline, 'dragging_sub', None) or getattr(self.timeline, 'resizing_sub', None):
            return
        if getattr(self.timeline, 'is_scrubbing', False):
            return
        if bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            return

        # Chỉ sync khi con trỏ đang ở trên viewport timeline (không phải scrollbar)
        if not self.timeline_scroll.viewport().underMouse():
            return

        pos = self.timeline.mapFromGlobal(QCursor.pos())
        if not self.timeline.rect().contains(pos):
            return

        self.timeline.handle_scrub(pos)

    def create_bottom_panel(self):
        panel = QWidget(); panel.setMinimumHeight(240)  # Tăng chiều cao tối thiểu để hiển thị đầy đủ 3 track
        layout = QVBoxLayout(panel); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        control_bar = QHBoxLayout(); control_bar.setContentsMargins(0, 5, 0, 5)

        self.btn_save = QPushButton("Lưu"); self.btn_save.clicked.connect(self.save_to_temp_file)
        self.btn_exit = QPushButton("Thoát"); self.btn_exit.clicked.connect(self.close)
        
        self.btn_del_interjection = QPushButton("Xóa Cảm Thán")
        self.btn_del_interjection.setToolTip("Xóa nhanh các phụ đề rác chỉ chứa từ cảm thán (Ví dụ: ừm, à, ồ,...)")
        self.btn_del_interjection.clicked.connect(self.filter_and_delete_interjections)
        
        self.btn_filter_ocr = QPushButton("Lọc Lỗi OCR")
        self.btn_filter_ocr.setToolTip("Lọc trực tiếp các dòng phụ đề chứa ký tự Latinh hoặc ký tự lạ do lỗi OCR.")
        self.btn_filter_ocr.clicked.connect(self.filter_ocr_errors)

        self.btn_filter_speed = QPushButton("Lọc Tốc Đọc")
        self.btn_filter_speed.setToolTip("Lọc các khối phụ đề có tốc độ đọc < 3 ký tự/s (khả năng thiếu ký tự do OCR).")
        self.btn_filter_speed.clicked.connect(self.filter_reading_speed_issues)

        self.btn_filter_duplicate = QPushButton("Trùng Lặp")
        self.btn_filter_duplicate.setToolTip("Tìm các dòng phụ đề liền kề có nội dung trùng nhau.")
        self.btn_filter_duplicate.clicked.connect(self.filter_adjacent_duplicate_subtitles)
        
        self.btn_magnet_snap = QPushButton()
        self.btn_magnet_snap.setFixedSize(30, 30)
        self.btn_magnet_snap.setIcon(self.get_magnet_snap_icon(active=True))
        self.btn_magnet_snap.setToolTip("Bật/Tắt Hút Playhead (Magnet): BẬT")
        self.btn_magnet_snap.setStyleSheet("background-color: #00E5FF; border-radius: 4px; padding: 4px;")
        self.btn_magnet_snap.clicked.connect(self.toggle_magnet_snap)
        
        self.btn_hover_scrub = QPushButton()
        self.btn_hover_scrub.setFixedSize(30, 30) # Gắn size vuông vức
        self.btn_hover_scrub.setIcon(self.get_hover_scrub_icon(active=False))
        self.btn_hover_scrub.setStyleSheet("padding: 4px;")
        self.btn_hover_scrub.setCheckable(True)
        self.btn_hover_scrub.setToolTip("Bật/Tắt dính Playhead vào chuột (Hover Scrub)")
        self.btn_hover_scrub.toggled.connect(self.toggle_hover_scrub)
        
        self.btn_undo = QPushButton(); self.btn_undo.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)); self.btn_undo.setToolTip("Hoàn tác (Ctrl+Z)"); self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton(); self.btn_redo.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)); self.btn_redo.setToolTip("Làm lại (Ctrl+Y)"); self.btn_redo.clicked.connect(self.redo)
        self.btn_play_pause = QPushButton(); self.play_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay); self.pause_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        self.btn_play_pause.setIcon(self.play_icon); self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal); self.zoom_slider.setRange(10, 1000); self.zoom_slider.setValue(100); self.zoom_slider.setMaximumWidth(150)
        self.zoom_slider.valueChanged.connect(self.on_zoom_slider_changed)
        
        control_bar.addWidget(self.btn_save); control_bar.addWidget(self.btn_exit); control_bar.addStretch()
        control_bar.addWidget(self.btn_del_interjection)
        control_bar.addWidget(self.btn_filter_ocr)
        control_bar.addWidget(self.btn_filter_speed)
        control_bar.addWidget(self.btn_filter_duplicate)
        control_bar.addWidget(self.btn_undo); control_bar.addWidget(self.btn_redo)
        control_bar.addWidget(self.btn_magnet_snap)
        control_bar.addWidget(self.btn_hover_scrub)
        control_bar.addWidget(QLabel("Zoom:")); control_bar.addWidget(self.zoom_slider); control_bar.addWidget(self.btn_play_pause)
        
        self.timeline = AdvancedTimelineWidget()
        self.timeline.time_changed.connect(self.seek_video); self.timeline.data_changed.connect(self.on_timeline_data_changed); self.timeline.zoom_changed.connect(lambda z: self.zoom_slider.setValue(int(z * 100)))
        
        self.timeline_scroll = QScrollArea(); self.timeline_scroll.setWidget(self.timeline); self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn); self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timeline_scroll.horizontalScrollBar().valueChanged.connect(self._on_timeline_hscroll_changed)
        self.timeline_scroll.horizontalScrollBar().setSingleStep(15)
        
        layout.addLayout(control_bar); layout.addWidget(self.timeline_scroll); return panel
    
    def on_zoom_slider_changed(self, value):
        """Xử lý zoom từ slider với playhead làm trung tâm"""
        new_zoom = value / 100.0
        if hasattr(self, 'timeline_scroll'):
            scroll_area = self.timeline_scroll
            viewport_width = scroll_area.viewport().width()
            
            # Tính vị trí playhead hiện tại
            current_playhead_x = self.timeline.time_to_x(self.timeline.current_time)
            
            # Áp dụng zoom mới
            self.timeline.set_zoom(new_zoom)
            
            # Tính vị trí playhead sau zoom
            new_playhead_x = self.timeline.time_to_x(self.timeline.current_time)
            
            # Đặt scroll để playhead ở trung tâm
            center_offset = viewport_width // 2
            new_scroll_value = max(0, new_playhead_x - center_offset)
            scroll_area.horizontalScrollBar().setValue(int(new_scroll_value))
        else:
            self.timeline.set_zoom(new_zoom)

    def on_timeline_data_changed(self):
        """Đồng bộ hóa toàn bộ ứng dụng khi dữ liệu Timeline thay đổi"""
        self.mark_change()
        # Dùng debounce thay vì immediate để tránh rebuild list liên tục khi kéo thả
        self.update_all_views(reorganize=True, immediate=False)

    def refresh_subtitle_list_timing(self):
        """Tối ưu hóa: Chỉ cập nhật timing labels thay vì rebuild toàn bộ."""
        # Chỉ update visible items để tăng tốc
        visible_rect = self.subtitle_list.viewport().rect()
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            item_rect = self.subtitle_list.visualItemRect(item)
            
            # Chỉ update items visible hoặc gần visible area
            if visible_rect.intersects(item_rect) or \
               abs(item_rect.top() - visible_rect.top()) < visible_rect.height() * 2:
                widget = self.subtitle_list.itemWidget(item)
                if widget and hasattr(widget, 'update_time_label'):
                    widget.update_time_label()

    def _adjust_visible_subtitle_row_heights(self):
        """Chỉ cân lại chiều cao cho các dòng đang hiển thị để giảm lag với file rất lớn."""
        if not hasattr(self, 'subtitle_list'):
            return
        visible_rect = self.subtitle_list.viewport().rect()
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            if not item:
                continue
            item_rect = self.subtitle_list.visualItemRect(item)
            if visible_rect.intersects(item_rect) or abs(item_rect.top() - visible_rect.top()) < visible_rect.height():
                widget = self.subtitle_list.itemWidget(item)
                if widget and hasattr(widget, 'adjust_height'):
                    widget.adjust_height()

    def _organize_subtitles_into_tracks(self, flat_subtitle_list):
        # Với 3 track cố định, đặt tất cả vào track chính (giữa - index 1)
        if not flat_subtitle_list: return [[], [], []]
        sorted_subs = sorted(flat_subtitle_list, key=lambda s: s.start_time)
        tracks = [[], [], []]
        
        # Đặt tất cả vào track chính (index 1) khi load file
        tracks[1] = sorted_subs
        return tracks

    def update_all_views(self, reorganize=False, immediate=False):
        """Tối ưu hóa: Sử dụng debouncing để tránh update quá nhiều lần.
        
        Args:
            reorganize: Có cần sắp xếp lại subtitles vào tracks không
            immediate: Bỏ qua debouncing và update ngay lập tức (dùng khi load file)
        """
        # Đảm bảo luôn có đúng 3 track
        while len(self.subtitle_tracks) < 3:
            self.subtitle_tracks.append([])
        self.subtitle_tracks = self.subtitle_tracks[:3]  # Giới hạn chỉ 3 track
        
        # Lưu trạng thái reorganize
        if reorganize:
            self.pending_update_reorganize = True
        
        # Nếu immediate=True, update ngay lập tức
        if immediate:
            if self.update_timer.isActive():
                self.update_timer.stop()
            self._perform_delayed_update()
        else:
            # Debounce update: chỉ update sau 150ms không có thay đổi mới (tăng để giảm tải khi kéo thả)
            if self.update_timer.isActive():
                self.update_timer.stop()
            self.update_timer.start(150)
    
    def _perform_delayed_update(self):
        """Thực hiện update thực tế sau khi debounce."""
        # KHÔNG tự ý gọi _organize_subtitles_into_tracks ở đây vì nó sẽ xóa sạch phân chia track hiện tại.
        # reorganization ở đây chỉ nên hiểu là làm mới (re-populate) danh sách hiển thị bên trái.
        
        self.populate_subtitle_list_optimized()
        self.timeline.set_data(self.subtitle_tracks, self.video_duration)
        self._ensure_reading_speed_issue_cache()
        self.pending_update_reorganize = False
        # KHÔNG gọi QApplication.processEvents() ở đây - gây re-entrant update loop

    def populate_subtitle_list(self):
        """Legacy method - redirect to optimized version."""
        self.populate_subtitle_list_optimized()
    
    def populate_subtitle_list_optimized(self):
        """Tối ưu hóa: Chỉ update các items thay đổi thay vì rebuild toàn bộ."""
        if self.is_updating_list:
            return  # Tránh recursive updates
        
        self.is_updating_list = True
        self.subtitle_list.blockSignals(True)
        self.subtitle_list.setUpdatesEnabled(False)
        
        # Lưu lại vị trí thanh cuộn hiện tại
        old_scroll_pos = self.subtitle_list.verticalScrollBar().value()
        
        # Sử dụng cached sorted list
        all_subs = self._get_sorted_subs()
        current_count = self.subtitle_list.count()
        
        # Tối ưu: Nếu số lượng subtitle thay đổi nhiều, rebuild toàn bộ
        # Ngược lại, chỉ update items đã thay đổi
        if abs(len(all_subs) - current_count) > 20 or current_count == 0:
            # Rebuild toàn bộ khi thay đổi lớn
            self.subtitle_list.clear()
            self.subtitle_widgets_cache.clear()
            selected_row = -1
            is_large_rebuild = len(all_subs) >= self.large_list_mode_threshold
            batch_size = max(20, self.large_list_batch_size)
            
            # Batch add items để tăng tốc
            for i, sub_item_data in enumerate(all_subs):
                widget = SubtitleListItemWidget(
                    sub_item_data,
                    i + 1,
                    schedule_initial_adjust=not is_large_rebuild
                )
                widget.text_changed_signal.connect(self.on_subtitle_text_modified)
                widget.delete_signal.connect(self.delete_specific_subtitle)
                widget.add_signal.connect(self.add_subtitle_after)
                self.subtitle_widgets_cache[id(sub_item_data)] = widget
                
                list_item = QListWidgetItem(self.subtitle_list)
                widget.list_item = list_item
                list_item.setSizeHint(widget.sizeHint())
                self.subtitle_list.addItem(list_item)
                self.subtitle_list.setItemWidget(list_item, widget)
                
                if sub_item_data == self.timeline.selected_sub:
                    selected_row = i

                if is_large_rebuild and (i + 1) % batch_size == 0:
                    self.statusBar().showMessage(f"⏳ Đang dựng danh sách phụ đề: {i + 1}/{len(all_subs)}", 0)
                    QApplication.processEvents()

            if is_large_rebuild:
                self.statusBar().showMessage(f"✅ Đã dựng xong danh sách {len(all_subs)} dòng phụ đề.", 3000)
                QTimer.singleShot(0, self._adjust_visible_subtitle_row_heights)
            
            # Chỉ scroll nếu cần
            if selected_row >= 0:
                self.subtitle_list.setCurrentRow(selected_row)
                if self.subtitle_list.item(selected_row):
                    self.subtitle_list.scrollToItem(
                        self.subtitle_list.item(selected_row), 
                        QListWidget.ScrollHint.PositionAtCenter
                    )
        else:
            # Update incremental cho thay đổi nhỏ
            selected_row = -1
            for i in range(min(len(all_subs), current_count)):
                sub_item_data = all_subs[i]
                list_item = self.subtitle_list.item(i)
                widget = self.subtitle_list.itemWidget(list_item)
                
                # Chỉ update nếu data thay đổi
                if widget and widget.item_data != sub_item_data:
                    widget.item_data = sub_item_data
                    widget.text_edit.blockSignals(True)
                    widget.text_edit.setPlainText(sub_item_data.text)
                    widget.text_edit.blockSignals(False)
                    widget.id_label.setText(f"{i+1}")
                
                if sub_item_data == self.timeline.selected_sub:
                    selected_row = i
            
            # Thêm items mới nếu cần
            if len(all_subs) > current_count:
                for i in range(current_count, len(all_subs)):
                    sub_item_data = all_subs[i]
                    widget = SubtitleListItemWidget(sub_item_data, i + 1)
                    widget.text_changed_signal.connect(self.on_subtitle_text_modified)
                    widget.delete_signal.connect(self.delete_specific_subtitle)
                    widget.add_signal.connect(self.add_subtitle_after)
                    
                    list_item = QListWidgetItem(self.subtitle_list)
                    widget.list_item = list_item
                    list_item.setSizeHint(widget.sizeHint())
                    self.subtitle_list.addItem(list_item)
                    self.subtitle_list.setItemWidget(list_item, widget)
                    
                    if sub_item_data == self.timeline.selected_sub:
                        selected_row = i
            
            # Xóa items thừa nếu cần
            elif len(all_subs) < current_count:
                for i in range(len(all_subs), current_count):
                    self.subtitle_list.takeItem(len(all_subs))
            
            # Update selection
            if selected_row >= 0:
                self.subtitle_list.setCurrentRow(selected_row)
        
        # Cập nhật kết quả tìm kiếm/lọc hiện tại (nếu có)
        self.refresh_search_results()
        
        self.subtitle_list.blockSignals(False)
        self.subtitle_list.setUpdatesEnabled(True)
        
        # Khôi phục vị trí thanh cuộn (Dùng QTimer để đảm bảo Qt đã layout xong)
        if old_scroll_pos > 0:
            QTimer.singleShot(0, lambda: self.subtitle_list.verticalScrollBar().setValue(old_scroll_pos))
            
        self.subtitle_list.viewport().update()
        self.is_updating_list = False
    
    def on_subtitle_text_modified(self):
        """Xử lý khi text subtitle thay đổi - Cập nhật search count và video preview tức thì."""
        # Đánh dấu đã thay đổi nhưng không invalidate sorted cache (text đổi không ảnh hưởng thứ tự time).
        self.has_unsaved_changes = True
        self._reading_speed_cache_invalid = True

        sender = self.sender()
        sender_widget = sender if isinstance(sender, SubtitleListItemWidget) else None
        if sender_widget:
            self._refresh_single_ocr_row_after_edit(sender_widget)

        # Debounce để tránh quét lại toàn bộ list theo từng phím bấm.
        if hasattr(self, 'subtitle_text_refresh_timer'):
            self.subtitle_text_refresh_timer.start(120)
        else:
            self.refresh_search_results(auto_navigate=False, update_highlight=not self.is_ocr_filter_active)
        
        # Cập nhật video overlay NGAY LẬP TỨC từ pixmap hiện có (không đợi frame mới từ worker)
        # Đây là cách nhanh nhất: chỉ vẽ lại lớp chữ trên frame đang hiển thị
        if hasattr(self, 'video_label') and self.video_label.pixmap():
            self._last_found_sub = None  # Bắt buộc lấy sub mới nhất
            active_sub = self.get_active_subtitle_item(self.current_time)
            target_size = self.video_label.size()
            self.update_overlay_geometry(self.video_label.pixmap(), target_size, active_sub)
    
    def _get_sorted_subs(self):
        """Tối ưu hóa: Cache sorted subtitles list để tránh sort nhiều lần."""
        if self._cache_invalid or self._sorted_subs_cache is None:
            self._sorted_subs_cache = sorted(
                [sub for track in self.subtitle_tracks for sub in track], 
                key=lambda x: x.start_time
            )
            self._start_times_cache = [s.start_time for s in self._sorted_subs_cache]
            self._cache_invalid = False
        return self._sorted_subs_cache

    def _count_reading_chars(self, text):
        """Đếm số ký tự hữu ích để tính tốc độ đọc (bỏ qua khoảng trắng và dấu câu)."""
        if not text:
            return 0
        normalized = normalize_whitespace(text).replace('\n', ' ')
        return len(self._reading_char_regex.findall(normalized))

    def _is_reading_speed_outlier(self, sub):
        """Trả về True nếu khối phụ đề có tốc độ đọc NHỎ HƠN ngưỡng tối thiểu (ký tự/giây)."""
        char_count = self._count_reading_chars(sub.text)
        if char_count <= 0:
            return False
        duration = max(sub.duration(), 1e-3)
        cps = char_count / duration
        # Chỉ coi khối là lỗi khi tốc độ đọc nhỏ hơn ngưỡng tối thiểu (thiếu ký tự do OCR)
        return cps < self.min_reading_cps

    def _ensure_reading_speed_issue_cache(self):
        """Cập nhật cache các khối vi phạm tốc độ đọc và đẩy marker sang timeline."""
        if self._reading_speed_cache_invalid:
            all_subs = self._get_sorted_subs()
            issue_rows = []
            issue_ids = set()

            for idx, sub in enumerate(all_subs):
                if self._is_reading_speed_outlier(sub):
                    issue_rows.append(idx)
                    issue_ids.add(id(sub))

            self._reading_speed_issue_rows = issue_rows
            self._reading_speed_issue_ids = issue_ids
            self._reading_speed_cache_invalid = False

        if hasattr(self, 'timeline'):
            self.timeline.set_reading_speed_issue_ids(self._reading_speed_issue_ids)

    def _normalize_text_for_duplicate_compare(self, text):
        """Chuẩn hóa text trước khi so sánh trùng lặp liền kề."""
        normalized = normalize_whitespace(text or "")
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized

    def _get_adjacent_duplicate_rows(self, all_subs=None):
        """Trả về index các dòng nằm trong các cặp phụ đề liền kề có text trùng nhau."""
        if all_subs is None:
            all_subs = self._get_sorted_subs()

        duplicate_rows = set()
        prev_text = None
        prev_idx = None

        for idx, sub in enumerate(all_subs):
            current_text = self._normalize_text_for_duplicate_compare(sub.text)
            if current_text and prev_text and current_text == prev_text:
                duplicate_rows.add(prev_idx)
                duplicate_rows.add(idx)
            prev_text = current_text
            prev_idx = idx

        return sorted(duplicate_rows)

    def _is_ocr_error_text(self, text):
        """Trả về True nếu text là lỗi OCR: rỗng, chỉ có số, chỉ có dấu câu, hoặc chứa ký tự lạ."""
        normalized = normalize_whitespace(text or "").strip()
        if not normalized:
            return True

        # Dòng chỉ có số vẫn là lỗi OCR.
        if OCR_DIGITS_ONLY_REGEX.fullmatch(normalized):
            return True

        # Quy tắc OCR cũ: ký tự không thuộc tập cho phép vẫn là lỗi.
        if OCR_INVALID_CHAR_REGEX.search(normalized):
            return True

        # Khối chỉ có dấu câu / ký hiệu, không có chữ hoặc số, cũng là lỗi.
        return OCR_MEANINGFUL_CHAR_REGEX.search(normalized) is None

    def _get_ocr_filter_snapshot_results(self, all_subs=None):
        """Trả về các index hiện còn nằm trong snapshot OCR filter."""
        if all_subs is None:
            all_subs = self._get_sorted_subs()

        snapshot_ids = getattr(self, '_ocr_filter_snapshot_ids', None)
        if snapshot_ids is None:
            return [i for i, sub in enumerate(all_subs) if self._is_ocr_error_text(sub.text)]

        return [i for i, sub in enumerate(all_subs) if id(sub) in snapshot_ids]

    def _get_ocr_filter_live_results(self, all_subs=None):
        """Trả về các index còn đang là lỗi OCR trong snapshot hiện tại."""
        if all_subs is None:
            all_subs = self._get_sorted_subs()

        snapshot_ids = getattr(self, '_ocr_filter_snapshot_ids', None)
        if snapshot_ids is None:
            return [i for i, sub in enumerate(all_subs) if self._is_ocr_error_text(sub.text)]

        return [i for i, sub in enumerate(all_subs) if id(sub) in snapshot_ids and self._is_ocr_error_text(sub.text)]

    def _update_ocr_filter_row_styles(self, all_subs=None):
        """Đổi màu các dòng trong OCR filter: dòng còn lỗi giữ nguyên, dòng đã sửa bị làm mờ."""
        if all_subs is None:
            all_subs = self._get_sorted_subs()

        snapshot_ids = getattr(self, '_ocr_filter_snapshot_ids', None)
        if snapshot_ids is None:
            for i in range(self.subtitle_list.count()):
                item = self.subtitle_list.item(i)
                widget = self.subtitle_list.itemWidget(item)
                if widget and hasattr(widget, 'set_ocr_state'):
                    widget.set_ocr_state("normal")
            return

        for i, sub in enumerate(all_subs):
            item = self.subtitle_list.item(i)
            widget = self.subtitle_list.itemWidget(item) if item else None
            if not widget or not hasattr(widget, 'set_ocr_state'):
                continue

            if id(sub) not in snapshot_ids:
                widget.set_ocr_state("normal")
            elif self._is_ocr_error_text(sub.text):
                widget.set_ocr_state("error")
            else:
                widget.set_ocr_state("fixed")

    def _refresh_single_ocr_row_after_edit(self, widget):
        """Cập nhật nhanh duy nhất dòng đang sửa khi OCR filter đang bật."""
        if not getattr(self, 'is_ocr_filter_active', False):
            return
        if not isinstance(widget, SubtitleListItemWidget):
            return

        snapshot_ids = getattr(self, '_ocr_filter_snapshot_ids', None)
        if snapshot_ids is None:
            return

        sub = getattr(widget, 'item_data', None)
        if sub is None:
            return

        if id(sub) not in snapshot_ids:
            widget.set_ocr_state("normal")
            return

        if self._is_ocr_error_text(sub.text):
            widget.set_ocr_state("error")
        else:
            widget.set_ocr_state("fixed")

        if getattr(widget, 'list_item', None):
            widget.list_item.setHidden(False)
        widget.highlight_search_text(OCR_HIGHLIGHT_REGEX, is_regex=True)

    def _flush_text_edit_updates(self):
        """Gộp các lần sửa text liên tiếp rồi mới refresh lại bộ lọc/tìm kiếm."""
        if not hasattr(self, 'search_input') or not self.search_input.text():
            return
        # Không tự nhảy timeline/video khi người dùng đang gõ để tránh lag cảm nhận.
        self.refresh_search_results(auto_navigate=False, update_highlight=not self.is_ocr_filter_active)
    
    def _apply_search_highlight(self, search_text, is_regex=False):
        """Apply hoặc xóa highlight cho tất cả subtitle widgets."""
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            widget = self.subtitle_list.itemWidget(item)
            if widget and hasattr(widget, 'highlight_search_text'):
                widget.highlight_search_text(search_text, is_regex=is_regex)
    
    def refresh_search_results(self, auto_navigate=True, update_highlight=True):
        """Cập nhật lại kết quả tìm kiếm dựa trên nội dung hiện tại (dùng sau khi xóa/thay đổi phụ đề)."""
        if not hasattr(self, 'search_input') or not self.search_input.text():
            return
            
        all_subs = self._get_sorted_subs()
        display_results = None
        
        if getattr(self, 'is_ocr_filter_active', False):
            display_results = self._get_ocr_filter_snapshot_results(all_subs)
            self.search_results = self._get_ocr_filter_live_results(all_subs)
            if update_highlight:
                self._apply_search_highlight(OCR_HIGHLIGHT_REGEX, is_regex=True)
        elif getattr(self, 'is_speed_filter_active', False):
            self._ensure_reading_speed_issue_cache()
            self.search_results = list(self._reading_speed_issue_rows)
            if update_highlight:
                self._apply_search_highlight("")
        elif getattr(self, 'is_duplicate_filter_active', False):
            self.search_results = self._get_adjacent_duplicate_rows(all_subs)
            if update_highlight:
                self._apply_search_highlight("")
        else:
            # Tìm kiếm văn bản thông thường
            search_text = normalize_whitespace(self.search_input.text().lower())
            self.search_results = [i for i, sub in enumerate(all_subs) if search_text in normalize_whitespace(sub.text.lower())]
            if update_highlight:
                self._apply_search_highlight(self.search_input.text())
            
        # Cập nhật hiển thị ẩn/hiện trong danh sách
        display_result_set = set(display_results) if display_results is not None else None
        search_result_set = set(self.search_results)
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            if item:
                if display_result_set is not None:
                    item.setHidden(i not in display_result_set)
                else:
                    item.setHidden(i not in search_result_set)

        if getattr(self, 'is_ocr_filter_active', False) and update_highlight:
            self._update_ocr_filter_row_styles(all_subs)
                
        # Cập nhật nhãn phân trang (1/5)
        total = len(self.search_results)
        selected_actual_idx = -1
        if total == 0:
            self.current_search_index = -1
            self.search_label.setText("0/0")
        else:
            # ƯU TIÊN: Đồng bộ current_search_index với phụ đề đang chọn (sau khi xóa/thay đổi)
            if self.timeline.selected_sub:
                try:
                    selected_actual_idx = all_subs.index(self.timeline.selected_sub)
                    if selected_actual_idx in self.search_results:
                        self.current_search_index = self.search_results.index(selected_actual_idx)
                except (ValueError, AttributeError):
                    pass
            
            # Đảm bảo index nằm trong dải cho phép
            if self.current_search_index >= total:
                self.current_search_index = total - 1
            if self.current_search_index < 0 and total > 0:
                self.current_search_index = 0
            self.search_label.setText(f"{self.current_search_index + 1}/{total}")
            
        # Tự động nhảy Timeline/Video tới kết quả hiện tại nếu đang ở chế độ lọc
        should_auto_navigate = (
            auto_navigate
            and (
                getattr(self, 'is_ocr_filter_active', False)
                or getattr(self, 'is_speed_filter_active', False)
                or getattr(self, 'is_duplicate_filter_active', False)
            )
            and bool(self.search_results)
        )
        # Nếu người dùng đang chọn 1 khối ngoài tập lọc (ví dụ sửa trực tiếp trên timeline),
        # không ép nhảy ngược về lỗi OCR hiện tại.
        if should_auto_navigate and selected_actual_idx >= 0 and selected_actual_idx not in self.search_results:
            should_auto_navigate = False

        if should_auto_navigate:
            self.highlight_current_search_result()
    
    def _sync_all_widgets_text(self):
        """Đồng bộ sub.text vào QTextEdit của tất cả widget trong danh sách.
        
        Cần gọi sau khi thay đổi sub.text trực tiếp (ví dụ: replace_all)
        để UI hiển thị đúng nội dung mới mà không cần rebuild toàn bộ list.
        Ghi chú: phải gọi _invalidate_cache() trước hàm này.
        """
        # Dùng _get_sorted_subs() để lấy list MỚI NHẤT (cache đã được invalidate trước khi gọi)
        all_subs = self._get_sorted_subs()
        self.subtitle_list.setUpdatesEnabled(False)
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            widget = self.subtitle_list.itemWidget(item)
            if widget and i < len(all_subs):
                sub = all_subs[i]
                current_text = widget.text_edit.toPlainText()
                if current_text != sub.text:
                    widget.text_edit.blockSignals(True)
                    widget.text_edit.setPlainText(sub.text)
                    widget.text_edit.blockSignals(False)
        self.subtitle_list.setUpdatesEnabled(True)
        self.subtitle_list.viewport().update()
    
    def select_sub_from_list(self, row):
        """Tối ưu hóa: Sử dụng cached sorted list, chỉ update 2 widget thay đổi."""
        if row == -1: return
        all_subs = self._get_sorted_subs()
        if row < len(all_subs):
            self.timeline.selected_sub = all_subs[row]
            self.timeline.update()
            # Chỉ update 2 widget cũ/mới thay vì loop toàn bộ list
            old_idx = getattr(self, 'last_selected_idx', -1)
            if old_idx != row:
                if old_idx >= 0:
                    old_item = self.subtitle_list.item(old_idx)
                    if old_item:
                        w = self.subtitle_list.itemWidget(old_item)
                        if w: w.set_selected(False)
                new_item = self.subtitle_list.item(row)
                if new_item:
                    w = self.subtitle_list.itemWidget(new_item)
                    if w: w.set_selected(True)
                self.last_selected_idx = row

            # Khi người dùng chọn dòng từ danh sách, luôn nhảy preview tới thời điểm bắt đầu của phụ đề
            # (bỏ qua throttle khi đang ở chế độ hover-scrub bằng force=True)
            try:
                subtitle = all_subs[row]
                self.seek_video(subtitle.start_time, force=True)
            except Exception:
                pass

            # Cuộn timeline để centrer playhead vào viewport (even khi hover-scrub đang bật)
            try:
                if hasattr(self, 'timeline_scroll') and self.timeline_scroll:
                    playhead_x = self.timeline.time_to_x(all_subs[row].start_time)
                    scroll_area = self.timeline_scroll
                    viewport_width = scroll_area.viewport().width() if scroll_area and scroll_area.viewport() else 0
                    new_scroll_value = max(0, int(playhead_x - viewport_width // 2))
                    scroll_area.horizontalScrollBar().setValue(new_scroll_value)
            except Exception:
                pass
    
    def on_subtitle_double_clicked(self, item):
        """Xử lý double-click vào subtitle trong list - nhảy đến vị trí trên timeline."""
        row = self.subtitle_list.row(item)
        if row == -1:
            return
        
        all_subs = self._get_sorted_subs()
        if row < len(all_subs):
            subtitle = all_subs[row]
            # Nhảy video đến thời điểm bắt đầu của subtitle
            self.seek_video(subtitle.start_time)
            # Chọn subtitle trên timeline
            self.timeline.selected_sub = subtitle
            self.timeline.update()

    def update_selection_in_list(self, sub_to_select):
        """Tối ưu hóa cực độ: Chỉ update những item thực sự thay đổi trạng thái."""
        if not sub_to_select: 
            # Bỏ chọn mục cũ nếu có
            if hasattr(self, 'last_selected_idx') and self.last_selected_idx != -1:
                old_item = self.subtitle_list.item(self.last_selected_idx)
                if old_item:
                    widget = self.subtitle_list.itemWidget(old_item)
                    if widget: widget.set_selected(False)
                self.last_selected_idx = -1
            return

        all_subs = self._get_sorted_subs()
        try:
            index = all_subs.index(sub_to_select)
            
            # Nếu mục chọn không thay đổi thì không làm gì cả để tiết kiệm CPU
            if hasattr(self, 'last_selected_idx') and self.last_selected_idx == index:
                return

            self.subtitle_list.blockSignals(True)
            self.subtitle_list.setCurrentRow(index)
            
            # 1. Tắt highlight của mục cũ
            if hasattr(self, 'last_selected_idx') and self.last_selected_idx != -1:
                old_item = self.subtitle_list.item(self.last_selected_idx)
                if old_item:
                    widget = self.subtitle_list.itemWidget(old_item)
                    if widget: widget.set_selected(False)
            
            # 2. Bật highlight cho mục mới
            new_item = self.subtitle_list.item(index)
            if new_item:
                widget = self.subtitle_list.itemWidget(new_item)
                if widget: widget.set_selected(True)
            
            self.last_selected_idx = index
            self.subtitle_list.blockSignals(False)
            
            # Kiểm tra xem item có đang visible không để tự động cuộn (Auto-scroll)
            if new_item:
                visible_rect = self.subtitle_list.viewport().rect()
                item_rect = self.subtitle_list.visualItemRect(new_item)
                if not visible_rect.intersects(item_rect):
                    self.subtitle_list.scrollToItem(new_item, QListWidget.ScrollHint.PositionAtCenter)
        except ValueError: pass 
        except Exception: pass
    def add_subtitle(self):
        self.mark_change()
        current_time = self.timeline.current_time
        min_duration = 0.5
        
        # Hàm kiểm tra xem có thể đặt phụ đề trong track không
        def can_place_subtitle_at_time(track, start_time, end_time):
            for sub in track:
                if not (end_time <= sub.start_time or start_time >= sub.end_time):
                    return False
            return True
        
        # Hàm tìm khoảng trống trong track từ thời điểm hiện tại
        def find_available_space_from_time(track, from_time):
            # Tìm phụ đề đầu tiên sau thời điểm hiện tại
            next_sub_start = self.video_duration  # Mặc định là cuối video
            for sub in track:
                if sub.start_time > from_time:
                    next_sub_start = min(next_sub_start, sub.start_time)
            
            return next_sub_start - from_time
        
        # Thử đặt vào track chính (index 1) trước
        main_track = self.subtitle_tracks[1]
        available_space_main = find_available_space_from_time(main_track, current_time)
        
        if available_space_main >= min_duration:
            # Đủ chỗ ở track chính
            duration = min(available_space_main, 3.0)  # Tối đa 3 giây
            new_sub = SubtitleItem(current_time, current_time + duration, "")
            
            if can_place_subtitle_at_time(main_track, new_sub.start_time, new_sub.end_time):
                self.subtitle_tracks[1].append(new_sub)
                self.subtitle_tracks[1].sort(key=lambda s: s.start_time)
                self.timeline.selected_sub = new_sub
                self.update_all_views(reorganize=False)
                return
        
        # Không đủ chỗ ở track chính, thử track phụ trên (index 0)
        upper_track = self.subtitle_tracks[0]
        available_space_upper = find_available_space_from_time(upper_track, current_time)
        
        if available_space_upper >= min_duration:
            # Đủ chỗ ở track phụ trên, đặt với duration tối thiểu hoặc available space
            duration = min(available_space_upper, max(min_duration, 2.0))  # Tối thiểu 0.5s, tối đa 2s
            new_sub = SubtitleItem(current_time, current_time + duration, "")
            
            if can_place_subtitle_at_time(upper_track, new_sub.start_time, new_sub.end_time):
                self.subtitle_tracks[0].append(new_sub)
                self.subtitle_tracks[0].sort(key=lambda s: s.start_time)
                self.timeline.selected_sub = new_sub
                self.update_all_views(reorganize=False)
                return
        
        # Thử track phụ dưới (index 2)
        lower_track = self.subtitle_tracks[2]
        available_space_lower = find_available_space_from_time(lower_track, current_time)
        
        if available_space_lower >= min_duration:
            # Đủ chỗ ở track phụ dưới
            duration = min(available_space_lower, max(min_duration, 2.0))  # Tối thiểu 0.5s, tối đa 2s
            new_sub = SubtitleItem(current_time, current_time + duration, "")
            
            if can_place_subtitle_at_time(lower_track, new_sub.start_time, new_sub.end_time):
                self.subtitle_tracks[2].append(new_sub)
                self.subtitle_tracks[2].sort(key=lambda s: s.start_time)
                self.timeline.selected_sub = new_sub
                self.update_all_views(reorganize=False)
                # Correct indentation for the return statement
                return
        
        # Nếu tất cả track đều không đủ chỗ tại vị trí playhead
        # Thử tìm vị trí sớm nhất có thể đặt được gần playhead
        best_position = None
        best_track_idx = None
        min_distance = float('inf')
        
        for track_idx in [1, 0, 2]:  # Ưu tiên track chính, sau đó track phụ trên, cuối cùng track phụ dưới
            track = self.subtitle_tracks[track_idx]
            
            # Tìm khoảng trống gần playhead nhất trong track này
            for i in range(len(track) + 1):
                if i == 0:
                    # Trước phụ đề đầu tiên
                    if len(track) > 0:
                        available_end = track[0].start_time
                        available_start = max(0, available_end - 3.0)
                    else:
                        available_start = 0
                        available_end = self.video_duration
                else:
                    # Giữa hai phụ đề hoặc sau phụ đề cuối
                    if i < len(track):
                        available_start = track[i-1].end_time
                        available_end = track[i].start_time
                    else:
                        available_start = track[i-1].end_time
                        available_end = self.video_duration
                
                available_duration = available_end - available_start
                if available_duration >= min_duration:
                    # Tìm vị trí tốt nhất trong khoảng trống này
                    if current_time >= available_start and current_time + min_duration <= available_end:
                        # Playhead nằm trong khoảng trống
                        position = current_time
                    elif current_time < available_start:
                        # Playhead trước khoảng trống
                        position = available_start
                    else:
                        # Playhead sau khoảng trống
                        position = max(available_start, available_end - min_duration)
                    
                    distance = abs(position - current_time)
                    if distance < min_distance:
                        min_distance = distance
                        best_position = position
                        best_track_idx = track_idx
        
        if best_position is not None:
            # Tìm được vị trí phù hợp
            track = self.subtitle_tracks[best_track_idx]
            available_space = find_available_space_from_time(track, best_position)
            duration = min(available_space, max(min_duration, 2.0))
            
            new_sub = SubtitleItem(best_position, best_position + duration, "")
            self.subtitle_tracks[best_track_idx].append(new_sub)
            self.subtitle_tracks[best_track_idx].sort(key=lambda s: s.start_time)
            self.timeline.selected_sub = new_sub
            self.update_all_views(reorganize=False)
            
            # Thông báo vị trí đã thay đổi
            if abs(best_position - current_time) > 0.1:
                QMessageBox.information(self, "Thông báo", 
                    f"Phụ đề mới đã được thêm vào track {['phụ trên', 'chính', 'phụ dưới'][best_track_idx]} "
                    f"tại thời điểm {best_position:.1f}s (gần playhead nhất có thể).")

    def add_subtitle_after_playhead(self):
        """Thêm một khối phụ đề mới ngay sau playhead, ưu tiên track chính trước."""
        if not hasattr(self, 'timeline'):
            return

        self.mark_change()
        current_time = self.timeline.current_time
        min_duration = 0.5
        preferred_duration = 2.0

        def get_track_gaps(track):
            sorted_track = sorted(track, key=lambda s: s.start_time)
            gaps = []
            previous_end = 0.0
            for sub in sorted_track:
                if sub.start_time > previous_end:
                    gaps.append((previous_end, sub.start_time))
                previous_end = max(previous_end, sub.end_time)
            if previous_end < self.video_duration:
                gaps.append((previous_end, self.video_duration))
            return gaps

        def find_slot_after_playhead(track):
            for gap_start, gap_end in get_track_gaps(track):
                if gap_end <= current_time:
                    continue

                start_time = max(current_time, gap_start)
                available = gap_end - start_time
                if available < min_duration:
                    continue

                duration = min(preferred_duration, available)
                end_time = start_time + duration
                if duration >= min_duration:
                    return start_time, end_time

            return None

        for track_idx in [1, 0, 2]:
            slot = find_slot_after_playhead(self.subtitle_tracks[track_idx])
            if not slot:
                continue

            start_time, end_time = slot
            new_sub = SubtitleItem(start_time, end_time, "")
            self.subtitle_tracks[track_idx].append(new_sub)
            self.subtitle_tracks[track_idx].sort(key=lambda s: s.start_time)
            self.timeline.selected_sub = new_sub
            self.update_all_views(reorganize=False, immediate=True)
            self.statusBar().showMessage(
                f"✅ Đã thêm khối sau playhead vào track {['phụ trên', 'chính', 'phụ dưới'][track_idx]}.",
                3000
            )
            return

        QMessageBox.information(
            self,
            "Thông báo",
            "Không tìm thấy khoảng trống phù hợp để thêm khối sau playhead."
        )

    def add_subtitle_after(self, after_sub):
        """Thêm một phụ đề mới ngay sau phụ đề hiện tại"""
        if not after_sub: return
        self.mark_change()
        
        # Tìm track chứa sau_phu_de
        target_track = None
        for track in self.subtitle_tracks:
            if after_sub in track:
                target_track = track
                break
        
        if not target_track: target_track = self.subtitle_tracks[1]
        
        # Tính toán thời gian bắt đầu mới (ngay sau khi kết thúc phụ đề này)
        start_time = after_sub.end_time + 0.1
        
        # Kiểm tra khoảng trống tiếp theo trong cùng track
        next_sub_start = self.video_duration
        for sub in target_track:
            if sub.start_time > after_sub.end_time:
                next_sub_start = sub.start_time
                break
        
        available = next_sub_start - start_time
        if available < 0.2: 
            return
            
        duration = min(2.0, available)
        new_sub = SubtitleItem(start_time, start_time + duration, "")
        target_track.append(new_sub)
        target_track.sort(key=lambda s: s.start_time)
        
        self.timeline.selected_sub = new_sub
        self._invalidate_cache()
        self.update_all_views(reorganize=False)

    def delete_subtitle(self):
        if not self.timeline.selected_sub: QMessageBox.warning(self, "Lưu ý", "Vui lòng chọn một phụ đề để xóa."); return
        reply = QMessageBox.question(self, 'Xác nhận xóa', 'Bạn có chắc muốn xóa phụ đề này?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._delete_subtitle_internal()

    def delete_subtitle_quick(self):
        """Xóa phụ đề nhanh không cần xác nhận - dùng cho phím tắt"""
        if not self.timeline.selected_sub: return
        self.delete_specific_subtitle(self.timeline.selected_sub)

    def delete_specific_subtitle(self, sub_to_delete):
        """Xóa một phụ đề cụ thể (dùng cho nút xóa trên dòng)"""
        if not sub_to_delete: return
        self.mark_change()
        
        # 1. Thu thập thông tin trước khi xóa
        all_subs = self._get_sorted_subs()
        is_searching = len(self.search_results) > 0
        current_global_idx = -1
        current_search_rank = -1
        
        try:
            current_global_idx = all_subs.index(sub_to_delete)
            if is_searching and current_global_idx in self.search_results:
                current_search_rank = self.search_results.index(current_global_idx)
        except ValueError:
            pass
            
        # 2. Thực hiện xóa khỏi track
        for track in self.subtitle_tracks:
            if sub_to_delete in track:
                track.remove(sub_to_delete)
                break

        if getattr(self, '_ocr_filter_snapshot_ids', None) is not None:
            self._ocr_filter_snapshot_ids.discard(id(sub_to_delete))
        
        self._invalidate_cache()
        
        # 3. Xác định phụ đề được chọn tiếp theo
        new_selected_sub = None
        
        if is_searching and current_search_rank >= 0:
            # ƯU TIÊN: Chọn lỗi tiếp theo trong danh sách đã lọc
            
            # Lấy danh sách sau khi xóa
            all_subs_after = self._get_sorted_subs()
            
            # Tái tính toán search_results để tìm item tiếp theo
            if getattr(self, 'is_ocr_filter_active', False):
                new_search_results = self._get_ocr_filter_live_results(all_subs_after)
            elif getattr(self, 'is_speed_filter_active', False):
                new_search_results = [i for i, sub in enumerate(all_subs_after) if self._is_reading_speed_outlier(sub)]
            elif getattr(self, 'is_duplicate_filter_active', False):
                new_search_results = self._get_adjacent_duplicate_rows(all_subs_after)
            else:
                search_text = normalize_whitespace(self.search_input.text().lower())
                new_search_results = [i for i, sub in enumerate(all_subs_after) if search_text in normalize_whitespace(sub.text.lower())]
            
            if new_search_results:
                # Rank mới vẫn là index cũ (vì phần tử cũ đã biến mất, phần tử sau nhảy lên)
                target_rank = min(current_search_rank, len(new_search_results) - 1)
                new_selected_sub = all_subs_after[new_search_results[target_rank]]
                # Cập nhật con trỏ ngay để tránh refresh_search_results bị reset về 0
                self.current_search_index = target_rank
            else:
                self.current_search_index = -1
        else:
            # Logic cũ cho danh sách bình thường
            remaining = self._get_sorted_subs()
            if remaining:
                idx = min(current_global_idx, len(remaining)-1) if current_global_idx >= 0 else 0
                new_selected_sub = remaining[idx]
        
        self.timeline.selected_sub = new_selected_sub
        self.update_all_views(reorganize=False, immediate=True)

    def _delete_subtitle_internal(self):
        """Logic xóa phụ đề chung"""
        self.mark_change()
        sub_to_delete = self.timeline.selected_sub
        if not sub_to_delete: return
        
        # 1. Thu thập thông tin trước khi xóa
        all_subs = self._get_sorted_subs()
        is_searching = len(self.search_results) > 0
        current_global_idx = -1
        current_search_rank = -1
        
        try:
            current_global_idx = all_subs.index(sub_to_delete)
            if is_searching and current_global_idx in self.search_results:
                current_search_rank = self.search_results.index(current_global_idx)
        except ValueError:
            pass
            
        # 2. Xóa phụ đề khỏi track
        for track in self.subtitle_tracks:
            if sub_to_delete in track: 
                track.remove(sub_to_delete)
                break

        if getattr(self, '_ocr_filter_snapshot_ids', None) is not None:
            self._ocr_filter_snapshot_ids.discard(id(sub_to_delete))
        
        # Invalidate cache sau khi xóa
        self._invalidate_cache()
        
        # 3. Xác định phụ đề tiếp theo
        new_selected_sub = None
        
        if is_searching and current_search_rank >= 0:
            # ƯU TIÊN: Chọn lỗi tiếp theo trong danh sách đã lọc
            all_subs_after = self._get_sorted_subs()
            
            if getattr(self, 'is_ocr_filter_active', False):
                new_search_results = self._get_ocr_filter_live_results(all_subs_after)
            elif getattr(self, 'is_speed_filter_active', False):
                new_search_results = [i for i, sub in enumerate(all_subs_after) if self._is_reading_speed_outlier(sub)]
            elif getattr(self, 'is_duplicate_filter_active', False):
                new_search_results = self._get_adjacent_duplicate_rows(all_subs_after)
            else:
                search_text = normalize_whitespace(self.search_input.text().lower())
                new_search_results = [i for i, sub in enumerate(all_subs_after) if search_text in normalize_whitespace(sub.text.lower())]
            
            if new_search_results:
                target_rank = min(current_search_rank, len(new_search_results) - 1)
                new_selected_sub = all_subs_after[new_search_results[target_rank]]
                self.current_search_index = target_rank
            else:
                self.current_search_index = -1
        else:
            # Chế độ bình thường
            remaining_subs = self._get_sorted_subs()
            if remaining_subs:
                idx = min(current_global_idx, len(remaining_subs)-1) if current_global_idx >= 0 else 0
                new_selected_sub = remaining_subs[idx]
        
        self.timeline.selected_sub = new_selected_sub
        self.update_all_views(reorganize=False, immediate=True)

    def load_srt_file(self, path=None):
        """Tối ưu hóa: Load SRT file với progress indicator cho file lớn."""
        if path and os.path.exists(path):
            try:
                # Đọc file SRT
                subs, used_encoding = self._open_srt_with_fallback_encodings(path)
                
                # Hiển thị progress dialog nếu có nhiều subtitles
                total_subs = len(subs)
                progress = None
                
                if total_subs > 100:
                    progress = QProgressDialog(
                        f"Đang tải {total_subs} khối phụ đề...", 
                        "Hủy", 0, total_subs, self
                    )
                    progress.setWindowTitle("Tải phụ đề")
                    progress.setWindowModality(Qt.WindowModality.WindowModal)
                    progress.setMinimumDuration(0)
                    progress.show()
                    QApplication.processEvents()
                
                # Convert sang SubtitleItem với batch processing
                flat_list = []
                batch_size = 50
                
                for i, s in enumerate(subs):
                    flat_list.append(
                        SubtitleItem(s.start.ordinal/1000.0, s.end.ordinal/1000.0, s.text)
                    )
                    
                    # Cập nhật progress và xử lý events mỗi batch
                    if progress and i % batch_size == 0:
                        progress.setValue(i)
                        QApplication.processEvents()
                        
                        if progress.wasCanceled():
                            if progress:
                                progress.close()
                            return False
                
                if progress:
                    progress.setValue(total_subs)
                    QApplication.processEvents()
                
                # Đóng progress dialog trước
                if progress:
                    progress.close()
                    QApplication.processEvents()
                
                # Tổ chức subtitles vào tracks
                self.subtitle_tracks = self._organize_subtitles_into_tracks(flat_list)
                self.timeline.selected_sub = None
                # Invalidate cache để đảm bảo dữ liệu mới được sử dụng
                self._invalidate_cache()
                self.statusBar().showMessage(f"⏳ Đang dựng giao diện cho {total_subs} dòng phụ đề...", 0)
                # Update ngay lập tức để hiển thị danh sách subtitle
                self.update_all_views(reorganize=False, immediate=True)
                # Đảm bảo UI được render ngay
                QApplication.processEvents()
                
                self.undo_stack.clear(); self.redo_stack.clear()
                self.save_state_for_undo()
                self.has_unsaved_changes = False
                self.temp_srt_path = path
                
                # Hiển thị thông báo thành công
                if total_subs > 100:
                    print(f"✅ Đã tải thành công {total_subs} khối phụ đề")
                self.statusBar().showMessage(
                    f"✅ Đã import {total_subs} dòng phụ đề ({used_encoding})",
                    4000
                )
                return True
                    
            except Exception as e: 
                QMessageBox.critical(self, "Lỗi", f"Không thể đọc file SRT: {e}")
                return False
        return False

    def save_to_temp_file(self, silent=False):
        """Tối ưu hóa: Lưu SRT file với progress indicator cho file lớn."""
        # Sử dụng cached sorted list
        all_subs = self._get_sorted_subs()
        if not all_subs: 
            if not silent: QMessageBox.warning(self, "Lưu ý", "Không có phụ đề để lưu.")
            return
        if not self.temp_srt_path: 
            if not silent: QMessageBox.critical(self, "Lỗi", "Không tìm thấy đường dẫn file tạm để lưu.")
            return
        try:
            total_subs = len(all_subs)
            progress = None
            
            if total_subs > 100:
                progress = QProgressDialog(
                    f"Đang lưu {total_subs} khối phụ đề...", 
                    "Hủy", 0, total_subs, self
                )
                progress.setWindowTitle("Lưu phụ đề")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.show()
                QApplication.processEvents()
            
            sub_file = pysrt.SubRipFile()
            batch_size = 50
            
            for i, sub_data in enumerate(all_subs):
                start = pysrt.SubRipTime.from_ordinal(int(sub_data.start_time * 1000))
                end = pysrt.SubRipTime.from_ordinal(int(sub_data.end_time * 1000))
                sub_file.append(pysrt.SubRipItem(i + 1, start, end, sub_data.text))
                
                if progress and i % batch_size == 0:
                    progress.setValue(i)
                    QApplication.processEvents()
                    
                    if progress.wasCanceled():
                        return
            
            if progress:
                progress.setValue(total_subs)
                QApplication.processEvents()
            
            sub_file.save(self.temp_srt_path, encoding='utf-8')
            self.has_unsaved_changes = False
            
            if progress:
                progress.close()
            
            if silent:
                self.statusBar().showMessage(f"✅ Đã lưu {len(all_subs)} phụ đề vào {os.path.basename(self.temp_srt_path)}", 3000)
            else:
                QMessageBox.information(self, "Thành công", f"Đã lưu các thay đổi.")
        except Exception as e: 
            if silent:
                self.statusBar().showMessage(f"❌ Lỗi khi lưu: {e}", 5000)
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể lưu file: {e}")

    def load_video(self, path=None):
        if path and os.path.exists(path):
            if self.video_capture: self.video_capture.release()
            
            # Khởi tạo Video Loader Worker (Luồng ngầm)
            if self.video_worker:
                self.video_worker.stop()
            self.video_worker = VideoLoaderWorker(path)
            self.video_worker.frame_ready.connect(self.on_video_frame_ready)
            self.video_worker.start()

            self.video_capture = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
            self.video_path = path
            fps = self.video_capture.get(cv2.CAP_PROP_FPS); frames = self.video_capture.get(cv2.CAP_PROP_FRAME_COUNT)
            self.video_duration = frames / fps if fps > 0 else 0
            
            self._invalidate_cache()
            self.update_all_views(reorganize=True, immediate=True)
            QApplication.processEvents()
            self.seek_video(0)
            self.undo_stack.clear(); self.redo_stack.clear()
            self.save_state_for_undo()
            self.has_unsaved_changes = False
            return True
        return False

    def _sync_ui_to_time(self, time_sec):
        self.current_time = time_sec # Cập nhật đồng hồ nội bộ
        self.timeline.set_current_time(time_sec)
        
        # Tối ưu hóa: Tìm active_sub bằng phương pháp nhanh
        active_sub = self.get_active_subtitle_item(time_sec)
        current_selected_sub = self.timeline.selected_sub
        preserve_manual_selection = (
            current_selected_sub is not None
            and active_sub is not None
            and current_selected_sub != active_sub
            and (
                getattr(self, 'is_ocr_filter_active', False)
                or getattr(self, 'is_speed_filter_active', False)
                or getattr(self, 'is_duplicate_filter_active', False)
            )
            and not self.video_timer.isActive()
        )

        if not preserve_manual_selection:
            self.auto_scroll_to_playhead(time_sec)

        # Chỉ update selection list khi có phụ đề mới (không re-render khi không có phụ đề)
        if active_sub is not None and current_selected_sub != active_sub:
            if preserve_manual_selection:
                return
            self.timeline.selected_sub = active_sub
            self.update_selection_in_list(active_sub)
            self.timeline.update()
    
    def auto_scroll_to_playhead(self, current_time):
        if not hasattr(self, 'timeline_scroll'): return
        
        # Nếu đang kéo chuột (scrub) hoặc đang bật dính chuột (hover scrub), không tự động cuộn timeline
        if self.timeline.is_scrubbing or getattr(self.timeline, 'hover_scrub_enabled', False):
            return
            
        playhead_x = self.timeline.time_to_x(current_time)
        scroll_area = self.timeline_scroll
        viewport_width = scroll_area.viewport().width()
        scroll_value = scroll_area.horizontalScrollBar().value()
        playhead_relative_x = playhead_x - scroll_value
        buffer = viewport_width * 0.1
        if playhead_relative_x < buffer or playhead_relative_x > viewport_width - buffer:
            new_scroll_value = max(0, playhead_x - viewport_width // 2)
            scroll_area.horizontalScrollBar().setValue(int(new_scroll_value))

    def seek_video(self, time_sec, force=False):
        if not self.video_capture: return
        
        # Throttling: Giới hạn tần suất seek khi đang scrubbing để bảo vệ decoder
        now = time.time()
        is_scrubbing = self.timeline.is_scrubbing or getattr(self.timeline, 'hover_scrub_enabled', False)
        
        if (not force) and is_scrubbing and (now - self.last_seek_time < self.seek_interval):
            # Chỉ cập nhật playhead position - không sync toàn bộ UI để tiết kiệm CPU
            self.current_time = time_sec
            self.timeline.set_current_time(time_sec)

            # Khi đang hover-scrub/scrub nhanh, vẫn cần đồng bộ selection để "khối phụ đề"
            # được chọn đúng theo playhead hiện tại.
            active_sub = self.get_active_subtitle_item(time_sec)
            current_selected_sub = self.timeline.selected_sub
            preserve_manual_selection = (
                current_selected_sub is not None
                and active_sub is not None
                and current_selected_sub != active_sub
                and (
                    getattr(self, 'is_ocr_filter_active', False)
                    or getattr(self, 'is_speed_filter_active', False)
                    or getattr(self, 'is_duplicate_filter_active', False)
                )
                and not self.video_timer.isActive()
            )

            if (not preserve_manual_selection) and active_sub is not None and current_selected_sub != active_sub:
                self.timeline.selected_sub = active_sub
                self.update_selection_in_list(active_sub)
                self.timeline.update()
            return
            
        self.last_seek_time = now
        
        # Đồng bộ hóa UI lập tức (Timeline, Playhead, List)
        self._sync_ui_to_time(time_sec)
        
        # Gửi yêu cầu nạp Video Frame tới luồng ngầm
        if self.video_worker:
            self.video_worker.request_seek(time_sec, self.video_label.size(), False if force else is_scrubbing)
            
    def on_video_frame_ready(self, q_img, time_sec):
        """Slot nhận khung hình từ luồng ngầm và hiển thị lên UI"""
        hover_scrub_enabled = getattr(self.timeline, 'hover_scrub_enabled', False)
        # Khi đang hover-scrub, ưu tiên giữ current_time theo playhead hiện tại
        # để tránh frame callback cũ kéo thời gian lùi lại.
        if hover_scrub_enabled:
            self.current_time = self.timeline.current_time
        else:
            self.current_time = time_sec  # Luôn tin tưởng thời gian thực tế từ Video Engine
        
        # Hiển thị ảnh
        pixmap = QPixmap.fromImage(q_img)
        self.video_label.setPixmap(pixmap)
        
        # Nếu đang Playback (không phải Scrubbing), đồng bộ timeline theo thời gian thực tế của frame
        if not (self.timeline.is_scrubbing or hover_scrub_enabled):
            self._sync_ui_to_time(time_sec)

        # Cập nhật Overlay (Vẽ chữ)
        target_size = self.video_label.size()
        active_sub = self.get_active_subtitle_item(self.current_time)
        self.update_overlay_geometry(pixmap, target_size, active_sub)

    def toggle_play_pause(self):
        if not self.video_capture: return
        if self.video_timer.isActive(): 
            self.video_timer.stop()
            self.btn_play_pause.setIcon(self.play_icon)
        else: 
            # Đảm bảo luồng ngầm seek tới vị trí hiện tại của Playhead trước khi bắt đầu phát tuần tự
            if self.video_worker:
                self.video_worker.request_seek(self.current_time, self.video_label.size(), False)
                
            # Bật timer để yêu cầu khung hình tiếp theo tuần tự
            self.video_timer.start(int(1000 / self.video_capture.get(cv2.CAP_PROP_FPS)))
            self.btn_play_pause.setIcon(self.pause_icon)
    
    def update_frame(self, is_playing=True):
        if not self.video_worker: return
        
        # Yêu cầu luồng ngầm nạp khung hình TIẾP THEO (tuần tự)
        self.video_worker.request_seek(-1, self.video_label.size(), False)
        
        # Kiểm tra kết thúc video dựa trên đồng hồ nội bộ
        if is_playing and self.current_time >= self.video_duration - 0.1:
            self.video_timer.stop()
            self.btn_play_pause.setIcon(self.play_icon)
            self.seek_video(0)

    def update_overlay_geometry(self, pixmap, container_size, active_sub):
        """Tính toán vùng video thực sự hiển thị (không tính black bars) và cập nhật Overlay"""
        pw, ph = pixmap.width(), pixmap.height()
        cw, ch = container_size.width(), container_size.height()
        
        # Resize overlay để khớp với parent label
        self.subtitle_overlay.resize(container_size)
        
        # Vị trí của pixmap (video thực tế) trong label (do AlignmentCenter)
        x_offset = (cw - pw) // 2
        y_offset = (ch - ph) // 2
        
        video_rect = QRect(x_offset, y_offset, pw, ph)
        self.subtitle_overlay.set_active_sub(active_sub, video_rect)
        self.subtitle_overlay.raise_()
        self.subtitle_overlay.show()

    def get_active_subtitle_item(self, current_time):
        """Tối ưu hóa: Tìm phụ đề hiện tại bằng Temporal Cache & Binary Search (O(log N))"""
        # 1. Kiểm tra cache (Temporal Locality) - Cực nhanh khi trượt/phát video
        if hasattr(self, '_last_found_sub') and self._last_found_sub:
            if self._last_found_sub.start_time <= current_time < self._last_found_sub.end_time:
                return self._last_found_sub
        
        # 2. Tìm kiếm nhanh trong danh sách đã sắp xếp
        all_subs = self._get_sorted_subs()
        if not all_subs: return None
        
        # Dùng start_times_cache (đã build sẵn trong _get_sorted_subs) tránh tạo list mới mỗi frame
        times = self._start_times_cache if self._start_times_cache is not None else [s.start_time for s in all_subs]
        idx = bisect.bisect_right(times, current_time) - 1
        
        if idx >= 0:
            sub = all_subs[idx]
            if sub.start_time <= current_time < sub.end_time:
                self._last_found_sub = sub
                return sub
                
        self._last_found_sub = None
        return None

    def draw_text_on_frame(self, frame, sub):
        if not sub: return frame
        text = sub.text
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)); draw = ImageDraw.Draw(pil_img)
        
        # Tối ưu hóa: Cache font để không nạp từ đĩa liên tục
        actual_font_size = int(sub.font_size * (pil_img.size[1] / 1080.0))
        cache_key = (self.font_path, actual_font_size)
        
        if cache_key in self.font_cache:
            font = self.font_cache[cache_key]
        else:
            try:
                font = ImageFont.truetype(self.font_path, size=actual_font_size) if self.font_path else ImageFont.load_default()
                self.font_cache[cache_key] = font
            except Exception:
                font = ImageFont.load_default()
        
        text_bbox = draw.textbbox((0, 0), text, font=font)
        
        # text_bbox = (left, top, right, bottom)
        # Sử dụng pos_x là tâm điểm chính giữa theo chiều ngang, pos_y là mép dưới của chữ
        center_x = pil_img.size[0] * sub.pos_x
        bottom_y = pil_img.size[1] * sub.pos_y
        
        # Tính điểm gốc (x,y) để vẽ text sao cho vị trí thực sự được hiển thị khớp với neo ở trên
        x = center_x - ((text_bbox[2] + text_bbox[0]) / 2)
        y = bottom_y - text_bbox[3]
        
        # Vẽ viền đen (Outline)
        outline_w = max(1, actual_font_size // 20)
        for dx in range(-outline_w, outline_w + 1):
            for dy in range(-outline_w, outline_w + 1):
                if dx*dx + dy*dy <= outline_w*outline_w:
                    draw.text((x + dx, y + dy), text, font=font, fill="black")
                    
        # Vẽ chữ trắng chính
        draw.text((x, y), text, font=font, fill="white")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def on_search_text_changed(self, text):
        """Được gọi khi text trong ô tìm kiếm thay đổi."""
        if not text:
            # Nếu ô tìm kiếm trống hoàn toàn, xóa kết quả tìm kiếm và hiển thị lại tất cả
            self.clear_search_results()
        else:
            # Thực hiện tìm kiếm và lọc danh sách
            self.perform_search(text)
    
    def perform_search(self, search_text):
        """Tìm kiếm, ẩn các dòng không khớp và highlight các dòng khớp."""
        # Khi tìm kiếm thủ công, thoát chế độ lọc lỗi OCR
        self.is_ocr_filter_active = False
        self.is_speed_filter_active = False
        self.is_duplicate_filter_active = False
        self._ocr_filter_snapshot_ids = None
        
        if not search_text:
            return
        
        # Chuẩn hóa search text
        search_text_norm = normalize_whitespace(search_text.lower())
        all_subs = self._get_sorted_subs()
        self.search_results = []
        
        # Lọc danh sách: Ẩn/Hiện tương ứng
        for i, sub in enumerate(all_subs):
            item = self.subtitle_list.item(i)
            if search_text_norm in normalize_whitespace(sub.text.lower()):
                self.search_results.append(i)
                if item: item.setHidden(False)
            else:
                if item: item.setHidden(True)
        
        # Apply highlight cho tất cả các subtitle widgets (dùng text gốc để highlight đúng)
        self._apply_search_highlight(search_text)
        self._update_ocr_filter_row_styles(all_subs)
        
        # Cập nhật label hiển thị số kết quả
        if self.search_results:
            self.current_search_index = 0
            self.highlight_current_search_result()
        else:
            self.current_search_index = -1
            self.search_label.setText("0/0")
    
    def highlight_current_search_result(self):
        """Highlight và scroll đến kết quả tìm kiếm hiện tại."""
        if not self.search_results or self.current_search_index < 0:
            return
        
        # Cập nhật label dạng "current/total" để người dùng biết đang ở kết quả thứ mấy
        total = len(self.search_results)
        self.search_label.setText(f"{self.current_search_index + 1}/{total}")
        
        # Chọn subtitle trong list
        row = self.search_results[self.current_search_index]
        self.subtitle_list.blockSignals(True)
        self.subtitle_list.setCurrentRow(row)
        
        # Scroll đến item
        item = self.subtitle_list.item(row)
        if item:
            self.subtitle_list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
        
        self.subtitle_list.blockSignals(False)
        
        # Cập nhật timeline selection và nhảy video tới đó
        all_subs = self._get_sorted_subs()
        if row < len(all_subs):
            subtitle = all_subs[row]
            self.timeline.selected_sub = subtitle
            self.seek_video(subtitle.start_time, force=True)
            self.timeline.update()
    
    def find_next(self):
        """Tìm kết quả tiếp theo."""
        if not self.search_results:
            return
        
        self.current_search_index = (self.current_search_index + 1) % len(self.search_results)
        self.highlight_current_search_result()
    
    def find_previous(self):
        """Tìm kết quả trước đó."""
        if not self.search_results:
            return
        
        self.current_search_index = (self.current_search_index - 1) % len(self.search_results)
        self.highlight_current_search_result()
    
    def clear_search(self):
        """Xóa nội dung tìm kiếm."""
        self.search_input.clear()
        self.clear_search_results()
    
    def clear_search_results(self):
        """Xóa kết quả, bỏ highlight và hiển thị lại toàn bộ giao diện."""
        self.is_ocr_filter_active = False
        self.is_speed_filter_active = False
        self.is_duplicate_filter_active = False
        self._ocr_filter_snapshot_ids = None
        self.search_results = []
        self.current_search_index = -1
        self.search_label.setText("0/0")
        
        # Xóa highlight
        self._apply_search_highlight("")
        
        # Hiển thị lại toàn bộ dòng trong list widget
        if hasattr(self, 'subtitle_list'):
            for i in range(self.subtitle_list.count()):
                item = self.subtitle_list.item(i)
                if item: item.setHidden(False)
                widget = self.subtitle_list.itemWidget(item) if item else None
                if widget and hasattr(widget, 'set_ocr_state'):
                    widget.set_ocr_state("normal")

    def show_find_replace_dialog(self):
        """Mở hộp thoại Tìm kiếm & Thay thế hàng loạt."""
        # Lấy text đang có trong ô tìm kiếm để tự điền sẵn
        initial_text = self.search_input.text()
        
        dialog = FindReplaceDialog(self, initial_find_text=initial_text)
        
        # Căn giữa dialog trong cửa sổ chính
        center = self.geometry().center()
        dialog.move(center.x() - dialog.width() // 2, center.y() - dialog.height() // 2)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            find_text = dialog.get_find_text()
            replace_text = dialog.get_replace_text()
            case_sensitive = dialog.is_case_sensitive()
            
            if not find_text:
                QMessageBox.warning(self, "Lưu ý", "Vui lòng nhập văn bản cần tìm kiếm.")
                return
            
            self.replace_all_subtitles(find_text, replace_text, case_sensitive)
    
    def replace_all_subtitles(self, find_text, replace_text, case_sensitive=False):
        """Thay thế tất cả văn bản khớp trong toàn bộ phụ đề.
        
        Args:
            find_text:      Văn bản cần tìm.
            replace_text:   Văn bản thay thế.
            case_sensitive: Phân biệt chữ hoa/thường (mặc định False).
        """
        if not find_text:
            return
        
        # Lưu trạng thái để Undo
        self.save_state_for_undo()
        
        count = 0
        find_cmp = find_text if case_sensitive else find_text.lower()
        
        for track in self.subtitle_tracks:
            for sub in track:
                original = sub.text
                
                if case_sensitive:
                    if find_text in original:
                        sub.text = original.replace(find_text, replace_text)
                        # Đếm số lần xuất hiện
                        count += original.count(find_text)
                else:
                    # Thay thế không phân biệt hoa/thường (giữ nguyên case của phần còn lại)
                    original_lower = original.lower()
                    if find_cmp in original_lower:
                        # Đếm lần xuất hiện trước khi thay thế
                        count += original_lower.count(find_cmp)
                        
                        # Thay thế từng occurrence giữ nguyên vị trí
                        result = []
                        idx = 0
                        while idx < len(original):
                            pos = original_lower.find(find_cmp, idx)
                            if pos == -1:
                                result.append(original[idx:])
                                break
                            result.append(original[idx:pos])
                            result.append(replace_text)
                            idx = pos + len(find_text)
                        sub.text = "".join(result)
        
        if count == 0:
            QMessageBox.information(
                self, "Không tìm thấy",
                f"Không tìm thấy văn bản:\n\"{find_text}\""
            )
            return
        
        # Đánh dấu đã có thay đổi
        self.mark_change()
        self._invalidate_cache()
        
        # QUAN TRỌNG: Sync text mới vào tất cả widget trong danh sách
        # (vì sub.text đã thay đổi trực tiếp trên object, nhưng QTextEdit trong widget chưa biết)
        self._sync_all_widgets_text()
        
        # Làm mới ô tìm kiếm nếu đang tìm kiếm cùng từ
        if self.search_input.text():
            self.perform_search(self.search_input.text())
        else:
            # Nếu không đang search, vẫn cần update highlight
            self._apply_search_highlight("")
        
        # Cập nhật toàn bộ UI - dùng immediate để list hiển thị ngay
        self.update_all_views(reorganize=False, immediate=True)
        
        # Cập nhật video preview ngay lập tức
        if not self.video_timer.isActive():
            self.update_video_frame_preview()
        
        # Thông báo kết quả
        self.statusBar().showMessage(
            f"✅ Đã thay thế {count} lần xuất hiện của \"{find_text}\" → \"{replace_text}\"", 
            5000
        )

    def closeEvent(self, event):
        if self.has_unsaved_changes:
            reply = QMessageBox.question(self, 'Lưu thay đổi?',
                                         'Bạn có các thay đổi chưa được lưu. Bạn có muốn lưu trước khi thoát không?',
                                         QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self.save_to_temp_file()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
        
        if event.isAccepted():
            if self.video_worker:
                self.video_worker.stop()
            if self.video_capture: self.video_capture.release()
            super().closeEvent(event)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trình chỉnh sửa phụ đề PyQt6")
    parser.add_argument("--video", type=str, help="Đường dẫn đến file video để tải ban đầu.")
    parser.add_argument("--srt", type=str, help="Đường dẫn đến file SRT để tải ban đầu.")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    
    window = MainWindow(initial_video_path=args.video, initial_srt_path=args.srt)
    window.showMaximized()
    sys.exit(app.exec())
