"""Integration: build the full sandbox in tmp_path and assert every case."""
from __future__ import annotations

from pathlib import Path

import pytest

from redx.config import Config, NodeStatus
from redx.scanner import Scanner, ScanNode
from tests.sandbox_builder import MANIFEST, build


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("redx_sandbox")
    # build() wipes target; tmp_path_factory hands us an empty dir, so wiping it
    # would error before mkdir. Pass an inner subdir instead.
    inner = target / "sandbox"
    build(inner)
    return inner


def _child_status(root: ScanNode, name: str) -> NodeStatus:
    for c in root.children:
        if c.path.name == name:
            return c.status
    raise AssertionError(f"case {name!r} not found in scan results")


def test_default_config_classifications(sandbox: Path) -> None:
    root = Scanner(Config()).scan(sandbox)
    failures = []
    for case in MANIFEST:
        actual = _child_status(root, case.name)
        if actual is not case.default:
            failures.append(
                f"  {case.name}: expected {case.default.name}, got {actual.name}"
                f"  ({case.description})"
            )
    assert not failures, "Sandbox cases misclassified:\n" + "\n".join(failures)


def test_txt_ignore_classifications(sandbox: Path) -> None:
    root = Scanner(Config(ignore_files=["*.txt"])).scan(sandbox)
    failures = []
    for case in MANIFEST:
        actual = _child_status(root, case.name)
        if actual is not case.with_txt_ignore:
            failures.append(
                f"  {case.name}: expected {case.with_txt_ignore.name}, got {actual.name}"
                f"  ({case.description})"
            )
    assert not failures, "Sandbox cases misclassified under *.txt ignore:\n" + "\n".join(failures)


def test_empty_files_toggle_only_changes_zero_byte_case(sandbox: Path) -> None:
    """ignore_empty_files=True flips ONLY 04_only_zero_byte_file to EMPTY."""
    off = Scanner(Config()).scan(sandbox)
    on = Scanner(Config(ignore_empty_files=True)).scan(sandbox)
    assert _child_status(off, "04_only_zero_byte_file") is NodeStatus.NOT_EMPTY
    assert _child_status(on, "04_only_zero_byte_file") is NodeStatus.EMPTY
    # All other NOT_EMPTY cases stay NOT_EMPTY (sanity)
    for case in MANIFEST:
        if case.name == "04_only_zero_byte_file":
            continue
        assert _child_status(on, case.name) is case.default
