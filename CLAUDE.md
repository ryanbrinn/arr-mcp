# Development Guidelines

This document contains critical information about working with this codebase. Follow these guidelines precisely.

## Core Development Rules

1. Package Management
   - ONLY use uv, NEVER pip
   - Installation: `uv add package`
   - Running tools: `uv run tool`
   - Upgrading: `uv add --dev package --upgrade-package package`
   - FORBIDDEN: `uv pip install`, `@latest` syntax

2. Code Quality
   - Type hints required for all code
   - Public APIs must have docstrings
   - Functions must be focused and small
   - Follow existing patterns exactly
   - Line length: 88 chars maximum

3. Testing Requirements
   - Framework: `uv run pytest`
   - Async testing: use anyio, not asyncio
   - Coverage: test edge cases and errors
   - New features require tests
   - Bug fixes require regression tests

4. Code Style
    - PEP 8 naming (snake_case for functions/variables)
    - Class names in PascalCase
    - Constants in UPPER_SNAKE_CASE
    - Document with docstrings
    - Use f-strings for formatting

- For commits fixing bugs or adding features based on user reports add:
  ```bash
  git commit --trailer "Reported-by:<name>"
  ```
  Where `<name>` is the name of the user.

- For commits related to a Github issue, add
  ```bash
  git commit --trailer "Github-Issue:#<number>"
  ```
- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Session Discipline

- **One issue per session.** Once the issue being worked on is identified, treat that issue as the session boundary.
- **Rename the session.** Acknowledge the issue at the start with the key and a short description (e.g. "Working on **#42 — fix install script**").
- **Flag scope creep.** If work is heading somewhere that warrants its own issue, say so explicitly before proceeding: "This feels out of scope for #N — should I open a new issue for it?"

## Roadmap and Gantt Discipline

- **Keep the Gantt in sync.** `docs/roadmap.md` contains a Mermaid Gantt chart that tracks phase items. It must stay accurate:
  - **When opening a new GitHub issue** for a planned feature or task: if it corresponds to a Gantt item, confirm the item exists (add it if not).
  - **When closing / merging a PR** that completes a Gantt item: mark it `:done` in the same PR.
  - **When changing the roadmap** — adding, removing, or re-scoping a phase item, or adding a new planning item of significance — update the Gantt in the same commit.
  - Never let the Gantt fall more than one PR behind reality.

## Branch and PR Workflow

- **One branch per issue.** Every GitHub issue gets its own branch. Name it after the issue: `fix/issue-23-short-description`, `feat/issue-17-quadlet-conversion`, etc.
- **Never commit directly to main.** All changes go through a branch and PR.
- **Check before pushing.** Before pushing to an existing branch, verify its PR has not already been merged:
  ```bash
  gh pr list --state merged --repo ryanbrinn/arr-mcp
  ```
  If the PR is merged, create a new branch instead.
- **Post-merge commits are fixes.** Any commit made to a branch after its PR was merged must use `fix:` or `bugfix:` prefix in the commit message.

## Development Philosophy

- **Simplicity**: Write simple, straightforward code
- **Readability**: Make code easy to understand
- **Performance**: Consider performance without sacrificing readability
- **Maintainability**: Write code that's easy to update
- **Testability**: Ensure code is testable
- **Reusability**: Create reusable components and functions
- **Less Code = Less Debt**: Minimize code footprint

## Coding Best Practices

- **Early Returns**: Use to avoid nested conditions
- **Descriptive Names**: Use clear variable/function names (prefix handlers with "handle")
- **Constants Over Functions**: Use constants where possible
- **DRY Code**: Don't repeat yourself
- **Functional Style**: Prefer functional, immutable approaches when not verbose
- **Minimal Changes**: Only modify code related to the task at hand
- **Function Ordering**: Define composing functions before their components
- **TODO Comments**: Mark issues in existing code with "TODO:" prefix
- **Simplicity**: Prioritize simplicity and readability over clever solutions
- **Build Iteratively** Start with minimal functionality and verify it works before adding complexity
- **Run Tests**: Test your code frequently with realistic inputs and validate outputs
- **Build Test Environments**: Create testing environments for components that are difficult to validate directly
- **Functional Code**: Use functional and stateless approaches where they improve clarity
- **Clean logic**: Keep core logic clean and push implementation details to the edges
- **File Organsiation**: Balance file organization with simplicity - use an appropriate number of files for the project scale

