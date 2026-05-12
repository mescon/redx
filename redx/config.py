"""Runtime configuration.

Mirrors RED2/Lib/RuntimeData.cs and the DeleteModes enum in
RED2/Lib/SystemFunctions.cs. Field names intentionally track the upstream
C# property names so the cross-reference stays obvious.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DeleteMode(Enum):
    SIMULATE = "simulate"
    TRASH = "trash"
    TRASH_CONFIRM = "trash_confirm"
    DIRECT = "direct"


class NodeStatus(Enum):
    EMPTY = "empty"
    NOT_EMPTY = "not_empty"
    ERROR = "error"
    IGNORED = "ignored"
    PROTECTED = "protected"
    DELETED = "deleted"


@dataclass
class Config:
    start_folder: Path | None = None
    delete_mode: DeleteMode = DeleteMode.TRASH

    ignore_files: list[str] = field(default_factory=list)
    ignore_dirs: list[str] = field(default_factory=lambda: [
        ".git", ".hg", ".svn",
        "node_modules", "__pycache__", ".venv",
    ])

    ignore_empty_files: bool = False
    ignore_hidden_dirs: bool = False

    max_depth: int = 200
    min_folder_age_hours: float = 0.0
    infinite_loop_threshold: int = 5
    pause_between_deletes_ms: int = 0

    follow_symlinks: bool = False
