---
name: development-workflow
description: Branch and PR workflow, session discipline, commit trailer conventions, and PR message format for arr-mcp. Activate when starting a new branch, preparing a PR, writing commit messages, or scoping multi-session work.
compatibility: Requires git, gh CLI
allowed-tools: Bash(git:*) Bash(gh:*)
---

# Development Workflow

## Branch workflow

Every GitHub issue gets its own branch. Name it after the issue:

- `fix/issue-N-short-description`
- `feat/issue-N-short-description`

Never commit directly to main. All changes go through a branch and PR.

Before pushing to an existing branch, verify its PR hasn't already been merged:

```bash
gh pr list --state merged --repo ryanbrinn/arr-mcp
```

If the PR is merged, create a new branch instead. Any commit made to a branch after its PR was merged must use `fix:` or `bugfix:` prefix.

## Session discipline

One issue per session. Once the issue is identified, treat it as the session boundary.

Acknowledge the issue at the start: "Working on **#N — short description**."

If work heads somewhere that warrants its own issue, say so explicitly before proceeding: "This feels out of scope for #N — should I open a new issue for it?"

## Commit conventions

For commits fixing bugs or adding features from user reports:

```bash
git commit --trailer "Reported-by:<name>"
```

For commits related to a GitHub issue:

```bash
git commit --trailer "Github-Issue:#<number>"
```

Never mention `co-authored-by`, the AI tool used, or any similar attribution.

## Pre-PR checklist

Before opening a pull request, run in order:

1. `/validate` — ruff format + lint + pyright. Fix all violations before continuing.
2. `/review` — checks implementation against `docs/specs/`. Fix any blockers.

Both must return `success: true` before the PR is opened. The full pytest suite runs on CI after push — do not run it locally before pushing.

## Pull request format

Write a detailed message focused on:

- High-level description of the problem being solved
- How it is solved

Do not recap implementation line-by-line unless it adds clarity. Never mention co-authored-by or AI tooling.
