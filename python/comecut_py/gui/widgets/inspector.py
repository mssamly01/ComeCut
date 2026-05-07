"""Right panel - project + clip properties."""

from __future__ import annotations

import re
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (  # type: ignore
    QAbstractTableModel,
    QByteArray,
    QEvent,
    QModelIndex,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap, QTransform  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStyledItemDelegate,
    QStyle,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.project import Clip, Project, Track
from ...core.text_style_presets import (
    apply_text_style_payload,
    apply_text_style_preset,
    list_text_style_presets,
    save_text_style_preset,
    text_style_payload_from_clip,
)
from ...subtitles.cue import Cue, CueList
from .inspector_audio import AudioPropertiesBox
from .inspector_video import VideoPropertiesBox

try:
    from PySide6.QtSvg import QSvgRenderer  # type: ignore
except Exception:  # pragma: no cover - optional dependency on some runtimes
    QSvgRenderer = None

_SYMBOL_RE = re.compile(
    r'<symbol\s+id="(?P<id>[^"]+)"(?P<attrs>[^>]*)>(?P<body>.*?)</symbol>',
    re.DOTALL,
)
_PROPERTIES_SYMBOL_CACHE: dict[str, tuple[str, str]] | None = None
_ICON_COLOR = "#a6acb8"
_MAIN_TRANSLATE_SVG = """
<svg width="800" height="800" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <path fill="none" d="M0 0h20v20H0z"/>
  <path fill="#e6f7fb" d="M11 7H9.49c-.63 0-1.25.3-1.59.7L7 5H4.13l-2.39 7h1.69l.74-2H7v4H2c-1.1 0-2-.9-2-2V5c0-1.1.9-2 2-2h7c1.1 0 2 .9 2 2zM6.51 9H4.49l1-2.93zM10 8h7c1.1 0 2 .9 2 2v7c0 1.1-.9 2-2 2h-7c-1.1 0-2-.9-2-2v-7c0-1.1.9-2 2-2m7.25 5v-1.08h-3.17V9.75h-1.16v2.17H9.75V13h1.28c.11.85.56 1.85 1.28 2.62-.87.36-1.89.62-2.31.62-.01.02.22.97.2 1.46.84 0 2.21-.5 3.28-1.15 1.09.65 2.48 1.15 3.34 1.15-.02-.49.2-1.44.2-1.46-.43 0-1.49-.27-2.38-.63.7-.77 1.14-1.77 1.25-2.61zm-3.81 1.93c-.5-.46-.85-1.13-1.01-1.93h2.09c-.17.8-.51 1.47-1 1.93l-.04.03s-.03-.02-.04-.03"/>
</svg>
"""

_SEARCH_PREV_SVG = """
<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path d="M17.45 2.11a1 1 0 0 0-1.05.09l-12 9a1 1 0 0 0 0 1.6l12 9a1 1 0 0 0 1.05.09A1 1 0 0 0 18 21V3a1 1 0 0 0-.55-.89" fill="#a6acb8"/>
</svg>
"""

_SEARCH_NEXT_SVG = """
<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path d="m18.6 11.2-12-9A1 1 0 0 0 5 3v18a1 1 0 0 0 .55.89 1 1 0 0 0 1-.09l12-9a1 1 0 0 0 0-1.6Z" fill="#a6acb8"/>
</svg>
"""

_TRASH_ICON_SVG = """
<svg viewBox="-2 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path fill-rule="evenodd" clip-rule="evenodd" d="M5 3a3 3 0 0 1 3-3h4a3 3 0 0 1 3 3h2a3 3 0 0 1 3 3 1 1 0 0 1-1 1H1a1 1 0 0 1-1-1 3 3 0 0 1 3-3zM2 9h16a1 1 0 0 1 1 1v11a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3V10a1 1 0 0 1 1-1m3 4.143v5.714C5 19.488 5.448 20 6 20s1-.512 1-1.143v-5.714C7 12.512 6.552 12 6 12s-1 .512-1 1.143m4 0v5.714C9 19.488 9.448 20 10 20s1-.512 1-1.143v-5.714c0-.631-.448-1.143-1-1.143s-1 .512-1 1.143m4 0v5.714c0 .631.448 1.143 1 1.143s1-.512 1-1.143v-5.714c0-.631-.448-1.143-1-1.143s-1 .512-1 1.143M8 2a1 1 0 0 0-1 1h6a1 1 0 0 0-1-1z" fill="#ef4444"/>
</svg>
"""

_TRASH_ICON_GREY_SVG = """
<svg viewBox="-2 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path fill-rule="evenodd" clip-rule="evenodd" d="M5 3a3 3 0 0 1 3-3h4a3 3 0 0 1 3 3h2a3 3 0 0 1 3 3 1 1 0 0 1-1 1H1a1 1 0 0 1-1-1 3 3 0 0 1 3-3zM2 9h16a1 1 0 0 1 1 1v11a3 3 0 0 1-3 3H4a3 3 0 0 1-3-3V10a1 1 0 0 1 1-1m3 4.143v5.714C5 19.488 5.448 20 6 20s1-.512 1-1.143v-5.714C7 12.512 6.552 12 6 12s-1 .512-1 1.143m4 0v5.714C9 19.488 9.448 20 10 20s1-.512 1-1.143v-5.714c0-.631-.448-1.143-1-1.143s-1 .512-1 1.143m4 0v5.714c0 .631.448 1.143 1 1.143s1-.512 1-1.143v-5.714c0-.631-.448-1.143-1-1.143s-1 .512-1 1.143M8 2a1 1 0 0 0-1 1h6a1 1 0 0 0-1-1z" fill="#a6acb8"/>
</svg>
"""

_PLUS_ICON_SVG = """
<svg width="48" height="48" viewBox="0 0 48 48" version="1" xmlns="http://www.w3.org/2000/svg">
  <circle fill="#22d3c5" cx="24" cy="24" r="21"/>
  <g fill="#fff">
    <path d="M21 14h6v20h-6z"/>
    <path d="M14 21h20v6H14z"/>
    </g>
  </svg>
  """

_REPLACE_ICON_SVG = """
<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">
  <g fill="#a6acb8" fill-rule="evenodd">
    <path d="M0 0h13.931v.983H0zm0 2h13.931v.942H0zm0 12h10.958v.951H0zm8.49-9.946C6.01 4.054 4 6.047 4 8.506s2.01 4.452 4.49 4.452 4.489-1.993 4.489-4.452-2.008-4.452-4.489-4.452m0 7.964a3.54 3.54 0 1 1 0-7.08 3.54 3.54 0 1 1 0 7.08m7.448 2.593-1.361 1.361-2.996-2.996s.57-.073.931-.434c.361-.362.431-.928.431-.928z"/>
    <path d="M8.677 6.43c.526 0 .329-.4-.403-.4a2.267 2.267 0 0 0-2.279 2.256c0 .725.404.921.404.4C6.398 7.44 7.418 6.43 8.677 6.43M0 4h3.973v.962H0zm0 2h3v.973H0zm0 2h2.98v.993H0zm0 2h3.02v.973H0zm0 2h4v.931H0z"/>
  </g>
</svg>
"""




class _MultiLineEdit(QPlainTextEdit):
    """A multi-line QPlainTextEdit that supports up to 3 lines without scrolling.

    The global stylesheet adds padding: 8px top/bottom + 1px border,
    so height = N*lineSpacing + 2*8 + 2*1 = N*lineSpacing + 18.
    """

    def __init__(self, parent=None, lines: int = 3):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        line_h = self.fontMetrics().lineSpacing()
        self.setFixedHeight(int(line_h * lines) + 18)

    def ensureCursorVisible(self):
        # We allow normal scrolling now that we have more space, 
        # but we can still ensure it doesn't jump unnecessarily.
        super().ensureCursorVisible()


def _load_property_symbols() -> dict[str, tuple[str, str]]:
    global _PROPERTIES_SYMBOL_CACHE
    if _PROPERTIES_SYMBOL_CACHE is not None:
        return _PROPERTIES_SYMBOL_CACHE
    symbols: dict[str, tuple[str, str]] = {}
    icon_sheet = Path(__file__).resolve().parents[4] / "index.html"
    try:
        raw = icon_sheet.read_text(encoding="utf-8")
    except OSError:
        _PROPERTIES_SYMBOL_CACHE = symbols
        return symbols
    for m in _SYMBOL_RE.finditer(raw):
        symbol_id = m.group("id")
        if symbol_id.startswith("icon-editor-properties-"):
            symbols[symbol_id] = (m.group("attrs"), m.group("body"))
    _PROPERTIES_SYMBOL_CACHE = symbols
    return symbols


def _property_icon(symbol_id: str, color: str = _ICON_COLOR, size: int = 14) -> QIcon:
    if QSvgRenderer is None:
        return QIcon()
    symbol = _load_property_symbols().get(symbol_id)
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


def _icon_from_svg(svg_text: str, size: int = 14) -> QIcon:
    if QSvgRenderer is None:
        return QIcon()
    data = QByteArray(svg_text.encode("utf-8"))
    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return QIcon()
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter)
    painter.end()
    return QIcon(pix)


def _rotate_icon(icon: QIcon, degrees: float, size: int = 14) -> QIcon:
    if icon.isNull():
        return QIcon()
    pix = icon.pixmap(size, size)
    rot = pix.transformed(QTransform().rotate(degrees), Qt.TransformationMode.SmoothTransformation)
    return QIcon(rot)


class _CaptionEditDelegate(QStyledItemDelegate):
    """Ensure inline editor font matches table row font."""

    def createEditor(self, parent, option, index):  # type: ignore[override]
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            item_font = index.data(Qt.ItemDataRole.FontRole)
            if item_font is not None:
                editor.setFont(item_font)
            editor.setFrame(False)
            editor.setTextMargins(0, 0, 0, 0)
            # Keep editor opaque so source cell text is not visible behind it.
            editor.setStyleSheet(
                "QLineEdit {"
                " background:#10383b;"
                " color:#eafffb;"
                " border:none;"
                " padding:0;"
                " margin:0;"
                "}"
            )
        return editor


