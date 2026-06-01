# Lessons Learned

Operational knowledge gained through real-world deployment. Referenced by the Phase 3 installation wizard design.

---

## Rootless Podman volume permissions for non-linuxserver images

**Issue:** [#19](https://github.com/ryanbrinn/arr-mcp/issues/19) | **Phase relevance:** Phase 3

### Problem

When running non-linuxserver images in rootless Podman with bind-mounted volumes, the container process may not be able to write to the mounted directory — even if the host directory is owned by the correct user.

**Root cause:** Rootless Podman uses user namespaces. UIDs inside the container do not directly correspond to UIDs on the host. `chown media:media /path` on the host does not make a directory writable by UID 1000 *inside the container's user namespace*.

**linuxserver images** (`lscr.io/linuxserver/*`) handle this transparently via their `PUID`/`PGID` init script. Non-linuxserver images (e.g. seerr running as `node:node`) do not.

### Symptoms

```
Error: EACCES: permission denied, open '/app/config/logs/seerr-2026-06-01.log'
```

The host directory appears correctly owned (`drwxr-xr-x media media`) but the container still cannot write to it.

### The fix

Use `podman unshare` to chown inside the user namespace:

```bash
podman unshare chown -R 1000:1000 /path/to/config
```

### What does NOT fix it

| Attempted fix | Why it fails |
|---|---|
| `PUID=1000` / `PGID=1000` env vars | linuxserver convention only — ignored by other images |
| `User=media:media` in quadlet | Changes the process user but not the namespace UID mapping |
| `chmod o+w` on directory | Works as a workaround but is not semantically correct |

### Detecting linuxserver vs non-linuxserver images

linuxserver images can be identified by:
- Image source: `lscr.io/linuxserver/*`
- Presence of `/etc/s6-overlay` inside the container
- Support for `PUID`/`PGID` environment variables documented on their image page

### Implication for Phase 3 wizard

The installation wizard must:

1. Detect whether each image is a linuxserver image
2. For non-linuxserver images, run `podman unshare chown -R 1000:1000 <config_dir>` after directory creation and before first container start
3. Verify the container can write to its config directory after first start as part of validation
4. Explain to the user what is being done and why

---

## Stack management not available inside the arr-mcp container

**Issue:** [#12](https://github.com/ryanbrinn/arr-mcp/issues/12) | **Phase relevance:** Phase 1

The `stack_up`, `stack_down`, `stack_restart`, `stack_pull`, and `compose_validate` tools invoke `podman-compose` as a subprocess. When arr-mcp runs inside a container, the `podman` binary is not available, causing these tools to fail.

**Fix:** Host-side helper agent (see [ADR-0002](adr/0002-host-side-helper-agent.md)).

---

## Quadlets vs compose — use quadlets on rootless Podman

Both quadlets and a compose file were present for the same stack, leading to confusion about which was managing the containers. On rootless Podman with systemd lingering enabled:

- **Quadlets are the source of truth** — systemd manages container lifecycle directly
- **Compose files should be renamed to `.bak`** to prevent accidental use
- Verify containers are quadlet-managed: `podman inspect <name> --format "{{index .Config.Labels \"PODMAN_SYSTEMD_UNIT\"}}"`
- `Restart=on-failure` is the correct quadlet equivalent of compose's `restart: unless-stopped` — `Restart=always` will restart even after a manual `systemctl stop`
