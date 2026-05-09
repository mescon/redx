"""Main window: orchestrates Search/Filters/Settings/Log tabs."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import Config, DeleteMode
from ..deleter import DeleteResult
from ..protect import iter_deletable
from ..scanner import ScanNode, ScanProgress
from .filters_tab import FiltersTab
from .log_widget import LogWidget
from .settings import Settings
from .settings_tab import SettingsTab
from .tree_widget import ScanTreeWidget
from .workers import DeleteWorker, ScanWorker


_DELETE_MODE_LABELS: dict[DeleteMode, str] = {
    DeleteMode.TRASH:         "Move to trash (default)",
    DeleteMode.TRASH_CONFIRM: "Move to trash, ask each time",
    DeleteMode.DIRECT:        "Delete permanently (skip trash)",
    DeleteMode.SIMULATE:      "Simulate (don't delete)",
}


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("redx: Remove Empty Directories")
        self.resize(960, 640)

        self._settings = settings if settings is not None else Settings()
        self._config = Config()
        self._settings.load_config(self._config)

        self._scan_root: ScanNode | None = None
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._delete_thread: QThread | None = None
        self._delete_worker: DeleteWorker | None = None
        self._delete_succeeded: list[Path] = []
        self._delete_failed: list[DeleteResult] = []

        self._build_ui()
        self._restore_persisted_view_state()

    # ---------- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        self._filters_tab = FiltersTab()
        self._filters_tab.load_from(self._config)

        self._settings_tab = SettingsTab()
        self._settings_tab.load_from(self._config)

        self._log = LogWidget()

        tabs = QTabWidget()
        tabs.addTab(self._build_search_tab(), "Search")
        tabs.addTab(self._filters_tab, "Filters")
        tabs.addTab(self._settings_tab, "Settings")
        tabs.addTab(self._log, "Log")
        self.setCentralWidget(tabs)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready. Pick a folder and click Scan.")

    def _build_search_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Folder picker row
        row = QHBoxLayout()
        row.addWidget(QLabel("Folder:"))
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("/path/to/scan")
        self._folder_edit.returnPressed.connect(self._on_scan)
        row.addWidget(self._folder_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        row.addWidget(browse)
        layout.addLayout(row)

        # Tree
        self._tree = ScanTreeWidget()
        self._tree.protection_changed.connect(self._update_delete_button)
        self._tree.node_protected.connect(self._on_node_protected)
        self._tree.node_unprotected.connect(self._on_node_unprotected)
        layout.addWidget(self._tree, stretch=1)

        # View toggle row
        view_row = QHBoxLayout()
        self._show_full = QCheckBox("Show full tree (matches RED, slower for big scans)")
        self._show_full.toggled.connect(self._on_show_full_toggled)
        view_row.addWidget(self._show_full)
        view_row.addStretch(1)
        layout.addLayout(view_row)

        # Scan controls
        scan_row = QHBoxLayout()
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.clicked.connect(self._on_scan)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        scan_row.addWidget(self._scan_btn)
        scan_row.addWidget(self._cancel_btn)
        scan_row.addStretch(1)
        layout.addLayout(scan_row)

        # Delete controls
        del_row = QHBoxLayout()
        del_row.addWidget(QLabel("Mode:"))
        self._mode_combo = QComboBox()
        for mode, label in _DELETE_MODE_LABELS.items():
            self._mode_combo.addItem(label, mode)
        # Pre-select the persisted mode if it round-tripped
        idx = self._mode_combo.findData(self._config.delete_mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        del_row.addWidget(self._mode_combo)
        del_row.addStretch(1)
        self._delete_btn = QPushButton("Delete empty directories")
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setEnabled(False)
        del_row.addWidget(self._delete_btn)
        layout.addLayout(del_row)

        return w

    def _restore_persisted_view_state(self) -> None:
        if self._config.start_folder is not None:
            self._folder_edit.setText(str(self._config.start_folder))
        self._show_full.setChecked(self._settings.show_full_tree)

    # ---------- Persistence on close --------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        # Cancel any in-flight work so threads finish cleanly.
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        if self._delete_worker is not None:
            self._delete_worker.cancel()

        self._filters_tab.apply_to(self._config)
        self._settings_tab.apply_to(self._config)
        self._config.delete_mode = self._mode_combo.currentData()
        if self._folder_edit.text().strip():
            self._config.start_folder = Path(self._folder_edit.text().strip())

        self._settings.save_config(self._config)
        self._settings.show_full_tree = self._show_full.isChecked()
        self._settings.sync()
        super().closeEvent(event)

    # ---------- Scan flow -------------------------------------------------------

    @Slot()
    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Pick a folder to scan",
            self._folder_edit.text().strip() or str(Path.home()),
        )
        if folder:
            self._folder_edit.setText(folder)

    @Slot()
    def _on_scan(self) -> None:
        text = self._folder_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "redx", "Pick a folder first.")
            return
        folder = Path(text).expanduser()
        if not folder.is_dir():
            QMessageBox.warning(self, "redx", f"Not a directory:\n{folder}")
            return

        self._filters_tab.apply_to(self._config)
        self._settings_tab.apply_to(self._config)
        self._config.start_folder = folder
        self._scan_root = None
        self._tree.clear()
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._delete_btn.setEnabled(False)
        self._status.showMessage(f"Scanning {folder}…")

        self._log.info(f"Scan started: {folder}")
        self._log.info(
            f"  ignore_files={self._config.ignore_files} "
            f"ignore_dirs={self._config.ignore_dirs} "
            f"ignore_empty_files={self._config.ignore_empty_files} "
            f"ignore_hidden_dirs={self._config.ignore_hidden_dirs}"
        )

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(self._config)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_done)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    @Slot()
    def _on_cancel(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        if self._delete_worker is not None:
            self._delete_worker.cancel()
        self._log.info("Cancellation requested.")

    @Slot(object)
    def _on_scan_progress(self, p: ScanProgress) -> None:
        self._status.showMessage(
            f"Scanning… {p.folders_scanned} folders, "
            f"{p.empty_found} empty so far  ·  {p.current_path}"
        )

    @Slot(object)
    def _on_scan_done(self, root: ScanNode) -> None:
        self._scan_root = root
        self._tree.set_root(root, prune=not self._show_full.isChecked())
        n = sum(1 for _ in iter_deletable(root))
        self._status.showMessage(f"Done. {n} empty directories.")
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._update_delete_button()
        self._log.info(f"Scan finished: {n} empty directories.")

    @Slot(bool)
    def _on_show_full_toggled(self, show_full: bool) -> None:
        if self._scan_root is not None:
            self._tree.set_root(self._scan_root, prune=not show_full)

    @Slot()
    def _update_delete_button(self) -> None:
        if self._scan_root is None:
            self._delete_btn.setText("Delete empty directories")
            self._delete_btn.setEnabled(False)
            return
        n = sum(1 for _ in iter_deletable(self._scan_root))
        if n == 0:
            self._delete_btn.setText("Nothing to delete")
            self._delete_btn.setEnabled(False)
        else:
            noun = "directory" if n == 1 else "directories"
            self._delete_btn.setText(f"Delete {n} empty {noun}")
            self._delete_btn.setEnabled(True)

    @Slot(str)
    def _on_scan_error(self, message: str) -> None:
        self._status.showMessage(f"Scan failed: {message}")
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._log.error(f"Scan failed: {message}")
        QMessageBox.warning(self, "Scan failed", message)

    # ---------- Protect / Unprotect logging ------------------------------------

    @Slot(object)
    def _on_node_protected(self, node) -> None:
        self._log.info(f"Protected: {node.path}")

    @Slot(object)
    def _on_node_unprotected(self, node) -> None:
        self._log.info(f"Unprotected: {node.path}")

    # ---------- Delete flow -----------------------------------------------------

    @Slot()
    def _on_delete(self) -> None:
        if self._scan_root is None:
            return
        self._config.delete_mode = self._mode_combo.currentData()
        empties = [n.path for n in iter_deletable(self._scan_root)]
        if not empties:
            return

        verb_for = {
            DeleteMode.TRASH:         f"move {len(empties)} empty directories to trash",
            DeleteMode.TRASH_CONFIRM: f"move up to {len(empties)} directories to trash (you'll confirm each)",
            DeleteMode.DIRECT:        f"PERMANENTLY DELETE {len(empties)} empty directories",
            DeleteMode.SIMULATE:      f"simulate deleting {len(empties)} directories (no changes)",
        }
        ans = QMessageBox.question(
            self, "redx", f"About to {verb_for[self._config.delete_mode]}.\n\nContinue?"
        )
        if ans is not QMessageBox.StandardButton.Yes:
            return

        self._delete_succeeded.clear()
        self._delete_failed.clear()
        self._scan_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._status.showMessage("Deleting…")
        self._log.info(
            f"Delete: mode={self._config.delete_mode.value} count={len(empties)}"
        )

        self._delete_thread = QThread(self)
        self._delete_worker = DeleteWorker(self._config, empties)
        self._delete_worker.moveToThread(self._delete_thread)
        self._delete_thread.started.connect(self._delete_worker.run)
        self._delete_worker.result.connect(self._on_delete_result)
        self._delete_worker.finished.connect(self._on_delete_done)
        self._delete_worker.finished.connect(self._delete_thread.quit)
        self._delete_worker.finished.connect(self._delete_worker.deleteLater)
        self._delete_thread.finished.connect(self._delete_thread.deleteLater)
        self._delete_thread.start()

    @Slot(object)
    def _on_delete_result(self, r: DeleteResult) -> None:
        if r.success:
            self._delete_succeeded.append(r.path)
            self._log.info(f"  ok   {r.path}")
        else:
            self._delete_failed.append(r)
            self._log.error(f"  fail {r.path}: {r.error}")
        self._status.showMessage(
            f"Deleting… {len(self._delete_succeeded)} ok / "
            f"{len(self._delete_failed)} failed"
        )

    @Slot()
    def _on_delete_done(self) -> None:
        ok = len(self._delete_succeeded)
        bad = len(self._delete_failed)
        self._status.showMessage(f"Deletion done: {ok} succeeded, {bad} failed.")
        self._log.info(f"Delete finished: {ok} succeeded, {bad} failed.")
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

        if bad > 0:
            preview = "\n".join(
                f"  {r.path.name}: {r.error}" for r in self._delete_failed[:20]
            )
            if bad > 20:
                preview += f"\n  …and {bad - 20} more"
            QMessageBox.warning(self, "Some deletes failed", preview)

        if self._config.start_folder is not None and ok > 0:
            self._on_scan()


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setOrganizationName("redx")
    app.setApplicationName("redx")
    win = MainWindow()
    win.show()
    event_loop = app.exec
    return event_loop()
