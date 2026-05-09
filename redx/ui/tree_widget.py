"""Tree view of scan results.

Mirrors RED2/Lib/TreeManager.cs. We prune subtrees with no empty/error/
protected descendants: for typical scans the full filesystem tree is
overwhelming and matches none of RED's UX. Pruning keeps the view
focused on what's actionable.

Right-click on a node opens a Protect/Unprotect menu: the engine logic
lives in :mod:`redx.protect` and propagates UP on protect, DOWN on
unprotect.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QCursor
from PySide6.QtWidgets import QMenu, QStyle, QTreeWidget, QTreeWidgetItem

from ..config import NodeStatus
from ..protect import protect, unprotect
from ..scanner import ScanNode


# Status colours roughly mirror RED's palette.
_COLORS = {
    NodeStatus.EMPTY:     QColor(190, 30, 30),
    NodeStatus.NOT_EMPTY: QColor(120, 120, 120),
    NodeStatus.IGNORED:   QColor(60, 100, 200),
    NodeStatus.ERROR:     QColor(190, 110, 0),
    NodeStatus.PROTECTED: QColor(60, 100, 200),
    NodeStatus.DELETED:   QColor(120, 120, 120),
}

_INTERESTING = {NodeStatus.EMPTY, NodeStatus.ERROR, NodeStatus.PROTECTED}


def _has_interesting_descendant(node: ScanNode) -> bool:
    if node.status in _INTERESTING or node.is_protected:
        return True
    return any(_has_interesting_descendant(c) for c in node.children)


class ScanTreeWidget(QTreeWidget):
    NODE_ROLE = Qt.ItemDataRole.UserRole + 1
    protection_changed = Signal()
    node_protected = Signal(object)   # ScanNode that the user clicked Protect on
    node_unprotected = Signal(object) # ScanNode that the user clicked Unprotect on

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Folder", "Status"])
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setColumnWidth(0, 520)

        self._prune = True
        self._items_by_node: dict[ScanNode, QTreeWidgetItem] = {}
        self._root_node: ScanNode | None = None

        style = self.style()
        self._icon_dir = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._icon_root = style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon)
        self._icon_warn = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        self._icon_link = style.standardIcon(QStyle.StandardPixmap.SP_DirLinkIcon)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    # ---------- Render ----------------------------------------------------------

    def set_root(self, root: ScanNode, *, prune: bool = True) -> None:
        """Render the scan tree.

        With ``prune=True`` (default) any subtree without an interesting
        (empty/error/protected) descendant is hidden: much faster on
        large filesystems. With ``prune=False`` every dir is shown (RED).
        """
        self.clear()
        self._items_by_node.clear()
        self._root_node = root
        self._prune = prune
        item = self._build_item(root, is_root=True)
        if item is not None:
            self.addTopLevelItem(item)
            item.setExpanded(True)
            self._expand_all(item)

    def _build_item(
        self, node: ScanNode, *, is_root: bool = False
    ) -> QTreeWidgetItem | None:
        if not is_root and self._prune and not _has_interesting_descendant(node):
            return None

        label = str(node.path) if is_root else node.path.name
        if node.empty_file_count > 0:
            plural = "s" if node.empty_file_count > 1 else ""
            label += f"   (contains {node.empty_file_count} empty file{plural})"

        item = QTreeWidgetItem()
        item.setText(0, label)
        item.setData(0, self.NODE_ROLE, node)
        self._items_by_node[node] = item
        self._apply_style(item, node, is_root=is_root)

        for child in node.children:
            child_item = self._build_item(child)
            if child_item is not None:
                item.addChild(child_item)
        return item

    def _apply_style(
        self, item: QTreeWidgetItem, node: ScanNode, *, is_root: bool
    ) -> None:
        # Protected styling overrides status-based styling. Order matters
        # because is_protected can coexist with EMPTY/NOT_EMPTY/etc.
        if node.is_protected:
            item.setIcon(0, self._icon_link)
            item.setText(1, "protected")
        elif is_root:
            item.setIcon(0, self._icon_root)
            item.setText(1, "")
        elif node.status is NodeStatus.ERROR:
            item.setIcon(0, self._icon_warn)
            item.setText(1, "error")
            if node.error:
                item.setToolTip(0, node.error)
        elif node.status is NodeStatus.IGNORED:
            item.setIcon(0, self._icon_link)
            item.setText(1, "ignored")
        else:
            item.setIcon(0, self._icon_dir)
            item.setText(1, node.status.name.replace("_", " ").lower())

        # Foreground colour. We always set it so that unprotect properly
        # restores theme/status colour from a previously-blue protected look.
        if node.is_protected:
            brush = QBrush(_COLORS[NodeStatus.PROTECTED])
        elif is_root:
            brush = self.palette().text()
        else:
            colour = _COLORS.get(node.status)
            brush = QBrush(colour) if colour is not None else self.palette().text()
        item.setForeground(0, brush)
        item.setForeground(1, brush)

    def _expand_all(self, item: QTreeWidgetItem) -> None:
        for i in range(item.childCount()):
            self._expand_all(item.child(i))
        item.setExpanded(True)

    # ---------- Protect / Unprotect --------------------------------------------

    @Slot(QPoint)
    def _on_context_menu(self, point: QPoint) -> None:
        item = self.itemAt(point)
        if item is None:
            return
        node = item.data(0, self.NODE_ROLE)
        if node is None:
            return

        menu = QMenu(self)
        if node.is_protected:
            act = menu.addAction("Unprotect (releases descendants too)")
            act.triggered.connect(
                lambda _checked=False, n=node: self._do_unprotect(n)
            )
        else:
            act = menu.addAction("Protect (also protects ancestors)")
            act.triggered.connect(
                lambda _checked=False, n=node: self._do_protect(n)
            )
        menu.popup(QCursor.pos())

    def _do_protect(self, node: ScanNode) -> None:
        flipped = protect(node)
        self._restyle(flipped)
        self.node_protected.emit(node)
        self.protection_changed.emit()

    def _do_unprotect(self, node: ScanNode) -> None:
        flipped = unprotect(node)
        self._restyle(flipped)
        self.node_unprotected.emit(node)
        self.protection_changed.emit()

    def _restyle(self, nodes: Iterable[ScanNode]) -> None:
        for node in nodes:
            item = self._items_by_node.get(node)
            if item is not None:
                self._apply_style(item, node, is_root=node is self._root_node)
