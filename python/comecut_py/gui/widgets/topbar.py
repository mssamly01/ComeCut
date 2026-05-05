"""Top bar: brand on the left, project title in the center, action buttons right."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QSize, Qt, Signal  # type: ignore
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygon  # type: ignore
from PySide6.QtSvg import QSvgRenderer  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedLayout,
    QWidget,
)


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TopBar(QFrame):
    """Custom title bar that supports dragging and window controls."""

    plugins_clicked = Signal()
    export_clicked = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()
    project_title_changed = Signal(str)

    def __init__(self, brand: str = "ComeCut") -> None:
        super().__init__()
        self.setObjectName("topBar")
        self.setFixedHeight(40)
        self.setStyleSheet(
            "QFrame#topBar { background: #111318; border-bottom: 1px solid #1a1d23; }"
        )

        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(12)

        # Left: logo + brand + menu.
        left_container = QWidget(self)
        left_container.setStyleSheet("background: transparent; border: none;")
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        brand_lbl = QLabel(
            f"<span style='color:#22d3c5; font-size:16px;'>&#8226;</span> "
            f"<span style='font-weight:700; font-size:13px;'>{brand}</span>"
        )
        brand_lbl.setStyleSheet("color: #e6e8ec; background: transparent;")
        left_layout.addWidget(brand_lbl)

        self.menu_btn = QPushButton("Menu")
        self.menu_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._menu_icon_down = self._make_capcut_menu_arrow_icon(up=False)
        self._menu_icon_up = self._make_capcut_menu_arrow_icon(up=True)
        self.menu_btn.setIcon(self._menu_icon_down)
        self.menu_btn.setIconSize(QSize(10, 10))
        self.menu_btn.setFixedHeight(24)
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setStyleSheet(
            """
            QPushButton {
                background: #2a2f3a;
                color: #f3f6fb;
                border: 1px solid #3c4452;
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #323947; border-color: #4a5667; }
            QPushButton:pressed { background: #242a35; border-color: #3b4554; }
            QPushButton::menu-indicator { image: none; width: 0; }
            """
        )
        left_layout.addWidget(self.menu_btn)
        layout.addWidget(left_container)

        layout.addStretch(1)

        # Center: editable project title.
        self._title_value = "Untitled"
        self._editing_title = False

        title_wrap = QWidget(self)
        title_wrap.setStyleSheet("background: transparent; border: none;")
        self._title_wrap = title_wrap
        self._title_stack = QStackedLayout(title_wrap)
        self._title_stack.setContentsMargins(0, 0, 0, 0)

        self._project_lbl = _ClickableLabel("Untitled")
        self._project_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._project_lbl.setCursor(Qt.CursorShape.IBeamCursor)
        self._project_lbl.setFixedHeight(40)
        self._project_lbl.setStyleSheet(
            "color: #8c93a0; font-size: 11px; background: transparent; padding: 0px; font-weight: 600;"
        )
        self._project_lbl.clicked.connect(self._begin_title_edit)

        self._project_edit = QLineEdit("Untitled")
        self._project_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._project_edit.setMinimumWidth(1)
        self._project_edit.setFixedHeight(40)
        self._project_edit.setStyleSheet(
            """
            QLineEdit {
                color: #e6e8ec;
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                font-size: 11px;
                font-weight: 600;
            }
            QLineEdit:focus {
                border: none;
                background: transparent;
            }
            """
        )
        self._project_edit.editingFinished.connect(self._commit_title_edit)
        self._project_edit.textChanged.connect(lambda _t: self._sync_title_width(editing=True))

        self._title_stack.addWidget(self._project_lbl)
        self._title_stack.addWidget(self._project_edit)
        self._title_stack.setCurrentWidget(self._project_lbl)
        layout.addWidget(title_wrap)
        self._sync_title_width()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        layout.addStretch(1)

        # Right actions + window controls.
        right_container = QWidget(self)
        right_container.setStyleSheet("background: transparent; border: none;")
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)


        self.export_btn = QPushButton("  Xuất")
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.setFixedHeight(28)
        self.export_btn.clicked.connect(self.export_clicked.emit)
        
        # Render embedded Export SVG
        export_svg = """<svg viewBox="0 0 17 17" version="1.1" xmlns="http://www.w3.org/2000/svg" fill="#ffffff"><path d="M4.359 5.956l-0.718-0.697 4.859-5.005 4.859 5.005-0.718 0.696-3.641-3.75v10.767h-1v-10.767l-3.641 3.751zM16 9.030v6.47c0 0.276-0.224 0.5-0.5 0.5h-14c-0.276 0-0.5-0.224-0.5-0.5v-6.475h-1v6.475c0 0.827 0.673 1.5 1.5 1.5h14c0.827 0 1.5-0.673 1.5-1.5v-6.47h-1z" fill="#ffffff"></path></svg>"""
        renderer = QSvgRenderer(QByteArray(export_svg.encode("utf-8")))
        if renderer.isValid():
            pix = QPixmap(14, 14)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            self.export_btn.setIcon(QIcon(pix))
            self.export_btn.setIconSize(QSize(14, 14))

        self.export_btn.setStyleSheet(
            """
            QPushButton {
                background: #22d3c5;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
                margin-right: 12px;
            }
            QPushButton:hover { background: #2fe6d8; }
            QPushButton:pressed { background: #18bdb0; }
            """
        )
        right_layout.addWidget(self.export_btn)

        win_controls = QWidget(self)
        win_controls.setStyleSheet("background: transparent; border: none;")
        win_ctrl_layout = QHBoxLayout(win_controls)
        win_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        win_ctrl_layout.setSpacing(0)

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

        min_btn = QPushButton("\uE921")
        min_btn.setStyleSheet(ctrl_style)
        min_btn.clicked.connect(self.minimize_requested.emit)
        win_ctrl_layout.addWidget(min_btn)

        self.max_btn = QPushButton("\uE922")
        self.max_btn.setStyleSheet(ctrl_style)
        self.max_btn.clicked.connect(self.maximize_requested.emit)
        win_ctrl_layout.addWidget(self.max_btn)

        close_btn = QPushButton("\uE8BB")
        close_btn.setStyleSheet(ctrl_style + " QPushButton:hover { background: #e81123; color: white; }")
        close_btn.clicked.connect(self.close_requested.emit)
        win_ctrl_layout.addWidget(close_btn)

        right_layout.addWidget(win_controls)
        layout.addWidget(right_container)

    def set_project_title(self, name: str) -> None:
        title = (name or "").strip() or "Untitled"
        self._title_value = title
        self._project_lbl.setText(title)
        if not self._editing_title:
            self._project_edit.setText(title)
        self._sync_title_width()

    def _begin_title_edit(self) -> None:
        if self._editing_title:
            return
        self._editing_title = True
        self._project_edit.setText(self._title_value)
        self._sync_title_width(editing=True)
        self._title_stack.setCurrentWidget(self._project_edit)
        self._project_edit.setFocus(Qt.FocusReason.MouseFocusReason)
        self._project_edit.selectAll()

    def _commit_title_edit(self) -> None:
        if not self._editing_title:
            return
        new_title = (self._project_edit.text() or "").strip() or "Untitled"
        changed = new_title != self._title_value
        self._editing_title = False
        self._title_value = new_title
        self._project_lbl.setText(new_title)
        self._project_edit.setText(new_title)
        self._title_stack.setCurrentWidget(self._project_lbl)
        self._sync_title_width(editing=False)
        if changed:
            self.project_title_changed.emit(new_title)

    def _sync_title_width(self, editing: bool | None = None) -> None:
        if editing is None:
            editing = self._editing_title
        text = self._project_edit.text() if editing else self._project_lbl.text()
        text = text or "Untitled"
        metrics = self._project_lbl.fontMetrics()
        width = max(36, min(320, metrics.horizontalAdvance(text) + 8))
        self._title_wrap.setFixedWidth(width)
        self._project_lbl.setFixedWidth(width)
        self._project_edit.setFixedWidth(width)

    def eventFilter(self, watched, event) -> bool:
        if self._editing_title and event.type() == QEvent.Type.MouseButtonPress:
            gpos = None
            if hasattr(event, "globalPosition"):
                gpos = event.globalPosition().toPoint()
            elif hasattr(event, "globalPos"):
                gpos = event.globalPos()
            if gpos is not None:
                top_left = self._project_edit.mapToGlobal(QPoint(0, 0))
                rect = QRect(top_left, self._project_edit.size())
                if not rect.contains(gpos):
                    self._commit_title_edit()
        return super().eventFilter(watched, event)

    def set_menu_opened(self, opened: bool) -> None:
        self.menu_btn.setIcon(self._menu_icon_up if opened else self._menu_icon_down)

    @staticmethod
    def _make_capcut_menu_arrow_icon(*, up: bool = False) -> QIcon:
        pix = QPixmap(10, 10)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#22d3c5"))
        if up:
            triangle = QPolygon([QPoint(2, 7), QPoint(8, 7), QPoint(5, 3)])
        else:
            triangle = QPolygon([QPoint(2, 3), QPoint(8, 3), QPoint(5, 7)])
        painter.drawPolygon(triangle)
        painter.end()
        return QIcon(pix)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.window().move(self.window().x() + delta.x(), self.window().y() + delta.y())
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_requested.emit()
            event.accept()


__all__ = ["TopBar"]
