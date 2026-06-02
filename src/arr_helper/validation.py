"""Input validation for arr-helper operations."""

from __future__ import annotations

import re

# Safe patterns — no path traversal, no shell metacharacters
_STACK_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9_@.-]+(\.service|\.container)$")
_QUADLET_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

MAX_CONTENT_BYTES = 64 * 1024  # 64 KB


def validate_stack_name(name: str) -> str:
    """Return name if valid, raise ValueError otherwise."""
    if not _STACK_NAME_RE.match(name):
        raise ValueError(f"Invalid stack name: {name!r}")
    return name


def validate_unit_name(name: str) -> str:
    """Return name if valid, raise ValueError otherwise."""
    if not _UNIT_NAME_RE.match(name):
        raise ValueError(f"Invalid unit name: {name!r}")
    return name


def validate_quadlet_name(name: str) -> str:
    """Return name if valid, raise ValueError otherwise."""
    if not _QUADLET_NAME_RE.match(name):
        raise ValueError(f"Invalid quadlet name: {name!r}")
    return name


def validate_content(content: str) -> str:
    """Return content if within size limit, raise ValueError otherwise."""
    if len(content.encode()) > MAX_CONTENT_BYTES:
        raise ValueError(f"Content exceeds maximum size of {MAX_CONTENT_BYTES} bytes")
    return content
