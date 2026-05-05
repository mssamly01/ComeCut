"""Find/replace dialog for subtitle clips."""

from __future__ import annotations

from PySide6.QtWidgets import (  # type: ignore
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


class FindReplaceDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tìm & Thay thế")
        self.setModal(True)
        self.resize(420, 170)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self._find = QLineEdit()
        self._find.setPlaceholderText("Từ cần tìm...")
        self._replace = QLineEdit()
        self._replace.setPlaceholderText("Thay thế bằng...")
        self._case = QCheckBox("Phân biệt chữ hoa/thường")

        form.addRow("Tìm:", self._find)
        form.addRow("Thay:", self._replace)
        form.addRow("", self._case)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Thay thế tất cả")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[str, str, bool]:
        return (
            self._find.text() or "",
            self._replace.text() or "",
            self._case.isChecked(),
        )
