"""CapCut-style 'Liên kết tệp phương tiện' modal dialog.

Shown automatically when a project is opened and one or more library
entries cannot be located on disk.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class RelinkRow:
    """One row in the dialog. ``index`` is the position in the underlying
    library list so the caller can map updates back."""
    index: int
    kind: str  # "media" | "subtitle"
    name: str
    old_path: str
    duration: float | None
    size: int = 0  # size from LibraryEntry for fingerprint match
    new_path: str | None = None  # set when relinked


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    s = int(round(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


class RelinkMediaDialog(QDialog):
    """Modal dialog that lets the user relink missing library files.

    Emits ``relinks_applied(list[RelinkRow])`` when the user clicks the
    primary button. The caller is responsible for persisting changes.
    """

    relinks_applied = Signal(list)  # list[RelinkRow]

    def __init__(self, rows: list[RelinkRow], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Liên kết tệp phương tiện")
        self.setModal(True)
        self.resize(720, 480)
        self._rows: list[RelinkRow] = rows
        self._build_ui()
        self._refresh_counter()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)

        info = QLabel(
            "Không tìm thấy một số tệp phương tiện đã nhập.\n"
            "Hãy liên kết tệp phương tiện rồi chỉnh sửa."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #cbd0d8; font-size: 12px;")
        outer.addWidget(info)

        self.table = QTableWidget(len(self._rows), 3, self)
        self.table.setHorizontalHeaderLabels(["Tên", "Đường dẫn cũ", "Thời lượng"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet(
            """
            QTableWidget { background: #15171c; border: 1px solid #2a2f38; border-radius: 6px; gridline-color: transparent; }
            QHeaderView::section { background: #1a1d23; color: #8a91a0; font-size: 11px; padding: 8px 10px; border: none; }
            QTableWidget::item { color: #22d3c5; padding: 8px 10px; }
            QTableWidget::item:selected { background: #1f3b3a; color: #5eead4; }
            """
        )

        for r, row in enumerate(self._rows):
            self.table.setItem(r, 0, QTableWidgetItem(row.name))
            self.table.setItem(r, 1, QTableWidgetItem(row.old_path))
            self.table.setItem(r, 2, QTableWidgetItem(_format_duration(row.duration)))

        if self._rows:
            self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
            self.table.selectRow(0)
        outer.addWidget(self.table, 1)

        self.counter_lbl = QLabel("0/0 Đã liên kết tệp phương tiện")
        self.counter_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.counter_lbl.setStyleSheet("color: #8a91a0; font-size: 11px;")
        outer.addWidget(self.counter_lbl)

        self.hint_lbl = QLabel("")
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setStyleSheet("color: #f59e0b; font-size: 11px; margin-top: 4px;")
        self.hint_lbl.hide()
        outer.addWidget(self.hint_lbl)

        self.folder_mode_cb = QCheckBox("Liên kết tệp phương tiện khi chọn một thư mục")
        self.folder_mode_cb.setChecked(True)
        self.folder_mode_cb.setStyleSheet("color: #cbd0d8; font-size: 12px;")
        outer.addWidget(self.folder_mode_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.link_btn = QPushButton("Liên kết tệp phương tiện")
        self.link_btn.setStyleSheet(
            """
            QPushButton {
                background: #22d3c5; color: #0b0d10; font-weight: 700;
                border: none; border-radius: 4px; padding: 8px 16px;
            }
            QPushButton:hover { background: #2af0e0; }
            QPushButton:disabled { background: #2a2f38; color: #54595f; }
            """
        )
        self.link_btn.clicked.connect(self._on_link_clicked)
        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setStyleSheet(
            """
            QPushButton {
                background: #2a2f38; color: #cbd0d8; border: none;
                border-radius: 4px; padding: 8px 16px;
            }
            QPushButton:hover { background: #363b46; }
            """
        )
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.link_btn)
        btn_row.addWidget(self.cancel_btn)
        outer.addLayout(btn_row)

    def _on_row_double_clicked(self, item: QTableWidgetItem) -> None:
        row_idx = item.row()
        if row_idx < 0 or row_idx >= len(self._rows):
            return
        row = self._rows[row_idx]
        start_dir = str(Path(row.old_path).parent) if Path(row.old_path).parent.exists() else ""
        new_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Liên kết: {row.name}",
            start_dir,
            "All Files (*)",
        )
        if new_path:
            self._apply_single(row_idx, Path(new_path))
            if self._all_relinked():
                self.relinks_applied.emit(self._rows)
                self.accept()

    def _on_link_clicked(self) -> None:
        if self.folder_mode_cb.isChecked():
            folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa tệp phương tiện")
            if folder:
                matched = self._apply_folder_search(Path(folder))
                if matched == 0:
                    self.hint_lbl.setText(
                        "⚠ Không tìm thấy file nào trong thư mục này. "
                        "Có thể tên file đã thay đổi — hãy chọn từng file thủ công."
                    )
                    self.hint_lbl.show()
                else:
                    self.hint_lbl.hide()
        else:
            # Multi-file selection mode for manual linking
            r = self.table.currentRow()
            start_dir = ""
            if r >= 0 and r < len(self._rows):
                row = self._rows[r]
                start_dir = str(Path(row.old_path).parent) if Path(row.old_path).parent.exists() else ""
            
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Chọn tệp phương tiện để liên kết",
                start_dir,
                "All Files (*)",
            )
            if files:
                matched = self._apply_files_search([Path(f) for f in files])
                if matched == 0 and len(files) == 1:
                    # If user picked one file specifically, assume they want to link it to the selected row
                    # even if names don't match (force link)
                    if r >= 0:
                        self._apply_single(r, Path(files[0]))
                elif matched == 0:
                    self.hint_lbl.setText("⚠ Các tệp đã chọn không khớp với bất kỳ tệp nào đang thiếu.")
                    self.hint_lbl.show()
                else:
                    self.hint_lbl.hide()

        if self._all_relinked():
            # Apply and close
            self.relinks_applied.emit(self._rows)
            self.accept()

    def _apply_files_search(self, files: list[Path]) -> int:
        """Match a list of specific files to missing rows."""
        from ...core.library_resolver import resolve_in_folder
        from ...core.project import LibraryEntry
        
        # We can reuse resolve_in_folder logic by treating the list as a virtual folder
        # but it's easier to just do it here for specific files.
        entries = [
            LibraryEntry(source=row.old_path, name=row.name, size=row.size)
            for row in self._rows if row.new_path is None
        ]
        pending_indices = [i for i, r in enumerate(self._rows) if r.new_path is None]
        
        matched_count = 0
        from ...core.library_resolver import _norm_name
        
        # Build index of files by normalized name
        files_by_norm = { _norm_name(f.name): f for f in files }
        files_by_size = {}
        for f in files:
            try:
                files_by_size.setdefault(f.stat().st_size, []).append(f)
            except OSError: pass

        for i, entry in enumerate(entries):
            target_norm = _norm_name(entry.name)
            chosen: Path | None = None
            
            # Match by name
            if target_norm in files_by_norm:
                c = files_by_norm[target_norm]
                try:
                    if entry.size > 0 and c.stat().st_size != entry.size:
                        pass
                    else:
                        chosen = c
                except OSError: pass
            
            # Match by size
            if chosen is None and entry.size > 0:
                candidates = files_by_size.get(entry.size, [])
                ext = Path(entry.name).suffix.lower()
                for c in candidates:
                    if c.suffix.lower() == ext:
                        chosen = c
                        break
            
            if chosen:
                row_idx = pending_indices[i]
                self._apply_single(row_idx, chosen)
                matched_count += 1
                
        return matched_count

    def _apply_single(self, row_idx: int, new_path: Path) -> None:
        if not new_path.is_file():
            return
        self._rows[row_idx].new_path = str(new_path)
        item = self.table.item(row_idx, 1)
        item.setText(str(new_path))
        item.setForeground(QColor("#10b981"))  # green = relinked
        self._refresh_counter()
        # Even on partial: emit so caller can persist progress
        self.relinks_applied.emit(self._rows)

    def _apply_folder_search(self, folder: Path) -> int:
        # Build a quick name → path map of folder contents
        from ...core.library_resolver import resolve_in_folder
        from ...core.project import LibraryEntry
        # Build LibraryEntry list from rows for the resolver
        entries = [
            LibraryEntry(
                source=row.new_path or row.old_path,
                name=row.name,
                size=row.size,
            )
            for row in self._rows
            if row.new_path is None
        ]
        # Map row indices that need resolving
        pending_indices = [i for i, r in enumerate(self._rows) if r.new_path is None]
        updates = resolve_in_folder(entries, folder, recursive=True)
        for local_i, e in updates.items():
            row_idx = pending_indices[local_i]
            self._apply_single(row_idx, Path(e.source))
        return len(updates)

    def _all_relinked(self) -> bool:
        return all(r.new_path is not None for r in self._rows)

    def _refresh_counter(self) -> None:
        n = sum(1 for r in self._rows if r.new_path is not None)
        total = len(self._rows)
        self.counter_lbl.setText(f"{n}/{total} Đã liên kết tệp phương tiện")
        if n == total and total > 0:
            self.cancel_btn.setText("Đóng")


__all__ = ["RelinkRow", "RelinkMediaDialog"]
