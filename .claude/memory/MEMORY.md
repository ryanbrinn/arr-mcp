# arr-mcp agent memory

## Development workflow

- [One branch per issue](.claude/skills/development-workflow/SKILL.md) — name: `fix/issue-N-short-desc` or `feat/issue-N-short-desc`; never commit to main.
- [Session discipline](.claude/skills/development-workflow/SKILL.md) — one issue per session; flag scope creep before proceeding.
- [Commit conventions](.claude/skills/development-workflow/SKILL.md) — use `--trailer` for reported-by and github-issue; never mention co-authored-by or AI tooling.
- [PR format](.claude/skills/development-workflow/SKILL.md) — high-level problem + solution; no implementation line-by-line; no AI attribution.
- [Pre-PR checklist](.claude/skills/development-workflow/SKILL.md) — `/validate` then `/review`; both must pass before opening a PR.

## Code quality

- [uv only](.claude/skills/code-quality/SKILL.md) — `uv add`, `uv run`; never `pip install` or `uv pip install`.
- [Ruff + pyright are blocking gates](.claude/skills/code-quality/SKILL.md) — run `/validate` to check; fix all violations before committing.
- [Type hints required](.claude/skills/code-quality/SKILL.md) — all code; explicit None checks; no bare Optional.
- [Line length 88](.claude/skills/code-quality/SKILL.md) — break with parentheses; multi-line function calls.

## Testing

- [pytest + anyio](.claude/skills/testing/SKILL.md) — `uv run pytest`; use anyio for async tests, not asyncio.
- [New features require tests](.claude/skills/testing/SKILL.md) — bug fixes require regression tests.
- [Run `/test` frequently](.claude/skills/testing/SKILL.md) — validate with realistic inputs before claiming completion.

## Phase management

- [Current phase: Phase 3 — Installation Wizard](.claude/skills/phase-management/SKILL.md) — do not build Phase 4 features.
- [Gantt stays in sync](.claude/skills/phase-management/SKILL.md) — update `docs/roadmap.md` when opening issues, merging PRs, or changing scope.
- [End-of-phase verification](.claude/skills/phase-management/SKILL.md) — walk the checklist before declaring a phase complete.
- [Phase guardrails](.claude/skills/phase-management/references/phase-definitions.md) — see phase definitions for what NOT to build in each phase.
