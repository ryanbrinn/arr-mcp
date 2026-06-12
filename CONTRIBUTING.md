# Contributing to arr-mcp

The full contributor guide — dev container setup, running tests, linting,
manual end-to-end testing against a throwaway stack, and commit guidelines —
lives at [docs/contributing.md](docs/contributing.md) (also published on the
[documentation site](https://ryanbrinn.github.io/arr-mcp/contributing/)).

## Quick start

```bash
git clone https://github.com/ryanbrinn/arr-mcp
cd arr-mcp
uv sync
cp .env.example .env   # edit as needed
uv run arr-mcp
```

Before opening a pull request:

```bash
make fmt        # ruff format + ruff check --fix
make typecheck  # pyright
make test       # pytest
```

See [docs/contributing.md](docs/contributing.md) for details on the dev
container, the test-stack workflow, and commit/PR conventions.
