"""Tests for dashboard data helpers."""

from __future__ import annotations

from arr_mcp.dashboard.data import _format_upgrade_notes


def test_format_upgrade_notes_strips_generic_branch_note() -> None:
    changelog = (
        "*To receive further Pre-Release or final updates for a non-docker "
        "installation, please change the branch to **master**."
    )
    notes = _format_upgrade_notes("minor", changelog)
    assert "branch to" not in notes
    assert not notes.endswith("*")
    assert notes.startswith("Minor version upgrade")


def test_format_upgrade_notes_keeps_real_changelog() -> None:
    notes = _format_upgrade_notes("patch", "Fixed a crash on startup.")
    assert "Fixed a crash on startup." in notes
    assert notes.startswith("Patch upgrade")


def test_format_upgrade_notes_falls_back_to_guidance_only() -> None:
    notes = _format_upgrade_notes("major", "")
    assert notes == _format_upgrade_notes("major", "")
    assert "breaking changes" in notes
