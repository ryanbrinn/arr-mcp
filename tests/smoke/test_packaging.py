"""Smoke tests: package build, install, and uninstall."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)  # type: ignore[call-overload]


def test_wheel_exists(installed_package: dict[str, Path | str]) -> None:
    """uv build produced a .whl file."""
    wheel = installed_package["wheel"]
    assert isinstance(wheel, Path)
    assert wheel.exists(), f"Wheel not found: {wheel}"
    assert wheel.suffix == ".whl"


def test_entry_point_arr_mcp(installed_package: dict[str, Path | str]) -> None:
    """arr-mcp entry point script is installed in the venv."""
    bin_dir = installed_package["bin"]
    assert isinstance(bin_dir, Path)
    exe = bin_dir / ("arr-mcp.exe" if sys.platform == "win32" else "arr-mcp")
    assert exe.exists(), f"arr-mcp not found at {exe}"

    # Verify the entry module resolves — don't start the server (no socket here)
    python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
    result = _run([str(python), "-c", "from arr_mcp.server import main"])
    assert result.returncode == 0, f"Entry module import failed:\n{result.stderr}"


def test_entry_point_arr_agent(installed_package: dict[str, Path | str]) -> None:
    """arr-agent entry point script is installed in the venv."""
    bin_dir = installed_package["bin"]
    assert isinstance(bin_dir, Path)
    exe = bin_dir / ("arr-agent.exe" if sys.platform == "win32" else "arr-agent")
    assert exe.exists(), f"arr-agent not found at {exe}"

    # Verify the entry module resolves — arr-helper uses Unix sockets (Linux only),
    # so we only check importability here, not execution.
    python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
    result = _run([str(python), "-c", "from arr_helper.__main__ import main"])
    assert result.returncode == 0, f"Entry module import failed:\n{result.stderr}"


def test_package_importable(installed_package: dict[str, Path | str]) -> None:
    """arr_mcp and arr_helper import without errors inside the installed venv."""
    bin_dir = installed_package["bin"]
    assert isinstance(bin_dir, Path)
    python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")

    for module in ("arr_mcp", "arr_helper"):
        result = _run([str(python), "-c", f"import {module}"])
        assert result.returncode == 0, (
            f"`import {module}` failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


def test_version_matches_pyproject(
    installed_package: dict[str, Path | str],
    project_root: Path,
) -> None:
    """Installed package version matches version in pyproject.toml."""
    import tomllib  # Python 3.11+

    pyproject = project_root / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    expected = data["project"]["version"]

    bin_dir = installed_package["bin"]
    assert isinstance(bin_dir, Path)
    python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")

    result = _run(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('arr-mcp-server'))",
        ]
    )
    assert result.returncode == 0, result.stderr
    installed = result.stdout.strip()
    assert installed == expected, (
        f"Version mismatch: installed={installed!r}, pyproject={expected!r}"
    )


def test_uninstall_clean(installed_package: dict[str, Path | str]) -> None:
    """Package uninstalls cleanly; arr_mcp is no longer importable afterwards."""
    pip = installed_package["pip"]
    bin_dir = installed_package["bin"]
    assert isinstance(pip, Path)
    assert isinstance(bin_dir, Path)
    python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")

    result = _run([str(pip), "uninstall", "arr-mcp-server", "-y"])
    assert result.returncode == 0, f"Uninstall failed:\n{result.stderr}"

    result = _run([str(python), "-c", "import arr_mcp"])
    assert result.returncode != 0, "arr_mcp should not be importable after uninstall"

    # Re-install so other session-scoped fixtures still work
    wheel = installed_package["wheel"]
    assert isinstance(wheel, Path)
    subprocess.run([str(pip), "install", str(wheel)], check=True, capture_output=True)
