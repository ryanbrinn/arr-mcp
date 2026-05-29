# Contributing to arr-mcp

Thanks for your interest! Here's how to get started.

## Development setup

```bash
git clone https://github.com/ryanbrinn/arr-mcp
cd arr-mcp
pip install -e ".[dev]"
cp .env.example .env   # edit as needed
```

## Running locally

```bash
arr-mcp
# or
python -m arr_mcp.server
```

The server starts on port 8081. Test with:

```bash
curl -H "Authorization: Bearer changeme" http://localhost:8081/health
```

## Code style

- Formatter/linter: `ruff check src/ && ruff format src/`
- Type checker: `mypy src/arr_mcp/`
- Tests: `pytest`

All three must pass before opening a PR.

## Adding a tool

1. Add your function inside the appropriate `register_*` function in `src/arr_mcp/tools/`.
2. Decorate it with `@server.tool()`.
3. Add a test in `tests/`.
4. Update the tool list in `README.md`.

## Pull requests

- One logical change per PR.
- Include a short description of what and why.
- Keep commits clean (`feat:`, `fix:`, `docs:`, `chore:` prefixes).
