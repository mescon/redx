#!/usr/bin/env bash
# Reverse install.sh: remove every file installed for the current user.
set -euo pipefail

rm -rf  "${HOME}/.local/share/redx"
rm -f   "${HOME}/.local/bin/redx"
rm -f   "${HOME}/.local/share/applications/redx.desktop"
rm -f   "${HOME}/.local/share/icons/hicolor/scalable/apps/redx.svg"

update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -t -f "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
kbuildsycoca6 2>/dev/null || true

echo "Uninstalled."
