"""Pytest config: keep Qt headless even when a display is available.

Set BEFORE any test module imports PySide6 so QApplication picks the
offscreen platform. conftest.py is collected by pytest at session start,
which runs ahead of test-module imports.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
