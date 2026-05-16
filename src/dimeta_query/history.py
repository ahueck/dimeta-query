"""
Undo/redo command history for the dimeta-query REPL.

This module operates on snapshots of an ``IRManager`` instance via a small interface
(:class:`GraphSnapshot`) and a stack manager (:class:`HistoryManager`).
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .ir import IRManager

#: Default maximum number of entries retained in either the undo or redo stack.
DEFAULT_HISTORY_DEPTH: int = 5


@dataclass
class GraphSnapshot:
    """A restorable snapshot of an :class:`IRManager`'s mutable state.

    Captures the full mutable surface of the manager so that future commands
    which mutate ``ir_lines`` or ``ir_refs`` continue to behave correctly
    under undo/redo without modification to this class.
    """

    node_map: Dict[str, Any]
    ir_lines: List[str]
    ir_refs: Dict[str, List[Tuple[str, int]]]
    metadata_count: int
    unresolved: List[str]

    @classmethod
    def capture(cls, manager: "IRManager") -> "GraphSnapshot":
        """Deep-copy the manager's mutable state into a new snapshots.
        """
        return cls(
            node_map=copy.deepcopy(manager.node_map),
            ir_lines=list(manager.ir_lines),
            ir_refs=copy.deepcopy(manager.ir_refs),
            metadata_count=manager.metadata_count,
            unresolved=list(manager.unresolved),
        )

    def restore(self, manager: "IRManager") -> None:
        """Restore the captured state into ``manager``.

        Restoration deep-copies the snapshot's ``node_map`` so the snapshot
        itself remains reusable (important for redo, which re-restores).
        """
        manager.node_map = copy.deepcopy(self.node_map)
        manager.ir_lines = list(self.ir_lines)
        manager.ir_refs = copy.deepcopy(self.ir_refs)
        manager.metadata_count = self.metadata_count
        manager.unresolved = list(self.unresolved)


class HistoryManager:
    """Bounded LIFO stacks of labeled snapshots supporting undo/redo.

    The history manager has no knowledge of ``IRManager``; it only stores
    and retrieves :class:`GraphSnapshot` instances. Callers are responsible
    for capturing the current state when issuing :meth:`undo` or
    :meth:`redo` (so the inverse operation can be pushed onto the other
    stack).
    """

    def __init__(self, max_depth: int = DEFAULT_HISTORY_DEPTH) -> None:
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        self._max_depth: int = max_depth
        self._undo: Deque[Tuple[str, GraphSnapshot]] = deque(maxlen=max_depth)
        self._redo: Deque[Tuple[str, GraphSnapshot]] = deque(maxlen=max_depth)

    @property
    def max_depth(self) -> int:
        return self._max_depth

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def record(self, label: str, snapshot: GraphSnapshot) -> None:
        """Record a pre-mutation snapshot. Clears the redo stack."""
        self._undo.append((label, snapshot))
        self._redo.clear()

    def undo(
        self, current_snapshot: GraphSnapshot
    ) -> Optional[Tuple[str, GraphSnapshot]]:
        """Pop the most recent undo entry and push the current state to redo.

        Returns ``(label, snapshot_to_restore)`` or ``None`` if undo stack
        is empty.
        """
        if not self._undo:
            return None
        label, snap = self._undo.pop()
        self._redo.append((label, current_snapshot))
        return label, snap

    def redo(
        self, current_snapshot: GraphSnapshot
    ) -> Optional[Tuple[str, GraphSnapshot]]:
        """Pop the most recent redo entry and push the current state to undo.

        Returns ``(label, snapshot_to_restore)`` or ``None`` if redo stack
        is empty.
        """
        if not self._redo:
            return None
        label, snap = self._redo.pop()
        self._undo.append((label, current_snapshot))
        return label, snap

    def undo_labels(self) -> List[str]:
        """Labels in undo order (oldest first, most recent last)."""
        return [label for label, _ in self._undo]

    def redo_labels(self) -> List[str]:
        """Labels in redo order (oldest first, most recent last)."""
        return [label for label, _ in self._redo]

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
