"""Tests for compose ↔ quadlet conversion tools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from arr_mcp.config import Settings
from arr_mcp.tools.conversion import (
    parse_quadlet,
    quadlet_to_service,
    register_conversion_tools,
    service_to_quadlet,
)

# ---------------------------------------------------------------------------
# Unit tests — pure conversion logic (no I/O)
# ---------------------------------------------------------------------------


class TestServiceToQuadlet:
    def test_basic_fields(self) -> None:
        svc = {"image": "nginx:latest", "container_name": "web"}
        content, warnings = service_to_quadlet("web", svc)
        assert "Image=nginx:latest" in content
        assert "ContainerName=web" in content
        assert not warnings

    def test_environment_dict(self) -> None:
        svc = {"image": "app", "environment": {"FOO": "bar", "BAZ": "qux"}}
        content, _ = service_to_quadlet("app", svc)
        assert "Environment=FOO=bar" in content
        assert "Environment=BAZ=qux" in content

    def test_environment_list(self) -> None:
        svc = {"image": "app", "environment": ["FOO=bar", "BAZ=qux"]}
        content, _ = service_to_quadlet("app", svc)
        assert "Environment=FOO=bar" in content
        assert "Environment=BAZ=qux" in content

    def test_volumes(self) -> None:
        svc = {"image": "app", "volumes": ["/data:/data", "/config:/config:ro"]}
        content, _ = service_to_quadlet("app", svc)
        assert "Volume=/data:/data" in content
        assert "Volume=/config:/config:ro" in content

    def test_ports(self) -> None:
        svc = {"image": "app", "ports": ["8080:80", "443:443"]}
        content, _ = service_to_quadlet("app", svc)
        assert "PublishPort=8080:80" in content
        assert "PublishPort=443:443" in content

    def test_networks(self) -> None:
        svc = {"image": "app", "networks": ["frontend", "backend"]}
        content, _ = service_to_quadlet("app", svc)
        assert "Network=frontend" in content
        assert "Network=backend" in content

    def test_restart_unless_stopped(self) -> None:
        content, _ = service_to_quadlet("app", {"image": "x", "restart": "unless-stopped"})
        assert "Restart=always" in content

    def test_restart_always(self) -> None:
        content, _ = service_to_quadlet("app", {"image": "x", "restart": "always"})
        assert "Restart=always" in content

    def test_restart_on_failure(self) -> None:
        content, _ = service_to_quadlet("app", {"image": "x", "restart": "on-failure"})
        assert "Restart=on-failure" in content

    def test_restart_no(self) -> None:
        content, _ = service_to_quadlet("app", {"image": "x", "restart": "no"})
        assert "Restart=no" in content

    def test_depends_on_list(self) -> None:
        svc = {"image": "app", "depends_on": ["db", "cache"]}
        content, _ = service_to_quadlet("app", svc)
        assert "After=db.service" in content
        assert "After=cache.service" in content

    def test_depends_on_dict(self) -> None:
        svc = {"image": "app", "depends_on": {"db": {"condition": "service_healthy"}}}
        content, _ = service_to_quadlet("app", svc)
        assert "After=db.service" in content

    def test_healthcheck_list_cmd(self) -> None:
        svc = {
            "image": "app",
            "healthcheck": {
                "test": ["CMD-SHELL", "curl -f http://localhost/health"],
                "interval": "30s",
                "timeout": "10s",
                "retries": 3,
            },
        }
        content, _ = service_to_quadlet("app", svc)
        assert "HealthCmd=curl -f http://localhost/health" in content
        assert "HealthInterval=30s" in content
        assert "HealthTimeout=10s" in content
        assert "HealthRetries=3" in content

    def test_unsupported_build_warns(self) -> None:
        svc = {"build": ".", "image": "app"}
        _, warnings = service_to_quadlet("app", svc)
        assert any("build" in w for w in warnings)

    def test_unsupported_deploy_warns(self) -> None:
        svc = {"image": "app", "deploy": {"replicas": 2}}
        _, warnings = service_to_quadlet("app", svc)
        assert any("deploy" in w for w in warnings)

    def test_unit_section_present(self) -> None:
        content, _ = service_to_quadlet("app", {"image": "x"})
        assert "[Unit]" in content
        assert "[Container]" in content
        assert "[Service]" in content
        assert "[Install]" in content
        assert "WantedBy=default.target" in content

    def test_container_name_defaults_to_service_name(self) -> None:
        content, _ = service_to_quadlet("myapp", {"image": "x"})
        assert "ContainerName=myapp" in content


class TestQuadletToService:
    def _make_quadlet(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test.container"
        p.write_text(content)
        return p

    def test_basic_roundtrip(self, tmp_path: Path) -> None:
        p = self._make_quadlet(
            tmp_path,
            "[Container]\nImage=nginx:latest\nContainerName=web\n",
        )
        quadlet = parse_quadlet(p)
        name, svc = quadlet_to_service(quadlet)
        assert name == "web"
        assert svc["image"] == "nginx:latest"

    def test_restart_always_maps_to_unless_stopped(self, tmp_path: Path) -> None:
        p = self._make_quadlet(
            tmp_path,
            "[Container]\nImage=x\nContainerName=app\n[Service]\nRestart=always\n",
        )
        _, svc = quadlet_to_service(parse_quadlet(p))
        assert svc["restart"] == "unless-stopped"

    def test_restart_on_failure(self, tmp_path: Path) -> None:
        p = self._make_quadlet(
            tmp_path,
            "[Container]\nImage=x\nContainerName=app\n[Service]\nRestart=on-failure\n",
        )
        _, svc = quadlet_to_service(parse_quadlet(p))
        assert svc["restart"] == "on-failure"

    def test_environment_parsed(self, tmp_path: Path) -> None:
        p = self._make_quadlet(
            tmp_path,
            "[Container]\nImage=x\nContainerName=app\nEnvironment=FOO=bar\nEnvironment=BAZ=qux\n",
        )
        _, svc = quadlet_to_service(parse_quadlet(p))
        assert "FOO=bar" in svc["environment"]
        assert "BAZ=qux" in svc["environment"]

    def test_depends_on_stripped(self, tmp_path: Path) -> None:
        p = self._make_quadlet(
            tmp_path,
            "[Unit]\nAfter=db.service\n[Container]\nImage=x\nContainerName=app\n",
        )
        _, svc = quadlet_to_service(parse_quadlet(p))
        assert "db" in svc["depends_on"]


# ---------------------------------------------------------------------------
# Integration tests — file I/O via MCP tools
# ---------------------------------------------------------------------------


def _make_server(settings: Settings) -> FastMCP:
    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)
    return server


SIMPLE_COMPOSE = """\
services:
  web:
    image: nginx:latest
    container_name: web
    ports:
      - "8080:80"
    restart: unless-stopped
  db:
    image: postgres:15
    container_name: db
    environment:
      POSTGRES_PASSWORD: secret
    volumes:
      - /data/postgres:/var/lib/postgresql/data
    restart: unless-stopped
