"""Media library panel — polished to match HTML parity (Alignment + Search + Thumbnails).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, QUrl, Signal  # type: ignore
from PySide6.QtGui import QColor, QDrag, QDragEnterEvent, QDropEvent, QIcon, QPainter, QPixmap  # type: ignore
from PySide6.QtSvg import QSvgRenderer  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFileDialog,
    QStackedWidget,
    QToolButton,
)

from ...engine.thumbnails import render_filmstrip_png

MEDIA_PATH_ROLE = 256
MEDIA_NORM_PATH_ROLE = 257
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


class _MediaListWidget(QListWidget):
    """List widget that starts a drag carrying the media path."""

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

        raw_path = item.data(MEDIA_PATH_ROLE)
        if not raw_path:
            return
        path = Path(str(raw_path))

        mime = QMimeData()
        mime.setData(MEDIA_MIME_TYPE, str(path).encode("utf-8"))
        mime.setText(str(path))
        mime.setUrls([QUrl.fromLocalFile(str(path))])

        drag = QDrag(self)
        drag.setMimeData(mime)

        thumb = self.itemWidget(item)
        if thumb is not None and hasattr(thumb, "thumb_lbl"):
            pix = thumb.thumb_lbl.grab()
            if not pix.isNull():
                drag.setPixmap(pix)
                drag.setHotSpot(pix.rect().center())

        drag.exec(Qt.DropAction.CopyAction)

SUPPORTED_HINT = "mp4, mkv, wav, mp3, srt, vtt, lrc, ass, txt, jpg, png"


class _DropZone(QFrame):
    """Dotted-border drop area shown above the imported-media list."""

    files_dropped = Signal(list)  # list[Path]
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setAcceptDrops(True)
        self.setMinimumHeight(240)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QFrame#card {
                border: 1px dashed #363b46;
                background: transparent;
                border-radius: 8px;
            }
            QFrame#card:hover {
                border-color: #22d3c5;
                background: rgba(34, 211, 197, 0.02);
            }
        """)

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

        title = QLabel("Drag and drop audio, video, photo, and subtitle files here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet("color: #8c93a0; font-size: 14px; background: transparent;")

        sub = QLabel(SUPPORTED_HINT)
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


class _MediaItemWidget(QFrame):
    """Custom widget for a media card in the library."""

    delete_requested = Signal()
    add_requested = Signal()

    def __init__(self, name: str, path: Path) -> None:
        super().__init__()
        self.setFixedSize(140, 110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False
        self._apply_style()
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.thumb_lbl = QLabel()
        self.thumb_lbl.setFixedSize(138, 78)
        self.thumb_lbl.setStyleSheet("background: #0b0d10; border-top-left-radius: 5px; border-top-right-radius: 5px; border: none;")
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Load image directly or generate video thumbnail
        ext = path.suffix.lower()
        thumb_success = False
        try:
            if ext in ('.jpg', '.jpeg', '.png', '.bmp', '.webp'):
                pix = QPixmap(str(path))
                if not pix.isNull():
                    self.thumb_lbl.setPixmap(pix.scaled(138, 78, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                    thumb_success = True
            else:
                # Try FFmpeg-based thumbnail
                t_path = render_filmstrip_png(str(path), strip_width=138, strip_height=78, frames=1)
                if t_path and Path(t_path).exists():
                    pix = QPixmap(str(t_path))
                    if not pix.isNull():
                        self.thumb_lbl.setPixmap(pix.scaled(138, 78, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                        thumb_success = True
        except Exception:
            pass

        if not thumb_success:
            # High-quality placeholder (HTML parity)
            icon_text = "🎬" if ext not in ('.wav', '.mp3') else "🎵"
            self.thumb_lbl.setText(icon_text)
            self.thumb_lbl.setStyleSheet("""
                color: #4a505c; 
                font-size: 32px; 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1d23, stop:1 #0b0d10);
                border-top-left-radius: 5px; 
                border-top-right-radius: 5px;
                border: none;
            """)

        # Floating Delete Button (HTML parity)
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

        # Floating "Added" Badge (CapCut style)
        self.added_badge = QLabel("Đã thêm", self.thumb_lbl)
        self.added_badge.setFixedSize(50, 18)
        self.added_badge.move(4, 4)
        self.added_badge.setStyleSheet("""
            background: #22d3c5;
            color: #111318;
            border-radius: 4px;
            font-size: 9px;
            font-weight: 800;
            padding: 0 4px;
        """)
        self.added_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.added_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.added_badge.hide()

        # Missing badge (top-right of thumb), red, hidden by default
        self.missing_badge = QLabel("Missing", self.thumb_lbl)
        self.missing_badge.setFixedSize(60, 18)
        self.missing_badge.move(74, 4)  # right side
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
        self._missing = False

        name_container = QWidget()
        name_layout = QHBoxLayout(name_container)
        name_layout.setContentsMargins(6, 4, 6, 4)
        name_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.name_lbl = QLabel(name)
        self.name_lbl.setStyleSheet("color: #e6e8ec; font-size: 11px; border: none; background: transparent;")
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_layout.addWidget(self.name_lbl)
        
        layout.addWidget(self.thumb_lbl)
        layout.addWidget(name_container, stretch=1)

    def _apply_style(self) -> None:
        if getattr(self, "_missing", False):
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
        # When missing, thumbnail gets a red border to flag it
        self._apply_style()

    def is_missing(self) -> bool:
        return getattr(self, "_missing", False)

    def set_selected(self, selected: bool) -> None:
        selected_b = bool(selected)
        if self._selected == selected_b:
            return
        self._selected = selected_b
        self._apply_style()

    def set_added(self, added: bool) -> None:
        self.added_badge.setVisible(bool(added))

    def enterEvent(self, event) -> None:
        self.del_btn.show()
        self.del_btn.raise_()
        self.add_btn.show()
        self.add_btn.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.del_btn.hide()
        self.add_btn.hide()
        super().leaveEvent(event)


class MediaLibraryPanel(QWidget):
    """Library panel rendered when the Media tab is active."""

    media_double_clicked = Signal(Path)
    media_add_requested = Signal(Path)
    files_imported = Signal(list)  # list[Path]
    files_removed = Signal(list)  # list[Path]
    voice_folder_import_requested = Signal(Path)
    relink_requested = Signal(Path)  # ← NEW: emitted when user double-clicks a missing card
    media_selection_changed = Signal(object)  # Path | None

    def __init__(self) -> None:
        super().__init__()
        self._loading_library = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header with Search and Icons (HTML parity)
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
        self.import_btn.clicked.connect(self._on_browse)
        self.import_btn.hide()

        self.add_voice_btn = QToolButton()
        self.add_voice_btn.setText("Thêm Voice")
        self.add_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_voice_btn.setFixedHeight(24)
        self.add_voice_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_voice_btn.setStyleSheet(self.import_btn.styleSheet())
        self.add_voice_btn.clicked.connect(self._on_add_voice_folder)

        action_col = QVBoxLayout()
        action_col.setContentsMargins(0, 0, 0, 0)
        action_col.setSpacing(4)
        action_col.addWidget(self.import_btn)
        self.add_voice_btn.hide()
        header_layout.addLayout(action_col)

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

        # FFmpeg Missing Warning Banner (Subtle HTML style)
        self.warning_banner = QFrame()
        self.warning_banner.setFixedHeight(32)
        self.warning_banner.setStyleSheet("background: #2d1a1a; border-bottom: 1px solid #363b46;")
        warn_layout = QHBoxLayout(self.warning_banner)
        warn_layout.setContentsMargins(12, 0, 12, 0)
        warn_text = QLabel("⚠️ FFmpeg missing: Video thumbnails disabled. Please install FFmpeg.")
        warn_text.setStyleSheet("color: #f87171; font-size: 10px;")
        warn_layout.addWidget(warn_text)
        warn_layout.addStretch(1)
        layout.addWidget(self.warning_banner)
        
        # Check FFmpeg using our custom logic
        from ...core.ffmpeg_cmd import ensure_ffmpeg, FFmpegNotFoundError
        try:
            ensure_ffmpeg()
            self.warning_banner.hide()
        except FFmpegNotFoundError:
            pass

        # Stacked Widget for Empty vs List states
        self.stack = QStackedWidget()
        
        # Page 1: Drop Zone
        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.addStretch(1)
        self._drop = _DropZone()
        self._drop.files_dropped.connect(self._add_many)
        self._drop.clicked.connect(self._on_browse)
        empty_layout.addWidget(self._drop)
        empty_layout.addStretch(1)
        
        # Page 2: Media List
        self.list_page = QWidget()
        list_layout = QVBoxLayout(self.list_page)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(0)

        self.list_widget = _MediaListWidget()
        self.list_widget.setObjectName("mediaList")
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setGridSize(QSize(150, 120))
        self.list_widget.setMovement(QListWidget.Movement.Static)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.list_widget.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.list_widget.setSpacing(8)
        self.list_widget.setStyleSheet("background: transparent; border: none;")
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        list_layout.addWidget(self.list_widget)

        self.stack.addWidget(self.empty_page)
        self.stack.addWidget(self.list_page)
        
        layout.addWidget(self.stack)

        # Bottom bar removed; actions are available from the drop zone and browser.
        self._update_import_button()

    def _on_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #22262e; border: 1px solid #363b46; color: #e6e8ec; padding: 4px; }
            QMenu::item { padding: 4px 24px; border-radius: 4px; }
            QMenu::item:selected { background: #ef4444; color: white; }
        """)

        add_action = menu.addAction("Add to Timeline (00:00)")
        menu.addSeparator()
        del_action = menu.addAction("Delete")

        action = menu.exec(self.list_widget.mapToGlobal(pos))
        if action == add_action:
            self._emit_add_item(item)
            return
        if action == del_action:
            self._delete_item(item)

    def _on_browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, 
            "Select Media", 
            "", 
            "Media Files (*.mp4 *.mkv *.wav *.mp3 *.srt *.vtt *.lrc *.ass *.ssa *.txt *.jpg *.png);;All Files (*)"
        )
        if files:
            self._add_many([Path(f) for f in files])

    def _on_add_voice_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn folder voice")
        if folder:
            self.voice_folder_import_requested.emit(Path(folder))

    @staticmethod
    def _normalize_path(path: Path | str) -> str:
        try:
            norm = str(Path(path).resolve())
        except Exception:
            norm = str(Path(path))
        return norm.lower()

    def add_media(self, path: Path, *, missing: bool = False) -> None:
        norm_path = self._normalize_path(path)
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.data(MEDIA_NORM_PATH_ROLE) == norm_path:
                # Update existing card's missing state
                widget = self.list_widget.itemWidget(it)
                if isinstance(widget, _MediaItemWidget):
                    widget.set_missing(missing)
                return

        if self.stack.currentIndex() == 0:
            self.stack.setCurrentIndex(1)

        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(140, 110))
        item.setData(MEDIA_PATH_ROLE, str(path))
        item.setData(MEDIA_NORM_PATH_ROLE, norm_path)

        widget = _MediaItemWidget(path.name, path)
        widget.set_missing(missing)
        if missing:
            widget.setToolTip(f"File not found:\n{path}\n\nDouble-click to relink.")
        widget.delete_requested.connect(lambda: self._delete_item(item))
        widget.add_requested.connect(lambda it=item: self._emit_add_item(it))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)
        self._apply_filter(self.search_edit.text())
        self._refresh_selection_visuals()
        self._update_import_button()

    def _delete_item(self, item: QListWidgetItem) -> None:
        raw = item.data(MEDIA_PATH_ROLE)
        removed_path = Path(str(raw)) if raw else None
        row = self.list_widget.row(item)
        if row >= 0:
            self.list_widget.takeItem(row)
            if self.list_widget.count() == 0:
                self.stack.setCurrentIndex(0)
        self._refresh_selection_visuals()
        self._update_import_button()
        if removed_path is not None:
            self.files_removed.emit([removed_path])

    def _apply_filter(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            # Use the data role or item text for filtering
            path_str = str(item.data(MEDIA_PATH_ROLE) or "")
            name = Path(path_str).name.lower()
            item.setHidden(query not in name)

    def _add_many(self, paths: list[Path]) -> None:
        for p in paths:
            self.add_media(p)
        if not self._loading_library:
            self.files_imported.emit(paths)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        widget = self.list_widget.itemWidget(item)
        path = Path(item.data(MEDIA_PATH_ROLE))
        if isinstance(widget, _MediaItemWidget) and widget.is_missing():
            self.relink_requested.emit(path)
            return
        self.media_double_clicked.emit(path)

    def _on_selection_changed(self) -> None:
        self._refresh_selection_visuals()
        selected = self.list_widget.selectedItems()
        if not selected:
            self.media_selection_changed.emit(None)
            return
        item = selected[0]
        raw = item.data(MEDIA_PATH_ROLE)
        self.media_selection_changed.emit(Path(str(raw)) if raw else None)

    def _update_import_button(self) -> None:
        has_items = self.list_widget.count() > 0
        self.import_btn.setVisible(has_items)
        self.add_voice_btn.setVisible(False)
        self.header_container.setVisible(True)

    def _refresh_selection_visuals(self) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, _MediaItemWidget):
                widget.set_selected(bool(item.isSelected()))

    def update_added_states(self, used_norm_paths: set[str]) -> None:
        """Update the 'Added' badge on media items based on whether they are in the project."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            norm_path = item.data(MEDIA_NORM_PATH_ROLE)
            widget = self.list_widget.itemWidget(item)
            if isinstance(widget, _MediaItemWidget):
                widget.set_added(norm_path in used_norm_paths)

    def _emit_add_item(self, item: QListWidgetItem) -> None:
        raw = str(item.data(MEDIA_PATH_ROLE) or "").strip()
        if not raw:
            return
        self.media_add_requested.emit(Path(raw))

    def set_imported_entries(
        self,
        entries: list[object],  # forward-ref LibraryEntry
        missing_flags: list[bool] | None = None,
    ) -> None:
        """Replace the panel's contents with library entries + missing flags.

        Called by MainWindow on project load.
        """
        self.list_widget.clear()
        if not entries:
            self.stack.setCurrentIndex(0)
            self._update_import_button()
            return
        flags = missing_flags or [False] * len(entries)
        self._loading_library = True
        try:
            for entry, missing in zip(entries, flags):
                try:
                    # entry may be LibraryEntry or string (backward compat)
                    src = getattr(entry, "source", str(entry))
                    path_obj = Path(src)
                except Exception:
                    continue
                self.add_media(path_obj, missing=bool(missing))
        finally:
            self._loading_library = False

    def set_imported_paths(self, paths: list[Path]) -> None:
        """Backward-compat alias for list[Path]."""
        self.set_imported_entries(
            [type("E", (), {"source": str(p)})() for p in paths],
            missing_flags=[False] * len(paths),
        )


__all__ = ["MediaLibraryPanel"]
