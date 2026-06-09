"""Adversarial / guardrail tests.

Attempts to:
  - Bypass authentication (missing header, wrong scheme, empty/garbage tokens)
  - Escape allowed filesystem roots via path traversal
  - Trigger destructive operations without the required confirmation
  - Access resources not owned by the current user
  - Inject malicious content into paths and queries
  - Exploit log-path restrictions

These tests do NOT need to be parametrized over runtimes — the guardrails
are independent of which container daemon is in use.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from arr_mcp.config import Settings
from arr_mcp.tools.diagnostics import _check_diagnostic_path
from arr_mcp.tools.filesystem import _check_path
from arr_mcp.tools.logs import _check_log_path

# ---------------------------------------------------------------------------
# Auth bypass (HTTP layer)
# ---------------------------------------------------------------------------


async def test_mcp_requires_auth(http_client: httpx.AsyncClient) -> None:
    r = await http_client.post("/mcp", json={})
    assert r.status_code == 401


async def test_missing_authorization_header_rejected(http_client: httpx.AsyncClient) -> None:
    r = await http_client.post("/mcp", content=b"{}")
    assert r.status_code == 401


async def test_wrong_scheme_rejected(http_client: httpx.AsyncClient) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert r.status_code == 401


async def test_empty_bearer_token_rejected(http_client: httpx.AsyncClient) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


async def test_wrong_api_key_rejected(http_client: httpx.AsyncClient) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 401


async def test_bearer_prefix_only_no_key_rejected(http_client: httpx.AsyncClient) -> None:
    r = await http_client.post("/mcp", headers={"Authorization": "Bearer"})
    assert r.status_code == 401


async def test_health_bypasses_auth(http_client: httpx.AsyncClient) -> None:
    r = await http_client.get("/health")
    assert r.status_code == 200


async def test_api_key_in_query_string_is_rejected(http_client: httpx.AsyncClient) -> None:
    """Auth must come from the Authorization header, not query params."""
    r = await http_client.post("/mcp?api_key=http-test-key")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Filesystem path traversal (tool layer)
# ---------------------------------------------------------------------------


class _TraversalCase:
    def __init__(self, label: str, path: str) -> None:
        self.label = label
        self.path = path

    def __repr__(self) -> str:
        return self.label


_TRAVERSAL_CASES = [
    _TraversalCase("dot-dot-slash", "{root}/../../../etc/passwd"),
    _TraversalCase("absolute-etc", "/etc/passwd"),
    _TraversalCase("absolute-root", "/"),
    _TraversalCase("proc-environ", "/proc/1/environ"),
    _TraversalCase("home-dir", "/root/.ssh/id_rsa"),
    _TraversalCase("tmp", "/tmp/evil"),
    _TraversalCase("null-byte-suffix", "{root}/safe\x00/../../../etc/passwd"),
]

# Paths that look like traversal attempts but are NOT blocked because Python's
# Path.resolve() treats %2e%2e as a literal directory name (not "..").
# These confirm that the guard relies on resolve() correctly — URL-encoded dots
# stay inside the allowed root as literal path components.
_SAFE_LOOKING_ENCODED = [
    _TraversalCase("encoded-dots-stay-in-root", "{root}/%2e%2e/%2e%2e/etc/passwd"),
]


@pytest.fixture
def _settings(tmp_path: Path) -> Settings:
    stacks = tmp_path / "stacks"
    stacks.mkdir()
    services = tmp_path / "services"
    services.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    return Settings(
        api_key="x",
        compose_dir=str(stacks),
        services_dir=str(services),
        media_dir=str(media),
        container_runtime="docker-compose",
        socket_path="unix:///fake.sock",
    )


@pytest.mark.parametrize("case", _TRAVERSAL_CASES, ids=lambda c: c.label)
def test_check_path_blocks_traversal(_settings: Settings, case: _TraversalCase) -> None:
    path = case.path.replace("{root}", _settings.compose_dir)
    with pytest.raises(PermissionError):
        _check_path(path, _settings)


@pytest.mark.parametrize("case", _TRAVERSAL_CASES, ids=lambda c: c.label)
def test_check_log_path_blocks_traversal(_settings: Settings, case: _TraversalCase) -> None:
    path = case.path.replace("{root}", _settings.compose_dir)
    extra_roots = [Path(_settings.compose_dir), Path(_settings.media_dir)]
    with pytest.raises(PermissionError):
        _check_log_path(path, extra_roots)


@pytest.mark.parametrize("case", _SAFE_LOOKING_ENCODED, ids=lambda c: c.label)
def test_url_encoded_dots_are_not_traversal(_settings: Settings, case: _TraversalCase) -> None:
    """Percent-encoded dots (%2e%2e) are literal path components, not ".." — they
    stay inside the allowed root and must NOT be treated as traversal."""
    path = case.path.replace("{root}", _settings.compose_dir)
    # Should not raise — the resolved path is still under the stacks root.
    resolved = _check_path(path, _settings)
    assert str(resolved).startswith(_settings.compose_dir)


# ---------------------------------------------------------------------------
# Tool-level guardrail probing (via call_tool)
# ---------------------------------------------------------------------------


@pytest.fixture
def _mcp(_settings: Settings):
    """Bare MCP server for guardrail probing — no container backend needed."""
    from unittest.mock import AsyncMock, MagicMock

    from arr_mcp.server import build_mcp_server

    client = MagicMock()
    client.get = AsyncMock(return_value=[])
    client.post = AsyncMock(return_value={})
    client.delete = AsyncMock(return_value={})
    client.socket_path = "unix:///fake.sock"
    from arr_mcp.ai.null import NullProvider

    return build_mcp_server(_settings, client, NullProvider())


async def test_file_write_outside_allowed_roots_raises(_mcp: FastMCP) -> None:
    with pytest.raises(ToolError, match="not in allowed roots"):
        await _mcp.call_tool("file_write", {"path": "/etc/evil.txt", "content": "bad"})


async def test_file_read_outside_allowed_roots_raises(_mcp: FastMCP) -> None:
    with pytest.raises(ToolError):
        await _mcp.call_tool("file_read", {"path": "/etc/shadow"})


async def test_directory_list_outside_allowed_roots_raises(_mcp: FastMCP) -> None:
    with pytest.raises(ToolError):
        await _mcp.call_tool("directory_list", {"path": "/var/spool"})


async def test_disk_usage_outside_allowed_roots_raises(_mcp: FastMCP) -> None:
    with pytest.raises(ToolError):
        await _mcp.call_tool("disk_usage", {"path": "/tmp"})


async def test_log_read_outside_allowed_roots_raises(_mcp: FastMCP) -> None:
    with pytest.raises(ToolError):
        await _mcp.call_tool("log_read", {"path": "/etc/cron.d/backdoor"})


async def test_log_search_outside_allowed_roots_raises(_mcp: FastMCP) -> None:
    with pytest.raises(ToolError):
        await _mcp.call_tool("log_search", {"path": "/proc/1/fd/1", "query": "secret"})


# ---------------------------------------------------------------------------
# Destructive-operation confirmation guards
# ---------------------------------------------------------------------------


async def test_container_remove_default_refuses(_mcp: FastMCP) -> None:
    result = await _mcp.call_tool("container_remove", {"name": "plex"})
    assert "confirm=True" in result[0][0].text


async def test_container_remove_explicit_false_refuses(_mcp: FastMCP) -> None:
    result = await _mcp.call_tool("container_remove", {"name": "plex", "confirm": False})
    assert "confirm=True" in result[0][0].text


async def test_stack_down_default_refuses(_mcp: FastMCP, _settings: Settings) -> None:
    stacks_root = Path(_settings.compose_dir)
    (stacks_root / "media").mkdir()
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await _mcp.call_tool("stack_down", {"name": "media"})
    assert "confirm=True" in result[0][0].text


async def test_stack_down_explicit_false_refuses(_mcp: FastMCP, _settings: Settings) -> None:
    stacks_root = Path(_settings.compose_dir)
    (stacks_root / "media").mkdir()
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        result = await _mcp.call_tool("stack_down", {"name": "media", "confirm": False})
    assert "confirm=True" in result[0][0].text


# ---------------------------------------------------------------------------
# Ownership enforcement
# ---------------------------------------------------------------------------


async def test_stack_not_owned_by_user_is_hidden(_mcp: FastMCP, _settings: Settings) -> None:
    stacks_root = Path(_settings.compose_dir)
    (stacks_root / "root-stack").mkdir()
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=False):
        result = await _mcp.call_tool("stack_list", {})
    assert "root-stack" not in result[0][0].text


async def test_stack_not_owned_by_user_raises_on_access(_mcp: FastMCP, _settings: Settings) -> None:
    stacks_root = Path(_settings.compose_dir)
    (stacks_root / "root-stack").mkdir()
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=False):
        with pytest.raises(ToolError, match="Stack not found"):
            await _mcp.call_tool("compose_read", {"stack": "root-stack"})


async def test_directory_list_hides_unowned_dirs_in_stacks_root(
    _mcp: FastMCP, _settings: Settings
) -> None:
    stacks_root = Path(_settings.compose_dir)
    (stacks_root / "mine").mkdir()
    (stacks_root / "not-mine").mkdir()
    with patch(
        "arr_mcp.tools.filesystem.is_owned_by_current_user",
        side_effect=lambda p: p.name != "not-mine",
    ):
        result = await _mcp.call_tool("directory_list", {"path": _settings.compose_dir})
    assert "mine" in result[0][0].text
    assert "not-mine" not in result[0][0].text


# ---------------------------------------------------------------------------
# Malicious input content (injection probing)
# ---------------------------------------------------------------------------


async def test_compose_write_with_shell_injection_content_is_stored_verbatim(
    _mcp: FastMCP, _settings: Settings
) -> None:
    """Malicious compose content must be stored as-is — no shell expansion."""
    stacks_root = Path(_settings.compose_dir)
    stack_dir = stacks_root / "target"
    stack_dir.mkdir()
    evil_content = "services:\n  x:\n    command: rm -rf / --no-preserve-root\n"
    with patch("arr_mcp.tools.stacks.is_owned_by_current_user", return_value=True):
        await _mcp.call_tool("compose_write", {"stack": "target", "content": evil_content})
    written = (stack_dir / "compose.yaml").read_text()
    # Content stored verbatim — no execution occurred
    assert written == evil_content


async def test_log_search_with_regex_special_chars_does_not_crash(
    _mcp: FastMCP, _settings: Settings
) -> None:
    """Regex-like query characters must not blow up the search."""
    log_file = Path(_settings.compose_dir) / "app.log"
    log_file.write_text("normal log line\n")
    # These would crash if the query were passed to re.search() unsanitised
    for evil_query in ["[invalid regex", ".*+?{}", "(unclosed", "\\"]:
        result = await _mcp.call_tool("log_search", {"path": str(log_file), "query": evil_query})
        # Just verify it returns a TextContent without raising
        assert result[0][0].text is not None


async def test_file_write_with_large_content_is_accepted(
    _mcp: FastMCP, _settings: Settings
) -> None:
    """No artificial size limits — but write must complete cleanly."""
    target = str(Path(_settings.compose_dir) / "big.txt")
    content = "x" * (1024 * 1024)  # 1 MB
    result = await _mcp.call_tool("file_write", {"path": target, "content": content})
    assert "Written" in result[0][0].text


# ---------------------------------------------------------------------------
# Diagnostic path security (_check_diagnostic_path)
# ---------------------------------------------------------------------------


def test_diagnostic_path_allows_config_xml(_settings: Settings) -> None:
    """config.xml is permitted by _check_diagnostic_path (unlike _check_path)."""
    p = str(Path(_settings.services_dir) / "sonarr" / "config.xml")
    result = _check_diagnostic_path(p, _settings)
    assert result.name == "config.xml"


def test_diagnostic_path_blocks_database(_settings: Settings) -> None:
    p = str(Path(_settings.services_dir) / "sonarr" / "sonarr.db")
    with pytest.raises(PermissionError, match="database"):
        _check_diagnostic_path(p, _settings)


def test_diagnostic_path_blocks_database_shm(_settings: Settings) -> None:
    p = str(Path(_settings.services_dir) / "sonarr" / "sonarr.db-shm")
    with pytest.raises(PermissionError, match="database"):
        _check_diagnostic_path(p, _settings)


def test_diagnostic_path_blocks_database_wal(_settings: Settings) -> None:
    p = str(Path(_settings.services_dir) / "sonarr" / "sonarr.db-wal")
    with pytest.raises(PermissionError, match="database"):
        _check_diagnostic_path(p, _settings)


@pytest.mark.parametrize("case", _TRAVERSAL_CASES, ids=lambda c: c.label)
def test_check_diagnostic_path_blocks_traversal(_settings: Settings, case: _TraversalCase) -> None:
    path = case.path.replace("{root}", _settings.services_dir)
    with pytest.raises(PermissionError):
        _check_diagnostic_path(path, _settings)
