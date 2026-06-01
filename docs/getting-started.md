# Getting Started

## Requirements

- Podman (rootless, UID 1000) or Docker
- Claude with MCP support (Claude.ai or Claude Desktop)

## Running the server

### Podman

```bash
podman run -d --name arr-mcp \
  -e ARR_MCP_API_KEY=your-secret-key \
  -e ARR_MCP_CONTAINER_RUNTIME=podman \
  -v /run/user/$(id -u)/podman/podman.sock:/run/user/1000/podman/podman.sock:z \
  -v /opt/stacks:/opt/stacks:z \
  -v /media-server:/media-server:z \
  -p 8081:8081 \
  ghcr.io/ryanbrinn/arr-mcp:latest
```

### Docker

```bash
docker run -d --name arr-mcp \
  -e ARR_MCP_API_KEY=your-secret-key \
  -e ARR_MCP_CONTAINER_RUNTIME=docker \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /opt/stacks:/opt/stacks \
  -v /media-server:/media-server \
  -p 8081:8081 \
  ghcr.io/ryanbrinn/arr-mcp:latest
```

### Docker Compose / Podman Compose

```yaml
services:
  arr-mcp:
    image: ghcr.io/ryanbrinn/arr-mcp:latest
    container_name: arr-mcp
    restart: unless-stopped
    ports:
      - "8081:8081"
    environment:
      ARR_MCP_API_KEY: your-secret-key
      ARR_MCP_CONTAINER_RUNTIME: podman  # or docker
    volumes:
      # Podman rootless socket — adjust UID if not 1000
      - /run/user/1000/podman/podman.sock:/run/user/1000/podman/podman.sock:z
      # Docker: use /var/run/docker.sock:/var/run/docker.sock instead
      - /opt/stacks:/opt/stacks:z
      - /media-server:/media-server:z
```

## Health check

```bash
curl http://localhost:8081/health
```

## Connecting to Claude

Add the following to your Claude MCP configuration:

```json
{
  "mcpServers": {
    "arr-mcp": {
      "url": "http://localhost:8081/mcp",
      "headers": {
        "Authorization": "Bearer your-secret-key"
      }
    }
  }
}
```
