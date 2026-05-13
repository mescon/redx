"""Main window: orchestrates Search/Filters/Settings/Log tabs."""
from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QIcon
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

from .. import __version__
from ..config import Config, DeleteMode
from ..deleter import DeleteResult
from ..protect import iter_deletable
from ..scanner import ScanNode, ScanProgress, is_system_path
from .filters_tab import FiltersTab
from .log_widget import LogWidget
from .settings import Settings
from .settings_tab import SettingsTab
from .tree_widget import ScanTreeWidget
from .workers import DeleteWorker, ScanWorker


# NOTE: DeleteMode.TRASH_CONFIRM is intentionally omitted from the UI
# dropdown for 0.1.0. The engine supports it (Deleter respects on_confirm)
# but the worker thread cannot block on a main-thread QMessageBox without
# a synchronization primitive bridging the two threads. The bare TRASH
# mode + the single top-level "About to move N files" confirmation cover
# the same UX without per-file thread-bridging code. Re-introduce when
# we have a tested cross-thread confirm channel.
_DELETE_MODE_LABELS: dict[DeleteMode, str] = {
    DeleteMode.TRASH:    "Move to trash (default)",
    DeleteMode.DIRECT:   "Delete permanently (skip trash)",
    DeleteMode.SIMULATE: "Simulate (don't delete)",
}


def _app_icon() -> QIcon:
    """Load the bundled SVG icon out of the package's resources dir."""
    path = files("redx").joinpath("resources/redx.svg")
    return QIcon(str(path))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"redx {__version__}: Remove Empty Directories")
        self.setWindowIcon(_app_icon())
        self.resize(960, 640)
        # Accept folder drops onto the whole window so users can drag a
        # directory from their file manager into redx as the scan target.
        self.setAcceptDrops(True)

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

        # About button lives on the tab-bar's right edge instead of in
        # a separate menubar. setCornerWidget puts a widget in the
        # corner of QTabWidget's tab bar — visually it sits to the
        # right of the rightmost tab.
        about_btn = QPushButton("About")
        about_btn.setFlat(True)
        about_btn.clicked.connect(self._on_about)
        tabs.setCornerWidget(about_btn, Qt.Corner.TopRightCorner)

        self.setCentralWidget(tabs)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(f"Ready (redx {__version__}). Pick a folder and click Scan.")

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
        self._show_full = QCheckBox("Show full tree (slower for big scans)")
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

    # ---------- Persistence ---------------------------------------------------
    #
    # Settings are written to disk in two situations:
    #   1. closeEvent: graceful window close (X button, app menu Quit).
    #   2. Every Scan: clicking Scan commits the current UI state, so we
    #      persist it then. This is what protects us against SIGTERM
    #      (e.g. ``pkill redx`` from a reinstall script) — closeEvent
    #      doesn't run on SIGTERM, but anything the user has actually
    #      run a scan with is already on disk.
    #
    # _persist() captures every UI tab into self._config and writes once.

    def _persist(self) -> None:
        self._filters_tab.apply_to(self._config)
        self._settings_tab.apply_to(self._config)
        self._config.delete_mode = self._mode_combo.currentData()
        if self._folder_edit.text().strip():
            self._config.start_folder = Path(self._folder_edit.text().strip())
        self._settings.save_config(self._config)
        self._settings.show_full_tree = self._show_full.isChecked()
        self._settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Signal in-flight workers to stop. cancel() only sets a flag;
        # the threads keep running until they check that flag and
        # return. If we proceed past super().closeEvent without
        # waiting, the QApplication tears down while a thread is mid-
        # iterdir / mid-send2trash, causing a use-after-free crash.
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        if self._delete_worker is not None:
            self._delete_worker.cancel()

        self._persist()

        # Wait up to 3s per thread for cancellation to take effect.
        # Cap is a UX backstop: typical cancels return in <100ms (next
        # iterdir entry check); 3s catches a worker stuck inside a
        # network-filesystem syscall without hanging quit indefinitely.
        for thread in (self._scan_thread, self._delete_thread):
            if thread is not None and thread.isRunning():
                thread.wait(3000)
        super().closeEvent(event)

    # ---------- Drag & drop folder onto the window ----------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        md = event.mimeData()
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            # Folder drop: use it directly. File drop: use its parent.
            target: Path | None = None
            if p.is_dir():
                target = p
            elif p.is_file():
                target = p.parent
            if target is not None:
                self._folder_edit.setText(str(target))
                event.acceptProposedAction()
                return

    @Slot()
    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About redx",
            f"<h3>redx {__version__}</h3>"
            "<p>Find and delete empty directories on Linux.</p>"
            "<p>License: LGPL-3.0-or-later</p>"
            "<p><a href='https://github.com/mescon/redx'>github.com/mescon/redx</a></p>",
        )

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
        # Refuse system / kernel mountpoints. The user almost certainly
        # didn't intend to scan a pseudo-filesystem; the safer behaviour
        # is to bounce them with a clear message rather than burn CPU
        # walking /proc and possibly producing alarming log output.
        if is_system_path(folder):
            QMessageBox.warning(
                self, "redx",
                f"Refusing to scan system directory:\n{folder}\n\n"
                "This path is a kernel/boot directory, not user data. "
                "Pick a folder under your home directory or a mounted "
                "data volume instead.",
            )
            return

        self._filters_tab.apply_to(self._config)
        self._settings_tab.apply_to(self._config)
        self._config.start_folder = folder
        # Persist the moment the user commits to a config by clicking Scan.
        # Survives SIGTERM-style kills (e.g. install scripts) that bypass
        # closeEvent.
        self._persist()
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

        # TRASH_CONFIRM intentionally absent: it's removed from the UI
        # dropdown until cross-thread confirm-channel wiring lands.
        verb_for = {
            DeleteMode.TRASH:    f"move {len(empties)} empty directories to trash",
            DeleteMode.DIRECT:   f"PERMANENTLY DELETE {len(empties)} empty directories",
            DeleteMode.SIMULATE: f"simulate deleting {len(empties)} directories (no changes)",
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
        # When at least one succeeded we re-scan, which calls
        # _update_delete_button after fresh classification. When NOTHING
        # succeeded the scan tree is still valid (nothing changed on
        # disk), so refresh the button state from it instead of leaving
        # the button stuck disabled.
        if self._config.start_folder is not None and ok > 0:
            self._on_scan()
        else:
            self._update_delete_button()

        if bad > 0:
            preview = "\n".join(
                f"  {r.path.name}: {r.error}" for r in self._delete_failed[:20]
            )
            if bad > 20:
                preview += f"\n  …and {bad - 20} more"
            QMessageBox.warning(self, "Some deletes failed", preview)


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setOrganizationName("redx")
    app.setApplicationName("redx")
    # On Wayland (and KDE Plasma in particular), the taskbar/dock icon is
    # not pulled from setWindowIcon; it's resolved via the running
    # window's app_id, which Qt sets from setDesktopFileName. Without
    # this call Plasma falls back to a generic cogwheel because it has
    # nothing to match the window against. The argument is the desktop
    # file's base name (no ``.desktop`` suffix).
    app.setDesktopFileName("redx")
    # setWindowIcon is still useful as a fallback (X11 _NET_WM_ICON,
    # title bars on some compositors) and must come AFTER the
    # QApplication exists.
    app.setWindowIcon(_app_icon())
    win = MainWindow()
    win.show()
    event_loop = app.exec
    return event_loop()