class _CaptionTextDelegate(_CaptionEditDelegate):
    """Paint yellow in-cell highlight spans for caption search matches."""

    def __init__(self, owner: "_CaptionListWidget") -> None:
        super().__init__(owner._table)
        self._owner = owner

    def paint(self, painter, option, index):  # type: ignore[override]
        super().paint(painter, option, index)

        spans = self._owner._match_spans_for_row(index.row())
        if not spans:
            return
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not text:
            return

        painter.save()
        fm = painter.fontMetrics()
        text_rect = option.rect.adjusted(4, 0, -4, 0)
        for start, end in spans:
            if end <= start:
                continue
            prefix_w = fm.horizontalAdvance(text[:start])
            match_w = fm.horizontalAdvance(text[start:end])
            if match_w <= 0:
                continue
            painter.fillRect(
                text_rect.x() + prefix_w,
                text_rect.y(),
                match_w,
                text_rect.height(),
                QColor(255, 235, 59, 110),
            )

        role = (
            option.palette.ColorRole.HighlightedText
            if (option.state & QStyle.StateFlag.State_Selected)
            else option.palette.ColorRole.Text
        )
        painter.setPen(option.palette.color(role))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        painter.restore()


class _CaptionTableModel(QAbstractTableModel):
    text_edited = Signal(object, str)  # Clip, new_text

    def __init__(self, item_font) -> None:
        super().__init__()
        self._clips: list[Clip] = []
        self._item_font = item_font
        self._filter_mode: str | None = None
        self._filter_snapshot_ids: set[int] = set()
        self._is_ocr_error_check = None

    def rowCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return len(self._clips)

    def columnCount(self, parent=QModelIndex()) -> int:  # type: ignore[override]
        if parent.isValid():
            return 0
        return 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "STT" if int(section) == 0 else "Text"
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._clips):
            return None
        clip = self._clips[row]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return str(row + 1)
            return clip.text_main or ""
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 0:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.FontRole:
            return self._item_font
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._filter_background_for_clip(clip)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._filter_foreground_for_clip(clip)
        return None

    def flags(self, index):  # type: ignore[override]
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        if index.column() == 1:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):  # type: ignore[override]
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() != 1:
            return False
        row = index.row()
        if row < 0 or row >= len(self._clips):
            return False
        clip = self._clips[row]
        self.text_edited.emit(clip, str(value or ""))
        if 0 <= row < len(self._clips) and self._clips[row] is clip:
            updated = self.index(row, index.column())
            self.dataChanged.emit(
                updated,
                updated,
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
            )
        return True

    def set_clips(self, clips: list[Clip]) -> None:
        self.beginResetModel()
        self._clips = list(clips)
        self.endResetModel()

    def clips(self) -> list[Clip]:
        return self._clips

    def clip_at(self, row: int) -> Clip | None:
        if 0 <= row < len(self._clips):
            return self._clips[row]
        return None

    def set_item_font(self, item_font) -> None:
        self._item_font = item_font
        if self._clips:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._clips) - 1, 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.FontRole])

    def set_filter_context(
        self,
        mode: str | None,
        matched_clip_ids: set[int],
        *,
        ocr_error_check=None,
    ) -> None:
        self._filter_mode = mode
        self._filter_snapshot_ids = set(matched_clip_ids)
        self._is_ocr_error_check = ocr_error_check if mode == "ocr" else None
        self.refresh_filter_styles()

    def refresh_filter_styles(self) -> None:
        if not self._clips:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._clips) - 1, 1)
        self.dataChanged.emit(
            top_left,
            bottom_right,
            [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
        )

    def _filter_background_for_clip(self, clip: Clip) -> QColor | None:
        if self._filter_mode is None:
            return None
        if id(clip) not in self._filter_snapshot_ids:
            return None
        if self._filter_mode == "ocr" and self._is_ocr_error_check is not None:
            return QColor("#3a1f1f") if bool(self._is_ocr_error_check(clip)) else QColor("#1d2027")
        return QColor("#2d1f3a")

    def _filter_foreground_for_clip(self, clip: Clip) -> QColor:
        if (
            self._filter_mode == "ocr"
            and id(clip) in self._filter_snapshot_ids
            and self._is_ocr_error_check is not None
            and not bool(self._is_ocr_error_check(clip))
        ):
            return QColor("#6F6F6F")
        return QColor("#e6e8ec")


class _CaptionListWidget(QWidget):
    """Caption table with inline edit, search and filter actions."""

    _ROW_MIN_HEIGHT = 48  # editor_app.py: 36px text area + 6px top/bottom margins
    _ROW_FONT_PT = 12      # editor_app.py: SubtitleListItemWidget font size
    _STT_COL_MIN_WIDTH = 72
    _AUTO_RESIZE_ROW_LIMIT = 300

    clip_double_clicked = Signal(object)  # Emits Clip
    clip_selected = Signal(object)  # Emits Clip | None
    clip_text_edit_requested = Signal(object, str)  # (clip, new_text)
    add_subtitle_requested = Signal()
    delete_subtitle_requested = Signal(object)  # Clip | None
    find_replace_requested = Signal()
    filter_requested = Signal(str)  # interjection|ocr|duplicate

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(2, 2, 2, 2)
        toolbar.setSpacing(6)
        self._btn_add = QPushButton()
        self._btn_add.setIcon(_icon_from_svg(_PLUS_ICON_SVG, size=18))
        self._btn_add.setIconSize(QSize(18, 18))
        self._btn_add.setFixedWidth(32)
        self._btn_add.setToolTip('Thêm dòng phụ đề mới')
        self._btn_add.clicked.connect(self.add_subtitle_requested.emit)
        self._btn_delete = QPushButton()
        self._btn_delete.setIcon(_icon_from_svg(_TRASH_ICON_SVG, size=18))
        self._btn_delete.setFixedWidth(32)
        self._btn_delete.setToolTip('Xóa dòng phụ đề đang chọn')
        self._btn_delete.clicked.connect(
            lambda: self.delete_subtitle_requested.emit(self._selected_clip())
        )
        toolbar.addWidget(self._btn_add)
        toolbar.addWidget(self._btn_delete)
        
        toolbar.addSpacing(10)
        for kind, label, tooltip in (
            ('interjection', 'Cảm thán', 'Lọc các câu cảm thán ngắn (啊, 哦,...) để kiểm tra.'),
            ('ocr', 'Lỗi OCR', 'Lọc các dòng nghi ngờ có lỗi nhận diện văn bản.'),
            ('duplicate', 'Trùng lặp', 'Lọc các dòng phụ đề giống nhau xuất hiện liên tiếp.'),
        ):
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda _checked=False, k=kind: self.filter_requested.emit(k))
            toolbar.addWidget(btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        search_bar = QHBoxLayout()
        search_bar.setContentsMargins(2, 0, 2, 2)
        search_bar.setSpacing(4)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText('Tìm kiếm phụ đề...')
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(self._on_find_next)
        self._btn_find_prev = QPushButton()
        self._btn_find_prev.setIcon(_icon_from_svg(_SEARCH_PREV_SVG, size=16))
        self._btn_find_prev.setFixedWidth(28)
        self._btn_find_prev.setToolTip("Tìm kết quả trước đó")
        self._btn_find_prev.clicked.connect(self._on_find_prev)
        self._btn_find_next = QPushButton()
        self._btn_find_next.setIcon(_icon_from_svg(_SEARCH_NEXT_SVG, size=16))
        self._btn_find_next.setFixedWidth(28)
        self._btn_find_next.setToolTip("Tìm kết quả tiếp theo")
        self._btn_find_next.clicked.connect(self._on_find_next)
        self._btn_clear_search = QPushButton()
        self._btn_clear_search.setIcon(_icon_from_svg(_TRASH_ICON_GREY_SVG, size=16))
        self._btn_clear_search.setFixedWidth(28)
        self._btn_clear_search.setToolTip("Xóa tìm kiếm")
        self._btn_clear_search.clicked.connect(self._on_clear_search)
        self._btn_replace = QPushButton()
        self._btn_replace.setIcon(_icon_from_svg(_REPLACE_ICON_SVG, size=16))
        self._btn_replace.setFixedWidth(28)
        self._btn_replace.setToolTip('Tìm & Thay thế')
        self._btn_replace.clicked.connect(self.find_replace_requested.emit)
        self._search_count_lbl = QLabel('0/0')
        self._search_count_lbl.setMinimumWidth(36)
        self._search_count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        search_bar.addWidget(self._search_input, stretch=1)
        search_bar.addWidget(self._btn_find_prev)
        search_bar.addWidget(self._search_count_lbl)
        search_bar.addWidget(self._btn_find_next)
        search_bar.addWidget(self._btn_clear_search)
        search_bar.addWidget(self._btn_replace)
        layout.addLayout(search_bar)

        self._table = QTableView(self)
        self._clips: list[Clip] = []
        self._model = _CaptionTableModel(self._caption_item_font())
        self._table.setModel(self._model)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(self._ROW_MIN_HEIGHT)
        self._table.verticalHeader().setMinimumSectionSize(self._ROW_MIN_HEIGHT)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self._table.setWordWrap(True)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            'QTableView { background:#1d2027; color:#e6e8ec; '
            'gridline-color:#363b46; border:1px solid #363b46; '
            'selection-background-color:#10383b; selection-color:#eafffb; } '
            'QTableView::item { padding:6px 10px; border-bottom:1px solid #2b3038; } '
            'QTableView::item:selected { background:#10383b; color:#eafffb; '
            'border:1px solid #22d3c5; } '
            'QTableView::item:focus { outline: none; } '
            'QTableView QLineEdit { border:none; background:#10383b; '
            'padding:0; margin:0; color:#eafffb; font-size:12pt; } '
            'QTableView QLineEdit:focus { border:none; outline:none; '
            'background:#10383b; color:#eafffb; font-size:12pt; } '
            'QHeaderView::section { background:#2b2f36; color:#a6acb8; '
            'border:0; padding:6px; font-weight:600; }'
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._update_stt_column_width()
        self._table.setItemDelegateForColumn(1, _CaptionTextDelegate(self))

        self._table.doubleClicked.connect(self._on_double_click)
        self._model.text_edited.connect(self._on_model_text_edited)
        selection_model = self._table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, stretch=1)

        self._search_matches: list[int] = []
        self._search_match_spans: dict[int, list[tuple[int, int]]] = {}
        self._search_cursor: int = -1
        self._suppress_item_changed = False
        self._filter_mode: str | None = None
        self._filter_label_map: dict[str, str] = {
            "ocr": "[Chế độ lọc: Lỗi OCR]",
            "duplicate": "[Chế độ lọc: Trùng lặp liền kề]",
        }
        self._filter_snapshot_ids: set[int] = set()
        self._is_ocr_error_check = None
        self._suppress_selection_emit = False
        self._caption_start_times: list[float] = []
        self._caption_end_times: list[float] = []
        self._caption_clip_signature: tuple[tuple[int, int, int], ...] = ()

    def _caption_item_font(self):
        font = self._table.font()
        font.setPointSize(self._ROW_FONT_PT)
        return font

    def _update_stt_column_width(self) -> None:
        max_index = max(1, len(getattr(self, "_clips", [])))
        stt_text = str(max_index)
        item_fm = QFontMetrics(self._caption_item_font())
        head_fm = QFontMetrics(self._table.horizontalHeader().font())
        text_w = max(
            item_fm.horizontalAdvance(stt_text),
            head_fm.horizontalAdvance("STT"),
        )
        # Reserve extra room for cell/header padding and border.
        width = max(self._STT_COL_MIN_WIDTH, text_w + 28)
        self._table.setColumnWidth(0, width)

    def _enforce_min_row_height(self, row: int) -> None:
        if row < 0 or row >= len(self._clips):
            return
        if self._table.rowHeight(row) < self._ROW_MIN_HEIGHT:
            self._table.setRowHeight(row, self._ROW_MIN_HEIGHT)

    def set_clips(self, clips: list[Clip]) -> None:
        items = list(clips)
        signature = tuple(
            (
                id(clip),
                int(round(float(getattr(clip, "start", 0.0) or 0.0) * 1000.0)),
                int(round(float(getattr(clip, "timeline_duration", 0.0) or 0.0) * 1000.0)),
            )
            for clip in items
        )
        if signature == self._caption_clip_signature and len(items) == len(self._clips):
            self._clips = items
            if self._filter_mode is not None:
                self.refresh_filter_styles()
            else:
                self._recompute_search_matches()
            return
        self._clips = items
        self._caption_clip_signature = signature
        self._caption_start_times = [float(getattr(clip, "start", 0.0) or 0.0) for clip in items]
        self._caption_end_times = [
            self._caption_start_times[row]
            + max(0.0, float(getattr(clip, "timeline_duration", 0.0) or 0.0))
            for row, clip in enumerate(items)
        ]
        self._model.set_item_font(self._caption_item_font())
        self._model.set_clips(items)
        self._update_stt_column_width()
        v_header = self._table.verticalHeader()
        if len(items) <= self._AUTO_RESIZE_ROW_LIMIT:
            v_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self._table.resizeRowsToContents()
            for row in range(len(items)):
                self._enforce_min_row_height(row)
        else:
            v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
            v_header.setDefaultSectionSize(self._ROW_MIN_HEIGHT)
        if self._filter_mode is not None:
            visible = 0
            for row, clip in enumerate(self._clips):
                in_set = id(clip) in self._filter_snapshot_ids
                self._table.setRowHidden(row, not in_set)
                if in_set:
                    visible += 1
            self._model.set_filter_context(
                self._filter_mode,
                self._filter_snapshot_ids,
                ocr_error_check=self._is_ocr_error_check,
            )
            self._search_count_lbl.setText(f"0/{visible}")
        else:
            self._recompute_search_matches()

    def clear(self) -> None:
        self._clips = []
        self._caption_clip_signature = ()
        self._caption_start_times = []
        self._caption_end_times = []
        self._model.set_clips([])
        self._update_stt_column_width()
        self._search_matches = []
        self._search_match_spans = {}
        self._search_cursor = -1
        self._filter_mode = None
        self._filter_snapshot_ids = set()
        self._is_ocr_error_check = None
        self._set_search_locked(False, "")
        self._update_search_count()

    def select_clip(self, clip: Clip | None) -> None:
        self._suppress_selection_emit = True
        try:
            if clip is None:
                self._table.clearSelection()
                return
            for row, c in enumerate(self._clips):
                if c is clip:
                    self._select_row(row)
                    return
        finally:
            self._suppress_selection_emit = False

    def scroll_to_clip_at_time(self, t_sec: float) -> None:
        """Auto-scroll caption rows so the active cue stays visible."""
        if self._filter_mode is not None:
            return
        if self._table.state() == QAbstractItemView.State.EditingState:
            return

        idx = bisect_right(self._caption_start_times, float(t_sec)) - 1
        target_row: int | None = None
        if 0 <= idx < len(self._clips) and float(t_sec) < self._caption_end_times[idx]:
            target_row = idx

        if target_row is None:
            return
        index = self._model.index(target_row, 0)
        if not index.isValid():
            return
        rect = self._table.visualRect(index)
        viewport_rect = self._table.viewport().rect()
        if viewport_rect.contains(rect.center()):
            return
        self._table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _selected_clip(self) -> Clip | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._clips):
            return self._clips[row]
        return None

    def _select_row(self, row: int) -> None:
        if row < 0 or row >= len(self._clips):
            return
        index = self._model.index(row, 0)
        if not index.isValid():
            return
        self._table.selectRow(row)
        self._table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_search_text_changed(self, _text: str) -> None:
        if self._filter_mode is not None:
            return
        self._recompute_search_matches()

    def _recompute_search_matches(self) -> None:
        if self._filter_mode is not None:
            return
        self._search_match_spans = {}

        raw = (self._search_input.text() or "").strip()
        if not raw:
            self._search_matches = []
            self._search_cursor = -1
            self._update_search_count()
            self._table.viewport().update()
            return

        # Smart Regex detection: try compiling if it looks like regex
        pattern = None
        if any(c in raw for c in ".*+?^$|{}[]()\\"):
            try:
                pattern = re.compile(raw, re.IGNORECASE)
            except re.error:
                pattern = None

        if pattern is None:
            # Fallback to plain text search (but handle whitespace normalization)
            normalized = re.escape(raw).replace(r"\ ", r"[\s\u00a0\u3000]")
            pattern = re.compile(normalized, re.IGNORECASE)

        self._search_matches = []
        for row, clip in enumerate(self._clips):
            text = clip.text_main or ""
            spans = [(m.start(), m.end()) for m in pattern.finditer(text) if m.end() > m.start()]
            if spans:
                self._search_matches.append(row)
                self._search_match_spans[row] = spans

        if not self._search_matches:
            self._search_cursor = -1
            self._update_search_count()
            self._table.viewport().update()
            return
        if self._search_cursor < 0 or self._search_cursor >= len(self._search_matches):
            self._search_cursor = 0
        self._select_row(self._search_matches[self._search_cursor])
        self._update_search_count()
        self._table.viewport().update()

    def _on_find_next(self) -> None:
        if self._filter_mode is not None:
            return
        if not self._search_matches:
            return
        self._search_cursor = (self._search_cursor + 1) % len(self._search_matches)
        self._select_row(self._search_matches[self._search_cursor])
        self._update_search_count()

    def _on_find_prev(self) -> None:
        if self._filter_mode is not None:
            return
        if not self._search_matches:
            return
        self._search_cursor = (self._search_cursor - 1) % len(self._search_matches)
        self._select_row(self._search_matches[self._search_cursor])
        self._update_search_count()

    def _on_clear_search(self) -> None:
        if self._filter_mode is not None:
            self.filter_requested.emit(self._filter_mode)
            return
        self._search_input.clear()
        self._search_matches = []
        self._search_match_spans = {}
        self._search_cursor = -1
        self._update_search_count()
        self._table.viewport().update()

    def _match_spans_for_row(self, row: int) -> list[tuple[int, int]]:
        return self._search_match_spans.get(row, [])

    def _update_search_count(self) -> None:
        if not self._search_matches:
            self._search_count_lbl.setText('0/0')
            return
        self._search_count_lbl.setText(f'{self._search_cursor + 1}/{len(self._search_matches)}')

    def is_filter_active(self) -> bool:
        return self._filter_mode is not None

    def current_filter_kind(self) -> str | None:
        return self._filter_mode

    def apply_filter(
        self,
        kind: str,
        matched_clip_ids: set[int],
        *,
        ocr_error_check=None,
    ) -> int:
        if kind not in ("ocr", "duplicate"):
            return 0

        self._filter_mode = kind
        self._filter_snapshot_ids = set(matched_clip_ids)
        self._is_ocr_error_check = ocr_error_check if kind == "ocr" else None
        self._search_matches = []
        self._search_match_spans = {}
        self._search_cursor = -1
        self._set_search_locked(True, self._filter_label_map.get(kind, ""))

        visible = 0
        for row, clip in enumerate(self._clips):
            in_set = id(clip) in self._filter_snapshot_ids
            self._table.setRowHidden(row, not in_set)
            if in_set:
                visible += 1
        self._model.set_filter_context(
            self._filter_mode,
            self._filter_snapshot_ids,
            ocr_error_check=self._is_ocr_error_check,
        )

        self._search_count_lbl.setText(f"0/{visible}")
        return visible

    def clear_filter(self) -> None:
        if self._filter_mode is None:
            return
        self._filter_mode = None
        self._filter_snapshot_ids = set()
        self._is_ocr_error_check = None
        self._set_search_locked(False, "")
        for row in range(len(self._clips)):
            self._table.setRowHidden(row, False)
        self._model.set_filter_context(None, set())
        self._recompute_search_matches()

    def refresh_filter_styles(self) -> None:
        if self._filter_mode is None:
            return
        self._model.refresh_filter_styles()

    def _paint_row_for_filter(self, row: int, clip: Clip | None) -> None:
        del row, clip
        self._model.refresh_filter_styles()

    def _set_search_locked(self, locked: bool, sentinel: str) -> None:
        self._search_input.blockSignals(True)
        try:
            if locked:
                self._search_input.setText(sentinel)
            else:
                self._search_input.clear()
        finally:
            self._search_input.blockSignals(False)
        self._search_input.setReadOnly(locked)
        self._btn_find_prev.setDisabled(locked)
        self._btn_find_next.setDisabled(locked)
        self._btn_replace.setDisabled(locked)

    def _on_double_click(self, index: QModelIndex) -> None:
        if not index.isValid() or index.column() != 0:
            return
        row = index.row()
        if 0 <= row < len(self._clips):
            self.clip_double_clicked.emit(self._clips[row])

    def _on_model_text_edited(self, clip: object, text: str) -> None:
        row = -1
        for idx, item in enumerate(self._clips):
            if item is clip:
                row = idx
                break
        if row < 0 or row >= len(self._clips):
            return
        if len(self._clips) <= self._AUTO_RESIZE_ROW_LIMIT:
            self._table.resizeRowToContents(row)
            self._enforce_min_row_height(row)
        self.clip_text_edit_requested.emit(clip, text)
        if self._filter_mode is not None:
            self._model.refresh_filter_styles()
            return
        self._recompute_search_matches()

    def _on_selection_changed(self, *args) -> None:
        del args
        if self._suppress_selection_emit:
            return
        self.clip_selected.emit(self._selected_clip())


