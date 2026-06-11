---
name: phase-management
description: Project phase definitions, guardrails, Gantt sync rules, and end-of-phase verification for arr-mcp. Activate when triaging new issues, working on roadmap items, transitioning between phases, or determining whether a feature is in scope for the current phase.
---

# Phase Management

Current phase: **Phase 3 — Installation Wizard**

See [phase definitions and guardrails](references/phase-definitions.md) for the full phase table and what NOT to build in each phase.

## Gantt discipline

`docs/roadmap.md` contains a Mermaid Gantt chart that must stay accurate:

- **Opening a new GitHub issue** for a planned feature: confirm the Gantt item exists (add it if not).
- **Closing / merging a PR** that completes a Gantt item: mark it `:done` in the same PR.
- **Changing the roadmap** — adding, removing, or re-scoping items: update the Gantt in the same commit.

Never let the Gantt fall more than one PR behind reality.

## End-of-phase verification

Before declaring a phase complete and beginning the next:

1. Walk through the phase verification checklist in `docs/roadmap.md` item by item
2. All CI checks pass — ruff, mypy, pytest — with no phase-related skips
3. All open `phase-N` security issues are resolved
4. ADRs are up to date and reflect decisions actually made
5. Ask: *"Has the project goal shifted?"* — if yes, update roadmap and CLAUDE.md before proceeding
6. Ask: *"Is there technical debt to capture?"* — if yes, create issues before moving on

## Updating phase status

When a phase is complete, update the **Current phase** line in `CLAUDE.md` and in this file, then commit to main:

```
chore: advance to Phase N — <phase name>
```
