"""Persist Config + view options across sessions via QSettings.

Lists are serialised as JSON to dodge QSettings' single-element list
collapsing-to-bare-string footgun on the INI backend.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QSettings

from ..config import Config, DeleteMode

ORG = "redx"
APP = "redx"


class Settings:
    """Wrapper around QSettings.

    Pass an explicit ``QSettings`` instance for tests so they don't write
    to the user's real config; default constructor uses the redx-wide
    settings backing store.
    """

    def __init__(self, qsettings: QSettings | None = None) -> None:
        self._s = qsettings if qsettings is not None else QSettings(ORG, APP)

    def save_config(self, config: Config) -> None:
        self._s.setValue(
            "config/start_folder",
            str(config.start_folder) if config.start_folder is not None else "",
        )
        self._set_list("config/ignore_files", config.ignore_files)
        self._set_list("config/ignore_dirs", config.ignore_dirs)
        self._s.setValue("config/ignore_empty_files", config.ignore_empty_files)
        self._s.setValue("config/ignore_hidden_dirs", config.ignore_hidden_dirs)
        self._s.setValue("config/delete_mode", config.delete_mode.value)
        self._s.setValue("config/pause_between_deletes_ms", config.pause_between_deletes_ms)
        self._s.setValue("config/min_folder_age_hours", config.min_folder_age_hours)
        self._s.setValue("config/max_depth", config.max_depth)
        self._s.setValue(
            "config/infinite_loop_threshold", config.infinite_loop_threshold
        )

    def load_config(self, config: Config) -> None:
        """Populate *config* in place with persisted values, leaving
        unset keys at the dataclass default."""
        path = self._s.value("config/start_folder", "")
        if isinstance(path, str) and path:
            config.start_folder = Path(path)

        ignore_files = self._get_list("config/ignore_files", None)
        if ignore_files is not None:
            config.ignore_files = ignore_files
        ignore_dirs = self._get_list("config/ignore_dirs", None)
        if ignore_dirs is not None:
            config.ignore_dirs = ignore_dirs

        config.ignore_empty_files = self._get_bool(
            "config/ignore_empty_files", config.ignore_empty_files
        )
        config.ignore_hidden_dirs = self._get_bool(
            "config/ignore_hidden_dirs", config.ignore_hidden_dirs
        )

        mode_str = self._s.value("config/delete_mode", "")
        if isinstance(mode_str, str) and mode_str:
            try:
                config.delete_mode = DeleteMode(mode_str)
            except ValueError:
                pass

        config.pause_between_deletes_ms = self._get_int(
            "config/pause_between_deletes_ms", config.pause_between_deletes_ms
        )
        config.min_folder_age_hours = self._get_float(
            "config/min_folder_age_hours", config.min_folder_age_hours
        )
        config.max_depth = self._get_int(
            "config/max_depth", config.max_depth
        )
        config.infinite_loop_threshold = self._get_int(
            "config/infinite_loop_threshold", config.infinite_loop_threshold
        )

    # ---------- View options (not part of Config) -----------------------------

    @property
    def show_full_tree(self) -> bool:
        return self._get_bool("view/show_full_tree", False)

    @show_full_tree.setter
    def show_full_tree(self, value: bool) -> None:
        self._s.setValue("view/show_full_tree", bool(value))

    # ---------- Helpers --------------------------------------------------------

    def clear(self) -> None:
        self._s.clear()
        self._s.sync()

    def sync(self) -> None:
        self._s.sync()

    def _set_list(self, key: str, items: Iterable[str]) -> None:
        self._s.setValue(key, json.dumps(list(items)))

    def _get_list(self, key: str, default: list[str] | None) -> list[str] | None:
        raw = self._s.value(key, "")
        if not isinstance(raw, str) or not raw:
            return default
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default
        if not isinstance(value, list):
            return default
        return [str(x) for x in value]

    def _get_bool(self, key: str, default: bool) -> bool:
        raw = self._s.value(key, default)
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes")
        return default

    def _get_int(self, key: str, default: int) -> int:
        raw = self._s.value(key, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def _get_float(self, key: str, default: float) -> float:
        raw = self._s.value(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default
