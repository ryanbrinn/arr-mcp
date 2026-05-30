"""Tests for the container runtime detector."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from arr_mcp.config import Settings
from arr_mcp.runtime.detector import detect_runtime


def test_detect_podman_explicit(settings: Settings) -> None:
    with patch(
        "arr_mcp.runtime.detector._find_podman",
        return_value=("podman", settings.socket_path),
    ):
        runtime, path = detect_runtime("podman")
    assert runtime == "podman"
    assert "podman.sock" in path


def test_detect_docker_explicit(settings: Settings) -> None:
    with patch("arr_mcp.runtime.detector._find_docker", return_value=("docker", "unix:///var/run/docker.sock")):
        runtime, path = detect_runtime("docker")
    assert runtime == "docker"
    assert "docker.sock" in path


def test_auto_prefers_podman_when_available(settings: Settings) -> None:
    with patch(
        "arr_mcp.runtime.detector._find_podman",
        return_value=("podman", settings.socket_path),
    ), patch(
        "arr_mcp.runtime.detector._find_docker",
        return_value=("docker", "unix:///var/run/docker.sock"),
    ):
        runtime, _ = detect_runtime("auto")
    assert runtime == "podman"


def test_auto_falls_back_to_docker(settings: Settings) -> None:
    with patch("arr_mcp.runtime.detector._find_podman", side_effect=RuntimeError("no podman")), \
         patch("arr_mcp.runtime.detector._find_docker", return_value=("docker", "unix:///var/run/docker.sock")):
        runtime, _ = detect_runtime("auto")
    assert runtime == "docker"


def test_no_runtime_available_raises(settings: Settings) -> None:
    with patch("arr_mcp.runtime.detector._find_podman", side_effect=RuntimeError("no podman")), \
         patch("arr_mcp.runtime.detector._find_docker", side_effect=RuntimeError("no docker")):
        with pytest.raises(RuntimeError):
            detect_runtime("auto")
