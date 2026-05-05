"""Home / project selection screen for the ComeCut desktop app."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Signal  # type: ignore
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap  # type: ignore
from PySide6.QtSvg import QSvgRenderer  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QDialog,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ...core.project import Project, Track
from ...core.store import ProjectMeta, delete_project, list_projects, load_project, save_project
from ...core.time_utils import format_timecode


def _resource_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[4].joinpath(*parts)


def svg_to_icon(svg_str: str, size: QSize = QSize(24, 24), color: str | None = None) -> QIcon:
    """Render an SVG string to a QIcon with optional color override."""
    if color:
        # Simple replacement for currentColor in the SVG string
        svg_str = svg_str.replace('currentColor', color)
    renderer = QSvgRenderer(svg_str.encode())
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# --- Icons ---
IC_HOME = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>'
IC_GLOBE = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>'
IC_CHECK = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>'
IC_PLUS = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>'
IC_SEARCH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>"""
IC_WARNING = """<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><path d="M5.9 62c-3.3 0-4.8-2.4-3.3-5.3L29.3 4.2c1.5-2.9 3.9-2.9 5.4 0l26.7 52.5c1.5 2.9 0 5.3-3.3 5.3z" fill="#ffce31"/><g fill="#ffffff"><path d="m27.8 23.6 2.8 18.5c.3 1.8 2.6 1.8 2.9 0l2.7-18.5c.5-7.2-8.9-7.2-8.4 0"/><circle cx="32" cy="49.6" r="4.2"/></g></svg>"""


