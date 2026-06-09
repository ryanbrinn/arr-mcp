"""Auto-detect the available container runtime."""

from __future__ import annotations

import shutil
from pathlib import Path


def detect_runtime(preference: str = "auto", socket_path: str = "") -> tuple[str, str]:
    """Return (runtime, socket_path) for the best available runtime.

    If socket_path is provided explicitly (e.g. from ARR_MCP_SOCKET_PATH),
    it is used as-is and detection is skipped. This is the correct behaviour
    when arr-mcp is running inside a container with the host socket bind-mounted.

    preference: 'auto' | 'podman' | 'docker'
    """
    if socket_path:
        # Explicit path wins — infer runtime from the path string.
        runtime = "podman" if "podman" in socket_path else "docker"
        sock = (
            socket_path
            if socket_path.startswith("unix://")
            else f"unix://{socket_path}"
        )
        return (runtime, sock)

    if preference == "docker":
        return _find_docker()
    if preference == "podman":
        return _find_podman()
    # auto: prefer rootless Podman, fall back to Docker
    try:
        return _find_podman()
    except RuntimeError:
        pass
    return _find_docker()


def _find_podman() -> tuple[str, str]:
    candidates = [
        "/run/user/1000/podman/podman.sock",
        "/run/podman/podman.sock",
    ]
    for path in candidates:
        if Path(path).exists():
            return ("podman", f"unix://{path}")
    if shutil.which("podman"):
        return ("podman", "unix:///run/podman/podman.sock")
    raise RuntimeError("Podman socket not found")


def _find_docker() -> tuple[str, str]:
    for path in ["/var/run/docker.sock", "/run/docker.sock"]:
        if Path(path).exists():
            return ("docker", f"unix://{path}")
    raise RuntimeError("Docker socket not found")
