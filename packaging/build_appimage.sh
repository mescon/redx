#!/usr/bin/env bash
# Build an AppImage of redx: a single self-contained binary that runs on
# any modern Linux without installing anything.
#
# Prerequisites (run once):
#   curl -L -o /tmp/appimagetool.AppImage \
#     https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
#   chmod +x /tmp/appimagetool.AppImage
#
# The bundled Python interpreter is what makes the resulting AppImage
# self-contained: users don't need Python installed. Trade-off: the
# binary is ~80 MB because it carries CPython + PySide6.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$REPO_ROOT/build/appimage"
APPDIR="$WORKDIR/redx.AppDir"

rm -rf "$WORKDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps"

# 1. Build a wheel of redx itself.
cd "$REPO_ROOT"
python -m build --wheel --no-isolation --outdir "$WORKDIR/dist"

# 2. Create a venv inside AppDir, install redx + runtime deps.
python -m venv "$APPDIR/usr/python"
"$APPDIR/usr/python/bin/pip" install --quiet --upgrade pip
"$APPDIR/usr/python/bin/pip" install --quiet "$WORKDIR/dist"/*.whl

# 3. AppRun shim that exec's our Python entry point.
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/python/bin:$PATH"
export PYTHONHOME="$HERE/usr/python"
exec "$HERE/usr/python/bin/redx" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# 4. Top-level .desktop + icon (AppImage convention requires both at AppDir root).
cp "$REPO_ROOT/packaging/redx.desktop" "$APPDIR/redx.desktop"
cp "$REPO_ROOT/packaging/redx.svg"     "$APPDIR/redx.svg"
cp "$REPO_ROOT/packaging/redx.desktop" "$APPDIR/usr/share/applications/redx.desktop"
cp "$REPO_ROOT/packaging/redx.svg"     "$APPDIR/usr/share/icons/hicolor/scalable/apps/redx.svg"

# 5. Pack into a single AppImage file.
APPIMAGETOOL="${APPIMAGETOOL:-/tmp/appimagetool.AppImage}"
if [[ ! -x "$APPIMAGETOOL" ]]; then
    echo "ERROR: appimagetool not found at $APPIMAGETOOL" >&2
    echo "See instructions at the top of this script." >&2
    exit 1
fi

cd "$WORKDIR"
"$APPIMAGETOOL" "$APPDIR" "$REPO_ROOT/build/redx-x86_64.AppImage"

echo
echo "Built: $REPO_ROOT/build/redx-x86_64.AppImage"
echo "Try it: ./build/redx-x86_64.AppImage"