class DeleteConfirmDialog(QDialog):
    """Custom deletion confirmation dialog styled like CapCut."""

    def __init__(self, parent: QWidget | None = None, count: int = 1) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("DeleteDialogContainer")
        container.setStyleSheet("""
            #DeleteDialogContainer {
                background-color: #2a2f38;
                border: 1px solid #3c4452;
                border-radius: 12px;
            }
        """)
        
        inner_layout = QVBoxLayout(container)
        inner_layout.setContentsMargins(20, 20, 20, 20)
        inner_layout.setSpacing(12)

        # Icon
        icon_label = QLabel()
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setPixmap(svg_to_icon(IC_WARNING, QSize(48, 48)).pixmap(48, 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner_layout.addWidget(icon_label)

        # Subtitle
        sub = QLabel(f"Bạn có chắc chắn muốn xóa {count} dự án đã chọn? Các mục này sẽ bị xóa vĩnh viễn.")
        sub.setStyleSheet("color: #798292; font-size: 13px; background: transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        inner_layout.addWidget(sub)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        ok_btn = QPushButton("OK")
        ok_btn.setFixedSize(110, 32)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #22d3c5;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #1ebdb0; }
        """)
        ok_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("Hủy")
        cancel_btn.setFixedSize(110, 32)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c4452;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #4b5563; }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        inner_layout.addLayout(btn_layout)

        layout.addWidget(container)


IC_VIDEO = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"></polygon><rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect></svg>'


_IC_CHECKED = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 191.667 191.667">
  <circle cx="95.833" cy="95.833" r="95.833" fill="#22d3c5"/>
  <path fill="#ffffff" d="M150.862 79.646l-60.207 60.207a13.46 13.46 0 0 1-9.583 3.969c-3.62 0-7.023-1.409-9.583-3.969l-30.685-30.685a13.46 13.46 0 0 1-3.97-9.583c0-3.621 1.41-7.024 3.97-9.584a13.46 13.46 0 0 1 9.583-3.97c3.62 0 7.024 1.41 9.583 3.971l21.101 21.1 50.623-50.623a13.46 13.46 0 0 1 9.583-3.969c3.62 0 7.023-1.409 9.583 3.969 5.286 5.286 5.286 13.883.002 19.167"/>
</svg>"""


class SelectionTick(QWidget):
    """A small circular toggle widget that looks like CapCut's project selection tick."""

    toggled = Signal(bool)

    def __init__(self, size: int = 18, parent=None) -> None:
        super().__init__(parent)
        self._checked = False
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._renderer_checked = QSvgRenderer(_IC_CHECKED.encode())

    @property
    def checked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if self._checked != value:
            self._checked = value
            self.update()
            self.toggled.emit(value)

    def isChecked(self) -> bool:
        return self._checked

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size

        if self._checked:
            self._renderer_checked.render(painter)
        else:
            # Draw empty circle with white border
            painter.setPen(QColor(255, 255, 255, 200))
            painter.setBrush(QColor(0, 0, 0, 100))
            painter.drawEllipse(1, 1, s - 2, s - 2)

        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            event.accept()


class ProjectCard(QFrame):
    """Clickable project card used by the HomeWindow grid, styled like CapCut."""

    open_requested = Signal(str)
    selection_changed = Signal(bool)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    duplicate_requested = Signal(str)
    rename_finished = Signal(str, str)

    def __init__(
        self,
        project_id: str,
        title: str,
        duration: str,
        thumbnail: Path | None = None,
        show_checkbox: bool = False,
    ) -> None:
        super().__init__()
        self._project_id = project_id
        self._title = title
        self.setObjectName("ProjectCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(100)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Thumbnail with rounded corners
        self.thumb_label = QLabel()
        self.thumb_label.setObjectName("ProjectThumbnail")
        self.thumb_label.setFixedSize(100, 100)
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        if thumbnail and thumbnail.exists():
            pix = QPixmap(str(thumbnail))
            if not pix.isNull():
                # Apply rounded corners to the pixmap
                rounded = QPixmap(pix.size())
                rounded.fill(Qt.GlobalColor.transparent)
                
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                
                from PySide6.QtGui import QPainterPath # type: ignore
                path = QPainterPath()
                # Use a smaller radius (12px) for less rounding
                path.addRoundedRect(0, 0, pix.width(), pix.height(), 12, 12) 
                
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, pix)
                painter.end()
                
                self.thumb_label.setPixmap(rounded)
            else:
                self.thumb_label.setText("Project")
        else:
            self.thumb_label.setText("Project")
        
        layout.addWidget(self.thumb_label)

        # Selection tick (CapCut style) - custom painted widget
        self.tick = SelectionTick(size=18, parent=self.thumb_label)
        self.tick.move(100 - 22, 100 - 22)  # bottom-right of 100x100 thumb
        self.tick.hide()
        self.tick.toggled.connect(self.selection_changed.emit)

        # If in global selection mode, keep it visible
        if show_checkbox:
            self.tick.show()
        self._global_selection_mode = show_checkbox

        # Info section
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(2, 0, 2, 4)
        info_layout.setSpacing(1)
        
        from PySide6.QtWidgets import QStackedWidget # type: ignore
        self._title_stack = QStackedWidget()
        
        # Display mode (Label)
        metrics = self.fontMetrics()
        elided_title = metrics.elidedText(title, Qt.TextElideMode.ElideMiddle, 100)
        self.title_label = QLabel(elided_title)
        self.title_label.setObjectName("ProjectTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.title_label.setToolTip(title)
        self._title_stack.addWidget(self.title_label)
        
        # Edit mode (LineEdit)
        self.title_edit = QLineEdit(title)
        self.title_edit.setObjectName("ProjectTitleEdit")
        self.title_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.title_edit.setStyleSheet("""
            #ProjectTitleEdit {
                background: #1a1d23;
                color: #ffffff;
                border: none;
                border-radius: 2px;
                font-size: 11px;
                padding: 1px;
            }
            #ProjectTitleEdit:focus {
                border: 1px solid #22d3c5;
            }
        """)
        self.title_edit.editingFinished.connect(self._finish_rename)
        self._title_stack.addWidget(self.title_edit)
        
        info_layout.addWidget(self._title_stack)
        
        meta_label = QLabel(duration)
        meta_label.setObjectName("ProjectMeta")
        meta_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        info_layout.addWidget(meta_label)
        
        layout.addLayout(info_layout)
        # Remove addStretch to keep card area compact around content
        self.setFixedHeight(145)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt override
        from PySide6.QtWidgets import QMenu # type: ignore
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2f38;
                color: #e6e8ec;
                border: 1px solid #3c4452;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 24px;
                border-radius: 2px;
            }
            QMenu::item:selected {
                background-color: #3c4452;
            }
        """)
        
        rename_act = menu.addAction("Đổi tên")
        rename_act.triggered.connect(self.start_rename)
        
        duplicate_act = menu.addAction("Bản sao")
        duplicate_act.triggered.connect(lambda: self.duplicate_requested.emit(self._project_id))
        
        delete_act = menu.addAction("Xóa")
        delete_act.triggered.connect(lambda: self.delete_requested.emit(self._project_id))
        
        menu.exec(event.globalPos())

    def start_rename(self) -> None:
        """Switch to edit mode."""
        self._title_stack.setCurrentIndex(1)
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _finish_rename(self) -> None:
        """Switch back to display mode and notify."""
        if self._title_stack.currentIndex() == 0:
            return
            
        new_name = self.title_edit.text().strip()
        if new_name and new_name != self._title:
            self.rename_finished.emit(self._project_id, new_name)
        
        self._title_stack.setCurrentIndex(0)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.tick.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self.tick.isChecked() and not self._global_selection_mode:
            self.tick.hide()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            # If the tick was clicked, do nothing here (it handles itself)
            if self.tick.underMouse():
                return
                
            if self._global_selection_mode:
                self.tick.setChecked(not self.tick.isChecked())
            else:
                self.open_requested.emit(self._project_id)
        super().mouseReleaseEvent(event)


class HomeWindow(QMainWindow):
    """Frameless project selection window shown before the editor."""

    new_project_requested = Signal(str)
    open_project_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._drag_position: QPoint | None = None
        self._metas: list[ProjectMeta] = []
        self._cards: list[ProjectCard] = []
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setWindowTitle("ComeCut Home")
        self.resize(1100, 760)
        self.setMinimumSize(900, 620)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._build_ui()
        self.refresh_projects()

    def _build_ui(self) -> None:
        root = QWidget(objectName="HomeRoot")
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_main(), 1)
        self.setCentralWidget(root)
        self.setStyleSheet(_HOME_QSS)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame(objectName="HomeSidebar")
        sidebar.setFixedWidth(260)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header Area
        header = QFrame(objectName="SidebarHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 30, 24, 30)
        header_layout.setSpacing(12)

        # Simple Circular Logo
        logo_icon = QFrame(objectName="LogoCircle")
        logo_icon.setFixedSize(48, 48)
        logo_inner_layout = QVBoxLayout(logo_icon)
        logo_inner_layout.setContentsMargins(0, 0, 0, 0)
        logo_inner_label = QLabel("C")
        logo_inner_label.setObjectName("LogoInnerText")
        logo_inner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_inner_layout.addWidget(logo_inner_label)
        header_layout.addWidget(logo_icon)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        logo_text = QLabel("ComeCut")
        logo_text.setObjectName("HomeLogoText")
        subtitle = QLabel("Lightweight Video Editor")
        subtitle.setObjectName("HomeSubtitle")
        title_layout.addWidget(logo_text)
        title_layout.addWidget(subtitle)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        layout.addWidget(header)

        # Nav Area
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(16, 0, 16, 0)
        nav_layout.setSpacing(8)

        self._home_btn = QPushButton("Home")
        self._home_btn.setObjectName("NavHome")
        self._home_btn.setIcon(svg_to_icon(IC_HOME, QSize(18, 18), "#ffffff"))
        self._home_btn.setIconSize(QSize(18, 18))
        self._home_btn.setFixedHeight(48)
        nav_layout.addWidget(self._home_btn)
        
        layout.addWidget(nav_container)
        layout.addStretch()
        
        return sidebar

    def _build_main(self) -> QFrame:
        main = QFrame(objectName="HomeMain")
        layout = QVBoxLayout(main)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Custom Title Bar
        title_bar = QWidget(objectName="HomeTitleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title_layout.addStretch()

        ctrl_style = """
            QPushButton {
                background: transparent;
                color: #e6e8ec;
                border: none;
                width: 46px;
                height: 40px;
                font-family: "Segoe MDL2 Assets", "Segoe UI Symbol", sans-serif;
                font-size: 10px;
                padding: 0;
            }
            QPushButton:hover { background: #2a2f38; }
            QPushButton:pressed { background: #363b46; }
        """

        minimize_btn = QPushButton("\uE921")
        minimize_btn.setObjectName("ChromeButton")
        minimize_btn.setStyleSheet(ctrl_style)
        minimize_btn.clicked.connect(self.showMinimized)
        title_layout.addWidget(minimize_btn)
        
        self._maximize_btn = QPushButton("\uE922")
        self._maximize_btn.setObjectName("ChromeButton")
        self._maximize_btn.setStyleSheet(ctrl_style)
        self._maximize_btn.clicked.connect(self._toggle_maximize)
        title_layout.addWidget(self._maximize_btn)
        
        close_btn = QPushButton("\uE8BB")
        close_btn.setObjectName("ChromeButton")
        close_btn.setStyleSheet(ctrl_style + " QPushButton:hover { background: #e81123; color: white; }")
        close_btn.clicked.connect(self.close)
        title_layout.addWidget(close_btn)
        layout.addWidget(title_bar)

        # Content Area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 20, 40, 40)
        content_layout.setSpacing(32)

        # Action Bar
        actions = QHBoxLayout()
        actions.setSpacing(16)
        
        new_btn = QPushButton("Tạo dự án")
        new_btn.setObjectName("NewProjectButton")
        new_btn.setIcon(svg_to_icon(IC_PLUS, QSize(16, 16), "#061312"))
        new_btn.setIconSize(QSize(16, 16))
        new_btn.clicked.connect(self._on_new_project_clicked)
        
        select_btn = QPushButton("Chọn dự án")
        select_btn.setObjectName("SelectProjectsButton")
        select_btn.setIcon(svg_to_icon(IC_CHECK, QSize(16, 16), "#e9edf4"))
        select_btn.setIconSize(QSize(16, 16))
        select_btn.clicked.connect(self._on_select_projects_clicked)
        
        actions.addWidget(new_btn)
        actions.addStretch()
        actions.addWidget(select_btn)
        content_layout.addLayout(actions)

        # List Header
        filters = QHBoxLayout()
        filters.setSpacing(8) # Tighten spacing between search components
        self._projects_header = QLabel("Dự án (0)")
        self._projects_header.setObjectName("ProjectsHeader")
        filters.addWidget(self._projects_header)
        filters.addStretch()
        
        self._search = QLineEdit()
        self._search.setObjectName("ProjectSearch")
        self._search.setPlaceholderText("Tìm kiếm dự án")
        self._search.setFixedWidth(210)
        self._search.setFixedHeight(32)
        self._search.textChanged.connect(self._refresh_project_grid)
        filters.addWidget(self._search)
        
        search_btn = QPushButton()
        search_btn.setObjectName("SearchButton")
        search_btn.setFixedSize(32, 32)
        search_btn.setIcon(svg_to_icon(IC_SEARCH, QSize(16, 16), "#e6e8ec"))
        search_btn.setIconSize(QSize(16, 16))
        filters.addWidget(search_btn)
        
        content_layout.addLayout(filters)

        # Grid
        self._cards_container = QWidget()
        self._grid = QGridLayout(self._cards_container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(24)
        self._grid.setVerticalSpacing(24)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        # Wrap grid in scroll area if needed, but for now just layout
        content_layout.addWidget(self._cards_container, 1)
        
        layout.addWidget(content, 1) # content stretches

        # --- Bottom Selection Bar ---
        self._bottom_bar = QFrame(objectName="BottomSelectionBar")
        self._bottom_bar.setFixedHeight(60)
        self._bottom_bar.hide() # Hidden by default
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(40, 0, 40, 0)
        
        self._selected_count_label = QLabel("Đã chọn 0")
        self._selected_count_label.setObjectName("SelectedCountLabel")
        bottom_layout.addWidget(self._selected_count_label)
        
        bottom_layout.addStretch()
        
        cancel_btn = QPushButton("Hủy")
        cancel_btn.setObjectName("CancelSelectionButton")
        cancel_btn.clicked.connect(self._on_select_projects_clicked) # Toggles off
        bottom_layout.addWidget(cancel_btn)
        
        delete_btn = QPushButton("Xóa")
        delete_btn.setObjectName("DeleteProjectsButton")
        delete_btn.clicked.connect(self._delete_selected_projects)
        bottom_layout.addWidget(delete_btn)

        layout.addWidget(self._bottom_bar)
        
        return main

    def refresh_projects(self) -> None:
        try:
            self._metas = list_projects()
        except Exception:
            self._metas = []
        self._refresh_project_grid()

    def _refresh_project_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        
        needle = (self._search.text() if hasattr(self, "_search") else "").strip().lower()
        filtered: list[ProjectMeta] = []
        for meta in self._metas:
            if not needle or needle in (meta.name or "").lower():
                filtered.append(meta)

        self._projects_header.setText(f"Dự án ({len(filtered)})")
        if not filtered:
            empty = QLabel("Chưa có dự án nào. Nhấp vào Tạo dự án để bắt đầu.")
            empty.setObjectName("ProjectMeta")
            self._grid.addWidget(empty, 0, 0)
            return

        self._cards.clear()
        columns = 9
        for i, meta in enumerate(filtered):
            row = i // columns
            col = i % columns
            card = self._build_project_card(meta)
            card.selection_changed.connect(self._update_selection_count)
            card.rename_finished.connect(self._on_rename_finished)
            card.duplicate_requested.connect(self._on_duplicate_project)
            card.delete_requested.connect(self._on_delete_project)
            self._cards.append(card)
            self._grid.addWidget(card, row, col)

    def _update_selection_count(self) -> None:
        """Count selected cards and update the bottom bar label."""
        count = sum(1 for card in self._cards if card.tick.isChecked())
        
        # If we selected something but were not in selection mode, enter it
        if count > 0 and not getattr(self, "_selection_mode", False):
            self._enter_selection_mode()
        elif count == 0 and getattr(self, "_selection_mode", False):
            # If everything unselected, exit selection mode automatically
            self._exit_selection_mode()
        
        if hasattr(self, "_selected_count_label"):
            self._selected_count_label.setText(f"Đã chọn {count}")

    def _delete_selected_projects(self) -> None:
        """Remove selected projects from disk and refresh."""
        selected = [card for card in self._cards if card.tick.isChecked()]
        if not selected:
            return
            
        # Custom Dialog
        dlg = DeleteConfirmDialog(self, count=len(selected))
        if self._exec_dialog_with_overlay(dlg) != QDialog.DialogCode.Accepted:
            return
            
        for card in selected:
            try:
                delete_project(card._project_id)
            except Exception:
                pass
        
        self._exit_selection_mode()
        self.refresh_projects()

    def _on_rename_finished(self, project_id: str, new_name: str) -> None:
        """Apply rename from inline edit."""
        try:
            project = load_project(project_id)
            project.name = new_name
            save_project(project, project_id=project_id)
            self.refresh_projects()
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể đổi tên dự án: {e}")

    def _on_duplicate_project(self, project_id: str) -> None:
        """Clone an existing project."""
        try:
            project = load_project(project_id)
            project.name = f"{project.name} - sao chép"
            # Save without project_id to create a new one
            save_project(project)
            self.refresh_projects()
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể tạo bản sao: {e}")

    def _on_delete_project(self, project_id: str) -> None:
        """Confirm and delete a single project."""
        dlg = DeleteConfirmDialog(self, count=1)
        if self._exec_dialog_with_overlay(dlg) == QDialog.DialogCode.Accepted:
            try:
                delete_project(project_id)
                self.refresh_projects()
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể xóa dự án: {e}")

    def _enter_selection_mode(self) -> None:
        """Helper to enter selection mode UI state."""
        self._selection_mode = True
        btn = self.findChild(QPushButton, "SelectProjectsButton")
        if btn:
            btn.setText("  Thoát chọn")
            btn.setIcon(svg_to_icon(IC_PLUS, QSize(16, 16), "#ffffff"))
        if hasattr(self, "_bottom_bar"):
            self._bottom_bar.show()
        
        # Tell all cards they are now in selection mode
        for card in self._cards:
            card._global_selection_mode = True

    def _exit_selection_mode(self) -> None:
        """Helper to exit selection mode UI state."""
        self._selection_mode = False
        btn = self.findChild(QPushButton, "SelectProjectsButton")
        if btn:
            btn.setText("  Chọn dự án")
            btn.setIcon(svg_to_icon(IC_CHECK, QSize(16, 16), "#e9edf4"))
        if hasattr(self, "_bottom_bar"):
            self._bottom_bar.hide()
        
        for card in self._cards:
            card._global_selection_mode = False
            card.tick.setChecked(False)
            card.tick.hide()

    def _exec_dialog_with_overlay(self, dlg: QDialog) -> int:
        """Executes a dialog while dimming the HomeWindow background."""
        overlay = QWidget(self)
        overlay.resize(self.size())
        overlay.setStyleSheet("background-color: rgba(0, 0, 0, 0.6);")
        overlay.show()
        
        result = dlg.exec()
        
        overlay.hide()
        overlay.deleteLater()
        return result

    def _build_project_card(self, meta: ProjectMeta) -> ProjectCard:
        thumb = None
        duration = "00:00:00"
        try:
            project = load_project(meta.project_id)
            duration = format_timecode(float(project.duration), millis=False)
            for track in project.tracks:
                for clip in track.clips:
                    src = Path(clip.source)
                    if src.exists():
                        # Use the engine to extract a single-frame thumbnail
                        from ...engine.thumbnails import render_filmstrip_png
                        rendered = render_filmstrip_png(src, frames=1, strip_width=240, strip_height=140)
                        if rendered:
                            thumb = rendered
                        else:
                            # Fallback to the file path itself (might be an image or just for name)
                            thumb = src
                        raise StopIteration
        except StopIteration:
            pass
        except Exception:
            pass
        
        if thumb is None:
            # Fallback to demo thumbnail if available
            thumb = _resource_path("resource", "images", "crads", "Portrait.jpg")
            
        is_sel = getattr(self, "_selection_mode", False)
        card = ProjectCard(meta.project_id, meta.name or "Untitled", duration, thumb, show_checkbox=is_sel)
        card.open_requested.connect(self.open_project_requested)
        return card

    def _on_new_project_clicked(self) -> None:
        project = Project(name=f"Untitled {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        project.tracks.append(Track(kind="video", name="Main"))
        try:
            meta = save_project(project)
        except Exception:
            return
        self.refresh_projects()
        self.new_project_requested.emit(meta.project_id)

    def _on_select_projects_clicked(self) -> None:
        """Toggle selection mode to manage projects."""
        if not getattr(self, "_selection_mode", False):
            self._enter_selection_mode()
        else:
            self._exit_selection_mode()
        
        # We don't necessarily need to refresh the whole grid, 
        # as cards now handle their own selection mode state change visually
        # but if we want to ensure everything is in sync:
        # self.refresh_projects()

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._maximize_btn.setText("\uE922")
        else:
            self.showMaximized()
            self._maximize_btn.setText("\uE923")

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.isMaximized():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._drag_position and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._drag_position = None
        super().mouseReleaseEvent(event)


_HOME_QSS = """
#HomeRoot { 
    background: #111318; 
    color: #f2f7f8; 
    font-family: "Inter", "Segoe UI", sans-serif; 
}

#HomeSidebar { 
    background: #16181d; 
    border-right: 1px solid #252936; 
}

#SidebarHeader {
    background: transparent;
}

#LogoCircle {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #22d3c5, stop:1 #111318);
    border-radius: 24px;
}

#LogoInnerText {
    color: #ffffff;
    font-size: 26px;
    font-weight: 900;
}

