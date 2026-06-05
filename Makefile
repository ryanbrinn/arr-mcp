.PHONY: test-deploy test-stop test lint fmt typecheck

# Deploy a branch to the test instance on the server.
# Usage: make test-deploy BRANCH=feat/your-branch
test-deploy:
	@if [ -z "$(BRANCH)" ]; then echo "Usage: make test-deploy BRANCH=<branch>"; exit 1; fi
	bash scripts/test-deploy.sh BRANCH=$(BRANCH)

# Stop the test instance on the server.
test-stop:
	bash scripts/test-deploy.sh --stop

# Run the full test suite locally.
test:
	uv run pytest tests/ -v

# Ruff format + lint.
fmt:
	uv run ruff format .
	uv run ruff check . --fix

# Type checking.
typecheck:
	uv run pyright
