# Changelog

## [Unreleased]

### Added
- Engine: recursive post-order scanner with symlink shield, ignore-pattern lists,
  zero-byte-file ignore toggle, hidden-dir skip, max depth, infinite-loop guard,
  min-folder-age filter
- Engine: four delete modes: simulate, trash, trash-with-confirm, direct
- Engine: protect/unprotect with RED's asymmetric propagation
  (up on protect, down on unprotect)
- GUI: Search tab with folder picker, scan tree, scan/delete buttons, mode dropdown,
  show-full-tree view toggle
- GUI: Filters tab with monospace pattern textareas + zero-byte/hidden toggles
- GUI: Settings tab with pause-between-deletes, min-folder-age, max-depth,
  loop-threshold, follow-symlinks knobs
- GUI: Log tab: timestamped, auto-scrolling, save-to-file
- GUI: Right-click on tree node → Protect/Unprotect with live delete-count update
- Persistence: Filters, Settings, last folder, delete mode, view options round-trip
  via QSettings (INI at `~/.config/redx/redx.conf`)
- Test sandbox: 12 numbered cases under `tests/sandbox/` for both unit and manual GUI testing
- 39 tests covering engine + persistence + filter widget round-trips
- Packaging: pyproject (PyPI), PKGBUILD (AUR), AppImage build script, Flatpak skeleton