#HomeLogoText { 
    color: #ffffff; 
    background: transparent;
    font-size: 18px; 
    font-weight: 800; 
}

#HomeSubtitle { 
    color: #798292; 
    background: transparent;
    font-size: 11px; 
}

#NavHome { 
    background: transparent; 
    color: #ffffff; 
    border: none; 
    text-align: left; 
    padding-left: 0; 
    font-size: 14px; 
    font-weight: 700; 
}

#HomeMain { 
    background: #0c0e12; 
}

#HomeTitleBar {
    background: transparent;
}

#ChromeButton { 
    background: transparent; 
    color: #98a3b3; 
    border: none; 
    padding: 6px 12px; 
    font-size: 14px; 
    font-weight: bold;
}

#ChromeButton:hover { 
    color: #ffffff; 
    background: #252a35; 
    border-radius: 6px; 
}

#NewProjectButton { 
    background: #22d3c5; 
    color: #061312; 
    border: none; 
    border-radius: 20px; 
    padding: 12px 30px; 
    font-size: 15px; 
    font-weight: 800; 
}

#NewProjectButton:hover { 
    background: #35eadc; 
}

#SelectProjectsButton { 
    background: transparent; 
    color: #e9edf4; 
    border: 1px solid #333a47; 
    border-radius: 20px; 
    padding: 12px 24px; 
    font-size: 14px; 
    font-weight: 700; 
}

