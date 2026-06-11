# arr-mcp

@.claude/memory/MEMORY.md

## Quick rules

- Package management: `uv` only — never `pip`. See `code-quality` skill.
- All code must pass Ruff and pyright. Run `/validate` before any commit.
- One branch per issue. Never commit directly to main.
- Current phase: **Phase 3 — Installation Wizard**.

## Before broad work

Load the relevant skill from `.claude/skills/` before implementation, refactoring, review, or debugging:

- Starting a branch, PR, or multi-session work → `development-workflow`
- Code quality, formatting, or CI failures → `code-quality`
- Phase transitions, roadmap, or issue triage → `phase-management`
- Writing or reviewing tests → `testing`
