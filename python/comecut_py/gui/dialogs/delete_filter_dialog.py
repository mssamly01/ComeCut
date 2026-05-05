"""Dialog to choose filtered subtitle rows for deletion."""

from __future__ import annotations

from PySide6.QtCore import Qt  # type: ignore
from PySide6.QtWidgets import (  # type: ignore
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from comecut_py.core.project import Clip


class DeleteFilterDialog(QDialog):
    def __init__(self, parent, *, title: str, candidates: list[Clip]) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Xóa: {title}")
        self.setModal(True)
        self.resize(560, 440)
        self._candidates = list(candidates)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        info = QLabel(
            f"Tìm thấy <b>{len(candidates)}</b> dòng phụ đề khớp.<br>"
            "Bỏ chọn các dòng bạn <b>muốn giữ</b>."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self._check_all = QCheckBox("Chọn tất cả để xóa")
        self._check_all.setChecked(True)
        self._check_all.stateChanged.connect(self._on_toggle_all)
        root.addWidget(self._check_all)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background:#121212; border:1px solid #333; border-radius:4px; } "
            "QListWidget::item { padding:6px; color:#bbb; border-bottom:1px solid #222; } "
            "QListWidget::item:selected { background:#1a1a1a; border:1px solid #00E5FF; "
            "color:#00E5FF; border-radius:4px; }"
        )
        for idx, clip in enumerate(self._candidates, start=1):
            text = (clip.text_main or "").replace("\n", " ").strip() or "(rỗng)"
            item = QListWidgetItem(f"#{idx} [{clip.start:.2f}s] {text[:120]}")
            item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, idx - 1)
            self._list.addItem(item)
        root.addWidget(self._list, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Xóa đã chọn")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_toggle_all(self, state: int) -> None:
        check_state = Qt.CheckState.Checked if state != 0 else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(check_state)

    def selected_clips(self) -> list[Clip]:
        selected: list[Clip] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            idx = int(item.data(Qt.ItemDataRole.UserRole))
            if 0 <= idx < len(self._candidates):
                selected.append(self._candidates[idx])
        return selected