## Project Phase

**Current phase: Phase 3 — Installation Wizard**

See `docs/roadmap.md` for the full public roadmap. This section governs how sessions should operate.

### Phase definitions

| Phase | Goal |
|---|---|
| **Phase 1 — MVP** | Solid, secure, well-tested foundation. All tools working. Dashboard. Documentation. |
| **Phase 2 — Media Intelligence** | Plex/-arr API integrations, watched content cleanup, log monitoring, multi-user support. |
| **Phase 3 — Installation Wizard** | Guided setup for non-technical users on a fresh machine. |
| **Phase 4 — Advanced Features** | Opt-in, config-driven ways for advanced users to widen the default safety scope (e.g. tiered infrastructure access) without weakening it for everyone else. |

### Guardrails — what NOT to build yet

**In Phase 1, do not:**
- Integrate with Plex, Sonarr, Radarr, or SABnzbd APIs
- Build user authentication or watchlist features
- Start installation wizard work
- Build Phase 2/3/4 features even if they seem "quick"

**In Phase 2, do not:**
- Start installation wizard work
- Implement Jellyfin support (future state — design for it, don't build it)
- Build Phase 4 features (e.g. tiered infrastructure access) — the default media-stack scope must stay solid first

**In Phase 3, do not:**
- Build Phase 4 features — advanced/opt-in scope changes come after the wizard is stable

### End-of-phase verification

Before declaring a phase complete and beginning the next, verify:

1. Walk through the phase verification checklist in `docs/roadmap.md` item by item
2. All CI checks pass — ruff, mypy, pytest — with no phase-related skips
3. All open `phase-N` security issues are resolved
4. ADRs are up to date and reflect decisions actually made
5. Ask: *"Has the project goal shifted?"* — if yes, update roadmap and CLAUDE.md before proceeding
6. Ask: *"Is there technical debt to capture?"* — if yes, create issues before moving on

### Updating phase status

When a phase is complete, update the **Current phase** line above and commit to main with message:
```
chore: advance to Phase N — <phase name>
```

## System Architecture

[fill in here]

## Core Components

- `config.py`: Configuration management
- `daemon.py`: Main daemon
[etc... fill in here]

## Pre-PR Checklist

Before opening a pull request, run these commands in order:

1. `/validate` — ruff format + lint + pyright. Fix all errors before continuing.
2. `/review` — checks implementation against the spec in `docs/specs/`. Fix any blockers.

Both must pass clean before the PR is opened. The full pytest suite is not run
locally before pushing — CI runs it on push.

## Pull Requests

- Create a detailed message of what changed. Focus on the high level description of
  the problem it tries to solve, and how it is solved. Don't go into the specifics of the
  code unless it adds clarity.

- NEVER ever mention a `co-authored-by` or similar aspects. In particular, never
  mention the tool used to create the commit message or PR.

## Python Tools

## Code Formatting

1. Ruff
   - Format: `uv run ruff format .`
   - Check: `uv run ruff check .`
   - Fix: `uv run ruff check . --fix`
   - Critical issues:
     - Line length (88 chars)
     - Import sorting (I001)
     - Unused imports
   - Line wrapping:
     - Strings: use parentheses
     - Function calls: multi-line with proper indent
     - Imports: split into multiple lines

2. Type Checking
   - Tool: `uv run pyright`
   - Requirements:
     - Explicit None checks for Optional
     - Type narrowing for strings
     - Version warnings can be ignored if checks pass

3. Pre-commit
   - Config: `.pre-commit-config.yaml`
   - Runs: on git commit
   - Tools: Prettier (YAML/JSON), Ruff (Python)
   - Ruff updates:
     - Check PyPI versions
     - Update config rev
     - Commit config first

## Error Resolution

1. CI Failures
   - Fix order:
     1. Formatting
     2. Type errors
     3. Linting
   - Type errors:
     - Get full line context
     - Check Optional types
     - Add type narrowing
     - Verify function signatures

2. Common Issues
   - Line length:
     - Break strings with parentheses
     - Multi-line function calls
     - Split imports
   - Types:
     - Add None checks
     - Narrow string types
     - Match existing patterns

3. Best Practices
   - Check git status before commits
   - Run formatters before type checks
   - Keep changes minimal
   - Follow existing patterns
   - Document public APIs
   - Test thoroughly