class _ProjectInfoTab(QWidget):
    """Static project metadata + clip/text properties."""

    clip_changed = Signal()
    translate_requested = Signal(object)
    title_changed = Signal(str)
    caption_clip_double_clicked = Signal(object)  # Clip
    caption_clip_selected = Signal(object)  # Clip | None
    caption_add_requested = Signal()
    caption_delete_requested = Signal(object)  # Clip | None
    caption_text_edit_requested = Signal(object, str)  # (Clip, new_text)
    caption_find_replace_requested = Signal()
    caption_filter_requested = Signal(str)

    _FONT_OPTIONS = [
        "Arial",
        "Verdana",
        "Tahoma",
        "Times New Roman",
        "Georgia",
        "Courier New",
        "Impact",
        "Comic Sans MS",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._project: Project | None = None
        self._clip: Clip | None = None
        self._track_kind: str | None = None
        self._binding_clip = False
        self._last_change_source: str = ""
        self._style_anchor_clip_id: int | None = None
        self._style_anchor_signature: tuple[object, ...] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ---- project meta ------------------------------------------------
        self._meta_container = QWidget()
        meta = QFormLayout(self._meta_container)
        meta.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(10)

        self._name_lbl = QLabel("-")
        self._created_lbl = QLabel("-")
        self._duration_lbl = QLabel("00:00:00")
        self._preview_lbl = QLabel("1920x1080")

        for name_text, value_widget in (
            ("Project", self._name_lbl),
            ("Created", self._created_lbl),
            ("Duration", self._duration_lbl),
            ("Preview", self._preview_lbl),
        ):
            name = QLabel(name_text)
            name.setStyleSheet("color: #8c93a0; font-weight: 600;")
            value_widget.setStyleSheet("color: #e6e8ec;")
            meta.addRow(name, value_widget)

        layout.addWidget(self._meta_container)

        self._meta_sep = QFrame()
        self._meta_sep.setFrameShape(QFrame.Shape.HLine)
        self._meta_sep.setStyleSheet("color: #363b46; background: #363b46;")
        self._meta_sep.setFixedHeight(1)
        layout.addWidget(self._meta_sep)

        # ---- media clip properties --------------------------------------
        self._clip_header = QLabel("PROJECT PROPERTIES")
        self._clip_header.hide()

        self._clip_box_video = VideoPropertiesBox()
        self._clip_box_video.hide()
        self._clip_box_video.clip_changed.connect(self._emit_clip_changed)
        layout.addWidget(self._clip_box_video)

        self._clip_box_audio = AudioPropertiesBox()
        self._clip_box_audio.hide()
        self._clip_box_audio.clip_changed.connect(self._emit_clip_changed)
        layout.addWidget(self._clip_box_audio)

        self._clip_box = QWidget()
        self._clip_box_legacy = self._clip_box
        clip_form = QFormLayout(self._clip_box_legacy)
        clip_form.setContentsMargins(0, 0, 0, 0)
        clip_form.setSpacing(10)

        self._source_lbl = QLabel("-")
        self._source_lbl.setWordWrap(True)
        self._source_lbl.setStyleSheet("color: #8c93a0; font-size: 11px;")
        clip_form.addRow("Source", self._source_lbl)

        def _spin(min_: float, max_: float, step: float = 0.1, decimals: int = 3) -> QDoubleSpinBox:
            sp = QDoubleSpinBox()
            sp.setRange(min_, max_)
            sp.setSingleStep(step)
            sp.setDecimals(decimals)
            sp.setFixedHeight(28)
            return sp

        self._start = _spin(0, 100_000)
        self._in = _spin(0, 100_000)
        self._out = _spin(0, 100_000)
        self._volume = _spin(0, 10, step=0.1, decimals=2)

        clip_form.addRow("Start (s)", self._start)
        clip_form.addRow("In (s)", self._in)
        clip_form.addRow("Out (s)", self._out)
        clip_form.addRow("Volume", self._volume)
        layout.addWidget(self._clip_box_legacy)

        # ---- subtitle text properties (HTML-like) -----------------------
        self._text_box = QWidget()
        text_layout = QVBoxLayout(self._text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(8)

        _base_arrow_icon = _property_icon("icon-editor-properties-collaps2", size=10)
        if _base_arrow_icon.isNull():
            _base_arrow_icon = _property_icon("icon-editor-properties-arrow-down", size=10)
        self._arrow_down_icon = _rotate_icon(_base_arrow_icon, 180.0, size=10)
        if self._arrow_down_icon.isNull():
            self._arrow_down_icon = _base_arrow_icon
        self._arrow_right_icon = _rotate_icon(_base_arrow_icon, 90.0, size=10)

        row_style = """
            QToolButton {
                text-align: left;
                padding: 6px 10px;
                color: #d0d5de;
                background: #2b2f36;
                border: 1px solid #3f444d;
                font-weight: 600;
            }
            QToolButton:hover {
                background: #303540;
            }
        """

        # ===== Top horizontal tab strip: ChÃº thÃ­ch | VÄƒn báº£n =====
        # ===== Top horizontal tab strip: ChÃº thÃ­ch | VÄƒn báº£n =====
        self._text_tab_group = QButtonGroup(self)
        self._text_tab_group.setExclusive(True)

        self._btn_text_tab_caption = QPushButton("Chú thích")
        self._btn_text_tab_text = QPushButton("Văn bản")
        seg_style = """
            QPushButton {
                background: #101215;
                color: #8c93a0;
                border: 1px solid #2f3440;
                border-left-width: 0px;
                border-radius: 0px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton[seg_left="true"] {
                border-left-width: 1px;
                border-top-left-radius: 4px;
                border-bottom-left-radius: 4px;
            }
            QPushButton[seg_right="true"] {
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }
            QPushButton:checked {
                background: #0f6f84;
                color: #ffffff;
                border-color: #0aa0bf;
            }
        """
        for i, btn in enumerate((self._btn_text_tab_caption, self._btn_text_tab_text)):
            btn.setCheckable(True)
            btn.setProperty("seg_left", i == 0)
            btn.setProperty("seg_right", i == 1)
            btn.setStyleSheet(seg_style)
            self._text_tab_group.addButton(btn, i)

        tab_strip = QWidget()
        tab_strip_layout = QHBoxLayout(tab_strip)
        tab_strip_layout.setContentsMargins(0, 0, 0, 0)
        tab_strip_layout.setSpacing(0)
        tab_strip_layout.addWidget(self._btn_text_tab_caption, 1)
        tab_strip_layout.addWidget(self._btn_text_tab_text, 1)
        text_layout.addWidget(tab_strip)

        # Stacked content: page 0 = ChÃº thÃ­ch (full-height list), page 1 = VÄƒn báº£n
        self._text_tab_stack = QStackedWidget()
        self._text_tab_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        text_layout.addWidget(self._text_tab_stack, stretch=1)  # stretch=1 Ä‘á»ƒ stack láº¥p Ä‘áº§y chiá»u cao

        # ----- Page 0: ChÃº thÃ­ch (chá»‰ caption list, full height) ---------
        self._caption_list = _CaptionListWidget()
        self._caption_list.clip_double_clicked.connect(
            self.caption_clip_double_clicked.emit
        )
        self._caption_list.clip_selected.connect(self._on_caption_clip_selected)
        self._caption_list.add_subtitle_requested.connect(
            self.caption_add_requested.emit
        )
        self._caption_list.delete_subtitle_requested.connect(
            self.caption_delete_requested.emit
        )
        self._caption_list.clip_text_edit_requested.connect(
            self.caption_text_edit_requested.emit
        )
        self._caption_list.find_replace_requested.connect(
            self.caption_find_replace_requested.emit
        )
        self._caption_list.filter_requested.connect(
            self.caption_filter_requested.emit
        )
        self._text_tab_stack.addWidget(self._caption_list)  # index 0

        # ----- Page 1: VÄƒn báº£n (Text + Hiá»‡u á»©ng) --------------------------
        vanban_scroll = QScrollArea()
        vanban_scroll.setFrameShape(QFrame.Shape.NoFrame)
        vanban_scroll.setWidgetResizable(True)
        vanban_scroll.setStyleSheet("background: transparent;")
        vanban_scroll.viewport().setStyleSheet("background: transparent;")
        
        vanban_page = QWidget()
        vanban_layout = QVBoxLayout(vanban_page)
        vanban_layout.setContentsMargins(0, 8, 0, 0)
        vanban_layout.setSpacing(6)

        # 1) Section "Text" (Display + Main + Second + Font + Stroke + Apply)
        self._btn_text_toggle = QToolButton()
        self._btn_text_toggle.setCheckable(True)
        self._btn_text_toggle.setChecked(True)
        self._btn_text_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_text_toggle.setIconSize(QPixmap(10, 10).size())
        self._btn_text_toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_text_toggle.setText("Text")
        self._btn_text_toggle.setStyleSheet(
            row_style
            + """
            QToolButton {
                color: #ffffff;
                font-weight: 700;
            }
            """
        )
        vanban_layout.addWidget(self._btn_text_toggle)

        self._text_content = QWidget()
        text_form = QFormLayout(self._text_content)
        text_form.setContentsMargins(10, 4, 6, 8)
        text_form.setSpacing(10)
        text_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        # Display segmented (Bilingual | Main-1 | Second-2)
        disp_wrap = QWidget()
        disp_layout = QHBoxLayout(disp_wrap)
        disp_layout.setContentsMargins(0, 0, 0, 0)
        disp_layout.setSpacing(0)

        self._display_group = QButtonGroup(self)
        self._btn_disp_bilingual = QPushButton("Bilingual")
        self._btn_disp_main = QPushButton("Main-1")
        self._btn_disp_second = QPushButton("Second-2")
        for i, btn in enumerate(
            (self._btn_disp_bilingual, self._btn_disp_main, self._btn_disp_second)
        ):
            btn.setCheckable(True)
            btn.setProperty("seg_left", i == 0)
            btn.setProperty("seg_right", i == 2)
            btn.setStyleSheet(
                """
                QPushButton {
                    background: #101215;
                    color: #8c93a0;
                    border: 1px solid #2f3440;
                    border-left-width: 0px;
                    border-radius: 0px;
                    padding: 6px 10px;
                    font-weight: 600;
                }
                QPushButton[seg_left="true"] {
                    border-left-width: 1px;
                    border-top-left-radius: 4px;
                    border-bottom-left-radius: 4px;
                }
                QPushButton[seg_right="true"] {
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QPushButton:checked {
                    background: #0f6f84;
                    color: #ffffff;
                    border-color: #0aa0bf;
                }
                """
            )
            self._display_group.addButton(btn)
            disp_layout.addWidget(btn)
        self._btn_disp_bilingual.clicked.connect(lambda _=False: self._apply_text_display("bilingual"))
        self._btn_disp_main.clicked.connect(lambda _=False: self._apply_text_display("main"))
        self._btn_disp_second.clicked.connect(lambda _=False: self._apply_text_display("second"))
        text_form.addRow("Display:", disp_wrap)

        # Main / Second rows
        def _build_text_line(
            *, second: bool
        ) -> tuple[QWidget, QPushButton, QSpinBox, QPlainTextEdit, QPushButton]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)

            color_btn = QPushButton()
            color_btn.setFixedSize(24, 24)
            color_btn.setToolTip("Pick text color")
            color_btn.setVisible(False)
            color_btn.setEnabled(False)

            size = QSpinBox()
            size.setRange(8, 200)
            size.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            size.setFixedWidth(56)
            size.setVisible(False)
            size.setEnabled(False)

            txt = _MultiLineEdit(lines=3)
            h.addWidget(txt, 1)

            tr_btn = QPushButton("Tr")
            tr_btn.setFixedWidth(42)
            tr_btn.setToolTip("Translate")
            tr_btn.setStyleSheet("background: #002c37; border: 1px solid #11495a;")
            if second:
                tr_btn.setVisible(False)
                tr_btn.setEnabled(False)
            else:
                tr_icon = _icon_from_svg(_MAIN_TRANSLATE_SVG, size=18)
                if not tr_icon.isNull():
                    tr_btn.setText("")
                    tr_btn.setIcon(tr_icon)
                    tr_btn.setIconSize(QPixmap(18, 18).size())
            h.addWidget(tr_btn)

            return row, color_btn, size, txt, tr_btn

        self._main_label = QLabel("Main")
        (
            self._main_row,
            self._main_color_btn,
            self._text_main_size,
            self._text_main,
            self._main_translate_btn,
        ) = _build_text_line(second=False)
        text_form.addRow(self._main_label, self._main_row)

        self._second_label = QLabel("Second")
        (
            self._second_row,
            self._second_color_btn,
            self._text_second_size,
            self._text_second,
            self._second_translate_btn,
        ) = _build_text_line(second=True)
        text_form.addRow(self._second_label, self._second_row)
        self._text_main.installEventFilter(self)
        self._text_second.installEventFilter(self)

        # Font
        self._text_font_family = QComboBox()
        self._text_font_family.setEditable(False)
        self._text_font_family.addItems(self._FONT_OPTIONS)
        text_form.addRow("Font", self._text_font_family)

        # Stroke
        stroke_row = QWidget()
        stroke_layout = QHBoxLayout(stroke_row)
        stroke_layout.setContentsMargins(0, 0, 0, 0)
        stroke_layout.setSpacing(8)
        self._stroke_color_btn = QPushButton()
        self._stroke_color_btn.setFixedSize(24, 24)
        self._stroke_color_btn.setToolTip("Pick stroke color")
        stroke_layout.addWidget(self._stroke_color_btn)
        stroke_layout.addWidget(QLabel("Thickness"))
        self._text_stroke_width = QSlider(Qt.Orientation.Horizontal)
        self._text_stroke_width.setRange(0, 10)
        self._text_stroke_width.setSingleStep(1)
        stroke_layout.addWidget(self._text_stroke_width, 1)
        text_form.addRow("Stroke", stroke_row)

        # Local text style presets
        preset_row = QWidget()
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.setSpacing(6)
        self._text_preset_combo = QComboBox()
        self._text_preset_combo.setMinimumContentsLength(14)
        self._btn_apply_text_preset = QPushButton("Apply")
        self._btn_save_text_preset = QPushButton("Save")
        preset_layout.addWidget(self._text_preset_combo, 1)
        preset_layout.addWidget(self._btn_apply_text_preset)
        preset_layout.addWidget(self._btn_save_text_preset)
        text_form.addRow("Preset", preset_row)

        # Apply track style
        apply_row = QWidget()
        apply_layout = QHBoxLayout(apply_row)
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.addStretch(1)
        self._btn_apply_style = QPushButton("[ ] Apply the style to this track")
        self._btn_apply_style.setCheckable(True)
        self._btn_apply_style.setStyleSheet(
            """
            QPushButton {
                color: #cfd5df;
                background: #1b1b1b;
                border: 1px solid #373737;
                padding: 4px 8px;
                text-align: left;
            }
            QPushButton:checked {
                color: #ffffff;
                background: #203038;
                border-color: #0aa0bf;
            }
            """
        )
        apply_layout.addWidget(self._btn_apply_style)
        text_form.addRow("", apply_row)

        vanban_layout.addWidget(self._text_content)

        # 2) Section "HiÃ¡Â»â€¡u Ã¡Â»Â©ng" (= Transform cÃ…Â© + B2 effects)
        self._btn_transform_toggle = QToolButton()
        self._btn_transform_toggle.setCheckable(True)
        self._btn_transform_toggle.setChecked(True)
        self._btn_transform_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn_transform_toggle.setIconSize(QPixmap(10, 10).size())
        self._btn_transform_toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_transform_toggle.setText("Hiệu ứng")
        self._btn_transform_toggle.setStyleSheet(row_style)
        vanban_layout.addWidget(self._btn_transform_toggle)

        self._transform_content = QWidget()
        transform_form = QFormLayout(self._transform_content)
        transform_form.setContentsMargins(10, 4, 6, 8)
        transform_form.setSpacing(8)
        transform_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._transform_x = QSpinBox()
        self._transform_x.setRange(-100_000, 100_000)
        self._transform_x.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        transform_form.addRow("X", self._transform_x)

        self._transform_y = QSpinBox()
        self._transform_y.setRange(-100_000, 100_000)
        self._transform_y.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        transform_form.addRow("Y", self._transform_y)

        self._transform_scale = QDoubleSpinBox()
        self._transform_scale.setRange(0.01, 1.00)
        self._transform_scale.setSingleStep(0.01)
        self._transform_scale.setDecimals(3)
        self._transform_scale.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        transform_form.addRow("Scale", self._transform_scale)

        self._transform_rotate = QDoubleSpinBox()
        self._transform_rotate.setRange(-360.0, 360.0)
        self._transform_rotate.setSingleStep(1.0)
        self._transform_rotate.setDecimals(1)
        self._transform_rotate.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        transform_form.addRow("Rotate", self._transform_rotate)

        # B2 Ã¢â‚¬â€ extended effects (mapped to ClipEffects fields):
        self._effect_blur = QDoubleSpinBox()
        self._effect_blur.setRange(0.0, 20.0)
        self._effect_blur.setSingleStep(0.5)
        self._effect_blur.setDecimals(1)
        self._effect_blur.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        transform_form.addRow("Blur", self._effect_blur)

        self._effect_grayscale = QCheckBox()
        transform_form.addRow("Grayscale", self._effect_grayscale)

        flips_row = QWidget()
        flips_layout = QHBoxLayout(flips_row)
        flips_layout.setContentsMargins(0, 0, 0, 0)
        flips_layout.setSpacing(20)
        self._effect_hflip = QCheckBox("Flip H")
        self._effect_vflip = QCheckBox("Flip V")
        flips_layout.addWidget(self._effect_hflip)
        flips_layout.addWidget(self._effect_vflip)
        flips_layout.addStretch(1)
        transform_form.addRow("", flips_row)

        vanban_layout.addWidget(self._transform_content)
        vanban_layout.addStretch(1)
        
        vanban_scroll.setWidget(vanban_page)
        self._text_tab_stack.addWidget(vanban_scroll)  # index 1

        # ===== Wire tab strip buttons =====
        self._btn_text_tab_caption.toggled.connect(
            lambda checked: checked and self._text_tab_stack.setCurrentIndex(0)
        )
        self._btn_text_tab_text.toggled.connect(
            lambda checked: checked and self._text_tab_stack.setCurrentIndex(1)
        )
        self._btn_text_tab_caption.setChecked(True)
        self._text_tab_stack.setCurrentIndex(0)

        # Existing collapsible behaviour
        self._btn_transform_toggle.toggled.connect(self._on_transform_section_toggled)
        self._btn_text_toggle.toggled.connect(self._on_text_section_toggled)
        self._update_section_toggle_icon(self._btn_transform_toggle)
        self._update_section_toggle_icon(self._btn_text_toggle)
        self._transform_content.setVisible(True)
        self._text_content.setVisible(True)
        layout.addWidget(self._text_box, stretch=1)  # Ã¢â€ Â stretch=1 Ã„â€˜Ã¡Â»Æ’ _text_box giÃƒÂ£n full height

        # ---- signal wiring ----------------------------------------------
        self._start.valueChanged.connect(self._apply_start)
        self._in.valueChanged.connect(self._apply_in)
        self._out.valueChanged.connect(self._apply_out)
        self._volume.valueChanged.connect(self._apply_volume)

        self._text_main.textChanged.connect(
            lambda: self._apply_text_main(self._text_main.toPlainText())
        )
        self._text_second.textChanged.connect(
            lambda: self._apply_text_second(self._text_second.toPlainText())
        )
        self._text_main_size.valueChanged.connect(self._apply_text_font_size)
        self._text_second_size.valueChanged.connect(self._apply_text_second_font_size)
        self._text_font_family.currentTextChanged.connect(self._apply_text_font_family)
        self._text_stroke_width.valueChanged.connect(self._apply_text_stroke_width)
        self._transform_x.valueChanged.connect(self._apply_transform_x)
        self._transform_y.valueChanged.connect(self._apply_transform_y)
        self._transform_scale.valueChanged.connect(self._apply_transform_scale)
        self._transform_rotate.valueChanged.connect(self._apply_transform_rotate)
        self._effect_blur.valueChanged.connect(self._apply_effect_blur)
        self._effect_grayscale.toggled.connect(self._apply_effect_grayscale)
        self._effect_hflip.toggled.connect(self._apply_effect_hflip)
        self._effect_vflip.toggled.connect(self._apply_effect_vflip)

        self._main_color_btn.clicked.connect(lambda: self._pick_text_color(second=False))
        self._second_color_btn.clicked.connect(lambda: self._pick_text_color(second=True))
        self._stroke_color_btn.clicked.connect(self._pick_stroke_color)
        self._main_translate_btn.clicked.connect(self._on_translate_clicked)
        self._second_translate_btn.clicked.connect(self._on_translate_clicked)
        self._btn_apply_text_preset.clicked.connect(self._apply_selected_text_preset)
        self._btn_save_text_preset.clicked.connect(self._save_current_text_preset)
        self._btn_apply_style.clicked.connect(self._apply_style_to_track)

        self._refresh_text_preset_combo()
        self.set_clip(None)

    # ---- public API -----------------------------------------------------

    def set_project(self, project: Project) -> None:
        self._project = project
        self._refresh_project()
        self.refresh_caption_list()

    def refresh(self) -> None:
        self._refresh_project()
        self.refresh_caption_list()
        if self._clip is not None and not self._clip.is_text_clip:
            resolved_track_kind = self._track_kind or self._infer_track_kind(self._clip)
            if resolved_track_kind == "audio":
                self._clip_box_audio.set_clip(self._clip, track_kind=resolved_track_kind)
            else:
                self._clip_box_video.set_clip(self._clip, track_kind=resolved_track_kind)

    def _infer_track_kind(self, clip: Clip) -> str | None:
        if self._project is None:
            return None
        for track in self._project.tracks:
            if clip in track.clips:
                return track.kind
        return None

    def current_clip(self) -> Clip | None:
        return self._clip

    def current_title(self) -> str:
        return self._clip_header.text()

    def _set_panel_title(self, title: str) -> None:
        self._clip_header.setText(title)
        self.title_changed.emit(title)

    def set_clip(self, clip: object | None, *, track_kind: str | None = None) -> None:
        self._binding_clip = True
        try:
            self._clip = clip if isinstance(clip, Clip) else None
            self._track_kind = track_kind
            enabled = self._clip is not None

            self._clip_header.setVisible(False)
            self._meta_container.setVisible(False)
            self._meta_sep.setVisible(False)
            self._clip_box_video.setVisible(False)
            self._clip_box_audio.setVisible(False)
            self._clip_box_legacy.setVisible(False)
            self._text_box.setVisible(False)

            for w in (self._start, self._in, self._out, self._volume):
                w.blockSignals(True)
                w.setEnabled(enabled)
            self._set_text_controls_enabled(enabled)

            if self._clip is None:
                self._track_kind = None
                self._set_panel_title("PROJECT PROPERTIES")
                self._meta_container.setVisible(True)
                self._source_lbl.setText("-")
                self._clip_box_video.set_clip(None)
                self._clip_box_audio.set_clip(None)
                for w in (self._start, self._in, self._out, self._volume):
                    w.setValue(0.0)
                    w.blockSignals(False)
                self._reset_text_defaults()
                self._set_text_controls_enabled(False, block=False)
                self._caption_list.select_clip(None)
                return

            c = self._clip
            self._source_lbl.setText(Path(c.source).name)
            self._start.setValue(c.start)
            self._in.setValue(c.in_point)
            self._out.setValue(c.out_point or 0.0)
            self._volume.setValue(c.volume)

            is_text = bool(getattr(c, "is_text_clip", False))
            self._volume.setEnabled(not is_text)
            self._in.setEnabled(not is_text)
            resolved_track_kind = track_kind or self._infer_track_kind(c)

            if is_text:
                self._set_panel_title("TEXT PROPERTIES")
                self._text_box.setVisible(True)
                self._clip_box_video.set_clip(None)
                self._clip_box_audio.set_clip(None)
                self._coerce_unified_text_style(c)
                self._transform_x.setValue(int(c.pos_x if c.pos_x is not None else 0))
                self._transform_y.setValue(int(c.pos_y if c.pos_y is not None else 0))
                self._transform_scale.setValue(float(c.scale if c.scale is not None else 1.0))
                self._transform_rotate.setValue(float(c.effects.rotate))
                self._effect_blur.setValue(float(c.effects.blur))
                self._effect_grayscale.setChecked(bool(c.effects.grayscale))
                self._effect_hflip.setChecked(bool(c.effects.hflip))
                self._effect_vflip.setChecked(bool(c.effects.vflip))

                self._set_plain_text_preserve_cursor(self._text_main, c.text_main or "")
                self._set_plain_text_preserve_cursor(self._text_second, c.text_second or "")
                self._text_main_size.setValue(int(c.text_font_size))
                self._text_second_size.setValue(int(c.text_font_size))

                font = (c.text_font_family or "Verdana").strip() or "Verdana"
                if self._text_font_family.findText(font) < 0:
                    self._text_font_family.addItem(font)
                self._text_font_family.setCurrentText(font)

                self._set_color_swatch(self._main_color_btn, c.text_color or "#ffffff")
                self._set_color_swatch(
                    self._second_color_btn,
                    c.text_color or "#ffffff",
                )
                self._set_color_swatch(
                    self._stroke_color_btn,
                    c.text_stroke_color or "#000000",
                )
                self._text_stroke_width.setValue(max(0, min(10, int(c.text_stroke_width))))
                self._set_display_buttons(c.text_display)
                self._refresh_display_visibility(c.text_display)
                self._refresh_text_row_backgrounds()
                self._refresh_text_preset_combo()
            else:
                self._text_box.setVisible(False)
                if resolved_track_kind == "audio":
                    self._set_panel_title("AUDIO PROPERTIES")
                    self._clip_box_video.set_clip(None)
                    self._clip_box_video.setVisible(False)
                    self._clip_box_legacy.setVisible(False)
                    self._clip_box_audio.setVisible(True)
                    self._clip_box_audio.set_clip(c, track_kind=resolved_track_kind)
                else:
                    self._set_panel_title("VIDEO PROPERTIES")
                    self._clip_box_video.setVisible(True)
                    self._clip_box_video.set_clip(c, track_kind=resolved_track_kind)
                    self._clip_box_legacy.setVisible(False)
                    self._clip_box_audio.setVisible(False)
                    self._clip_box_audio.set_clip(None)

            for w in (self._start, self._in, self._out, self._volume):
                w.blockSignals(False)
            self._set_text_controls_enabled(enabled, block=False)
            self._update_apply_style_button_state()
            self._caption_list.select_clip(self._clip)
        finally:
            self._binding_clip = False

    # ---- helper methods -------------------------------------------------

    def _refresh_project(self) -> None:
        p = self._project
        if p is None:
            return
        self._name_lbl.setText(p.name)
        self._created_lbl.setText(datetime.now().strftime("%Y-%m-%d"))
        secs = int(p.duration)
        self._duration_lbl.setText(
            f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
        )
        self._preview_lbl.setText(f"{p.width}x{p.height}")

    def refresh_caption_list(self) -> None:
        """Cáº­p nháº­t báº£ng STT|Text tá»« táº¥t cáº£ text clip trong project."""
        p = self._project
        if p is None:
            self._caption_list.clear()
            return
        text_clips: list[Clip] = []
        for track in p.tracks:
            for clip in track.clips:
                if clip.is_text_clip:
                    text_clips.append(clip)
        text_clips.sort(key=lambda c: (c.start, c.in_point))
        self._caption_list.set_clips(text_clips)
        self._caption_list.select_clip(self._clip)

    def show_caption_list_neutral(self) -> None:
        """Show caption list with no selected row, while keeping TEXT panel visible."""
        self._clip = None
        self._track_kind = None
        self._set_panel_title("TEXT PROPERTIES")
        self._clip_header.setVisible(False)
        self._meta_container.setVisible(False)
        self._meta_sep.setVisible(False)
        self._clip_box_video.set_clip(None)
        self._clip_box_video.setVisible(False)
        self._clip_box_audio.set_clip(None)
        self._clip_box_audio.setVisible(False)
        self._clip_box_legacy.setVisible(False)
        self._text_box.setVisible(True)
        self._set_text_controls_enabled(False, block=False)
        self._btn_text_tab_caption.setChecked(True)
        self._text_tab_stack.setCurrentIndex(0)
        self.refresh_caption_list()
        self._caption_list.select_clip(None)
        try:
            self._caption_list._table.verticalScrollBar().setValue(0)
        except Exception:
            pass

    def _on_caption_clip_selected(self, clip_obj: object) -> None:
        if self._binding_clip:
            return
        clip = clip_obj if isinstance(clip_obj, Clip) else None
        self.caption_clip_selected.emit(clip)
        if clip is None:
            return
        keep_caption_tab = bool(self._btn_text_tab_caption.isChecked())
        keep_caption_idx = self._text_tab_stack.currentIndex() == 0
        self.set_clip(clip)
        if keep_caption_tab or keep_caption_idx:
            self._btn_text_tab_caption.setChecked(True)
            self._text_tab_stack.setCurrentIndex(0)

    def _set_text_controls_enabled(self, enabled: bool, *, block: bool = True) -> None:
        controls = (
            self._transform_x,
            self._transform_y,
            self._transform_scale,
            self._transform_rotate,
            self._text_main,
            self._text_second,
            self._text_main_size,
            self._text_second_size,
            self._text_font_family,
            self._text_stroke_width,
            self._main_color_btn,
            self._second_color_btn,
            self._stroke_color_btn,
            self._main_translate_btn,
            self._second_translate_btn,
            self._text_preset_combo,
            self._btn_apply_text_preset,
            self._btn_save_text_preset,
            self._btn_apply_style,
        )
        for w in controls:
            if block and hasattr(w, "blockSignals"):
                w.blockSignals(True)
            w.setEnabled(enabled)
            if not block and hasattr(w, "blockSignals"):
                w.blockSignals(False)
        self._update_text_preset_button_state()

    def _reset_text_defaults(self) -> None:
        self._transform_x.setValue(0)
        self._transform_y.setValue(0)
        self._transform_scale.setValue(1.0)
        self._transform_rotate.setValue(0.0)
        self._effect_blur.setValue(0.0)
        self._effect_grayscale.setChecked(False)
        self._effect_hflip.setChecked(False)
        self._effect_vflip.setChecked(False)
        self._text_main.setPlainText("")
        self._text_second.setPlainText("")
        self._text_main_size.setValue(36)
        self._text_second_size.setValue(36)
        self._text_font_family.setCurrentText("Verdana")
        self._set_color_swatch(self._main_color_btn, "#ffffff")
        self._set_color_swatch(self._second_color_btn, "#ffffff")
        self._set_color_swatch(self._stroke_color_btn, "#000000")
        self._text_stroke_width.setValue(2)
        self._set_display_buttons("main")
        self._refresh_display_visibility("main")
        self._refresh_text_row_backgrounds()
        self._refresh_text_preset_combo()
        self._btn_apply_style.setChecked(False)
        self._btn_apply_style.setText("[ ] Apply the style to this track")
        self._btn_transform_toggle.setChecked(True)
        self._btn_text_toggle.setChecked(True)
        self._on_transform_section_toggled(self._btn_transform_toggle.isChecked())
        self._on_text_section_toggled(self._btn_text_toggle.isChecked())
        self._btn_text_tab_caption.setChecked(True)
        self._text_tab_stack.setCurrentIndex(0)

    def _set_display_buttons(self, mode: str) -> None:
        self._btn_disp_bilingual.setChecked(mode == "bilingual")
        self._btn_disp_second.setChecked(mode == "second")
        self._btn_disp_main.setChecked(mode not in {"bilingual", "second"})

    def _refresh_display_visibility(self, mode: str) -> None:
        show_main = mode in {"main", "bilingual"}
        show_second = mode in {"second", "bilingual"}
        self._main_label.setVisible(show_main)
        self._main_row.setVisible(show_main)
        self._second_label.setVisible(show_second)
        self._second_row.setVisible(show_second)
        self._main_translate_btn.setVisible(show_main)
        self._second_translate_btn.setVisible(False)

    def _update_section_toggle_icon(self, btn: QToolButton) -> None:
        icon = self._arrow_down_icon if btn.isChecked() else self._arrow_right_icon
        if icon.isNull():
            icon = _property_icon("icon-editor-properties-collaps2", size=10)
        if icon.isNull():
            btn.setText(("v " if btn.isChecked() else "> ") + btn.text().lstrip("v> ").strip())
            return
        btn.setIcon(icon)

    def _on_transform_section_toggled(self, expanded: bool) -> None:
        self._transform_content.setVisible(expanded)
        self._update_section_toggle_icon(self._btn_transform_toggle)

    def _on_text_section_toggled(self, expanded: bool) -> None:
        self._text_content.setVisible(expanded)
        self._update_section_toggle_icon(self._btn_text_toggle)

    def eventFilter(self, watched: object, event: object) -> bool:
        if (
            watched in (getattr(self, "_text_main", None), getattr(self, "_text_second", None))
            and isinstance(event, QEvent)
            and event.type() == QEvent.Type.KeyPress
        ):
            key = getattr(event, "key", None)
            pressed = key() if callable(key) else None
            if pressed in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                editor = watched if isinstance(watched, QPlainTextEdit) else None
                if editor is not None:
                    QTimer.singleShot(
                        0, lambda e=editor: self._keep_previous_line_visible_in_editor(e)
                    )
        return super().eventFilter(watched, event)

    def _keep_previous_line_visible_in_editor(self, editor: QPlainTextEdit) -> None:
        if editor is None:
            return
        if editor.document().blockCount() <= 1:
            return
        sb = editor.verticalScrollBar()
        if sb is None or sb.maximum() <= sb.minimum():
            return
        line_h = max(1, editor.fontMetrics().lineSpacing())
        rect = editor.cursorRect()
        # Keep one previous line visible after pressing Enter.
        if rect.top() <= int(line_h * 0.75) and sb.value() > sb.minimum():
            sb.setValue(max(sb.minimum(), sb.value() - line_h))

    @staticmethod
    def _normalize_hex_color(value: str, default: str = "#ffffff") -> str:
        v = (value or "").strip()
        if len(v) == 7 and v.startswith("#"):
            return v.lower()
        return default

    @staticmethod
    def _hex_to_rgba(color: str, alpha: float = 0.12) -> str:
        c = color.lstrip("#")
        try:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
        except Exception:
            r, g, b = (38, 41, 49)
        return f"rgba({r}, {g}, {b}, {alpha:.3f})"

    def _set_color_swatch(self, btn: QPushButton, color: str) -> None:
        c = self._normalize_hex_color(color)
        btn.setProperty("picked_color", c)
        btn.setStyleSheet(
            f"border: 1px solid #3a404a; border-radius: 4px; background: {c};"
        )

    def _swatch_color(self, btn: QPushButton, default: str = "#ffffff") -> str:
        return self._normalize_hex_color(str(btn.property("picked_color") or default), default)

    def _coerce_unified_text_style(self, clip: Clip) -> None:
        if not bool(getattr(clip, "is_text_clip", False)):
            return
        base_color = self._normalize_hex_color(getattr(clip, "text_color", "#ffffff"), "#ffffff")
        clip.text_color = base_color
        clip.text_second_color = base_color
        clip.text_second_font_size = int(max(8, int(getattr(clip, "text_font_size", 36))))

    def _refresh_text_row_backgrounds(self) -> None:
        # Keep text editors visually consistent now that per-row color controls are hidden.
        main_bg = "#343a46"
        second_bg = "#343a46"
        self._text_main.setStyleSheet(
            f"background: {main_bg}; border: 1px solid #2f3440; border-radius: 6px; padding: 4px 6px;"
        )
        self._text_second.setStyleSheet(
            f"background: {second_bg}; border: 1px solid #2f3440; border-radius: 6px; padding: 4px 6px;"
        )

    def take_last_change_source(self) -> str:
        source = self._last_change_source
        self._last_change_source = ""
        return source

    def _emit_clip_changed(self, source: str = "") -> None:
        if self._binding_clip:
            return
        if source:
            self._last_change_source = source
        self.clip_changed.emit()

    def _current_style_signature(self) -> tuple[object, ...] | None:
        c = self._clip
        if c is None or not c.is_text_clip:
            return None
        return (
            c.text_display,
            c.text_font_family,
            int(c.text_font_size),
            int(getattr(c, "text_second_font_size", c.text_font_size)),
            c.text_color,
            getattr(c, "text_second_color", "#ffffff"),
            c.text_stroke_color,
            int(c.text_stroke_width),
        )

    def _update_apply_style_button_state(self) -> None:
        sig = self._current_style_signature()
        active = (
            sig is not None
            and self._style_anchor_clip_id == id(self._clip)
            and self._style_anchor_signature == sig
        )
        self._btn_apply_style.setChecked(active)
        self._btn_apply_style.setText(
            "[x] Apply the style to this track" if active else "[ ] Apply the style to this track"
        )

    def _refresh_text_preset_combo(self, select_name: str | None = None) -> None:
        if not hasattr(self, "_text_preset_combo"):
            return
        current = select_name or str(self._text_preset_combo.currentData() or "")
        self._text_preset_combo.blockSignals(True)
        self._text_preset_combo.clear()
        presets = list_text_style_presets()
        if not presets:
            self._text_preset_combo.addItem("No presets yet", None)
        else:
            for preset in presets:
                self._text_preset_combo.addItem(preset.name, preset.name)
        if current:
            index = self._text_preset_combo.findData(current)
            if index >= 0:
                self._text_preset_combo.setCurrentIndex(index)
        self._text_preset_combo.blockSignals(False)
        self._update_text_preset_button_state()

    def _update_text_preset_button_state(self) -> None:
        if not hasattr(self, "_btn_apply_text_preset"):
            return
        has_clip = self._clip is not None and self._clip.is_text_clip
        has_preset = bool(self._text_preset_combo.currentData())
        self._text_preset_combo.setEnabled(has_clip)
        self._btn_save_text_preset.setEnabled(has_clip)
        self._btn_apply_text_preset.setEnabled(has_clip and has_preset)

    def _save_current_text_preset(self) -> None:
        c = self._clip
        if c is None or not c.is_text_clip:
            return
        default_name = ((c.text_main or "").strip().splitlines() or ["Text Style"])[0]
        default_name = default_name[:40].strip() or "Text Style"
        name, accepted = QInputDialog.getText(
            self,
            "Save text style preset",
            "Preset name:",
            text=default_name,
        )
        name = name.strip()
        if not accepted or not name:
            return
        try:
            save_text_style_preset(name, c)
        except Exception as exc:  # pragma: no cover - defensive UI path
            QMessageBox.warning(self, "Save preset failed", str(exc))
            return
        self._refresh_text_preset_combo(select_name=name)

    def _apply_selected_text_preset(self) -> None:
        c = self._clip
        name = str(self._text_preset_combo.currentData() or "")
        if c is None or not c.is_text_clip or not name:
            return
        try:
            apply_text_style_preset(c, name)
        except Exception as exc:  # pragma: no cover - defensive UI path
            QMessageBox.warning(self, "Apply preset failed", str(exc))
            return
        track_kind = self._track_kind
        self.set_clip(c, track_kind=track_kind)
        self._emit_clip_changed()

    def _pick_text_color(self, *, second: bool) -> None:
        if self._clip is None or not self._clip.is_text_clip:
            return
        btn = self._second_color_btn if second else self._main_color_btn
        current = QColorDialog.getColor(QColor(self._swatch_color(btn)), self, "Pick text color")
        if not current.isValid():
            return
        picked = current.name()
        self._set_color_swatch(btn, picked)
        self._refresh_text_row_backgrounds()
        if second:
            self._apply_text_second_color(picked)
        else:
            self._apply_text_color(picked)

    def _pick_stroke_color(self) -> None:
        if self._clip is None or not self._clip.is_text_clip:
            return
        current = QColorDialog.getColor(
            QColor(self._swatch_color(self._stroke_color_btn, "#000000")),
            self,
            "Pick stroke color",
        )
        if not current.isValid():
            return
        picked = current.name()
        self._set_color_swatch(self._stroke_color_btn, picked)
        if self._clip is not None and self._clip.is_text_clip:
            self._clip.text_stroke_color = picked
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_style_to_track(self) -> None:
        c = self._clip
        if c is None or not c.is_text_clip or self._project is None:
            self._btn_apply_style.setChecked(False)
            return
        self._coerce_unified_text_style(c)

        owner: Track | None = None
        for tr in self._project.tracks:
            if c in tr.clips:
                owner = tr
                break
        if owner is None:
            self._btn_apply_style.setChecked(False)
            return

        payload = text_style_payload_from_clip(c)
        for clip in owner.clips:
            if clip is c or not clip.is_text_clip:
                continue
            apply_text_style_payload(clip, payload)

        self._style_anchor_clip_id = id(c)
        self._style_anchor_signature = self._current_style_signature()
        self._update_apply_style_button_state()
        self._emit_clip_changed()

    # ---- media/text apply handlers -------------------------------------

    def _apply_start(self, v: float) -> None:
        if self._clip:
            self._clip.start = v
            self._emit_clip_changed()

    def _apply_in(self, v: float) -> None:
        if self._clip and not self._clip.is_text_clip:
            self._clip.in_point = v
            self._emit_clip_changed()

    def _apply_out(self, v: float) -> None:
        if self._clip:
            self._clip.out_point = v if v > 0 else None
            self._emit_clip_changed()

    def _apply_volume(self, v: float) -> None:
        if self._clip and not self._clip.is_text_clip:
            self._clip.volume = v
            self._emit_clip_changed()

    def _apply_transform_x(self, v: int) -> None:
        if self._clip:
            self._clip.pos_x = int(v)
            self._emit_clip_changed()

    def _apply_transform_y(self, v: int) -> None:
        if self._clip:
            self._clip.pos_y = int(v)
            self._emit_clip_changed()

    def _apply_transform_scale(self, v: float) -> None:
        if self._clip:
            self._clip.scale = max(0.01, min(1.0, float(v)))
            self._emit_clip_changed()

    def _apply_transform_rotate(self, v: float) -> None:
        if self._clip:
            self._clip.effects.rotate = max(-360.0, min(360.0, float(v)))
            self._emit_clip_changed()

    def _apply_effect_blur(self, v: float) -> None:
        if self._clip:
            self._clip.effects.blur = max(0.0, float(v))
            self._emit_clip_changed()

    def _apply_effect_grayscale(self, checked: bool) -> None:
        if self._clip:
            self._clip.effects.grayscale = bool(checked)
            self._emit_clip_changed()

    def _apply_effect_hflip(self, checked: bool) -> None:
        if self._clip:
            self._clip.effects.hflip = bool(checked)
            self._emit_clip_changed()

    def _apply_effect_vflip(self, checked: bool) -> None:
        if self._clip:
            self._clip.effects.vflip = bool(checked)
            self._emit_clip_changed()

    @staticmethod
    def _set_plain_text_preserve_cursor(widget: QPlainTextEdit, new_text: str) -> None:
        """Set text on a QPlainTextEdit without resetting the cursor to position 0.

        If the text content has not changed (e.g. during a live-binding refresh
        while the user is still typing), the widget is left untouched so the
        cursor stays exactly where the user left it.  Only when the content
        actually differs do we fall back to setPlainText – and in that case we
        try to restore the cursor to the *end* of the document, which is a
        sensible default when switching to a different clip.
        """
        current = widget.toPlainText()
        if current == new_text:
            return
        # Content changed (e.g. different clip selected) – update and put cursor at end.
        cursor = widget.textCursor()
        old_pos = cursor.position()
        widget.setPlainText(new_text)
        # Try to keep cursor near the same position; fall back to end.
        new_cursor = widget.textCursor()
        new_cursor.setPosition(min(old_pos, len(new_text)))
        widget.setTextCursor(new_cursor)

    def _apply_text_main(self, v: str) -> None:
        if self._clip and self._clip.is_text_clip:
            self._clip.text_main = v
            self._emit_clip_changed("text_main_typing")

    def _apply_text_second(self, v: str) -> None:
        if self._clip and self._clip.is_text_clip:
            self._clip.text_second = v
            self._emit_clip_changed("text_second_typing")

    def _apply_text_display(self, v: str) -> None:
        self._refresh_display_visibility(v)
        if self._clip and self._clip.is_text_clip:
            self._clip.text_display = v  # type: ignore[assignment]
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_text_font_size(self, v: int) -> None:
        if self._clip and self._clip.is_text_clip:
            size = max(8, int(v))
            self._clip.text_font_size = size
            self._clip.text_second_font_size = size
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_text_second_font_size(self, v: int) -> None:
        if self._clip and self._clip.is_text_clip:
            size = max(8, int(v))
            self._clip.text_font_size = size
            self._clip.text_second_font_size = size
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_text_font_family(self, v: str) -> None:
        if self._clip and self._clip.is_text_clip:
            self._clip.text_font_family = (v or "").strip() or "Verdana"
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_text_color(self, v: str) -> None:
        if self._clip and self._clip.is_text_clip:
            color = self._normalize_hex_color(v, "#ffffff")
            self._clip.text_color = color
            self._clip.text_second_color = color
            self._refresh_text_row_backgrounds()
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_text_second_color(self, v: str) -> None:
        if self._clip and self._clip.is_text_clip:
            color = self._normalize_hex_color(v, "#ffffff")
            self._clip.text_color = color
            self._clip.text_second_color = color
            self._refresh_text_row_backgrounds()
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _apply_text_stroke_width(self, v: int) -> None:
        if self._clip and self._clip.is_text_clip:
            self._clip.text_stroke_width = max(0, min(10, int(v)))
            self._update_apply_style_button_state()
            self._emit_clip_changed()

    def _on_translate_clicked(self) -> None:
        if self._clip is None or not self._clip.is_text_clip:
            return
        self.translate_requested.emit(self._clip)


class InspectorPanel(QWidget):
    """Single right panel: dynamic Project/Video/Text properties."""

    clip_changed = Signal()
    translate_requested = Signal(object)
    cue_double_clicked = Signal(object)  # Cue
    caption_clip_double_clicked = Signal(object)  # Clip
    caption_clip_selected = Signal(object)  # Clip | None
    caption_add_requested = Signal()
    caption_delete_requested = Signal(object)
    caption_text_edit_requested = Signal(object, str)
    caption_find_replace_requested = Signal()
    caption_filter_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel("PROJECT PROPERTIES")
        self._header.setObjectName("sectionHeader")
        self._header.setFixedHeight(48)
        layout.addWidget(self._header)

        self._stack = QStackedWidget()
        
        # Page 1: Info (Main Tab)
        self._info = _ProjectInfoTab()
        self._stack.addWidget(self._info)

        layout.addWidget(self._stack)

        self._info.clip_changed.connect(self.clip_changed.emit)
        self._info.translate_requested.connect(self.translate_requested.emit)
        self._info.title_changed.connect(self._on_info_title_changed)
        self._info.caption_clip_double_clicked.connect(
            self.caption_clip_double_clicked.emit
        )
        self._info.caption_clip_selected.connect(self.caption_clip_selected.emit)
        self._info.caption_add_requested.connect(self.caption_add_requested.emit)
        self._info.caption_delete_requested.connect(self.caption_delete_requested.emit)
        self._info.caption_text_edit_requested.connect(
            self.caption_text_edit_requested.emit
        )
        self._info.caption_find_replace_requested.connect(
            self.caption_find_replace_requested.emit
        )
        self._info.caption_filter_requested.connect(self.caption_filter_requested.emit)
        
    def _on_info_title_changed(self, title: str) -> None:
        if self._stack.currentIndex() == 0:
            self._header.setText(title)

    def show_properties(self) -> None:
        """Chuyá»ƒn sang tab thuá»™c tÃ­nh (máº·c Ä‘á»‹nh)."""
        self._stack.setCurrentWidget(self._info)
        self._header.setText(self._info.current_title())

    def clear_ocr_results(self) -> None:
        pass

    def switch_to_text_tab(self) -> None:
        """Chuyển sang tab Văn bản (Text Properties)."""
        self.show_properties()
        self._info._btn_text_tab_text.setChecked(True)



    @staticmethod
    def _wrap_scroll_tab(content: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        area.viewport().setStyleSheet("background: transparent;")
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        area.setWidget(content)
        return area

    def set_project(self, project: Project) -> None:
        self._info.set_project(project)

    def refresh(self) -> None:
        self._info.refresh()

    def set_clip(
        self,
        clip: object | None,
        *,
        prefer_caption_tab_for_text: bool = False,
        track_kind: str | None = None,
    ) -> None:
        prev_clip = self._info.current_clip()
        prev_text_tab = bool(self._info._btn_text_tab_text.isChecked())
        self.show_properties()
        self._info.set_clip(clip, track_kind=track_kind)
        # Auto-switch tab if a text clip is selected.
        if self._info._clip and self._info._clip.is_text_clip:
            if prefer_caption_tab_for_text:
                # Keep user on "Văn bản" when re-binding the same text clip
                # (for example after inspector-driven refresh).
                if prev_clip is self._info._clip and prev_text_tab:
                    self._info._btn_text_tab_text.setChecked(True)
                else:
                    self._info._btn_text_tab_caption.setChecked(True)
            else:
                self._info._btn_text_tab_text.setChecked(True)

    def show_caption_list_neutral(self) -> None:
        self.show_properties()
        self._info.show_caption_list_neutral()

    def current_clip(self) -> Clip | None:
        return self._info.current_clip()


__all__ = ["InspectorPanel"]


