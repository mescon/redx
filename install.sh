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

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR" "$ICONS_DIR"

# 2. Build the wheel in a throwaway venv so we don't touch the user's site-packages.
echo "Building wheel..."
BUILD_VENV_PARENT="$(mktemp -d)"
trap 'rm -rf "$BUILD_VENV_PARENT"' EXIT
"$PY" -m venv "$BUILD_VENV_PARENT/build-venv"
"$BUILD_VENV_PARENT/build-venv/bin/pip" install --quiet --upgrade pip build hatchling
"$BUILD_VENV_PARENT/build-venv/bin/python" -m build \
    --wheel --no-isolation --outdir "$REPO_ROOT/dist" "$REPO_ROOT" >/dev/null

WHEEL=$(ls -1t "$REPO_ROOT"/dist/redx-*-py3-none-any.whl | head -1)
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
ln -sf "$VENV_DIR/bin/redx" "$BIN_DIR/redx"
install -m 644 "$REPO_ROOT/redx/resources/redx.svg" "$ICONS_DIR/redx.svg"

DESKTOP="$APPS_DIR/redx.desktop"
# Use the absolute Exec path so the menu launcher works even if ~/.local/bin
# is not on the user's PATH.
sed -e "s|^Exec=redx\$|Exec=$VENV_DIR/bin/redx|" \
    "$REPO_ROOT/packaging/redx.desktop" > "$DESKTOP"

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
