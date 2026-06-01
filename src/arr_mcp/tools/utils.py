"""Shared utilities for arr-mcp tools."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


def is_owned_by_current_user(path: Path) -> bool:
    """Return True if path is owned by the current process UID.

    Always returns True on platforms without os.getuid() (e.g. Windows),
    so ownership filtering is a no-op in non-Linux environments.
    """
    getuid: Callable[[], int] | None = getattr(os, "getuid", None)
    if getuid is None:
        return True
    return path.stat().st_uid == getuid()
