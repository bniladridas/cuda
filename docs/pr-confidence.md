# PR Confidence

`PR Confidence` is a GitHub Actions check that scores the evidence available
for a pull request from 0 to 5. It publishes the score in the Actions job
summary, so it appears in the pull request's Checks UI without a conversation
comment. The check is read-only: it does not post comments, labels, statuses,
approvals or merges.

The score measures evidence coverage. It is not a probability that the pull
request is correct, safe or ready to merge, and it never replaces the checks it
reads.

## Check contract

- Stable check name: `PR Confidence`. The numeric score is in the summary, not
  in the name.
- Job: `.github/workflows/pr-confidence.yml`.
- Recompute triggers: `pull_request` opened, synchronize, reopened,
  ready_for_review, converted_to_draft and edited; `pull_request_review`
  submitted, edited and dismissed; manual `workflow_dispatch` with a pull
  request number.
- Each run waits up to 600 seconds for the configured critical and security
  checks to complete, polling every 15 seconds. This avoids publishing a pending
  result that no later event would refresh.
- Exit codes: `0` no hard blockers, `1` one or more hard blockers, `2` evidence
  collection or configuration failure. A low score alone does not fail.

## Rubric v1

Each category is worth one point when the stated evidence is present. The score
is the number of categories that pass, from 0 to 5.

| Category | One point when | Not one point when |
| -------- | -------------- | ------------------ |
| Automated validation | Every configured critical check has a completed `success` for the head SHA | A failure or timeout is `blocked`; a running check is `pending`; skipped, cancelled, neutral, stale or missing checks are `missing` |
| Relevant tests and regression coverage | At least one changed file matches a configured test pattern | Docs-only changes are `not applicable`; code without a test-file change is `missing`; unavailable or truncated file data is `unassessed` |
| Review feedback | The review decision is `APPROVED` and there are no unresolved threads | Changes requested is `blocked` by default; unresolved threads, no approval or review data that is unavailable or truncated is not a pass |
| Change scope and implementation evidence | The description is at least 40 characters, the diff is at most 30 files and at most 1500 changed lines | Any threshold missed is `missing`; unavailable or truncated file data is `unassessed` |
| Security and failure-handling evidence | Configured security checks pass, and a changed security-sensitive path is accompanied by a test-file change | A security check failure, pending check or missing check is not a pass; a sensitive path without a test change is `missing`; unavailable data is `unassessed` |

Statuses are deliberate:

- `pass`: evidence is present and positive.
- `missing`: evidence is absent or does not support the category. Missing test
  files are not proof that tests are inadequate.
- `pending`: checks have not completed.
- `blocked`: a condition configured as a hard blocker is present.
- `not applicable`: the category cannot apply, such as tests for a docs-only
  diff. It does not earn a point.
- `unassessed`: the evidence could not be read reliably, for example because an
  API list was truncated. It does not earn a point.

## Hard blockers

Hard blockers are reported separately from the score and decide the check
conclusion. A score of 5 can still carry a blocker.

| Blocker | Default | Condition |
| ------- | ------- | --------- |
| Failed critical check | yes | A configured critical check concludes `failure`, `timed_out`, `action_required` or `startup_failure` |
| Changes requested | yes | The latest review decision is `CHANGES_REQUESTED` |
| Merge conflict | yes | GitHub reports the pull request as not mergeable |
| Draft | no | The pull request is a draft |
| Unresolved review threads | no | One or more review threads are unresolved |
| Security check failure | no | A configured security check does not pass |
| Head moved during collection | always | The event head differs from the API head, so the result is stale |

Skipped, cancelled, neutral, stale and missing checks are incomplete evidence,
not failures. They lose the category point and are not hard blockers by default.
A check that is still running is `pending`, not a failure.

## Evidence sources

The engine reads only repository and GitHub metadata:

- pull request title, body, draft state, mergeability, file count, additions and
  deletions;
- changed files from the REST pull request files endpoint, up to 100;
- check runs for the head SHA from the REST check-runs endpoint, up to 100;
- `reviewDecision`, unresolved `reviewThreads` and thread URLs from GraphQL, up
  to 100 threads.

