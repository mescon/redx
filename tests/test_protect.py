from __future__ import annotations

from pathlib import Path

from redx.config import Config, NodeStatus
from redx.protect import iter_deletable, protect, unprotect
from redx.scanner import Scanner


def _scan(path: Path):
    return Scanner(Config()).scan(path)


def test_parent_pointers_set_during_scan(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    root = _scan(tmp_path)
    a = root.children[0]
    b = a.children[0]
    assert root.parent is None
    assert a.parent is root
    assert b.parent is a


def test_protect_propagates_up_to_root(tmp_path: Path) -> None:
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    root = _scan(tmp_path)
    a = root.children[0]
    b = a.children[0]
    c = b.children[0]
    flipped = protect(c)
    assert {root, a, b, c} == flipped
    assert all(n.is_protected for n in (root, a, b, c))


def test_protect_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    root = _scan(tmp_path)
    a = root.children[0]
    first = protect(a)
    second = protect(a)
    assert first == {root, a}
    assert second == set()


def test_protect_stops_at_first_already_protected_ancestor(tmp_path: Path) -> None:
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    root = _scan(tmp_path)
    a = root.children[0]
    b = a.children[0]
    c = b.children[0]
    protect(b)  # protects root, a, b
    flipped = protect(c)
    # Only c flips; ancestors are already protected
    assert flipped == {c}


def test_unprotect_propagates_down_only(tmp_path: Path) -> None:
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    root = _scan(tmp_path)
    a = root.children[0]
    b = a.children[0]
    c = b.children[0]
    protect(c)  # all four protected
    flipped = unprotect(a)  # a, b, c flip; root stays protected
    assert flipped == {a, b, c}
    assert root.is_protected
    assert not any(n.is_protected for n in (a, b, c))


def test_unprotect_on_unprotected_is_noop(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    root = _scan(tmp_path)
    a = root.children[0]
    assert unprotect(a) == set()


def test_iter_deletable_excludes_protected(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    root = _scan(tmp_path)
    by_name = {c.path.name: c for c in root.children}
    x, y = by_name["x"], by_name["y"]
    protect(x)
    paths = {n.path for n in iter_deletable(root)}
    assert y.path in paths
    assert x.path not in paths
    # root is up-protected too: also excluded
    assert tmp_path not in paths


def test_iter_deletable_includes_unprotected_sibling_of_protected(tmp_path: Path) -> None:
    """Each node checked individually (RED's semantics).

    Up-prop pins the parent so the parent survives, but its un-protected
    child is still in the deletion list: protecting one sibling does NOT
    immunise the other.
    """
    (tmp_path / "a" / "protected_one").mkdir(parents=True)
    (tmp_path / "a" / "deletable_one").mkdir()
    root = _scan(tmp_path)
    a = root.children[0]
    by_name = {c.path.name: c for c in a.children}
    protect(by_name["protected_one"])

    deletable = {n.path for n in iter_deletable(root)}
    assert by_name["deletable_one"].path in deletable
    assert by_name["protected_one"].path not in deletable
    assert a.path not in deletable        # protected via up-prop
    assert tmp_path not in deletable      # protected via up-prop


def test_iter_deletable_post_order(tmp_path: Path) -> None:
    """Deepest-first ordering must survive protection logic."""
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    root = _scan(tmp_path)
    paths = [n.path for n in iter_deletable(root)]
    # c should appear before b which appears before a
    assert paths.index(tmp_path / "a" / "b" / "c") < paths.index(tmp_path / "a" / "b")
    assert paths.index(tmp_path / "a" / "b") < paths.index(tmp_path / "a")
