from __future__ import annotations

import os
from pathlib import Path

from redx.config import Config, NodeStatus
from redx.scanner import Scanner, iter_empty_descendants


def make_tree(root: Path, layout: dict) -> None:
    """Materialise a nested dict into directories and files.

    dict value -> subdirectory; str -> file with that text; None -> empty file.
    """
    for name, value in layout.items():
        path = root / name
        if isinstance(value, dict):
            path.mkdir(exist_ok=True)
            make_tree(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value or "")


def test_truly_empty_dir_is_empty(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {}})
    root = Scanner(Config()).scan(tmp_path)
    assert root.children[0].status is NodeStatus.EMPTY


def test_dir_with_real_file_is_not_empty(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {"keep.dat": "hi"}})
    root = Scanner(Config()).scan(tmp_path)
    assert root.children[0].status is NodeStatus.NOT_EMPTY


def test_ignore_pattern_makes_dir_empty(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {"x.txt": "hi", "y.txt": "ho"}})
    root = Scanner(Config(ignore_files=["*.txt"])).scan(tmp_path)
    a = root.children[0]
    assert a.status is NodeStatus.EMPTY
    assert a.empty_file_count == 2


def test_one_real_file_blocks_emptiness(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {"x.txt": "hi", "real.dat": "data"}})
    root = Scanner(Config(ignore_files=["*.txt"])).scan(tmp_path)
    assert root.children[0].status is NodeStatus.NOT_EMPTY


def test_nested_empty_cascade(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {"b": {"c": {}}}})
    root = Scanner(Config()).scan(tmp_path)
    a = root.children[0]
    assert a.status is NodeStatus.EMPTY
    empties = {n.path for n in iter_empty_descendants(root)}
    assert tmp_path / "a" in empties
    assert tmp_path / "a" / "b" in empties
    assert tmp_path / "a" / "b" / "c" in empties


def test_ignore_empty_files_toggle(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {"empty.dat": None}})
    off = Scanner(Config()).scan(tmp_path)
    assert off.children[0].status is NodeStatus.NOT_EMPTY
    on = Scanner(Config(ignore_empty_files=True)).scan(tmp_path)
    assert on.children[0].status is NodeStatus.EMPTY


def test_symlink_not_followed(tmp_path: Path) -> None:
    make_tree(tmp_path, {"target": {"file.dat": "hi"}})
    (tmp_path / "linkdir").symlink_to(tmp_path / "target")
    root = Scanner(Config()).scan(tmp_path)
    # The symlink looks like a non-dir entry to the scanner; it counts as
    # a "real file" and pins root as not empty.
    assert root.status is NodeStatus.NOT_EMPTY


def test_ignored_dir_blocks_parent_emptiness(tmp_path: Path) -> None:
    make_tree(tmp_path, {"a": {".git": {"config": "x"}}})
    root = Scanner(Config(ignore_dirs=[".git"])).scan(tmp_path)
    a = root.children[0]
    # .git is ignored (not scanned); we don't know it's empty, so a is
    # NOT_EMPTY rather than EMPTY. Safer default.
    assert a.status is NodeStatus.NOT_EMPTY
    assert a.children[0].status is NodeStatus.IGNORED


def test_dir_empty_when_only_ignored_files(tmp_path: Path) -> None:
    """The user's headline use case: dir with only *.txt files counts as empty."""
    make_tree(tmp_path, {
        "project": {
            "old": {"notes.txt": "...", "todo.txt": "..."},
            "src": {"main.py": "print()"},
        },
    })
    root = Scanner(Config(ignore_files=["*.txt"])).scan(tmp_path)
    project = root.children[0]
    by_name = {c.path.name: c for c in project.children}
    assert by_name["old"].status is NodeStatus.EMPTY
    assert by_name["src"].status is NodeStatus.NOT_EMPTY
    assert project.status is NodeStatus.NOT_EMPTY  # src holds it


def test_progress_callback_fires(tmp_path: Path) -> None:
    # 250 dirs to cross the every-100 threshold a couple of times.
    for i in range(250):
        (tmp_path / f"d{i:03d}").mkdir()
    seen: list[int] = []
    Scanner(Config(), on_progress=lambda p: seen.append(p.folders_scanned)).scan(tmp_path)
    assert seen, "expected at least one progress event"
    assert all(s % 100 == 0 for s in seen)
