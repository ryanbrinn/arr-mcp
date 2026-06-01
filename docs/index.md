# arr-mcp

MCP server for natural language management of a home media server stack — Plex, Sonarr, Radarr, SABnzbd, and more — via Podman or Docker.

Connects to Claude as an MCP tool server so you can manage your stack conversationally.

---

## Documentation

- [Roadmap](roadmap.md) — project phases, goals, and verification criteria
- [Getting Started](getting-started.md) — installation and running the server
- [Configuration](configuration.md) — environment variables and settings
- [Tools Reference](tools.md) — all available MCP tools
- [Architecture](architecture.md) — deployment model and components
- [Security](security.md) — security model and principles

## Architecture Decisions

- [ADR-0001](adr/0001-filesystem-ownership-scoping.md) — Filesystem ownership scoping
- [ADR-0002](adr/0002-host-side-helper-agent.md) — Host-side helper agent
- [ADR-0003](adr/0003-frontend-strategy.md) — Frontend strategy
