"""Text tab - subtitle library styled similarly to the Media panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, Signal  # type: ignore
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QPainter, QPixmap  # type: ignore
from PySide6.QtSvg import QSvgRenderer  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

SUPPORTED_SUBS_HINT = "srt, vtt, lrc, ass, ssa, txt"
SUBTITLE_EXTS = {".srt", ".vtt", ".lrc", ".ass", ".ssa", ".txt"}
MEDIA_MIME_TYPE = "application/x-comecut-media-path"
PLUS_ICON_SVG = (
    '<svg width="800" height="800" viewBox="0 0 48 48" version="1" '
    'xmlns="http://www.w3.org/2000/svg"><circle fill="#22d3c5" cx="24" cy="24" r="21"/>'
    '<g fill="#fff"><path d="M21 14h6v20h-6z"/><path d="M14 21h20v6H14z"/></g></svg>'
)
TRASH_ICON_SVG = (
    '<svg viewBox="-2 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M5 3a3 3 0 0 1 3-3h4a3 3 0 0 1 3 3h2a3 3 0 0 1 3 3 1 1 0 0 1-1 1H1a1 1 0 0 1-1-1 3 3 0 0 1 3-3zM2 9h16a1 1 0 0 1 1 1v11a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3V10a1 1 0 0 1 1-1m3 4.143v5.714C5 19.488 5.448 20 6 20s1-.512 1-1.143v-5.714C7 12.512 6.552 12 6 12s-1 .512-1 1.143m4 0v5.714C9 19.488 9.448 20 10 20s1-.512 1-1.143v-5.714c0-.631-.448-1.143-1-1.143s-1 .512-1 1.143m4 0v5.714c0 .631.448 1.143 1 1.143s1-.512 1-1.143v-5.714c0-.631-.448-1.143-1-1.143s-1 .512-1 1.143M8 2a1 1 0 0 0-1 1h6a1 1 0 0 0-1-1z" fill="#ef4444"/></svg>'
)


def _icon_from_svg(svg: str, size: int) -> QIcon:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


class _SubtitleListWidget(QListWidget):
    """List widget that starts a drag carrying the subtitle path."""

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.pos()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
            self.setCurrentRow(-1)
            event.accept()
            return
        super().mousePressEvent(event)

    def startDrag(self, supported_actions) -> None:  # type: ignore[override]
        item = self.currentItem()
        if item is None:
            return

        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        raw_path = data.get("raw")
        if not raw_path:
            return
        path = Path(str(raw_path))

        from PySide6.QtCore import QMimeData, QUrl  # type: ignore
        from PySide6.QtGui import QDrag  # type: ignore

        mime = QMimeData()
        mime.setData(MEDIA_MIME_TYPE, str(path).encode("utf-8"))
        mime.setText(str(path))
        mime.setUrls([QUrl.fromLocalFile(str(path))])

        drag = QDrag(self)
        drag.setMimeData(mime)

        widget = self.itemWidget(item)
        if widget is not None:
            pix = widget.grab()
            if not pix.isNull():
                drag.setPixmap(pix)
                drag.setHotSpot(pix.rect().center())

        drag.exec(Qt.DropAction.CopyAction)


class _SubtitleDropZone(QFrame):
    files_dropped = Signal(list)  # list[Path]
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(240)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            """
            QFrame#card {
                border: 1px dashed #363b46;
                background: transparent;
                border-radius: 8px;
            }
            QFrame#card:hover {
                border-color: #22d3c5;
                background: rgba(34, 211, 197, 0.02);
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        import_svg = """<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="#8c93a0"><path d="M5.552 20.968a2.577 2.577 0 0 1-2.5-2.73c-.012-2.153 0-4.306 0-6.459a.5.5 0 0 1 1 0c0 2.2-.032 4.4 0 6.6.016 1.107.848 1.589 1.838 1.589h12.463A1.55 1.55 0 0 0 19.825 19a3 3 0 0 0 .1-1.061v-6.16a.5.5 0 0 1 1 0c0 2.224.085 4.465 0 6.687a2.567 2.567 0 0 1-2.67 2.5Z"/><path d="M11.63 15.818a.46.46 0 0 0 .312.138c.014 0 .027.005.042.006s.027 0 .041-.006a.46.46 0 0 0 .312-.138l3.669-3.669a.5.5 0 0 0-.707-.707l-2.815 2.815V3.515a.5.5 0 0 0-1 0v10.742l-2.816-2.815a.5.5 0 0 0-.707.707Z"/></svg>"""
        renderer = QSvgRenderer(QByteArray(import_svg.encode("utf-8")))
        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if renderer.isValid():
            pix = QPixmap(48, 48)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            icon.setPixmap(pix)
        icon.setStyleSheet("background: transparent;")

        title = QLabel("Drag and drop subtitle files here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet("color: #8c93a0; font-size: 14px; background: transparent;")

        sub = QLabel(SUPPORTED_SUBS_HINT)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #4a505c; font-size: 11px; background: transparent;")

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addSpacing(10)
        layout.addWidget(sub)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


def _first_subtitle_preview(path: Path) -> str:
    try:
        with path.open("rb") as f:
            text = f.read(64 * 1024).decode("utf-8", errors="ignore")
    except Exception:
        return "Subtitle file"
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.isdigit():
            continue
        if "-->" in line:
            continue
        if line.startswith("[") and "]" in line:
            continue
        return line[:34]
    return "Subtitle file"


class _SubtitleItemWidget(QFrame):
    delete_requested = Signal()
    add_requested = Signal()

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.setFixedSize(140, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False
        self._missing = False
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        ext = path.suffix.lower().lstrip(".") or "txt"
        preview = _first_subtitle_preview(path)
        tile = QLabel(f"{ext.upper()}\n{preview}")
        tile.setFixedSize(138, 78)
        tile.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        tile.setWordWrap(True)
        tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tile.setStyleSheet(
            """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0f172a, stop:1 #1f2937);
            color: #e6e8ec;
            border-top-left-radius: 5px;
            border-top-right-radius: 5px;
            border: none;
            font-size: 11px;
            font-weight: 600;
            padding: 6px;
            """
        )
        layout.addWidget(tile)

        # Missing badge (top-right of thumb)
        self.missing_badge = QLabel("Missing", tile)
        self.missing_badge.setFixedSize(60, 18)
        self.missing_badge.move(74, 4)
        self.missing_badge.setStyleSheet("""
            QLabel {
                background: rgba(239, 68, 68, 0.92);
                color: white;
                font-size: 10px;
                font-weight: 700;
                border-radius: 9px;
                padding: 0 6px;
            }
        """)
        self.missing_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.missing_badge.hide()

        name = QLabel(path.name)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(
            "color: #e6e8ec; font-size: 11px; border: none; background: transparent; padding: 0 6px 4px 6px;"
        )
        layout.addWidget(name)

        self.add_btn = QToolButton(self)
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.move(84, 4)
        self.add_btn.hide()
        self.add_btn.setIcon(_icon_from_svg(PLUS_ICON_SVG, 20))
        self.add_btn.setIconSize(QSize(20, 20))
        self.add_btn.setStyleSheet(
            """
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.08);
            }
            """
        )
        self.add_btn.clicked.connect(self.add_requested.emit)
        self.add_btn.raise_()

        self.del_btn = QToolButton(self)
        self.del_btn.setText("")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.move(112, 4)
        self.del_btn.hide()
        self.del_btn.setIcon(_icon_from_svg(TRASH_ICON_SVG, 16))
        self.del_btn.setIconSize(QSize(16, 16))
        self.del_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 4px;
            }
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.08);
            }
        """)
        self.del_btn.clicked.connect(self.delete_requested.emit)
        self.del_btn.raise_()

    def _apply_style(self) -> None:
        if self._missing:
            border = "#ef4444"
            bg = "#22262e" if self._selected else "#1a1d23"
        elif self._selected:
            border = "#22d3c5"
            bg = "#22262e"
        else:
            border = "#363b46"
            bg = "#1a1d23"

        self.setStyleSheet(
            f"""
            QFrame {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 6px;
            }}
            QFrame:hover {{
                border-color: #22d3c5;
                background: #22262e;
            }}
            """
        )

    def set_missing(self, missing: bool) -> None:
        self._missing = bool(missing)
        self.missing_badge.setVisible(self._missing)
        self._apply_style()

    def is_missing(self) -> bool:
        return self._missing

    def set_selected(self, selected: bool) -> None:
        selected_b = bool(selected)
        if self._selected == selected_b:
            return
        self._selected = selected_b
        self._apply_style()

    def enterEvent(self, event) -> None:
        if hasattr(self, 'del_btn'):
            self.del_btn.show()
            self.del_btn.raise_()
        if hasattr(self, 'add_btn'):
            self.add_btn.show()
            self.add_btn.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if hasattr(self, 'del_btn'):
            self.del_btn.hide()
        if hasattr(self, 'add_btn'):
            self.add_btn.hide()
        super().leaveEvent(event)


class _OcrSettingsView(QWidget):
    """Configuration view for AI Subtitle Extraction (OCR)."""
    
    start_ocr_requested = Signal()
    cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(20)

        # Title
        desc = QLabel("CÀI ĐẶT TRÍCH XUẤT OCR")
        desc.setStyleSheet("color: #8c93a0; font-weight: 700; font-size: 11px;")
        layout.addWidget(desc)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(15)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["Tiếng Trung (ch)", "Tiếng Anh (en)", "Tiếng Việt (vi)", "Tiếng Nhật (ja)", "Tiếng Hàn (ko)"])
        self._lang_combo.setFixedHeight(28)
        self._lang_combo.setStyleSheet("""
            QComboBox { background: #1a1d23; border: 1px solid #363b46; border-radius: 4px; padding: 0 8px; color: #e6e8ec; }
            QComboBox::drop-down { border: none; }
        """)
        form.addRow("Ngôn ngữ:", self._lang_combo)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Nhanh (Fast)", "Chính xác (Accurate)"])
        self._mode_combo.setFixedHeight(28)
        self._mode_combo.setStyleSheet("""
            QComboBox { background: #1a1d23; border: 1px solid #363b46; border-radius: 4px; padding: 0 8px; color: #e6e8ec; }
            QComboBox::drop-down { border: none; }
        """)
        form.addRow("Chế độ:", self._mode_combo)

        layout.addWidget(form_widget)

        # Action Buttons
        self._start_btn = QPushButton("BẮT ĐẦU TRÍCH XUẤT")
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.setFixedHeight(36)
        self._start_btn.setStyleSheet("""
            QPushButton {
                background: #0e7490;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: 700;
                font-size: 12px;
            }
            QPushButton:hover { background: #155e75; }
            QPushButton:pressed { background: #164e63; }
        """)
        self._start_btn.clicked.connect(self.start_ocr_requested.emit)
        layout.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("Hủy")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setFixedHeight(30)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8c93a0;
                border: 1px solid #363b46;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover { color: #e6e8ec; border-color: #4b5563; }
        """)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self._cancel_btn)

        tip = QLabel(
            "Mẹo: Bạn có thể di chuyển hoặc thay đổi kích thước vùng chọn màu xanh trên màn hình Preview "
            "để khớp với vị trí phụ đề trong video."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #5a606c; font-size: 11px; line-height: 1.4;")
        layout.addWidget(tip)

        layout.addStretch(1)

    def get_settings(self) -> tuple[str, str]:
        lang_map = {
            "Tiếng Trung (ch)": "ch",
            "Tiếng Anh (en)": "en",
            "Tiếng Việt (vi)": "vi",
            "Tiếng Nhật (ja)": "ja",
            "Tiếng Hàn (ko)": "ko"
        }
        mode_map = {
            "Nhanh (Fast)": "fast",
            "Chính xác (Accurate)": "accurate"
        }
        return lang_map.get(self._lang_combo.currentText(), "ch"), mode_map.get(self._mode_combo.currentText(), "fast")


class TextPanel(QWidget):
    """Subtitle import/list panel with Media-like structure."""

    # Kept for backward compatibility with existing MainWindow wiring.
    template_chosen = Signal(str)
    subtitle_import_requested = Signal()
    subtitle_add_requested = Signal(Path)
    ocr_mode_requested = Signal()   # Kích hoạt chế độ OCR trên Preview
    card_selected = Signal(Path)    # Khi click vào 1 card phụ đề
    subtitle_files_imported = Signal(list)  # list[Path]
    subtitle_files_removed = Signal(list)  # list[Path]
    relink_subtitle_requested = Signal(Path) # ← NEW

    def __init__(self) -> None:
        super().__init__()
        self._loading_library = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header_container = QWidget()
        self.header_container.setStyleSheet("background: transparent; border: none;")
        self.header_container.hide()  # Hide by default
        header_layout = QHBoxLayout(self.header_container)
        header_layout.setContentsMargins(12, 6, 12, 6)
        header_layout.setSpacing(8)

        header_layout.addStretch(1)

        self.import_btn = QToolButton()
        self.import_btn.setText("Nhập")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.setFixedHeight(24)
        self.import_btn.setIcon(_icon_from_svg(PLUS_ICON_SVG, 14))
        self.import_btn.setIconSize(QSize(14, 14))
        self.import_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.import_btn.setStyleSheet(
            """
            QToolButton {
                background: #2a2f38;
                color: #e6e8ec;
                border: 1px solid #363b46;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 10px;
            }
            QToolButton:hover {
                border-color: #22d3c5;
                color: #22d3c5;
            }
            """
        )
        self.import_btn.clicked.connect(self.subtitle_import_requested.emit)
        self.import_btn.hide()
        header_layout.addWidget(self.import_btn)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name...")

        # Apply custom SVG search icon
        search_svg = """<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><g fill="none" fill-rule="evenodd"><path d="M10.5 19a8.5 8.5 0 1 0 0-17 8.5 8.5 0 0 0 0 17Z" stroke="#8c93a0" stroke-linejoin="round" stroke-width="1.5"/><path d="M13.328 7.172A4 4 0 0 0 10.5 6a4 4 0 0 0-2.828 1.172m8.939 9.439 4.243 4.243" stroke="#8c93a0" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"/></g></svg>"""
        renderer = QSvgRenderer(QByteArray(search_svg.encode("utf-8")))
        if renderer.isValid():
            pix = QPixmap(14, 14)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            self.search_edit.addAction(QIcon(pix), QLineEdit.ActionPosition.LeadingPosition)

        self.search_edit.setFixedWidth(160)
        self.search_edit.setFixedHeight(24)
        self.search_edit.setStyleSheet(
            f"background: #1a1d23; border: 1px solid #363b46; border-radius: 12px; "
            f"font-size: 11px; padding: 0 4px; color: #e6e8ec;"
        )
        self.search_edit.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # Custom Clear Action with SVG
        self.clear_action = self.search_edit.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        self.clear_action.setVisible(False)
        self.clear_action.triggered.connect(lambda: self.search_edit.clear())

        clear_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><path fill="#8c93a0" d="M256 0C114.615 0 0 114.615 0 256s114.615 256 256 256 256-114.615 256-256S397.385 0 256 0m71.115 365.904L256 294.789l-71.115 71.115-38.789-38.789L217.211 256l-71.115-71.115 38.789-38.789L256 217.211l71.115-71.115 38.789 38.789L294.789 256l71.115 71.115z"/></svg>"""
        clr_renderer = QSvgRenderer(QByteArray(clear_svg.encode("utf-8")))
        if clr_renderer.isValid():
            cpix = QPixmap(14, 14)
            cpix.fill(Qt.GlobalColor.transparent)
            cpainter = QPainter(cpix)
            clr_renderer.render(cpainter)
            cpainter.end()
            self.clear_action.setIcon(QIcon(cpix))

        def on_text_changed(text: str) -> None:
            self.clear_action.setVisible(bool(text))
            self._apply_filter(text)

        self.search_edit.textChanged.connect(on_text_changed)
        header_layout.addWidget(self.search_edit)

        layout.addWidget(self.header_container)

        self.stack = QStackedWidget()

        # Page 0: Subtitle List
        self.list_view_widget = QWidget()
        list_view_layout = QVBoxLayout(self.list_view_widget)
        list_view_layout.setContentsMargins(0, 0, 0, 0)
        list_view_layout.setSpacing(0)

        self.list_stack = QStackedWidget() # Sub-stack for Empty vs Items
        
        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.addStretch(1)
        self._drop = _SubtitleDropZone()
        self._drop.clicked.connect(self.subtitle_import_requested.emit)
        self._drop.files_dropped.connect(self._on_drop_files)
        empty_layout.addWidget(self._drop)
        empty_layout.addStretch(1)
        self.list_stack.addWidget(self.empty_page)

        self.list_page = QWidget()
        list_layout = QVBoxLayout(self.list_page)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(0)

        self.subtitle_list = _SubtitleListWidget()
        self.subtitle_list.setObjectName("subtitleList")
        self.subtitle_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.subtitle_list.setGridSize(QSize(150, 120))
        self.subtitle_list.setMovement(QListWidget.Movement.Static)
        self.subtitle_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.subtitle_list.setDragEnabled(True)
        self.subtitle_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.subtitle_list.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.subtitle_list.setSpacing(8)
        self.subtitle_list.setStyleSheet("background: transparent; border: none;")
        self.subtitle_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.subtitle_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.subtitle_list.customContextMenuRequested.connect(self._on_context_menu)
        self.subtitle_list.itemClicked.connect(self._on_item_clicked)
        list_layout.addWidget(self.subtitle_list)
        self.list_stack.addWidget(self.list_page)

        list_view_layout.addWidget(self.list_stack)
        self.stack.addWidget(self.list_view_widget)

        # Page 1: OCR Settings
        self.ocr_settings_view = _OcrSettingsView()
        self.stack.addWidget(self.ocr_settings_view)
        layout.addWidget(self.stack)

    def show_ocr_settings(self) -> None:
        self.stack.setCurrentIndex(1)
        self.header_container.hide() # Hide search/import when in OCR settings

    def show_subtitle_list(self) -> None:
        self.stack.setCurrentIndex(0)
        self._update_import_button() # This handles header visibility

    def get_ocr_settings(self) -> tuple[str, str]:
        return self.ocr_settings_view.get_settings()

    @property
    def start_ocr_requested(self) -> Signal:
        return self.ocr_settings_view.start_ocr_requested

    @property
    def ocr_cancel_requested(self) -> Signal:
        return self.ocr_settings_view.cancel_requested

    def _on_drop_files(self, paths: list[Path]) -> None:
        added = False
        for path in paths:
            if path.suffix.lower() not in SUBTITLE_EXTS:
                continue
            self.add_imported_subtitle(path)
            added = True
        if not added:
            self.subtitle_import_requested.emit()

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            name = item.text().lower()
            data = item.data(Qt.ItemDataRole.UserRole)
            preview = ""
            if isinstance(data, dict):
                preview = str(data.get("preview", "")).lower()
            item.setHidden(query not in name and query not in preview)

    def _delete_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        removed_path: Path | None = None
        if isinstance(data, dict):
            raw = str(data.get("raw", ""))
            if raw:
                removed_path = Path(raw)
        row = self.subtitle_list.row(item)
        if row >= 0:
            self.subtitle_list.takeItem(row)
            if self.subtitle_list.count() == 0:
                self.list_stack.setCurrentIndex(0)
        self._update_import_button()
        if removed_path is not None:
            self.subtitle_files_removed.emit([removed_path])

    def _on_context_menu(self, pos) -> None:
        item = self.subtitle_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu { background: #22262e; border: 1px solid #363b46; color: #e6e8ec; padding: 4px; }
            QMenu::item { padding: 4px 24px; border-radius: 4px; }
            QMenu::item:selected { background: #ef4444; color: white; }
            """
        )
        add_action = menu.addAction("Add to Timeline (00:00)")
        menu.addSeparator()
        del_action = menu.addAction("Delete")
        action = menu.exec(self.subtitle_list.mapToGlobal(pos))
        if action == add_action:
            self._emit_add_item(item)
            return
        if action == del_action:
            self._delete_item(item)

    @staticmethod
    def _normalize_path(path: Path | str) -> str:
        try:
            norm = str(Path(path).resolve())
        except Exception:
            norm = str(Path(path))
        return norm.lower()

    def add_imported_subtitle(self, path: Path, *, missing: bool = False) -> None:
        path_str = str(path)
        norm_path = self._normalize_path(path)
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            old = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(old, dict):
                old_norm = str(old.get("norm", ""))
                old_raw = str(old.get("raw", ""))
            else:
                old_norm = self._normalize_path(str(old)) if old else ""
                old_raw = str(old) if old else ""
            if old_norm == norm_path or old_raw == path_str:
                # Update missing state if already present
                widget = self.subtitle_list.itemWidget(item)
                if isinstance(widget, _SubtitleItemWidget):
                    widget.set_missing(missing)
                self.show_subtitle_list()
                self.list_stack.setCurrentIndex(1)
                self.subtitle_list.setCurrentItem(item)
                self.subtitle_list.scrollToItem(item)
                return
        self.show_subtitle_list()
        self.list_stack.setCurrentIndex(1)
        item = QListWidgetItem(path.name)
        item.setSizeHint(QSize(140, 110))
        item.setToolTip(path_str)
        item.setData(Qt.ItemDataRole.UserRole, {"raw": str(path), "norm": norm_path})

        widget = _SubtitleItemWidget(path)
        widget.set_missing(missing)
        if missing:
            widget.setToolTip(f"File not found:\n{path}\n\nDouble-click to relink.")
        widget.delete_requested.connect(lambda: self._delete_item(item))
        widget.add_requested.connect(lambda p=path: self.subtitle_add_requested.emit(p))
        self.subtitle_list.addItem(item)
        self.subtitle_list.setItemWidget(item, widget)

        self._apply_filter(self.search_edit.text())
        self._update_import_button()
        self.select_card(path)
        if not self._loading_library:
            self.subtitle_files_imported.emit([path])

    def select_card(self, path: Path) -> None:
        """Tìm và chọn card có path tương ứng."""
        path_str = str(path)
        norm_path = self._normalize_path(path)
        for i in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                if data.get("norm") == norm_path or data.get("raw") == path_str:
                    self.subtitle_list.setCurrentItem(item)
                    self.subtitle_list.scrollToItem(item)
                    # Phát tín hiệu để các panel khác biết
                    self.card_selected.emit(path)
                    return

    def add_imported_subtitles(self, paths: list[Path]) -> None:
        for path in paths:
            self.add_imported_subtitle(path)

    def set_imported_subtitles_with_missing(
        self,
        entries: list[object],  # list[LibraryEntry]
        missing_flags: list[bool] | None = None,
    ) -> None:
        """Replace panel contents with entries + missing status.

        Called by MainWindow on project load.
        """
        self.subtitle_list.clear()
        if not entries:
            self.list_stack.setCurrentIndex(0)
            self._update_import_button()
            return
        flags = missing_flags or [False] * len(entries)
        self._loading_library = True
        try:
            for entry, missing in zip(entries, flags):
                try:
                    src = getattr(entry, "source", str(entry))
                    path_obj = Path(src)
                except Exception:
                    continue
                self.add_imported_subtitle(path_obj, missing=bool(missing))
        finally:
            self._loading_library = False
        if self.subtitle_list.count() > 0:
            self.list_stack.setCurrentIndex(1)
        else:
            self.list_stack.setCurrentIndex(0)
        self._update_import_button()

    def set_imported_subtitles(self, paths: list[Path]) -> None:
        """Backward-compat alias for list[Path]."""
        self.set_imported_subtitles_with_missing(
            [type("E", (), {"source": str(p)})() for p in paths],
            missing_flags=[False] * len(paths),
        )

    def _update_import_button(self) -> None:
        if self.stack.currentIndex() == 1:
            return # Don't show header if in OCR settings
        has_items = self.subtitle_list.count() > 0
        self.import_btn.setVisible(has_items)
        self.header_container.setVisible(has_items)

    def _emit_add_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        raw = str(data.get("raw", "")).strip()
        if not raw:
            return
        self.subtitle_add_requested.emit(Path(raw))

    def _on_double_click(self, item: QListWidgetItem) -> None:
        widget = self.subtitle_list.itemWidget(item)
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or not data.get("raw"):
            return
        path = Path(str(data["raw"]))
        if isinstance(widget, _SubtitleItemWidget) and widget.is_missing():
            self.relink_subtitle_requested.emit(path)
            return
        self.subtitle_add_requested.emit(path)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict) and "raw" in data:
            self.card_selected.emit(Path(data["raw"]))


__all__ = ["TextPanel"]
