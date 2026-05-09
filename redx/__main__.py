"""Entry point for ``python -m redx`` and the installed ``redx`` script.

Tries to launch the GUI; falls back to a CLI smoke test of the engine
when (a) PySide6 isn't installed yet, or (b) a folder is passed as argv.
The CLI mode is mainly for engine development before the GUI lands.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _cli(folder: Path) -> int:
    from redx.config import Config
    from redx.scanner import Scanner, iter_empty_descendants

    config = Config(start_folder=folder)
    scanner = Scanner(config)
    root = scanner.scan(folder)
    empties = list(iter_empty_descendants(root))
    print(f"Found {len(empties)} empty directories under {folder}:")
    for node in empties:
        print(f"  {node.path}")
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and Path(sys.argv[1]).is_dir():
        return _cli(Path(sys.argv[1]))

    try:
        from redx.ui.main_window import run
    except ImportError as e:
        print(f"GUI not available ({e}).", file=sys.stderr)
        print("Pass a folder for CLI mode: python -m redx /path", file=sys.stderr)
        return 1
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
