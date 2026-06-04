"""Smoke test fixtures.

Two session-scoped fixtures drive the entire suite:

``installed_package``
    Builds a wheel from the current source tree, installs it into a fresh
    temporary venv, and yields metadata about that venv.  Confirms the
    packaging pipeline works end-to-end.

``running_server``
    Starts ``arr-mcp`` from the installed venv as a real subprocess, waits
    until ``/health`` responds, and yields the base URL + API key.
    ``ARR_MCP_SOCKET_PATH`` is set to a nonexistent path so that
    ``detect_runtime()`` is bypassed and the server can start without a real
    Docker or Podman socket.  HTTP surface tests (auth, dashboard, MCP
    endpoint) work fine; actual tool calls that touch the container daemon
    would fail — which is expected and tested elsewhere.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import venv
from pathlib import Path
from collections.abc import Generator

import httpx
import pytest

_SMOKE_API_KEY = "smoke-test-key"
_SMOKE_PORT = 18081
_SMOKE_FAKE_SOCK = "/nonexistent-smoke.sock"
_HEALTH_URL = f"http://localhost:{_SMOKE_PORT}/health"
_STARTUP_TIMEOUT = 20  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scripts_dir(venv_path: Path) -> Path:
    """Return the scripts/bin directory inside a venv (cross-platform)."""
    if sys.platform == "win32":
        return venv_path / "Scripts"
    return venv_path / "bin"


def _find_wheel(dist: Path) -> Path:
    """Return the first .whl in dist/, raise if none found."""
    wheels = list(dist.glob("*.whl"))
    if not wheels:
        raise FileNotFoundError(f"No wheel found in {dist}")
    return wheels[0]


def _wait_for_health(url: str, timeout: int) -> None:
    """Poll GET url until 200 or timeout (raises RuntimeError)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.4)
    raise RuntimeError(f"Server at {url} did not become healthy within {timeout}s")


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the repository root."""
    return Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def installed_package(
    tmp_path_factory: pytest.TempPathFactory,
    project_root: Path,
) -> Generator[dict[str, Path | str], None, None]:
    """Build wheel, install into fresh venv, yield venv metadata."""
    base = tmp_path_factory.mktemp("smoke_install")
    venv_path = base / "venv"
    dist_dir = base / "dist"

    # Build wheel into dist_dir
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    wheel = _find_wheel(dist_dir)

    # Create a clean venv and install the wheel
    venv.create(str(venv_path), with_pip=True, clear=True)
    bin_dir = _scripts_dir(venv_path)
    pip = bin_dir / ("pip.exe" if sys.platform == "win32" else "pip")

    subprocess.run(
        [str(pip), "install", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )

    yield {
        "venv": venv_path,
        "bin": bin_dir,
        "wheel": wheel,
        "pip": pip,
    }


@pytest.fixture(scope="session")
def running_server(
    installed_package: dict[str, Path | str],
) -> Generator[dict[str, str], None, None]:
    """Start arr-mcp from the installed venv; yield base URL and API key."""
    bin_dir = installed_package["bin"]
    exe = bin_dir / ("arr-mcp.exe" if sys.platform == "win32" else "arr-mcp")

    env = {
        **os.environ,
        "ARR_MCP_API_KEY": _SMOKE_API_KEY,
        "ARR_MCP_PORT": str(_SMOKE_PORT),
        # Bypass detect_runtime() — no real Docker/Podman needed
        "ARR_MCP_SOCKET_PATH": _SMOKE_FAKE_SOCK,
        "ARR_MCP_LOG_LEVEL": "warning",
        # Disable compose tools to avoid stack-dir validation noise
        "ARR_MCP_COMPOSE_DIR": "",
    }

    proc = subprocess.Popen(
        [str(exe)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_for_health(_HEALTH_URL, _STARTUP_TIMEOUT)
    except RuntimeError:
        proc.terminate()
        out, _ = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Server failed to start.\nOutput:\n{out.decode(errors='replace') if out else '(none)'}"
        )

    yield {
        "url": f"http://localhost:{_SMOKE_PORT}",
        "api_key": _SMOKE_API_KEY,
    }

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
