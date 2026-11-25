# PR scope check

The PR scope check is a read-only, advisory check that compares the scope in a
pull request title with the files the pull request changes. It does not replace
review, required checks or branch protection.

## What runs

`pull_request_target` on opened, edited, synchronize, reopened and
ready_for_review, plus a manual dispatch with a pull request number. Each run:

1. validates the pull request number;
2. checks out the default branch with `persist-credentials: false`;
3. installs PyYAML and jsonschema;
4. runs `pr-scope-guard/engine/scope_guard.py`;
5. appends a report to the job summary and uploads the JSON artifact.

## Permissions

`contents: read` and `pull-requests: read`. The job uses the automatic
`github.token` and no secret. It has no issue, label, comment, status, approval
or merge permission.

## Trust boundary

The workflow file, engine, registry and path map come from the default branch.
Pull request code is never checked out or executed. A pull request cannot change
its own check before it merges.

## Reading the report

The step summary lists the declared scope, fetched and expected file counts,
findings, files outside the scope, files that match no scope, and candidate
scopes. The JSON artifact holds the same evidence plus head and base SHAs and a
`coverage` object with `expected_files`, `fetched_files` and `complete`. When the
counts differ, the report includes `coverage_incomplete` and says it is not a
clean scope result. Findings are advisory: the job stays green unless the engine
or configuration fails.

## Path map

`.github/pr-scope-guard.yml` maps every scope in `.github/pr-scopes.json` to
repository-relative globs. Overlaps are intentional. A tool workflow matches
both `ci` and its tool scope; a tool guide matches both `docs` and its tool
scope. `ignore` excludes files such as `LICENSE`.

Add a scope to both files in the same pull request. A missing or extra mapping
fails configuration validation, so drift is caught before the report runs.

## Running by hand

Use Actions, **PR Scope**, Run workflow, and enter a pull request number.
The report appears in the run summary and as the `pr-scope-guard-evidence`
artifact.

## Limitations

- The check is advisory and does not block a pull request.
- GitHub's changed-files endpoint returns at most 3,000 files. The guard marks
  the report incomplete when the fetched count differs from `changed_files`; it
  does not analyse the remaining files.
- Matching uses paths only. It cannot tell whether a file is relevant to the
  change.
- Renames are judged by the current path; the previous path is recorded in the
  artifact.
- A pull request that legitimately spans scopes will report outside files. That
  is expected; explain the split in the pull request.
- The registry and path map are read from the default branch, so changes to
  them take effect only after merge.
- The workflow starts only after its file reaches the default branch.

## Tests

`pr-scope-guard/tests/test_scope_guard.py` covers parsing, glob matching,
configuration, findings, coverage, escaping, artifacts and fixtures.
`pr-scope-guard/tests/test_workflow_policy.py` checks the read-only trigger,
permissions, base checkout, absence of secrets and the validated engine call.

CI runs both with `python3 -m unittest discover -s pr-scope-guard/tests`.

## Turning it off

Disable **PR Scope** in the Actions UI or remove
`.github/workflows/pr-scope-guard.yml`. Nothing else depends on it.
