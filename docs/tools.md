# Tools Reference

## Container lifecycle

| Tool | Description |
|---|---|
| `container_list()` | All containers with status, uptime, and ports |
| `container_start(name)` | Start a stopped container |
| `container_stop(name)` | Stop a running container |
| `container_restart(name)` | Restart a container |
| `container_remove(name, confirm=True)` | Remove a container (requires `confirm=True`) |
| `container_logs(name, lines=100)` | Fetch last N log lines |
| `container_stats()` | CPU, memory, and network stats for all running containers |

## Stack management

!!! warning
    Stack up/down/pull/restart require `podman-compose` or `docker-compose` on the host. These tools are currently non-functional when arr-mcp runs inside a container. See [issue #12](https://github.com/ryanbrinn/arr-mcp/issues/12).

| Tool | Description |
|---|---|
| `stack_list()` | List all stacks owned by the current user |
| `stack_up(name)` | `podman-compose up -d` |
| `stack_down(name, confirm=True)` | `podman-compose down` (requires `confirm=True`) |
| `stack_pull(name)` | Pull latest images |
| `stack_restart(name)` | Down then up |

## Compose files

| Tool | Description |
|---|---|
| `compose_read(stack)` | Read the compose.yaml for a stack |
| `compose_write(stack, content)` | Write/replace the compose.yaml for a stack |
| `compose_validate(stack)` | Dry-run validate a stack's compose file |

## Filesystem

All filesystem operations are scoped to allowed roots (`/opt/stacks`, `/media-server`, `/var/log`) and restricted to resources owned by the current user. See [Security](security.md).

| Tool | Description |
|---|---|
| `disk_usage(path="/media-server")` | Disk usage for a path |
| `directory_list(path)` | List directory contents |
| `file_read(path)` | Read a text file |
| `file_write(path, content)` | Write a file (creates parent dirs as needed) |

## Logs

| Tool | Description |
|---|---|
| `log_read(path, lines=100)` | Tail a log file |
| `log_search(path, query, lines=50)` | Search a log file (case-insensitive) |
