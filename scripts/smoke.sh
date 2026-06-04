#!/usr/bin/env bash
# Run the smoke test suite (build → install → server start → tests → teardown).
# Usage: bash scripts/smoke.sh [extra pytest args]
set -euo pipefail

cd "$(dirname "$0")/.."
uv run pytest tests/smoke/ -v -m smoke "$@"