"""


async def test_compose_to_quadlets_writes_files(settings: Settings) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(SIMPLE_COMPOSE)

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    text = result[0][0].text

    assert "web.container" in text
    assert "db.container" in text
    assert (stack_dir / "quadlets" / "web.container").exists()
    assert (stack_dir / "quadlets" / "db.container").exists()


async def test_compose_to_quadlets_content_correct(settings: Settings) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(SIMPLE_COMPOSE)

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    web_content = (stack_dir / "quadlets" / "web.container").read_text()

    assert "Image=nginx:latest" in web_content
    assert "PublishPort=8080:80" in web_content
    assert "Restart=always" in web_content


async def test_compose_to_quadlets_idempotent(settings: Settings) -> None:
    """Running twice should overwrite staging files without error."""
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(SIMPLE_COMPOSE)

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    result = await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    assert "web.container" in result[0][0].text


async def test_compose_to_quadlets_stack_not_found(settings: Settings) -> None:
    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("compose_to_quadlets", {"stack": "nope"})
    assert "not found" in result[0][0].text.lower()


async def test_compose_to_quadlets_invalid_yaml(settings: Settings) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("{ bad yaml: [}")

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    assert "could not parse" in result[0][0].text.lower()


async def test_compose_to_quadlets_no_compose_file(settings: Settings) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    assert "no compose file" in result[0][0].text.lower()


async def test_quadlets_to_compose_writes_file(settings: Settings) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    quadlets_dir = stack_dir / "quadlets"
    quadlets_dir.mkdir(parents=True)
    (quadlets_dir / "web.container").write_text(
        "[Container]\nImage=nginx:latest\nContainerName=web\nPublishPort=8080:80\n"
        "[Service]\nRestart=always\n"
    )

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("quadlets_to_compose", {"stack": "mystack"})
    text = result[0][0].text

    assert "compose.from-quadlets.yaml" in text
    assert (stack_dir / "compose.from-quadlets.yaml").exists()
    content = (stack_dir / "compose.from-quadlets.yaml").read_text()
    assert "nginx:latest" in content


async def test_quadlets_to_compose_no_files(settings: Settings) -> None:
    stack_dir = Path(settings.stacks_dir) / "mystack"
    (stack_dir / "quadlets").mkdir(parents=True)

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("quadlets_to_compose", {"stack": "mystack"})
    assert "no .container files" in result[0][0].text.lower()


async def test_quadlets_to_compose_stack_not_found(settings: Settings) -> None:
    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    result = await server.call_tool("quadlets_to_compose", {"stack": "nope"})
    assert "not found" in result[0][0].text.lower()


async def test_roundtrip(settings: Settings) -> None:
    """compose → quadlets → compose should preserve service images."""
    stack_dir = Path(settings.stacks_dir) / "mystack"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text(SIMPLE_COMPOSE)

    server = FastMCP("test")
    with patch("arr_mcp.tools.conversion.is_owned_by_current_user", return_value=True):
        register_conversion_tools(server, settings)

    await server.call_tool("compose_to_quadlets", {"stack": "mystack"})
    await server.call_tool("quadlets_to_compose", {"stack": "mystack"})

    final_yaml = (stack_dir / "compose.from-quadlets.yaml").read_text()
    assert "nginx:latest" in final_yaml
    assert "postgres:15" in final_yaml