#SelectProjectsButton:hover {
    background: #1e222a;
}

#ProjectsHeader { 
    color: #ffffff; 
    font-size: 14px; 
    font-weight: 700; 
}

#ProjectSearch {
    background: #2a2f38;
    border: 1px solid #3c4452;
    border-radius: 4px;
    color: #e6e8ec;
    font-size: 13px;
    padding: 0 10px;
    selection-background-color: #22d3c5;
}

#SearchButton {
    background: #2a2f38;
    border: 1px solid #3c4452;
    border-radius: 4px;
    padding: 0;
}

#SearchButton:hover {
    background: #3c4452;
}

#ProjectCard { 
    background: transparent; 
    border: none; 
}

#ProjectThumbnail { 
    background: #1a1d23;
    border: 1px solid #2d333f;
    border-radius: 8px; 
}

#ProjectTitle { 
    color: #ffffff; 
    font-size: 12px; 
}

#ProjectMeta { 
    color: #5c6779; 
    font-size: 12px; 
}

#BottomSelectionBar {
    background: #2a2f38;
    border-top: 1px solid #3c4452;
}

#SelectedCountLabel {
    color: #e6e8ec;
    background: transparent;
    font-size: 14px;
    font-weight: 500;
}

#CancelSelectionButton {
    background: #3c4452;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}

#CancelSelectionButton:hover {
    background: #4b5563;
}

#DeleteProjectsButton {
    background: transparent;
    color: #ff4d4f;
    border: 1px solid #ff4d4f;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
    margin-left: 12px;
}

#DeleteProjectsButton:hover {
    background: rgba(255, 77, 79, 0.1);
}
"""
