# Python Test Suite

Run the arr-mcp test suite with pytest. Returns results as a JSON array.

**Note:** This command runs tests only. For linting and type-checking, use `/validate`.

## Instructions

### Run tests

```bash
uv run pytest tests/ -v
```

- Capture pass/fail per test and any error output
- Return ONLY the JSON array below — no prose, no markdown, no explanation
- Sort failed tests to the top
- Omit the `error` field for passing tests

## Output Structure

```json
[
  {
    "test_name": "string",
    "passed": "boolean",
    "execution_command": "string",
    "test_purpose": "string",
    "error": "optional string"
  }
]
```

## Example — failure

```json
[
  {
    "test_name": "test_filesystem.py::test_delete_outside_root",
    "passed": false,
    "execution_command": "uv run pytest tests/test_filesystem.py::test_delete_outside_root -v",
    "test_purpose": "Verify deletion is rejected when path is outside allowed roots",
    "error": "AssertionError: expected 403, got 200"
  }
]
```
