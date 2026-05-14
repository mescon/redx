"""Delete empty directories.

Mirrors RED2/Lib/DeletionWorker.cs + SystemFunctions.SecureDeleteDirectory.
Four modes; see config.DeleteMode.

A directory the scanner classified as EMPTY may still hold files that
match the user's ignore patterns (e.g. ``*.nfo``, ``*.jpg``). The race
re-check therefore applies those same patterns rather than a plain
emptiness test, otherwise every such directory would falsely report
"No longer empty (race)".

Subdirectory detection uses ``Path.is_dir`` AND an independent ``lstat``
check; either reporting "directory" is treated as conclusive. This is
defense in depth against an observed CIFS failure mode where
``is_dir()`` returned False for entries that were in fact directories,
which let send2trash atomically move a parent and pull its surviving
children into trash.
"""
from __future__ import annotations

import fnmatch
import stat
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
        # SIMULATE mode pretends every successful delete actually happened.
        # Subsequent race-checks on parent dirs need to ignore children that
        # we've already pretended to delete; otherwise post-order cascades
        # falsely report "No longer empty (race)" for every parent.
        self._simulated_deleted: set[Path] = set()

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

        # In SIMULATE mode, pretend that previous "successful" deletes in
        # this run actually removed the directory. Without this filter the
        # parent of any simulated-deleted child still sees the child via
        # iterdir() and reports "No longer empty (race)".
        if (
            self.config.delete_mode is DeleteMode.SIMULATE
            and self._simulated_deleted
        ):
            entries = [e for e in entries if e not in self._simulated_deleted]

        real_entries: list[Path] = []
        ignored_files: list[Path] = []
        for entry in entries:
            # Symlink-to-anything is treated as a file-like entry: we
            # never follow them, so they can't carry children, and the
            # ignore-pattern test on the link's own name is the right
            # decision point.
            if _is_symlink_safe(entry):
                target = ignored_files if self._is_ignored(entry) else real_entries
                target.append(entry)
                continue
            # Belt-and-braces subdir detection: if EITHER Path.is_dir or
            # an independent lstat reports "directory", we refuse. CIFS
            # under load has been observed to lie via is_dir alone, and
            # that lie is what enables a parent-rename to take its
            # surviving children into trash with it.
            if _is_subdir(entry):
                real_entries.append(entry)
                continue
            target = ignored_files if self._is_ignored(entry) else real_entries
            target.append(entry)

        if real_entries:
            return DeleteResult(path, False, "No longer empty (race)")

        mode = self.config.delete_mode

        if mode == DeleteMode.SIMULATE:
            self._simulated_deleted.add(path)
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


def _is_symlink_safe(entry: Path) -> bool:
    """Is *entry* a symlink? Errors on the side of "yes, treat as a link".

    The follow-up call paths handle symlinks as file-like entries (no
    recursion). Returning True on stat failure means we don't accidentally
    treat a stat-broken entry as a directory.
    """
    try:
        return entry.is_symlink()
    except OSError:
        return True


def _is_subdir(entry: Path) -> bool:
    """Belt-and-braces "is *entry* a real subdirectory?" check.

    Returns True if EITHER ``Path.is_dir`` or an independent ``os.lstat``
    + ``S_ISDIR`` reports "directory". On flaky network filesystems,
    notably CIFS under load, ``is_dir`` alone has been observed to
    return False for entries that are in fact directories; without this
    cross-check, send2trash would then atomically move the parent and
    take the misclassified children with it. We always fail-safe: any
    error raises True so we refuse to delete the parent.
    """
    # Path.is_dir(): primary check.
    try:
        if entry.is_dir():
            return True
    except OSError:
        return True

    # lstat-based S_ISDIR: independent confirmation. If is_dir lied,
    # this catches it. lstat() doesn't follow symlinks, so a symlink to
    # a dir is correctly NOT classified as a subdir here (the caller
    # handled the symlink case separately).
    try:
        st = entry.lstat()
    except OSError:
        return True
    return stat.S_ISDIR(st.st_mode)
