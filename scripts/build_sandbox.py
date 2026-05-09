#!/usr/bin/env python3
"""Materialise the redx test sandbox at <repo>/tests/sandbox/.

Re-run any time: it wipes the target and rebuilds.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.sandbox_builder import MANIFEST, build  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the redx test sandbox under tests/sandbox/.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=REPO_ROOT / "tests" / "sandbox",
        help="Where to build the sandbox (default: tests/sandbox/).",
    )
    args = parser.parse_args()
    build(args.target)
    print(f"Built sandbox at {args.target}")
    print(f"  {len(MANIFEST)} cases")
    print(f"  python -m redx {args.target}    # CLI smoke-test the engine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
