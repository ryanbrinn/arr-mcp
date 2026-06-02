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

!!! info "Not yet available"
    Stack management tools (`stack_up`, `stack_down`, `stack_pull`, `stack_restart`, `compose_validate`) require a host-side helper agent that is not yet implemented. See [issue #12](https://github.com/ryanbrinn/arr-mcp/issues/12) and [ADR-0002](adr/0002-host-side-helper-agent.md) for the planned solution.

    The compose file read and write tools below work today.

## Compose files

| Tool | Description |
|---|---|
| `compose_read(stack)` | Read the compose.yaml for a stack |
| `compose_write(stack, content)` | Write/replace the compose.yaml for a stack |

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
