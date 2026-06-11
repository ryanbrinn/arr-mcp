---
name: code-quality
description: Python code quality rules for arr-mcp: uv package management, Ruff formatting and linting, pyright type checking, and error resolution ladder. Activate when touching CI, fixing formatting or type errors, adding dependencies, or reviewing code style.
compatibility: Requires Python 3.12+, uv
allowed-tools: Bash(uv:*) Bash(ruff:*)
---

# Code Quality

Run `/validate` to execute the full quality gate (ruff format + ruff check + pyright). Fix all violations before committing.

## Package management

Use `uv` exclusively — never `pip`, `pip install`, or `uv pip install`.

| Action | Command |
|---|---|
| Add dependency | `uv add package` |
| Add dev dependency | `uv add --dev package` |
| Upgrade a package | `uv add --dev package --upgrade-package package` |
| Run a tool | `uv run tool` |

Forbidden: `uv pip install`, `@latest` syntax.

## Code standards

- Type hints required for all code
- Public APIs must have docstrings
- Functions must be focused and small
- Follow existing patterns in the codebase
- Line length: 88 characters maximum
- PEP 8 naming: `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Use f-strings for string formatting

## Ruff

```bash
uv run ruff format .          # auto-format
uv run ruff format --check .  # check without modifying
uv run ruff check .           # lint
uv run ruff check . --fix     # lint + auto-fix
```

Critical rules: line length (88), import sorting (I001), unused imports.

Line wrapping: use parentheses for strings; multi-line with proper indent for function calls; split imports across multiple lines.

## Pyright

```bash
uv run pyright
```

Requirements: explicit None checks for Optional; type narrowing for strings. Version warnings can be ignored if all checks pass.

## Error resolution order

When CI fails, fix in this order:

1. Formatting (`ruff format`)
2. Type errors (`pyright`)
3. Linting (`ruff check`)

For type errors: get full line context, check Optional types, add type narrowing, verify function signatures.

For line length violations: break strings with parentheses, use multi-line function calls, split imports.

## Pre-commit

Config: `.pre-commit-config.yaml`. Runs on `git commit`. Tools: Prettier (YAML/JSON), Ruff (Python).

To update Ruff version: check PyPI for latest, update `rev` in config, commit config change first.
