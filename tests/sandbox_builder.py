"""Build a varied directory tree for manual GUI testing and integration tests.

Each top-level folder under the sandbox is one named case demonstrating a
specific scanner behaviour. The MANIFEST below records the expected
classification per case under two configs (default + ignore_files=['*.txt']).

The same logic backs both:
  * scripts/build_sandbox.py: CLI to materialise tests/sandbox/ for humans
  * tests/test_sandbox_integration.py: assertions against a tmp_path copy
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from redx.config import NodeStatus


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    default: NodeStatus
    with_txt_ignore: NodeStatus


# Keep in sync with build() below.
MANIFEST: tuple[Case, ...] = (
    Case("00_empty_leaf",
         "Truly empty leaf directory.",
         NodeStatus.EMPTY, NodeStatus.EMPTY),
    Case("01_dir_with_real_file",
         "Holds a real binary file: never empty.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("02_only_txt_files",
         "Only *.txt files: empty under the user's headline rule.",
         NodeStatus.NOT_EMPTY, NodeStatus.EMPTY),
    Case("03_mixed_files",
         "*.txt + a real .dat: still not empty under any rule.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("04_only_zero_byte_file",
         "One zero-byte file: only empty when ignore_empty_files is on.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("05_nested_empty_chain",
         "5-deep cascading empty chain: whole branch is EMPTY.",
         NodeStatus.EMPTY, NodeStatus.EMPTY),
    Case("06_partial_busy",
         "One empty subdir + one busy subdir: busy one wins.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("07_dotdir_with_visible_file",
         "Hidden empty subdir alongside a visible real file.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("08_only_hidden_subdir",
         "Single hidden empty subdir: parent cascades to EMPTY by default.",
         NodeStatus.EMPTY, NodeStatus.EMPTY),
    Case("09_with_default_ignored_dir",
         ".git inside (default-ignored). Ignored child blocks parent emptiness.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("10_symlink_to_busy",
         "Symlink + a real busy target. Symlink counts as a non-dir entry.",
         NodeStatus.NOT_EMPTY, NodeStatus.NOT_EMPTY),
    Case("11_protect_demo",
         "Three empty branches; manual GUI: Protect one, delete the rest.",
         NodeStatus.EMPTY, NodeStatus.EMPTY),
)


def build(target: Path) -> None:
    """Wipe target and rebuild the sandbox layout."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    # 00: truly empty
    (target / "00_empty_leaf").mkdir()

    # 01: real file
    d = target / "01_dir_with_real_file"
    d.mkdir()
    (d / "important.dat").write_bytes(b"\x00\x01\x02real")

    # 02: only *.txt
    d = target / "02_only_txt_files"
    d.mkdir()
    (d / "notes.txt").write_text("notes\n")
    (d / "readme.txt").write_text("readme\n")

    # 03: mixed
    d = target / "03_mixed_files"
    d.mkdir()
    (d / "notes.txt").write_text("notes\n")
    (d / "important.dat").write_bytes(b"\xff" * 16)

    # 04: single zero-byte file
    d = target / "04_only_zero_byte_file"
    d.mkdir()
    (d / "placeholder.dat").write_bytes(b"")

    # 05: deep cascade
    chain = target / "05_nested_empty_chain" / "a" / "b" / "c" / "d"
    chain.mkdir(parents=True)

    # 06: partial busy
    d = target / "06_partial_busy"
    d.mkdir()
    (d / "empty_branch").mkdir()
    busy = d / "busy_branch"
    busy.mkdir()
    (busy / "stuff.dat").write_text("stuff\n")

    # 07: dotdir + visible file
    d = target / "07_dotdir_with_visible_file"
    d.mkdir()
    (d / ".hidden_empty").mkdir()
    (d / "visible.dat").write_text("visible\n")

    # 08: only a hidden empty subdir
    d = target / "08_only_hidden_subdir"
    d.mkdir()
    (d / ".hidden_empty").mkdir()

    # 09: has .git (default-ignored)
    d = target / "09_with_default_ignored_dir"
    d.mkdir()
    git = d / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")

    # 10: symlink to a busy real dir
    d = target / "10_symlink_to_busy"
    d.mkdir()
    real = d / "_real_target"
    real.mkdir()
    (real / "data.dat").write_text("data\n")
    (d / "link_to_target").symlink_to(real, target_is_directory=True)

    # 11: protect demo (three empty branches; user protects one in GUI)
    d = target / "11_protect_demo"
    d.mkdir()
    (d / "keep_this_empty").mkdir()
    (d / "delete_me_1").mkdir()
    (d / "delete_me_2" / "inner_empty").mkdir(parents=True)

    (target / "README.md").write_text(_README)


_README = """# redx test sandbox

This tree is **generated** by `scripts/build_sandbox.py` (gitignored).

Re-run any time to wipe and recreate:

```sh
python scripts/build_sandbox.py
```

## Layout (default Config)

| Folder                          | Status      | Notes                                       |
|---------------------------------|-------------|---------------------------------------------|
| 00_empty_leaf                   | EMPTY       | The simplest case.                          |
| 01_dir_with_real_file           | NOT_EMPTY   | Has a real binary file.                     |
| 02_only_txt_files               | NOT_EMPTY   | Becomes EMPTY when *.txt is in ignore list. |
| 03_mixed_files                  | NOT_EMPTY   | Real .dat blocks emptiness regardless.      |
| 04_only_zero_byte_file          | NOT_EMPTY   | EMPTY only with ignore_empty_files=on.      |
| 05_nested_empty_chain           | EMPTY       | 5-deep cascade. Whole branch deletable.     |
| 06_partial_busy                 | NOT_EMPTY   | One empty + one busy subdir.                |
| 07_dotdir_with_visible_file     | NOT_EMPTY   | Visible file blocks parent.                 |
| 08_only_hidden_subdir           | EMPTY       | Hidden empty subdir cascades to parent.     |
| 09_with_default_ignored_dir     | NOT_EMPTY   | .git is IGNORED: blocks parent emptiness.  |
| 10_symlink_to_busy              | NOT_EMPTY   | Symlinks count as non-dir entries.          |
| 11_protect_demo                 | EMPTY       | Manual: right-click a branch, Protect, then |
|                                 |             | delete: protected branch should survive.   |
"""
