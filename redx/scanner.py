"""Empty-directory scanner.

Mirrors RED2/Lib/FindEmptyDirectoryWorker.cs: recursive depth-first walk,
post-order emptiness cascade, symlink-safe.

The class is deliberately single-threaded so it can be driven from a
``QThread`` for GUI use without coupling to Qt here.
"""
from __future__ import annotations

import errno
import fnmatch
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config, NodeStatus


# eq=False keeps ScanNode hashable by identity: required for set-based
# protect/unprotect bookkeeping. We don't need value-equality between
# nodes anywhere; same path scanned twice yields distinct nodes.
@dataclass(eq=False)
class ScanNode:
    path: Path
    status: NodeStatus = NodeStatus.NOT_EMPTY
    children: list["ScanNode"] = field(default_factory=list)
    error: str | None = None
    # Two reasons a file doesn't block emptiness, counted separately
    # so the UI can label them distinctly:
    #   - ignored_file_count: matched the user's ignore_files patterns
    #     (any size, any content; an explicit-rule match)
    #   - empty_file_count:   literally zero bytes, when the
    #     ignore_empty_files toggle is on (a file-property match)
    # Precedence is zero-byte first: a 0-byte .jpg counts as empty,
    # not ignored, because the literal property is more specific than
    # the user's name-based rule.
    ignored_file_count: int = 0
    empty_file_count: int = 0
    is_protected: bool = False
    parent: "ScanNode | None" = field(default=None, repr=False)


@dataclass
class ScanProgress:
    folders_scanned: int
    empty_found: int
    current_path: Path


ProgressCallback = Callable[[ScanProgress], None]