When a list is truncated, the affected category is `unassessed` rather than
guessed. No external model is used, and no pull request code is executed.

Checks are matched by exact name. The current names are:

- critical: `cpu`, `CodeQL`, `analyze (c-cpp)`;
- security: `GitGuardian Security Checks`,
  `Socket Security: Pull Request Alerts`.

The `gpu` check is not critical because GPU CI is disabled until a self-hosted
device is registered. Add it to the configuration when it becomes reliably
available.

## Trust model and fork safety

The workflow checks out the repository's default branch and runs the engine and
rubric from there. A pull request cannot change the code or configuration used
to score itself.

The token is limited to `contents: read`, `pull-requests: read` and
`checks: read`. The workflow uses no repository secrets and does not pass pull
request code or untrusted event fields into a shell without validation. Pull
number and head SHA are passed through environment variables, checked against
numeric and commit SHA patterns, and quoted. `persist-credentials` is off. A
pull request from a fork receives the same read-only view; nothing is written to
the repository or the pull request.

## Configuration

`.github/pr-confidence.yml` holds the versioned rubric inputs:

- `version`: currently `1`.
- `critical_checks`: non-empty exact check names required for automated
  validation.
- `security_checks`: non-empty exact check names for the security category. The
  critical and security lists must not overlap.
- `hard_blockers`: booleans for the configurable blockers in the table above.
  Missing keys use the defaults.
- `scope`: `max_files`, `max_changed_lines` and `min_body_chars`.
- `test_patterns`: repository-relative globs for test files. `**` spans
  directories and `*` does not.
- `security_sensitive_paths`: repository-relative globs whose changes need
  accompanying test-file changes.

The engine rejects unknown keys, duplicate check names, overlapping lists,
non-boolean blockers, invalid limits and path patterns that are absolute, use
backslashes or contain `..`. Invalid configuration exits 2 and fails the check
rather than silently scoring with defaults.

A change to the configuration or engine takes effect only after it merges to the
default branch, because that is the checked-out source.

## Local use

The tests are offline. They replace the GitHub command with fixtures and need
only Python 3.12 and PyYAML.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install pyyaml==6.0.2
python -m unittest discover -s pr-confidence/tests
```

To score a pull request locally, `gh` must be authenticated with read access to
the repository:

```bash
python pr-confidence/engine/confidence.py \
  --repo OWNER/NAME \
  --pr 123 \
  --head-sha <head-sha> \
  --config .github/pr-confidence.yml
```

Add `--wait` to poll the configured checks, `--summary <file>` to append the
Markdown summary to a file, or `--evidence-out <file>` to save the collected
evidence. A saved evidence file can be rescored without network access:

```bash
python pr-confidence/engine/confidence.py \
  --evidence evidence.json \
  --config .github/pr-confidence.yml
```

## Requiring the check

In the repository settings, open Branches, edit the rule for `main`, enable
"Require status checks to pass before merging", and add `PR Confidence` alongside
the checks it summarizes, such as `cpu`, `CodeQL` and `analyze (c-cpp)`.

The name is stable because it is the job name. Requiring it makes hard blockers
and collection failures block a merge. It does not make the score a merge
criterion: a score of 5 with no blocker passes, and a score below 5 without a
blocker still passes. Keep the underlying checks required in their own right.

## Limits

- The score is evidence coverage, not correctness, security or merge readiness.
- Test presence and diff size are heuristics. They do not measure test quality.
- API lists are read up to 100 items and marked `unassessed` when truncated.
- The run waits for checks that are configured at the time it starts. A check
  rerun after `PR Confidence` has already finished does not emit a pull request
  event, so re-run the `pr-confidence` workflow manually with the pull request
  number.
- Resolving a review thread has no supported GitHub Actions event. The result
  refreshes on the next pull request or review event, or by manual dispatch.
- Pull request titles, bodies and file names are untrusted text. They appear in
  the job summary as plain evidence; GitHub sanitizes the rendered Markdown.
