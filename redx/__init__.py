"""redx: find and delete empty directories on Linux.

A Qt port of RED (Remove-Empty-Directories) by hxseven.
Upstream: https://github.com/hxseven/Remove-Empty-Directories
License: LGPL-3.0-or-later
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # Authoritative source: the installed wheel's METADATA, which
    # derives from pyproject.toml's ``version = "..."``. Works for pip,
    # pipx, AUR, AppImage, Flatpak: any path that goes through a real
    # install.
    __version__ = _pkg_version("redx")
except PackageNotFoundError:
    # Running directly out of a git checkout that hasn't been
    # pip-installed (e.g. ``python -m redx`` from the repo root for a
    # quick dev test). Surface that clearly rather than lying.
    __version__ = "0.0.0+source"