class Scanner:
    def __init__(self, config: Config, on_progress: ProgressCallback | None = None):
        self.config = config
        self.on_progress = on_progress
        self._cancel = False
        self._folders_scanned = 0
        self._empty_found = 0
        self._loop_warnings = 0
        self._cutoff_mtime: float | None = None
        if config.min_folder_age_hours > 0:
            self._cutoff_mtime = (
                datetime.now() - timedelta(hours=config.min_folder_age_hours)
            ).timestamp()

    def cancel(self) -> None:
        self._cancel = True

    def scan(self, root: Path) -> ScanNode:
        node = ScanNode(path=root)
        self._scan_into(node, depth=0)
        return node

    def _scan_into(self, node: ScanNode, depth: int) -> None:
        if self._cancel:
            return
        if depth > self.config.max_depth:
            node.status = NodeStatus.ERROR
            node.error = "Max depth reached"
            return

        path = node.path

        try:
            if path.is_symlink() and not self.config.follow_symlinks:
                node.status = NodeStatus.ERROR
                node.error = "Symbolic link (not followed)"
                return
        except OSError as e:
            node.status = NodeStatus.ERROR
            node.error = str(e)
            return

        if self._cutoff_mtime is not None and depth > 0:
            try:
                if path.stat().st_mtime > self._cutoff_mtime:
                    node.status = NodeStatus.IGNORED
                    return
            except OSError:
                pass

        try:
            entries = list(os.scandir(path))
        except PermissionError as e:
            node.status = NodeStatus.ERROR
            node.error = f"Permission denied: {e}"
            return
        except OSError as e:
            node.status = NodeStatus.ERROR
            node.error = str(e)
            # ENAMETOOLONG and ELOOP are the signature of a filesystem
            # loop (almost always a self-referential symlink, possibly
            # via a network mount). Count them; once we exceed the
            # user's threshold we set _cancel so all remaining
            # recursion bails out fast rather than churning forever.
            if e.errno in (errno.ENAMETOOLONG, errno.ELOOP):
                self._loop_warnings += 1
                threshold = self.config.infinite_loop_threshold
                if threshold > 0 and self._loop_warnings >= threshold:
                    node.error = (
                        f"Aborted: hit {self._loop_warnings} path-length / "
                        f"symlink-loop errors (threshold={threshold}). "
                        "Likely a circular symlink."
                    )
                    self._cancel = True
            return

        contains_real_files = False
        subdir_entries: list[os.DirEntry[str]] = []

        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                contains_real_files = True
                continue
            if is_dir:
                subdir_entries.append(entry)
                continue
            kind = self._classify_non_dir(entry)
            if kind == "empty":
                node.empty_file_count += 1
            elif kind == "ignored":
                node.ignored_file_count += 1
            else:
                contains_real_files = True

        for entry in subdir_entries:
            if self._cancel:
                return
            child_path = Path(entry.path)
            if self._dir_is_ignored(entry.name):
                child = ScanNode(path=child_path, status=NodeStatus.IGNORED, parent=node)
                node.children.append(child)
                continue
            if self.config.ignore_hidden_dirs and entry.name.startswith("."):
                child = ScanNode(path=child_path, status=NodeStatus.IGNORED, parent=node)
                node.children.append(child)
                continue
            child = ScanNode(path=child_path, parent=node)
            node.children.append(child)
            self._scan_into(child, depth + 1)

        # Empty iff: no real (non-ignored) files, AND every child subdir is
        # itself Empty. Ignored/Error children block parent emptiness: we
        # didn't fully classify them, so we cannot safely conclude empty.
        all_children_empty = all(
            c.status == NodeStatus.EMPTY for c in node.children
        )
        if not contains_real_files and all_children_empty:
            node.status = NodeStatus.EMPTY
            # Don't count the scan root in _empty_found. The deleter's
            # iter_deletable explicitly skips the root for safety, so
            # counting it here would make progress-event tallies
            # inconsistent with the actual deletable set (off by one).
            if depth > 0:
                self._empty_found += 1
        else:
            node.status = NodeStatus.NOT_EMPTY

        self._folders_scanned += 1
        if self.on_progress and self._folders_scanned % 100 == 0:
            self.on_progress(ScanProgress(
                folders_scanned=self._folders_scanned,
                empty_found=self._empty_found,
                current_path=path,
            ))

    def _file_is_ignored(self, entry: os.DirEntry[str]) -> bool:
        # Kept for callers that only need the boolean (does this file
        # block emptiness?). For the per-count split, use
        # _classify_non_dir instead.
        return self._classify_non_dir(entry) != "real"

    def _classify_non_dir(self, entry: os.DirEntry[str]) -> str:
        """Return ``'empty'``, ``'ignored'``, or ``'real'`` for a non-dir entry.

        Precedence: zero-byte (when the toggle is on) first, then
        pattern match, then real. A 0-byte file matched by ``*.jpg``
        counts as ``empty`` rather than ``ignored``: the literal
        property is more specific than the user's name-based rule.
        """
        if self.config.ignore_empty_files:
            try:
                if entry.stat(follow_symlinks=False).st_size == 0:
                    return "empty"
            except OSError:
                pass
        for pattern in self.config.ignore_files:
            if fnmatch.fnmatch(entry.name, pattern):
                return "ignored"
        return "real"

    def _dir_is_ignored(self, name: str) -> bool:
        for pattern in self.config.ignore_dirs:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False


def iter_empty_descendants(node: ScanNode) -> Iterator[ScanNode]:
    """Yield every Empty descendant in post-order (deepest first).

    Post-order is required for safe deletion: children must be removed
    before parents or rmdir() will refuse the parent.
    """
    for child in node.children:
        yield from iter_empty_descendants(child)
    if node.status == NodeStatus.EMPTY:
        yield node


# Linux equivalent of RED's KeepSystemFolders: a small frozen set of
# paths that are owned by the kernel / boot process and have no business
# being a redx scan target. Scanning them is at best useless (they're
# pseudo-filesystems with millions of entries) and at worst harmful
# (a stray send2trash on /proc would do nothing useful and might log
# alarming errors). We also refuse the filesystem root itself.
_SYSTEM_PATHS: frozenset[Path] = frozenset({
    Path("/"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/run"),
    Path("/boot"),
    Path("/lost+found"),
})


def is_system_path(path: Path) -> bool:
    """Return True if *path* is a system directory redx must refuse to scan.

    Resolves symlinks so that e.g. /var/run → /run still trips the
    guard. Returns False on OS errors (path doesn't exist, permission
    denied): those cases are handled elsewhere with their own messages.
    """
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    return resolved in _SYSTEM_PATHS
