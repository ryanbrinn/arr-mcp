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

---

## Stack management

Stack management tools require the [arr-helper agent](getting-started.md#arr-helper) to be running on the host. When the helper is unavailable, these tools return a message explaining what's needed — they never silently fail.

| Tool | Description |
|---|---|
| `stack_list()` | List all stacks in the stacks directory |
| `stack_up(name)` | Start a stack with `podman-compose up -d` |
| `stack_down(name, confirm=True)` | Stop a stack (requires `confirm=True`) |
| `stack_pull(name)` | Pull latest images for a stack |
| `stack_restart(name)` | Restart a stack (down then up) |
| `compose_validate(name)` | Dry-run validate a stack compose file |

---

## Compose files

| Tool | Description |
|---|---|
| `compose_read(stack)` | Read the compose.yaml for a stack |
| `compose_write(stack, content)` | Write/replace the compose.yaml for a stack |

---

## Compose ↔ Quadlet conversion

Tools for migrating between Docker Compose and Podman quadlet unit files. Both tools write to staging locations and never overwrite originals — you review and install the output yourself.

| Tool | Description |
|---|---|
| `compose_to_quadlets(stack)` | Convert `compose.yaml` → `.container` files in `/opt/stacks/<stack>/quadlets/` |
| `quadlets_to_compose(stack)` | Convert `.container` files → `compose.from-quadlets.yaml` |

**Field coverage:** `image`, `container_name`, `environment`, `volumes`, `ports`, `networks`, all four restart policies, `depends_on`, and `healthcheck`. Unsupported compose fields (e.g. `build`, `deploy`) produce warnings in the output but do not fail the conversion.

**Installing generated quadlets:**

```bash
cp /opt/stacks/<stack>/quadlets/*.container ~/.config/containers/systemd/
systemctl --user daemon-reload
```

If [arr-helper](getting-started.md#arr-helper) is running, it can install the files directly via `systemd_daemon_reload`.

---

## Filesystem

All filesystem operations are scoped to allowed roots (`/opt/stacks`, `/media-server`, `/var/log`) and restricted to resources owned by the current user. See [Security](security.md).

| Tool | Description |
|---|---|
| `disk_usage(path="/media-server")` | Disk usage for a path |
| `directory_list(path)` | List directory contents |
| `file_read(path)` | Read a text file |
| `file_write(path, content)` | Write a file (creates parent dirs as needed) |
| `file_delete(path, confirm=True)` | Delete a file (requires `confirm=True`, rejects root-owned files) |

---

## Logs

| Tool | Description |
|---|---|
| `log_read(path, lines=100)` | Tail a log file |
| `log_search(path, query, lines=50)` | Search a log file (case-insensitive) |
