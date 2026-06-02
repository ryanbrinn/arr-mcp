# Python Code Validation

Run the full quality gate for arr-mcp: formatting, linting, and type-checking.
Returns violations as a JSON array.

**Note:** This command runs static analysis only. For running tests, use `/test`.

## Instructions

Execute each step in order. Collect all violations across all steps before returning.

### 1. Format check

```bash
uv run ruff format --check .
```

If this fails, run the auto-fix and note which files were changed:

```bash
uv run ruff format .
```

### 2. Lint check

```bash
uv run ruff check .
```

Auto-fix where possible:

```bash
uv run ruff check . --fix
```

### 3. Type check

```bash
uv run pyright
```

### 4. Parse and return results

- Parse output from all three tools
- Categorize by severity: type errors and unfixable lint errors → `error`; style/formatting → `warning`
- Return ONLY the JSON array below — no prose, no markdown, no explanation
- Return `[]` if there are no violations

## Output Structure

```json
[
  {
    "rule": "string",
    "file": "string",
    "line": "number | null",
    "column": "number | null",
    "severity": "error | warning",
    "message": "string",
    "fix_suggestion": "string | null"
  }
]
```
