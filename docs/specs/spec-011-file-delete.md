# Spec: file_delete tool

| | |
|---|---|
| **Issue** | [#11](https://github.com/ryanbrinn/arr-mcp/issues/11) |
| **Phase** | 1 — MVP |
| **Status** | Ready for implementation |
| **Depends on** | Issue #10 ✅ (root-owned path exclusion) |

## Problem

The filesystem toolset has `file_read` and `file_write` but no `file_delete`. Users must drop to a shell to remove files (e.g. stale config files, orphaned logs), which defeats the purpose of managing the server through arr-mcp.

## Goal

Add a `file_delete(path, confirm)` MCP tool to `src/arr_mcp/tools/filesystem.py` that deletes a single file safely, constrained by the same path and ownership rules already in place.

## Tool specification

### Signature

```python
async def file_delete(path: str, confirm: bool = False) -> list[TextContent]:
    """Delete a file. Requires confirm=True to prevent accidental deletion."""
```

### Behaviour

| Condition | Response |
|---|---|
| `confirm=False` (default) | Return an error message: `"Pass confirm=True to delete {path}."` — do not delete |
| Path outside allowed roots | Raise `PermissionError` via `_check_path()` (existing behaviour) |
| File is root-owned | Raise `PermissionError` via `is_owned_by_current_user()` check |
| Path does not exist | Return an error message: `"File not found: {path}"` |
| Path is a directory | Return an error message: `"Path is a directory — use a more specific tool."` |
| Success | Delete file, return `"Deleted: {path}"` |

### Security rules

- Call `_check_path(path, settings)` first — restricts to `stacks_dir`, `media_dir`, `/var/log`
- Call `is_owned_by_current_user(p)` after path check — reject files owned by root or another user
- Never delete directories — `Path.is_dir()` check before unlink
- No recursive deletion — single file only

### Implementation notes

- Use `Path.unlink()` for the delete operation
- Follow the existing pattern in `filesystem.py` exactly — same import style, same `TextContent` return
- Place the function after `file_write` in the file

## Tests required

File: `tests/tools/test_filesystem.py`

| Test | Description |
|---|---|
| `test_file_delete_success` | Creates a temp file in an allowed path, deletes it with `confirm=True`, verifies it is gone |
| `test_file_delete_requires_confirm` | Calls without `confirm=True`, asserts file is untouched and response contains guidance |
| `test_file_delete_outside_allowed_root` | Path outside allowed roots → `PermissionError` |
| `test_file_delete_not_found` | Non-existent path → error message, no exception |
| `test_file_delete_directory_rejected` | Directory path → error message, directory untouched |
| `test_file_delete_root_owned_rejected` | Root-owned file → `PermissionError` (regression guard for the ownership check) |

## Out of scope

- Recursive / directory deletion — a separate tool if ever needed
- Soft delete / trash bin — not in Phase 1
- Bulk deletion — not in Phase 1
