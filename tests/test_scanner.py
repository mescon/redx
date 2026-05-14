from __future__ import annotations

import os
from pathlib import Path

from redx.config import Config, NodeStatus
from redx.scanner import Scanner, is_system_path, iter_empty_descendants


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
    assert a.ignored_file_count == 2


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
    a = on.children[0]
    assert a.status is NodeStatus.EMPTY
    # The zero-byte file should land in empty_file_count, NOT
    # ignored_file_count (there are no ignore_files patterns set).
    assert a.empty_file_count == 1
    assert a.ignored_file_count == 0


def test_pattern_match_and_zero_byte_counts_split(tmp_path: Path) -> None:
    """Both rules can fire in the same directory. The UI shows both
    counts distinctly, so the scanner must keep them separate.
    """
    make_tree(tmp_path, {
        "mixed": {
            "thumb.jpg": "real bytes here",  # pattern-match, non-empty
            "marker.dat": None,              # zero-byte, no pattern match
        },
    })
    cfg = Config(ignore_files=["*.jpg"], ignore_empty_files=True)
    root = Scanner(cfg).scan(tmp_path)
    m = root.children[0]
    assert m.status is NodeStatus.EMPTY
    assert m.ignored_file_count == 1, "thumb.jpg should be ignored"
    assert m.empty_file_count == 1,   "marker.dat should be empty"


def test_zero_byte_file_matching_pattern_counts_as_empty(tmp_path: Path) -> None:
    """When both rules would match the same file, the more specific
    one wins: zero-byte (a literal property) takes precedence over
    pattern-match (a user name rule).
    """
    make_tree(tmp_path, {"d": {"placeholder.jpg": None}})  # 0 bytes AND *.jpg
    cfg = Config(ignore_files=["*.jpg"], ignore_empty_files=True)
    d = Scanner(cfg).scan(tmp_path).children[0]
    assert d.status is NodeStatus.EMPTY
    assert d.empty_file_count == 1
    assert d.ignored_file_count == 0


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


def test_infinite_loop_threshold_actually_aborts(
    tmp_path: Path, monkeypatch
) -> None:
    """SAFETY: the Settings-tab tooltip claims the threshold "aborts the
    scan" after N path-too-long errors. Until this test, the scanner
    incremented an internal counter but never compared it to the
    threshold and never aborted.

    Simulate ENAMETOOLONG on a set of marked subdirs (matched by exact
    path, NOT by substring: pytest's tmp_path name can contain the
    test's own words, which would otherwise make the root itself
    trigger the fake error and short-circuit the recursion).
    """
    import errno
    real_scandir = os.scandir

    poisoned: set[str] = set()
    for i in range(10):
        d = tmp_path / f"sub{i}"
        d.mkdir()
        poisoned.add(str(d))

    def fake_scandir(path):
        if str(path) in poisoned:
            e = OSError("simulated path too long")
            e.errno = errno.ENAMETOOLONG
            raise e
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)

    cfg = Config(infinite_loop_threshold=3)
    s = Scanner(cfg)
    s.scan(tmp_path)
    assert s._loop_warnings == 3, (
        f"expected exactly threshold-many warnings before abort, "
        f"got {s._loop_warnings}"
    )
    assert s._cancel, "scanner must trip _cancel once the threshold is reached"


def test_is_system_path_blocks_kernel_and_boot_paths() -> None:
    """SAFETY: redx must refuse to scan kernel pseudo-filesystems and
    boot mountpoints. Linux analog of RED's KeepSystemFolders.
    """
    for blocked in ("/", "/proc", "/sys", "/dev", "/run", "/boot",
                    "/lost+found"):
        assert is_system_path(Path(blocked)), (
            f"{blocked} must be classified as a system path"
        )


def test_is_system_path_permits_user_paths(tmp_path: Path) -> None:
    assert not is_system_path(tmp_path)
    assert not is_system_path(Path.home())
    assert not is_system_path(Path("/tmp"))
    assert not is_system_path(Path("/usr"))


def test_is_system_path_follows_symlinks(tmp_path: Path) -> None:
    """Resolve symlinks before comparing; a symlink to /proc must be
    classified as a system path regardless of its own name.
    """
    link = tmp_path / "innocuous_looking_name"
    link.symlink_to("/proc")
    assert is_system_path(link)


def test_is_system_path_handles_missing_paths() -> None:
    """Non-existent paths return False (the not-a-directory check
    runs separately and gives its own user-visible error)."""
    assert not is_system_path(Path("/this/does/not/exist"))


def test_progress_callback_fires(tmp_path: Path) -> None:
    # 250 dirs to cross the every-100 threshold a couple of times.
    for i in range(250):
        (tmp_path / f"d{i:03d}").mkdir()
    seen: list[int] = []
    Scanner(Config(), on_progress=lambda p: seen.append(p.folders_scanned)).scan(tmp_path)
    assert seen, "expected at least one progress event"
    assert all(s % 100 == 0 for s in seen)
