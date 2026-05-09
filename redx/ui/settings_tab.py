"""Settings tab: extra Config knobs not on the Filters tab."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Config


class SettingsTab(QWidget):
    """Configurable knobs for scan/delete behaviour.

    Values persist via the parent window's Settings on close. There's no
    Apply button: flip a setting, run a Scan, the new values take effect.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())

        self._pause = QSpinBox()
        self._pause.setRange(0, 10000)
        self._pause.setSuffix(" ms")
        self._pause.setToolTip(
            "Sleep this long between deletions. Useful if the destination "
            "is on a slow/networked filesystem."
        )
        form.addRow("Pause between deletions:", self._pause)

        self._min_age = QDoubleSpinBox()
        self._min_age.setRange(0.0, 8760.0)  # one year
        self._min_age.setSuffix(" hours")
        self._min_age.setToolTip(
            "Skip directories whose modification time is newer than N hours. "
            "Use to avoid racing live processes that are still creating files."
        )
        form.addRow("Ignore folders newer than:", self._min_age)

        self._max_depth = QSpinBox()
        self._max_depth.setRange(1, 1000)
        self._max_depth.setToolTip(
            "Hard cap on recursion depth. Defends against pathological trees."
        )
        form.addRow("Max scan depth:", self._max_depth)

        self._loop_threshold = QSpinBox()
        self._loop_threshold.setRange(0, 100)
        self._loop_threshold.setToolTip(
            "How many path-too-long errors before aborting. 0 disables the check."
        )
        form.addRow("Infinite-loop threshold:", self._loop_threshold)

        self._follow_symlinks = QCheckBox(
            "Follow symbolic links when scanning (DANGEROUS: can loop)"
        )
        self._follow_symlinks.setToolTip(
            "Off by default. Following symlinks can cause infinite loops or "
            "delete directories you didn't expect."
        )
        form.addRow("", self._follow_symlinks)

        layout.addLayout(form)
        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._on_reset)
        button_row.addWidget(reset)
        layout.addLayout(button_row)

        layout.addWidget(QLabel(
            "<i><span style='color:gray'>Settings persist automatically when "
            "the app closes.</span></i>"
        ))

    def load_from(self, config: Config) -> None:
        self._pause.setValue(int(config.pause_between_deletes_ms))
        self._min_age.setValue(float(config.min_folder_age_hours))
        self._max_depth.setValue(int(config.max_depth))
        self._loop_threshold.setValue(int(config.infinite_loop_threshold))
        self._follow_symlinks.setChecked(bool(config.follow_symlinks))

    def apply_to(self, config: Config) -> None:
        config.pause_between_deletes_ms = self._pause.value()
        config.min_folder_age_hours = self._min_age.value()
        config.max_depth = self._max_depth.value()
        config.infinite_loop_threshold = self._loop_threshold.value()
        config.follow_symlinks = self._follow_symlinks.isChecked()

    def _on_reset(self) -> None:
        self.load_from(Config())
