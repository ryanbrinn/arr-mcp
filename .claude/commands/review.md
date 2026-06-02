# Code Review

Review the current branch implementation against its spec file. Returns a
severity-tagged issue list as a JSON object.

**Note:** Do NOT re-run validate or test here — those already ran. If you need
to know whether they passed, read their output rather than re-running them.

## Instructions

1. Run `git branch` to confirm the current branch
2. Run `git diff origin/main` to see all changes on this branch
3. Find the matching spec: look for `docs/specs/feature-{branch-slug}.md`
   - If no spec file exists, report that and review against the PR description instead
4. Read the spec's **Acceptance Criteria** and **Edge Cases** sections
5. Check the implementation against each criterion — focus on:
   - Correctness and adherence to spec
   - Error handling covers the defined edge cases
   - Tests exist for each acceptance criterion
   - No Phase 2/3 scope has crept in (see `CLAUDE.md` guardrails)
6. Return ONLY the JSON object below — no prose, no markdown, no explanation

## Severity definitions

- `skippable` — non-blocking, can ship as-is
- `tech_debt` — non-blocking, but will cause problems later
- `blocker` — must fix before merging; breaks behaviour or harms users

## Output Structure

```json
{
  "success": "boolean — true if no blockers, false if any blockers exist",
  "review_summary": "string — 2-4 sentences: what was built, does it match the spec",
  "review_issues": [
    {
      "issue_number": "number",
      "file_path": "string — path/to/file:line",
      "issue_description": "string",
      "issue_resolution": "string",
      "severity": "skippable | tech_debt | blocker"
    }
  ]
}
```
