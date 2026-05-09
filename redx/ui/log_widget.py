"""Log tab: append-only timestamped log of scans, deletions, and protect actions."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogWidget(QWidget):
    """Read-only log with auto-scroll, clear, and save-to-file."""

    MAX_LINES = 10000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self.MAX_LINES)
        self._text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self._text, stretch=1)

        button_row = QHBoxLayout()
        self._line_count_label = QLabel("0 lines")
        button_row.addWidget(self._line_count_label)
        button_row.addStretch(1)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear)
        button_row.addWidget(clear_btn)
        save_btn = QPushButton("Save to file…")
        save_btn.clicked.connect(self._on_save)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

    @Slot(str)
    def info(self, message: str) -> None:
        self._append(message)

    @Slot(str)
    def error(self, message: str) -> None:
        self._append(f"ERROR: {message}")

    def _append(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.appendPlainText(f"[{ts}] {message}")
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._line_count_label.setText(f"{self._text.blockCount()} lines")

    def _on_clear(self) -> None:
        self._text.clear()
        self._line_count_label.setText("0 lines")

    def _on_save(self) -> None:
        default_name = f"redx-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save log to file", default_name,
            "Log files (*.log);;Text files (*.txt);;All files (*)",
        )
        if not path_str:
            return
        try:
            Path(path_str).write_text(self._text.toPlainText(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "redx", f"Could not save log:\n{e}")
            return

    def to_text(self) -> str:
        return self._text.toPlainText()
