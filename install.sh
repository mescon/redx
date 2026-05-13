#!/usr/bin/env bash
# Install redx for the current user. Works from a fresh git clone.
#
# What this does:
#   1. Builds a wheel from this source tree
#   2. Creates a private Python venv at ~/.local/share/redx/venv/
#   3. Installs the wheel + dependencies into that venv
#   4. Drops a desktop launcher and icon in your XDG user directories
#   5. Refreshes the desktop database and icon cache
#
# After running, open your app menu and search "redx".
# To reverse: ./uninstall.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/redx"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
PIXMAPS_DIR="${HOME}/.local/share/pixmaps"

# 1. Sanity-check Python.
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.11 or newer." >&2
    exit 1
fi
read -r PY_MAJOR PY_MINOR < <("$PY" -c 'import sys; print(sys.version_info[0], sys.version_info[1])')
if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
    echo "ERROR: redx needs Python 3.11+. You have $PY_MAJOR.$PY_MINOR." >&2
    exit 1
fi
echo "Using Python $PY_MAJOR.$PY_MINOR at $(command -v "$PY")"

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR" "$ICONS_DIR" "$PIXMAPS_DIR"

# 2. Build the wheel in a throwaway venv so we don't touch the user's site-packages.
echo "Building wheel..."
BUILD_VENV_PARENT="$(mktemp -d)"
trap 'rm -rf "$BUILD_VENV_PARENT"' EXIT
"$PY" -m venv "$BUILD_VENV_PARENT/build-venv"
"$BUILD_VENV_PARENT/build-venv/bin/pip" install --quiet --upgrade pip build hatchling

# Clear stale wheels from prior installs so we end up with exactly one
# redx-*.whl in dist/. Also keeps shellcheck happy: no need for `ls`
# sorted by mtime when there's only one candidate.
rm -f "$REPO_ROOT/dist/"redx-*-py3-none-any.whl

"$BUILD_VENV_PARENT/build-venv/bin/python" -m build \
    --wheel --no-isolation --outdir "$REPO_ROOT/dist" "$REPO_ROOT" >/dev/null

shopt -s nullglob
wheels=("$REPO_ROOT/dist"/redx-*-py3-none-any.whl)
shopt -u nullglob
if [[ ${#wheels[@]} -eq 0 ]]; then
    echo "ERROR: build did not produce a wheel" >&2
    exit 1
fi
WHEEL="${wheels[0]}"
echo "  built: $(basename "$WHEEL")"

# 3. Runtime venv and install.
# If redx is currently running, kill it first; otherwise wiping its venv
# below would leave it in a broken half-state.
pkill -f "${VENV_DIR}/bin/redx" 2>/dev/null || true
sleep 0.2
echo "Installing into $VENV_DIR ..."
rm -rf "$VENV_DIR"
"$PY" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet "$WHEEL"

# 4. Launcher symlink, desktop entry, icon.
#
# All three writes are atomic: write to a sibling tempfile in the same
# directory, then rename(2) it over the target. This prevents inotify
# watchers (notably ArcMenu's gnome-shell extension) from ever reading
# a partially-written file. A non-atomic write to redx.desktop can
# crash gnome-shell entirely when the watcher's glib keyfile parser
# encounters a half-written entry:
#   https://gitlab.gnome.org/GNOME/glib/-/work_items/3947
#
# Tempfile names are dot-prefixed (no `.desktop` / `.svg` extension)
# so directory scanners that filter by extension don't even see the
# in-flight tempfile. After mv -f the destination has the proper name.
DESKTOP="$APPS_DIR/redx.desktop"
ICON="$ICONS_DIR/redx.svg"
LAUNCHER="$BIN_DIR/redx"

# Use the absolute Exec= path so the menu launcher works even when
# ~/.local/bin is not on the user's PATH.
TMP_DESKTOP="$(mktemp "${APPS_DIR}/.redx-install.desktop.XXXXXX")"
sed -e "s|^Exec=redx\$|Exec=$VENV_DIR/bin/redx|" \
    "$REPO_ROOT/packaging/redx.desktop" > "$TMP_DESKTOP"
chmod 644 "$TMP_DESKTOP"
mv -f "$TMP_DESKTOP" "$DESKTOP"

TMP_ICON="$(mktemp "${ICONS_DIR}/.redx-install.icon.XXXXXX")"
cp -f "$REPO_ROOT/redx/resources/redx.svg" "$TMP_ICON"
chmod 644 "$TMP_ICON"
mv -f "$TMP_ICON" "$ICON"

# Also install to ~/.local/share/pixmaps. This is the legacy XDG icon
# fallback that does NOT require icon-theme cache indexing, which on
# its own happily ignores SVGs in scalable/apps/. Without this dup
# gnome-shell on Wayland may show a generic icon even though the SVG
# is present in the theme directory.
TMP_PIXMAP="$(mktemp "${PIXMAPS_DIR}/.redx-install.icon.XXXXXX")"
cp -f "$REPO_ROOT/redx/resources/redx.svg" "$TMP_PIXMAP"
chmod 644 "$TMP_PIXMAP"
mv -f "$TMP_PIXMAP" "$PIXMAPS_DIR/redx.svg"

# `ln -sf` does unlink+symlink, briefly making the launcher absent.
# Doing it via tempname + rename keeps the path always-valid.
TMP_LAUNCHER="${BIN_DIR}/.redx-install.launcher.$$"
ln -sf "$VENV_DIR/bin/redx" "$TMP_LAUNCHER"
mv -f "$TMP_LAUNCHER" "$LAUNCHER"

# 5. Best-effort cache refresh. None of these are required, but Plasma
# in particular caches icon-not-found results in ~/.cache/icon-cache.kcache,
# so a stale cache makes the cogwheel fallback persist after install.
update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache -t -f "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
rm -f "${HOME}/.cache/icon-cache.kcache"
kbuildsycoca6 --noincremental 2>/dev/null || true

cat <<EOF

Done. redx is installed.

  Open your app menu, search "redx", click the icon.
  Or in a terminal: redx (if ~/.local/bin is on your PATH)

  Uninstall: ./uninstall.sh

EOF
