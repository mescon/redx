"""Delete empty directories.

Mirrors RED2/Lib/DeletionWorker.cs + SystemFunctions.SecureDeleteDirectory.
Four modes; see config.DeleteMode.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import Config, DeleteMode

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None  # type: ignore[assignment]


@dataclass
class DeleteResult:
    path: Path
    success: bool
    error: str | None = None


ProgressCallback = Callable[[DeleteResult], None]
ConfirmCallback = Callable[[Path], bool]


class Deleter:
    """Delete a sequence of paths.

    Caller is responsible for ensuring (a) every path is actually empty,
    and (b) the sequence is post-ordered (deepest first) so parents come
    after their children.
    """

    def __init__(
        self,
        config: Config,
        on_result: ProgressCallback | None = None,
        on_confirm: ConfirmCallback | None = None,
    ):
        self.config = config
        self.on_result = on_result
        self.on_confirm = on_confirm
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def delete_all(self, paths: Iterable[Path]) -> list[DeleteResult]:
        results: list[DeleteResult] = []
        for path in paths:
            if self._cancel:
                break
            result = self._delete_one(path)
            results.append(result)
            if self.on_result is not None:
                self.on_result(result)
            if self.config.pause_between_deletes_ms > 0:
                time.sleep(self.config.pause_between_deletes_ms / 1000.0)
        return results

    def _delete_one(self, path: Path) -> DeleteResult:
        # Re-verify emptiness at the moment of deletion (race-safe: RED
        # does the same in SecureDeleteDirectory).
        try:
            if any(path.iterdir()):
                return DeleteResult(path, False, "No longer empty (race)")
        except FileNotFoundError:
            return DeleteResult(path, False, "Already gone")
        except OSError as e:
            return DeleteResult(path, False, str(e))

        mode = self.config.delete_mode

        if mode == DeleteMode.SIMULATE:
            return DeleteResult(path, True)

        if mode == DeleteMode.TRASH_CONFIRM:
            if self.on_confirm is None or not self.on_confirm(path):
                return DeleteResult(path, False, "User declined")
            mode = DeleteMode.TRASH

        if mode == DeleteMode.TRASH:
            if send2trash is None:
                return DeleteResult(
                    path, False,
                    "send2trash not installed",
                )
            try:
                send2trash(str(path))
                return DeleteResult(path, True)
            except OSError as e:
                return DeleteResult(path, False, str(e))

        if mode == DeleteMode.DIRECT:
            try:
                path.rmdir()
                return DeleteResult(path, True)
            except OSError as e:
                return DeleteResult(path, False, str(e))

        return DeleteResult(path, False, f"Unknown mode {mode}")
