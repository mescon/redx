"""Delete empty directories.

Mirrors RED2/Lib/DeletionWorker.cs + SystemFunctions.SecureDeleteDirectory.
Four modes; see config.DeleteMode.

A directory the scanner classified as EMPTY may still hold files that
match the user's ignore patterns (e.g. ``*.nfo``, ``*.jpg``). The race
re-check therefore applies those same patterns rather than a plain
emptiness test, otherwise every such directory would falsely report
"No longer empty (race)".
"""
from __future__ import annotations

import fnmatch
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
        # Re-verify the directory holds nothing the user wants kept.
        # An entry "blocks" deletion iff it's a real subdir, OR it's a
        # file that doesn't match any of the user's ignore patterns.
        try:
            entries = list(path.iterdir())
        except FileNotFoundError:
            return DeleteResult(path, False, "Already gone")
        except OSError as e:
            return DeleteResult(path, False, str(e))

        real_entries: list[Path] = []
        ignored_files: list[Path] = []
        for entry in entries:
            # Order matters: a symlink-to-dir should be treated as a
            # file-like entry (we never follow), not as a real subdir.
            if entry.is_symlink():
                target = ignored_files if self._is_ignored(entry) else real_entries
                target.append(entry)
            elif entry.is_dir():
                # A real subdir means post-order delete missed it, or it
                # was created mid-run: bail rather than risk data loss.
                real_entries.append(entry)
            else:
                target = ignored_files if self._is_ignored(entry) else real_entries
                target.append(entry)

        if real_entries:
            return DeleteResult(path, False, "No longer empty (race)")

        mode = self.config.delete_mode

        if mode == DeleteMode.SIMULATE:
            return DeleteResult(path, True)

        if mode == DeleteMode.TRASH_CONFIRM:
            if self.on_confirm is None or not self.on_confirm(path):
                return DeleteResult(path, False, "User declined")
            mode = DeleteMode.TRASH

        if mode == DeleteMode.TRASH:
            # send2trash moves the directory AND its contents atomically,
            # so we don't need to pre-delete ignored files here.
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
            # rmdir refuses non-empty dirs, so unlink the ignored files first.
            for f in ignored_files:
                try:
                    f.unlink()
                except OSError as e:
                    return DeleteResult(
                        path, False, f"could not remove {f.name}: {e}"
                    )
            try:
                path.rmdir()
                return DeleteResult(path, True)
            except OSError as e:
                return DeleteResult(path, False, str(e))

        return DeleteResult(path, False, f"Unknown mode {mode}")

    def _is_ignored(self, p: Path) -> bool:
        """Return True if *p* matches the user's ignore patterns.

        Mirrors :meth:`redx.scanner.Scanner._file_is_ignored`. Both must
        agree, otherwise the scanner classifies a dir as empty but the
        deleter refuses it (or vice versa).
        """
        if self.config.ignore_empty_files:
            try:
                if p.lstat().st_size == 0:
                    return True
            except OSError:
                pass
        for pattern in self.config.ignore_files:
            if fnmatch.fnmatch(p.name, pattern):
                return True
        return False
