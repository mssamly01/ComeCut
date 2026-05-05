"""Subtitle edit + translate dialog (closer HTML parity)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class SubtitleDialogInfo:
    provider_info: str
    target_language: str
    source_language: str | None


class SubtitleEditTranslateDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        title: str,
        main_text: str,
        second_text: str,
        info: SubtitleDialogInfo,
        batch_rows: list[tuple[str, str, str]],
        on_open_plugin_settings: Callable[[], None],
        on_translate_to_second: Callable[[str], str],
        on_batch_translate_track: Callable[[], None],
        on_save: Callable[[str, str], None],
    ) -> None:
        super().__init__(parent)
        self._on_save = on_save
        title_meta = f"{info.provider_info}  •  Target: {info.target_language or 'Vietnamese'}"
        self.setWindowTitle(f"{title}  |  {title_meta}")
        self.resize(940, 640)
        self.setStyleSheet(
            """
            QDialog { background: #06090f; color: #e6e8ec; }
            QFrame#headCard { background: #111722; border: 1px solid #2f3847; border-radius: 6px; }
            QLabel#headTitle { color: #f1f4fb; font-weight: 800; font-size: 11px; }
            QLabel#headMeta { color: #9aa3b3; font-size: 11px; }

            QTabWidget::pane { border: none; background: transparent; }
            QTabBar::tab {
                background: transparent;
                color: #98a2b3;
                padding: 8px 12px;
                border: none;
                border-bottom: 2px solid transparent;
                font-size: 9px;
                font-weight: 700;
            }
            QTabBar::tab:selected {
                color: #20d0e6;
                border-bottom: 2px solid #20d0e6;
            }

            QFrame#sectionCard {
                background: #1d2430;
                border: 1px solid #334257;
                border-radius: 6px;
            }
            QLabel#sectionTitle {
                background: #111722;
                color: #dce3ef;
                border: none;
                font-weight: 700;
                padding: 2px 0;
                font-size: 10px;
            }
            QComboBox {
                background: #2a2a2d;
                border: 1px solid #454b58;
                border-radius: 6px;
                color: #e6e8ec;
                min-height: 28px;
                padding: 0 24px 0 8px;
                font-size: 10px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 22px;
                border: none;
                background: transparent;
            }
            QTextEdit {
                background: #1e222b;
                border: 1px solid #3b4150;
                border-radius: 6px;
                color: #e6e8ec;
                padding: 8px;
                font-size: 10px;
            }
            QTextEdit:focus { border-color: #20d0e6; }

            QTableWidget {
                background: #1e2531;
                border: 1px solid #00a6b7;
                border-radius: 0px;
                gridline-color: #0d8e9b;
            }
            QTableWidget::item {
                border-bottom: 1px solid #0d8e9b;
                padding: 6px;
            }
            QPushButton#htmlPrimary {
                background: #00495d;
                border: 1px solid #0b8ea0;
                color: #e7fbff;
                border-radius: 0px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
                min-height: 30px;
            }
            QPushButton#htmlPrimary:hover { background: #005c72; }
            QPushButton#htmlClose {
                background: transparent;
                border: none;
                color: #b9c0cc;
                font-size: 14px;
                min-width: 28px;
                min-height: 26px;
            }
            QPushButton#htmlClose:hover { color: #ffffff; }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        root.addWidget(tabs, stretch=1)
        tabs.tabBar().setExpanding(True)
        tabs.tabBar().setDrawBase(False)
        tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)

        # --- Tab: Edit current clip -------------------------------------------------
        tab_edit = QWidget()
        tab_edit_layout = QVBoxLayout(tab_edit)
        tab_edit_layout.setContentsMargins(0, 0, 0, 0)
        tab_edit_layout.setSpacing(14)

        self._main_edit = self._build_editor_section("Main -1", main_text, "Auto")
        self._second_edit = self._build_editor_section("Second -2", second_text, "Chinese")
        tab_edit_layout.addWidget(self._main_edit["card"])
        tab_edit_layout.addWidget(self._second_edit["card"])
        tab_edit_layout.addSpacing(8)

        edit_actions = QHBoxLayout()
        edit_actions.addStretch(1)
        btn_translate = QPushButton("Click to translate subtitles   ( 1 ➜ 2 )")
        btn_translate.setObjectName("htmlPrimary")
        btn_translate.setFixedWidth(360)
        edit_actions.addWidget(btn_translate)
        edit_actions.addStretch(1)
        tab_edit_layout.addLayout(edit_actions)
        tab_edit_layout.addStretch(1)

        def _translate_clicked() -> None:
            src = (self._main_edit["edit"].toPlainText() or "").strip()
            if not src:
                src = (self._second_edit["edit"].toPlainText() or "").strip()
            if not src:
                self._toast("No subtitle text to translate.")
                return
            try:
                out = on_translate_to_second(src)
            except Exception as e:
                self._toast(str(e), is_error=True)
                return
            self._second_edit["edit"].setPlainText(out or "")
            self._toast("Subtitle translated.")

        btn_translate.clicked.connect(_translate_clicked)

        # --- Tab: Batch translate track --------------------------------------------
        tab_batch = QWidget()
        tab_batch_layout = QVBoxLayout(tab_batch)
        tab_batch_layout.setContentsMargins(0, 0, 0, 0)
        tab_batch_layout.setSpacing(8)

        self._batch_table = QTableWidget(0, 3)
        self._batch_table.setObjectName("batchTable")
        self._batch_table.setHorizontalHeaderLabels(["", "", ""])
        self._batch_table.verticalHeader().setVisible(False)
        self._batch_table.horizontalHeader().setVisible(False)
        self._batch_table.setShowGrid(True)
        self._batch_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._batch_table.setAlternatingRowColors(True)
        self._batch_table.setWordWrap(True)
        self._batch_table.setColumnWidth(0, 52)
        self._batch_table.setColumnWidth(1, 160)
        tab_batch_layout.addWidget(self._batch_table, stretch=1)
        self.set_batch_rows(batch_rows)

        batch_actions = QHBoxLayout()
        batch_actions.setSpacing(0)
        batch_actions.addStretch(1)
        btn_batch = QPushButton("Click to translate subtitles   ( 1 ➜ 2 )")
        btn_batch.setObjectName("htmlPrimary")
        btn_batch.setFixedWidth(330)
        batch_actions.addWidget(btn_batch)
        batch_actions.addStretch(1)

        tab_batch_layout.addLayout(batch_actions)
        tab_batch_layout.addStretch(1)

        def _batch_clicked() -> None:
            try:
                on_batch_translate_track()
            except Exception as e:
                self._toast(str(e), is_error=True)
                return
            self._toast("Batch translation done.")

        btn_batch.clicked.connect(_batch_clicked)

        tabs.addTab(tab_edit, "⚒ Edit subtitles & Translate")
        tabs.addTab(tab_batch, "☰ Batch edit & Translate")
        tabs.tabBar().setUsesScrollButtons(False)
        tabs.tabBar().setStyle(QTabBar().style())

        self._toast_lbl = QLabel("")
        self._toast_lbl.setWordWrap(True)
        self._toast_lbl.setStyleSheet("color: #8c93a0; padding: 2px 0;")
        root.addWidget(self._toast_lbl)

    def set_batch_rows(self, rows: list[tuple[str, str, str]]) -> None:
        rows = rows or []
        self._batch_table.setRowCount(len(rows))
        for r, (idx, span, text) in enumerate(rows):
            i0 = QTableWidgetItem(str(idx))
            i1 = QTableWidgetItem(str(span))
            i2 = QTableWidgetItem(str(text))
            for it in (i0, i1, i2):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            i0.setTextAlignment(int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter))
            i1.setTextAlignment(int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter))
            i2.setTextAlignment(int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
            self._batch_table.setItem(r, 0, i0)
            self._batch_table.setItem(r, 1, i1)
            self._batch_table.setItem(r, 2, i2)
            self._batch_table.setRowHeight(r, 48 if "\n" in text else 40)
        self._batch_table.setColumnWidth(0, 52)
        self._batch_table.setColumnWidth(1, 170)
        self._batch_table.horizontalHeader().setStretchLastSection(True)

    def set_second_text(self, text: str) -> None:
        self._second_edit["edit"].setPlainText(text or "")

    def _toast(self, msg: str, *, is_error: bool = False) -> None:
        self._toast_lbl.setStyleSheet(
            "color: #ef4444; padding: 2px 0;" if is_error else "color: #8c93a0; padding: 2px 0;"
        )
        self._toast_lbl.setText((msg or "").strip())

    @staticmethod
    def _build_editor_section(label: str, initial: str, lang_default: str) -> dict[str, object]:
        card = QFrame()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(6)

        head_row = QHBoxLayout()
        head = QLabel(label)
        head.setObjectName("sectionTitle")
        head_row.addWidget(head)
        head_row.addStretch(1)
        lang = QComboBox()
        lang.setFixedWidth(90)
        lang.addItems(["Auto", "Chinese", "English", "Vietnamese", "Japanese", "Korean"])
        lang.setCurrentText(lang_default)
        head_row.addWidget(lang)
        card_layout.addLayout(head_row)

        edit = QTextEdit()
        edit.setPlainText(initial or "")
        edit.setAcceptRichText(False)
        edit.setMinimumHeight(170)
        card_layout.addWidget(edit, stretch=1)

        return {"card": card, "edit": edit, "lang": lang}

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # HTML-like behavior: persist edits when closing dialog.
        self._on_save(
            (self._main_edit["edit"].toPlainText() or "").strip(),
            (self._second_edit["edit"].toPlainText() or "").strip(),
        )
        super().closeEvent(event)


__all__ = ["SubtitleEditTranslateDialog", "SubtitleDialogInfo"]

