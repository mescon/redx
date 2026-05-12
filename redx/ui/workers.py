"""QThread-friendly wrappers around the engine.

Pattern: a ``QObject`` worker is moved onto a ``QThread`` and ``run()`` is
called via the thread's ``started`` signal. Engine-side progress callbacks
become Qt signals, which marshal across threads via queued connections
automatically.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import Config
from ..deleter import Deleter
from ..scanner import Scanner


class ScanWorker(QObject):
    progress = Signal(object)   # ScanProgress
    finished = Signal(object)   # ScanNode
    error = Signal(str)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        # The engine takes a plain callable; emitting a Qt signal is one.
        self._scanner = Scanner(config, on_progress=self.progress.emit)

    def cancel(self) -> None:
        self._scanner.cancel()

    def run(self) -> None:
        try:
            # Don't use assert here: it'd be stripped under python -O,
            # silently degrading the precondition into a TypeError from
            # Path(None) deeper in the scanner. Explicit raise keeps the
            # error message clear regardless of optimisation level.
            folder = self._config.start_folder
            if folder is None:
                raise ValueError("scan launched with no start_folder configured")
            root = self._scanner.scan(folder)
            self.finished.emit(root)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class DeleteWorker(QObject):
    result = Signal(object)   # DeleteResult
    finished = Signal()

    def __init__(self, config: Config, paths: list[Path]) -> None:
        super().__init__()
        self._paths = paths
        self._deleter = Deleter(config, on_result=self.result.emit)

    def cancel(self) -> None:
        self._deleter.cancel()

    def run(self) -> None:
        self._deleter.delete_all(self._paths)
        self.finished.emit()
