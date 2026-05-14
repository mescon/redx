# Changelog

## 0.1.0: 2026-05-15

Initial public release.

### Scanner
- Recursive post-order classification with a symbolic-link shield (never traverses links).
- Glob-pattern ignore list for files; directories containing only matching files
  count as empty.
- Glob-pattern skip list for directories; skipped directories are not scanned and
  prevent their parent from being classified empty (safer default).
- Toggle: treat zero-byte files as empty.
- Toggle: ignore hidden (dot-prefixed) directories.
- Configurable max scan depth.
- Infinite-loop threshold: aborts the scan after N path-too-long or symlink-loop
  errors (default 5, 0 disables).
- Minimum-folder-age filter (skip directories modified within the last N hours).
- Refuses to scan kernel/boot mountpoints: `/`, `/proc`, `/sys`, `/dev`, `/run`,
  `/boot`, `/lost+found` (symlink-aware).
- Counts "ignored" (pattern-matched) and "empty" (zero-byte) files distinctly
  so the UI can label both when both apply.

### GUI (PySide6 / Qt 6)
- Four-tab layout: Search, Filters, Settings, Log.
- Colour-coded tree: empty=red, protected=blue, error=orange, not-empty=gray.
- Tree pruning by default (hides branches with no actionable nodes); a
  Search-tab toggle reveals the full tree.
- Three delete modes: move to trash (default, reversible), permanent (skip trash),
  simulate (dry run with consistent post-order cascade).
- Right-click protect/unprotect on tree nodes with RED's asymmetric propagation
  (protect goes UP to ancestors, unprotect goes DOWN to descendants).
- Drag-and-drop a folder onto the window to set the scan target.
- Per-folder Protect/Unprotect with live delete-count update.
- Version shown in the title bar and an About dialog reachable from the tab-bar corner.
- Log tab with timestamps, line count, clear, and save-to-file.

### Safety
- Scan root is never a deletion candidate, regardless of cascade classification.
- Deletion race-check uses dual `Path.is_dir` + `lstat S_ISDIR` so a flaky
  filesystem can't smuggle a subdir past the guard.
- Simulate mode maintains a per-run pretend-deleted set so post-order cascades
  match real-mode behaviour.
- Settings persist on every Scan in addition to clean close: survives SIGTERM
  and other ungraceful exits.
- Install scripts use atomic rename (write to sibling tempfile + `mv`) for
  every XDG file they touch; inotify watchers never see a half-written
  `.desktop` or icon file.

### Packaging
- Per-user install via `./install.sh` (no sudo, drops everything under `~/.local/`).
- Arch AUR `PKGBUILD` ready to submit.
- AppImage build script and Flatpak manifest skeleton in `packaging/`.
- Wheel buildable with `python -m build`; entry point is `redx`.
- Icon installed to both `hicolor/scalable/apps/` and `pixmaps/` for maximum
  desktop-shell compatibility (GNOME, KDE, XFCE, Sway, etc).
- Trust badges on README: CI status, license, supported Python versions,
  latest release tag.

### CI
- GitHub Actions runs on every push and PR.
- `pytest` matrix on Python 3.11, 3.12, 3.13 with `QT_QPA_PLATFORM=offscreen`.
- Security audit: `bandit` (static), `ruff --select=S` (lint with security ruleset),
  `pip-audit` (CVE check on dependencies).
- `shellcheck` on all shell scripts.
- Wheel build job uploads the produced wheel as an artifact.

### Tests
- 56 tests covering scanner, deleter, protect/unprotect, settings persistence,
  filter widget round-trips, and integration against a generated 12-case sandbox.
