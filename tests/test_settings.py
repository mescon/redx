"""Tests for the persistence layer (Settings wrapping QSettings)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from redx.config import Config, DeleteMode
from redx.ui.settings import Settings


@pytest.fixture
def isolated_qsettings(tmp_path: Path) -> QSettings:
    """A QSettings backed by an INI file inside ``tmp_path``: never the user's real config."""
    return QSettings(str(tmp_path / "redx.ini"), QSettings.Format.IniFormat)


def test_save_and_reload_round_trip(isolated_qsettings: QSettings) -> None:
    s = Settings(isolated_qsettings)
    cfg_in = Config(
        start_folder=Path("/tmp/foo"),
        ignore_files=["*.txt", "*.log"],
        ignore_dirs=[".git", "node_modules", "__pycache__"],
        ignore_empty_files=True,
        ignore_hidden_dirs=True,
        delete_mode=DeleteMode.DIRECT,
        pause_between_deletes_ms=250,
        min_folder_age_hours=12.5,
        max_depth=42,
        infinite_loop_threshold=7,
    )
    s.save_config(cfg_in)
    s.sync()

    cfg_out = Config()
    s.load_config(cfg_out)

    assert cfg_out.start_folder == Path("/tmp/foo")
    assert cfg_out.ignore_files == ["*.txt", "*.log"]
    assert cfg_out.ignore_dirs == [".git", "node_modules", "__pycache__"]
    assert cfg_out.ignore_empty_files is True
    assert cfg_out.ignore_hidden_dirs is True
    assert cfg_out.delete_mode is DeleteMode.DIRECT
    assert cfg_out.pause_between_deletes_ms == 250
    assert cfg_out.min_folder_age_hours == 12.5
    assert cfg_out.max_depth == 42
    assert cfg_out.infinite_loop_threshold == 7


def test_single_element_list_round_trips_correctly(isolated_qsettings: QSettings) -> None:
    """Regression: QSettings collapses single-element string lists to bare strings.
    Our JSON workaround must round-trip a one-element list as a list, not a string.
    """
    s = Settings(isolated_qsettings)
    cfg_in = Config(ignore_files=["*.tmp"])
    s.save_config(cfg_in)
    s.sync()

    cfg_out = Config()
    s.load_config(cfg_out)
    assert cfg_out.ignore_files == ["*.tmp"]
    assert isinstance(cfg_out.ignore_files, list)


def test_empty_lists_round_trip(isolated_qsettings: QSettings) -> None:
    s = Settings(isolated_qsettings)
    cfg_in = Config(ignore_files=[], ignore_dirs=[])
    s.save_config(cfg_in)
    s.sync()

    cfg_out = Config()
    s.load_config(cfg_out)
    assert cfg_out.ignore_files == []
    assert cfg_out.ignore_dirs == []


def test_load_with_no_persisted_data_keeps_defaults(isolated_qsettings: QSettings) -> None:
    s = Settings(isolated_qsettings)  # nothing saved yet
    cfg = Config()
    defaults_before = (cfg.ignore_dirs[:], cfg.delete_mode, cfg.max_depth)
    s.load_config(cfg)
    # Untouched fields should still hold dataclass defaults.
    assert cfg.ignore_dirs == defaults_before[0]
    assert cfg.delete_mode is defaults_before[1]
    assert cfg.max_depth == defaults_before[2]


def test_view_options_persist(isolated_qsettings: QSettings) -> None:
    s = Settings(isolated_qsettings)
    assert s.show_full_tree is False  # default
    s.show_full_tree = True
    s.sync()
    s2 = Settings(isolated_qsettings)
    assert s2.show_full_tree is True


def test_invalid_delete_mode_falls_back_to_default(isolated_qsettings: QSettings) -> None:
    """If the persisted mode string is unknown (e.g. from an older redx with
    different mode names), load should keep the dataclass default rather than crash.
    """
    isolated_qsettings.setValue("config/delete_mode", "obliterate_violently")
    isolated_qsettings.sync()
    s = Settings(isolated_qsettings)
    cfg = Config()
    s.load_config(cfg)
    assert cfg.delete_mode is Config().delete_mode  # default unchanged


def test_clear_wipes_settings(isolated_qsettings: QSettings) -> None:
    s = Settings(isolated_qsettings)
    s.save_config(Config(ignore_files=["*.junk"]))
    s.sync()
    s.clear()
    cfg = Config()
    s.load_config(cfg)
    assert cfg.ignore_files == []
