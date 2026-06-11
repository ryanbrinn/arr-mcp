---
name: testing
description: Test suite requirements and workflow for arr-mcp. Activate when writing new tests, fixing failing tests, adding features that need test coverage, or reviewing test quality.
compatibility: Requires Python 3.12+, uv
allowed-tools: Bash(uv:*) Bash(pytest:*)
---

# Testing

Run `/test` to execute the full test suite. Address all failures before marking work complete.

## Framework and conventions

- Framework: `uv run pytest`
- Async tests: use `anyio`, not `asyncio`
- Run tests frequently with realistic inputs — validate outputs, not just that code runs

## Coverage requirements

- New features require tests
- Bug fixes require regression tests
- Test edge cases and error paths, not just the happy path

## Running tests

```bash
uv run pytest tests/ -v
```

For a single test file or test:

```bash
uv run pytest tests/test_file.py::test_name -v
```

## Test environment

Build testing environments for components that are difficult to validate directly. The `test-stack/` directory contains a local container stack for integration testing.

## Before claiming completion

1. Run `/test` and confirm all tests pass
2. Confirm new behavior is covered by at least one test
3. Confirm failure paths are covered — not just success paths
