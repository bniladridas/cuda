# CUDA Repository Steward

This package is the first read-only coordination layer for issue tracking,
repository health, validation evidence, and release-readiness reporting.

## Run

The initial interface consumes a JSON snapshot. This keeps the engine
offline-testable and avoids requiring GitHub credentials for local reports.

```sh
python3 -m repository-steward.engine.steward snapshot.json --output steward-report.json
```

Because hyphens are not valid Python package identifiers, run the module by
adding the package directory to `PYTHONPATH`:

```sh
PYTHONPATH=repository-steward python3 -m engine.steward snapshot.json
python3 -m unittest discover -s repository-steward/tests
```

Snapshot fields:
- `repository`, `head_sha`
- `issues[]`: number, title, body, state, labels, assignees, updated_at,
  optional linked_pr_numbers, dependency_numbers and acceptance_criteria
- `pull_requests[]`: number, title, body, state, head_sha, draft, checks,
  review_decision, url, optional linked_issue_numbers
- `validations[]`: kind, state, head_sha, source, url and details
- `files{}`: repository-relative paths mapped to text content
- optional `readiness_policy.required_kinds`

## Trust boundaries

The engine is read-only. It never applies labels, closes issues, approves or
merges PRs, changes branches, or publishes releases. It treats absent, skipped,
stale and unknown evidence as distinct states. GPU runtime success requires
explicit current-head evidence. Model integration is disabled by default and
cannot authorize actions.

Existing Label Review, Issue Landing, PR Confidence, PR Scope Guard,
Squash Merge and Rebase Agent remain separate engines. This coordinator records
their integration boundaries; it does not replace their policy or workflow
execution.
