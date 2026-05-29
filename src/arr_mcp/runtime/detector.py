"""Auto-detect the available container runtime."""

from __future__ import annotations

import os
from pathlib import Path
import shutil


def detect_runtime(preference: str = "auto") -> tuple[str, str]:
    """Return (runtime, socket_path) for the best available runtime.

    preference: 'auto' | 'podman' | 'docker'
    """
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
    uid = os.getuid()
    candidates = [
        f"/run/user/{uid}/podman/podman.sock",
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
