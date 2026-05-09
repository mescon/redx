"""Protect / Unprotect with RED's asymmetric propagation.

Protect goes UP: marking a node Protected also marks every ancestor up to
the root. This is what guarantees a protected leaf survives: without
ancestors being protected too, the parent (which becomes empty after
sibling deletes) would itself be deleted, taking the protected child with it.

Unprotect goes DOWN: releasing a parent releases everything beneath it.
This matches user intent ("I changed my mind about keeping this whole
branch").

Mirrors RED2/Lib/TreeManager.cs ProtectNode / UnprotectNode.
"""
from __future__ import annotations

from collections.abc import Iterator

from .config import NodeStatus
from .scanner import ScanNode


def protect(node: ScanNode) -> set[ScanNode]:
    """Mark *node* and every ancestor as protected.

    Stops at the first already-protected ancestor (so repeated protects
    cost only the distance to the nearest protected ancestor).
    Returns the set of nodes whose state actually flipped.
    """
    flipped: set[ScanNode] = set()
    cur: ScanNode | None = node
    while cur is not None and not cur.is_protected:
        cur.is_protected = True
        flipped.add(cur)
        cur = cur.parent
    return flipped


def unprotect(node: ScanNode) -> set[ScanNode]:
    """Unprotect *node* and every descendant.

    Returns the set of nodes whose state flipped (False after, True before).
    """
    flipped: set[ScanNode] = set()
    if not node.is_protected:
        return flipped
    stack: list[ScanNode] = [node]
    while stack:
        cur = stack.pop()
        if cur.is_protected:
            cur.is_protected = False
            flipped.add(cur)
            stack.extend(cur.children)
    return flipped


def iter_deletable(root: ScanNode) -> Iterator[ScanNode]:
    """Yield empty descendants of *root* in post-order, skipping protected nodes.

    SAFETY INVARIANT: the scan root itself is NEVER yielded, even when
    its classification cascade ends up labelling it EMPTY. The user
    chose that folder as the scan target, not as a deletion candidate;
    deleting it is almost always wrong (and on at least one occasion
    has nuked a user's data root). This is a hard-coded "hands off the
    folder you picked" guarantee that mirrors RED's behaviour.

    Each remaining node is checked individually: same as RED's deletion
    pass. Up-propagation has already marked ancestors of protected
    nodes, so they will be skipped here too. Children of protected
    ancestors that aren't themselves protected ARE still yielded.
    """
    for child in root.children:
        yield from _iter_deletable_recursive(child)


def _iter_deletable_recursive(node: ScanNode) -> Iterator[ScanNode]:
    for child in node.children:
        yield from _iter_deletable_recursive(child)
    if node.status is NodeStatus.EMPTY and not node.is_protected:
        yield node
