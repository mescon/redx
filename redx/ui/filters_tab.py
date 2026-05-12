"""Filters tab: editable ignore-pattern lists and zero-byte/hidden toggles.

Mirrors RED's Filters/Whitelist+Blacklist tab. Pattern syntax is fnmatch
glob (``*.txt``, ``Thumbs.db``, ``[Tt]emp``): the same matcher the scanner
uses, kept consistent here intentionally.
"""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Config


def _parse_lines(text: str) -> list[str]:
    """Split user pattern text into trimmed non-empty patterns.

    Lines starting with ``#`` are treated as comments and dropped. Blank
    lines are dropped. Leading/trailing whitespace is trimmed so users
    can copy-paste freely.
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


class FiltersTab(QWidget):
    """Filters tab widget.

    Stateful in the sense that it owns the visible widget contents, but
    holds no persistent reference to a Config: the parent window calls
    ``apply_to(config)`` before scanning to copy values out.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._zero_byte = QCheckBox("Treat zero-byte files as empty")
        self._zero_byte.setToolTip(
            "When on, files of size 0 are ignored: a directory containing "
            "only zero-byte files counts as empty."
        )

        self._hidden_dirs = QCheckBox(
            "Ignore hidden directories (names starting with '.')"
        )
        self._hidden_dirs.setToolTip(
            "When on, dot-directories like .cache or .config are not scanned."
        )

        layout.addWidget(self._zero_byte)
        layout.addWidget(self._hidden_dirs)
        layout.addSpacing(12)

        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        layout.addWidget(_bold("Ignore files matching these patterns"))
        layout.addWidget(QLabel(
            "Directories containing ONLY matching files are treated as empty."
        ))
        self._ignore_files = QPlainTextEdit()
        self._ignore_files.setFont(mono)
        self._ignore_files.setPlaceholderText("*.tmp\n*.bak\nThumbs.db")
        self._ignore_files.setMaximumHeight(140)
        layout.addWidget(self._ignore_files)
        layout.addWidget(_hint(
            "One pattern per line. Glob syntax: * matches anything, "
            "? matches one char, [abc] matches a char class. Lines starting with # are comments."
        ))

        layout.addSpacing(12)

        layout.addWidget(_bold("Skip directories matching these patterns"))
        layout.addWidget(QLabel(
            "Skipped dirs are not scanned. Their parent is NOT counted as empty "
            "(safer default: we didn't look inside)."
        ))
        self._ignore_dirs = QPlainTextEdit()
        self._ignore_dirs.setFont(mono)
        self._ignore_dirs.setPlaceholderText(".git\nnode_modules\n__pycache__")
        self._ignore_dirs.setMaximumHeight(140)
        layout.addWidget(self._ignore_dirs)
        layout.addWidget(_hint("One pattern per line. Same glob syntax."))

        layout.addSpacing(8)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._on_reset)
        button_row.addWidget(reset)
        layout.addLayout(button_row)

        layout.addStretch(1)

        # Re-scan hint at the bottom so users know changes don't auto-apply.
        layout.addWidget(_hint(
            "Changes here take effect on the next Scan."
        ))

    def load_from(self, config: Config) -> None:
        self._zero_byte.setChecked(config.ignore_empty_files)
        self._hidden_dirs.setChecked(config.ignore_hidden_dirs)
        self._ignore_files.setPlainText("\n".join(config.ignore_files))
        self._ignore_dirs.setPlainText("\n".join(config.ignore_dirs))

    def apply_to(self, config: Config) -> None:
        config.ignore_empty_files = self._zero_byte.isChecked()
        config.ignore_hidden_dirs = self._hidden_dirs.isChecked()
        config.ignore_files = _parse_lines(self._ignore_files.toPlainText())
        config.ignore_dirs = _parse_lines(self._ignore_dirs.toPlainText())

    def _on_reset(self) -> None:
        self.load_from(Config())


def _bold(text: str) -> QLabel:
    label = QLabel(f"<b>{text}</b>")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(f"<i><span style='color: gray'>{text}</span></i>")
    label.setWordWrap(True)
    return label
