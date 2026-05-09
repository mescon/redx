from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")

from redx.config import Config
from redx.ui.filters_tab import FiltersTab, _parse_lines


def test_parse_lines_strips_blanks_and_comments() -> None:
    text = """
*.txt
# a comment
*.log

# another
   *.bak
"""
    assert _parse_lines(text) == ["*.txt", "*.log", "*.bak"]


def test_parse_lines_empty_input() -> None:
    assert _parse_lines("") == []
    assert _parse_lines("\n\n\n") == []
    assert _parse_lines("# only comments\n# nothing else") == []


def test_filters_tab_round_trip(qtbot) -> None:
    cfg_in = Config(
        ignore_files=["*.txt", "*.log"],
        ignore_dirs=[".git", "node_modules"],
        ignore_empty_files=True,
        ignore_hidden_dirs=True,
    )
    tab = FiltersTab()
    qtbot.addWidget(tab)
    tab.load_from(cfg_in)

    cfg_out = Config()  # different defaults, should be overwritten
    tab.apply_to(cfg_out)

    assert cfg_out.ignore_files == ["*.txt", "*.log"]
    assert cfg_out.ignore_dirs == [".git", "node_modules"]
    assert cfg_out.ignore_empty_files is True
    assert cfg_out.ignore_hidden_dirs is True


def test_filters_tab_user_edit_then_apply(qtbot) -> None:
    """Simulate the headline use case: user types ``*.txt`` and rescans."""
    tab = FiltersTab()
    qtbot.addWidget(tab)
    tab.load_from(Config(ignore_files=[]))
    tab._ignore_files.setPlainText("*.txt\n# user comment\n*.log\n")

    cfg = Config()
    tab.apply_to(cfg)
    assert cfg.ignore_files == ["*.txt", "*.log"]


def test_filters_tab_reset_button(qtbot) -> None:
    tab = FiltersTab()
    qtbot.addWidget(tab)
    tab.load_from(Config(ignore_files=["junk"], ignore_dirs=["junk_dir"]))
    tab._on_reset()

    cfg = Config()
    tab.apply_to(cfg)
    # Reset uses Config() defaults: ignore_files default empty,
    # ignore_dirs default has the standard list.
    assert cfg.ignore_files == []
    assert ".git" in cfg.ignore_dirs
