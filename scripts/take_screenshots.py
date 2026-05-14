#!/usr/bin/env python3
"""Generate README screenshots from MainWindow against the test sandbox.

Runs entirely headless via QT_QPA_PLATFORM=offscreen and renders with
GNOME's Adwaita theme so the captured PNGs match what users on GNOME
desktops actually see, not Qt's bare Fusion fallback. Re-run after any
visual change to refresh the README assets:

    python scripts/take_screenshots.py
"""
from __future__ import annotations

import os

# Must precede every Qt import: setting after QApplication construction
# is a no-op.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = "gnome"

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTabWidget

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from redx.config import Config            # noqa: E402
from redx.scanner import Scanner          # noqa: E402
from redx.ui.main_window import MainWindow  # noqa: E402
from redx.ui.settings import Settings     # noqa: E402


def grab(widget, out_path: Path) -> None:
    """Force a layout pass, then render the widget to PNG."""
    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(str(out_path), "PNG")
    print(f"  -> {out_path.relative_to(REPO_ROOT)} ({pixmap.width()}x{pixmap.height()})")


def main() -> int:
    sandbox = REPO_ROOT / "tests" / "sandbox"
    if not sandbox.is_dir():
        print(f"ERROR: sandbox missing at {sandbox}", file=sys.stderr)
        print("  run: python scripts/build_sandbox.py", file=sys.stderr)
        return 1

    out_dir = REPO_ROOT / "screenshots"
    out_dir.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        # Isolated QSettings: never write to the user's real config.
        qs = QSettings(str(Path(td) / "screenshot.ini"), QSettings.Format.IniFormat)
        # Underscore prefix marks the QApplication as intentionally
        # kept-but-unreferenced: PySide6 needs the Python-side handle
        # alive for the lifetime of any widget it owns, but we don't
        # call any method on it directly past construction.
        _app = QApplication(sys.argv)
        win = MainWindow(settings=Settings(qs))
        win.show()  # offscreen no-op visually but triggers showEvent + layout
        QApplication.processEvents()

        tabs = win.findChild(QTabWidget)

        # ---- Screenshot 1: Search tab with scan results ----
        # Drive the scan against the on-disk sandbox synchronously
        # (no QThread timing complexity). Then REDACT the displayed
        # path so the published screenshot doesn't expose the real
        # absolute path on whoever ran this script.
        win._filters_tab._ignore_files.setPlainText("*.txt")
        win._config.ignore_files = ["*.txt"]
        config = Config(start_folder=sandbox, ignore_files=["*.txt"])
        root = Scanner(config).scan(sandbox)
        win._scan_root = root
        win._tree.set_root(root, prune=True)
        win._update_delete_button()
        win._status.showMessage("Done. 16 empty directories.")

        # Redact the folder field: generic, looks like a real use case
        # without leaking the absolute path of whoever generated the
        # screenshot.
        DEMO_PATH = "~/Downloads/cleanup-target"
        win._folder_edit.setText(DEMO_PATH)
        # Redact the tree's root display label to match.
        root_item = win._tree.topLevelItem(0)
        if root_item is not None:
            root_item.setText(0, DEMO_PATH)

        tabs.setCurrentIndex(0)
        QApplication.processEvents()
        grab(win, out_dir / "main-window.png")

        # ---- Screenshot 2: Filters tab ----
        win._filters_tab._ignore_files.setPlainText(
            "# common junk files\n"
            "*.tmp\n"
            "*.bak\n"
            "Thumbs.db\n"
            "*~"
        )
        win._filters_tab._ignore_dirs.setPlainText(
            ".git\n"
            ".hg\n"
            ".svn\n"
            "node_modules\n"
            "__pycache__\n"
            ".venv"
        )
        win._filters_tab._zero_byte.setChecked(True)
        tabs.setCurrentIndex(1)
        QApplication.processEvents()
        grab(win, out_dir / "filters-tab.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
