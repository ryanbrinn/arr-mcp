"""Tests for arr-agent operation handlers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from arr_helper.handlers import handle_compose_validate


class TestHandleComposeValidate:
    async def test_calls_podman_compose_config(self) -> None:
        """compose_validate uses 'podman-compose config', not --dry-run."""
        captured: list[tuple[str, ...]] = []

        async def fake_run(*args: str) -> tuple[int, str]:
            captured.append(args)
            return 0, "services:\n  app:\n    image: nginx\n"

        with patch("arr_helper.handlers.run_command", new=fake_run):
            code, out = await handle_compose_validate({"stack": "media"})

        assert code == 0
        assert captured[0] == (
            "podman-compose",
            "-f",
            "/opt/stacks/media/compose.yaml",
            "config",
        )
        assert "--dry-run" not in captured[0]

    async def test_returns_output_on_success(self) -> None:
        compose_output = "name: media\nservices:\n  sonarr:\n    image: linuxserver/sonarr\n"

        async def fake_run(*args: str) -> tuple[int, str]:
            return 0, compose_output

        with patch("arr_helper.handlers.run_command", new=fake_run):
            code, out = await handle_compose_validate({"stack": "media"})

        assert code == 0
        assert "sonarr" in out

    async def test_returns_nonzero_on_invalid_compose(self) -> None:
        async def fake_run(*args: str) -> tuple[int, str]:
            return 1, "ERROR: invalid compose file"

        with patch("arr_helper.handlers.run_command", new=fake_run):
            code, out = await handle_compose_validate({"stack": "media"})

        assert code == 1
        assert "ERROR" in out

    async def test_rejects_invalid_stack_name(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            await handle_compose_validate({"stack": "../../etc"})

    async def test_rejects_empty_stack_name(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            await handle_compose_validate({"stack": ""})

    async def test_rejects_stack_name_with_semicolon(self) -> None:
        with pytest.raises(ValueError, match="Invalid stack name"):
            await handle_compose_validate({"stack": "media; rm -rf /"})
