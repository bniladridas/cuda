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
- optional `integration_evidence` entries for `label_review` and `issue_landing`, each carrying state, head SHA, source, URL and details

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

## Benchmark integrity

The coordinator validates provenance fields added by `benchmarks/provenance.py`
and the device and measurement metadata emitted by the benchmark binary. A
valid record is not, by itself, permission to publish a performance claim.
Methodology remains documented in `docs/methodology.md`.

## Optional model summary

Model summaries are disabled unless `--model-summary` is explicitly passed and
all three environment variables are configured:

- `STEWARD_MODEL_ENDPOINT`: HTTPS OpenAI-compatible chat-completions endpoint.
- `STEWARD_MODEL_NAME`: exact configured model identifier.
- `STEWARD_MODEL_API_KEY`: provider credential.

The model receives the generated report and returns advisory prose only. Its
output is not evidence and cannot change readiness, checks, permissions, labels,
branches, issues, PRs or releases.
## Scheduled report

After the workflow is merged, run **Repository Steward Report** manually from
Actions or let its daily schedule run. It uses a read-only GitHub token and
uploads the source snapshot and JSON report as a 14-day artifact. It does not
post comments, apply labels, close issues, modify branches, merge pull
requests, or publish releases.
