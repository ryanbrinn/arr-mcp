# Run the smoke test suite (build -> install -> server start -> tests -> teardown).
# Usage: .\scripts\smoke.ps1 [extra pytest args]
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
uv run pytest tests/smoke/ -v -m smoke @args
