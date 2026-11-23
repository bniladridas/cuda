# CUDA Repository Steward

This package is a read-only coordination layer for issue tracking, repository
health, validation evidence, and release-readiness reporting.

## Run locally

The GitHub CLI adapter collects a snapshot from repository metadata, issues,
pull requests, checks, workflow runs, and retained PR evidence artifacts.
Authenticate the GitHub CLI for the target repository first:

```sh
gh auth status
PYTHONPATH=repository-steward python3 -m engine.github_snapshot \
  --repository OWNER/REPO --root . --output steward-snapshot.json
PYTHONPATH=repository-steward python3 -m engine.steward \
  steward-snapshot.json --output steward-report.json
python3 -m unittest discover -s repository-steward/tests
```

The report engine can also consume an existing JSON snapshot without network
access. The snapshot collector uses read-only GitHub API operations and does
not execute code from pull requests. Label Review and Issue Landing workflow
evidence is accepted only for the exact default-branch SHA observed during
snapshot collection. Pull-request review decisions come from GitHub's
`reviewDecision` field; unavailable GraphQL evidence is reported as `unknown`.

Repository Health checks relative Markdown links, JSON and GitHub Actions YAML
syntax, duplicate mapping keys, and local action references. It is read-only.
The snapshot collector includes workflow files and local action metadata needed
for these checks.

## Snapshot contract

- `repository`, timezone-aware `generated_at`, `head_sha`
- `issues[]`: number, title, body, state, labels, assignees, updated_at,
  optional linked_pr_numbers, dependency_numbers, acceptance_criteria and
  acceptance_criteria_status. Explicit checkboxes are preserved as complete or
  incomplete; plain bullets remain unverified.
- `pull_requests[]`: number, title, body, state, head_sha, draft, checks,
  review_decision, url, optional linked_issue_numbers, base_ref, base_sha,
  merged_at and merge_commit_sha. Issue tracking reports `open`, `merged`,
  `closed_unmerged` or `unknown` merge state without treating a closed PR as
  merged.
- `validations[]`: kind, state, head_sha, source, url, details and optional
  workflow-run/runner metadata. Device identity remains `not_reported` unless
  independently established.
- `files{}`: repository-relative paths mapped to text content
- optional `readiness_policy.required_kinds`, `required_docs`,
  `require_benchmark_evidence`, `require_version_consistency`, and
  `block_on_health_warnings`
- optional `version_evidence` with `declared_version` and
  `release_version`. Missing version evidence is reported as unavailable,
  never inferred from a tag or a project file alone.
- optional `integration_evidence` entries for `label_review` and
  `issue_landing`, each carrying state, observed head SHA, exact expected SHA,
  source, URL and details
- optional `pull_request_integrations[pr_number]` entries for
  `pr_confidence` and `pr_scope_guard`. Each entry carries workflow state,
  source, URL, details and the parsed JSON artifact under `evidence`. The
  collector downloads artifacts only from successful `pull_request_target`
  runs associated with that exact PR number and head SHA.

Issue Tracking reports closure readiness as a human-review candidate only
when every acceptance criterion is explicitly checked, all linked PRs are
verified merged, and dependencies are closed. Unchecked criteria and open PRs
block the candidate; missing merge evidence remains unknown. It never closes
an issue.

## Trust boundaries

The engine is read-only. It never applies labels, closes issues, approves or
merges PRs, changes branches, or publishes releases. It treats absent, skipped,
stale and unknown evidence as distinct states. GPU runtime success requires
explicit current-head evidence. Model integration is disabled by default and
cannot authorize actions.

Existing Label Review, Issue Landing, PR Confidence, PR Scope Guard,
Squash Merge and Rebase Agent remain separate engines. The report preserves
PR Confidence scores, categories, blockers and notes, plus PR Scope Guard
findings, as source evidence. Per-PR states distinguish current, stale,
missing, incomplete, pending, malformed and failed artifacts. These findings
remain advisory data: neither adapter can authorize approval or merge, and
the coordinator does not dispatch workflows or perform mutations.

## Benchmark integrity

The coordinator validates provenance fields added by `benchmarks/provenance.py`
and the device and measurement metadata emitted by the benchmark binary. A
valid record is not, by itself, permission to publish a performance claim.
Methodology remains documented in `docs/methodology.md`.

Release Readiness now combines current-head validation evidence with required
documentation presence, repository-health errors, benchmark provenance, and
explicit declared-versus-release version evidence. Health warnings are
reported but do not block by default. Missing benchmark or version evidence
remains unavailable and blocks readiness under the default policy. This module
only reports readiness; it never publishes a release.

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

The **Repository Steward Report** workflow runs daily or manually from
Actions. It uses the workflow's read-only GitHub token and uploads both the
source snapshot and JSON report as a 14-day artifact. Download the artifact to
inspect the exact inputs and generated output for a run.

The workflow does not post comments, apply labels, close issues, modify
branches, merge pull requests, or publish releases. GPU evidence remains
pending, skipped, or unknown unless a matching current-head validation result
establishes otherwise.

## Issue activity and ownership

Issue tracking reports owner presence and activity age when the snapshot includes
a timezone-aware `generated_at` timestamp. Open issues without assignees are
flagged as unowned. Open issues with no recorded activity for at least 30 days
are flagged as stale by default. The threshold is configurable through
`analyze_tracking(..., stale_after_days=N)`. Activity age is calculated only
when both `generated_at` and `updated_at` are timezone-aware timestamps. Missing
or invalid timestamps remain unknown rather than being treated as stale.

Closure readiness is a human-review candidate, not a close command. It requires
all criteria to be explicitly checked, dependencies to be closed, and every
linked pull request to be verified merged. Ordinary bullets remain unverified.
Missing evidence blocks the candidate. No issue state is changed.

## Documentation drift checks

Repository Health scans Markdown guidance for explicit
`.github/workflows/*.yml` and `.yaml` references. A reference whose workflow
file is no longer present is reported as a warning with its source path and
line. This check is intentionally narrow: it detects stale explicit workflow
paths, not whether every workflow has complete prose documentation.

Model summaries record the configured model identifier, endpoint host, provider
request ID when available, SHA-256 digests of the input report and output
summary, and generation time. Credentials and the full endpoint URL are not
recorded. This provenance documents the recommendation but does not make model
output verification evidence or grant it authority over repository actions.
