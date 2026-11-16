# PR Scope Guard

Read-only check that compares the scope declared in a pull request title with
the files the pull request changes. It is advisory: findings never fail the
check, and it never comments, labels, approves, blocks or merges.

## Layout

```
pr-scope-guard/
  engine/scope_guard.py       title parsing, matching, API access, rendering
  schema/config.schema.json   configuration validation
  tests/                      offline engine and workflow policy tests
```

## How a run works

1. The title is parsed as `[scope] Description`.
2. The pull request and its changed files are read through the GitHub API. The
   fetched count is compared with the pull request's `changed_files` count; a
   mismatch marks the report incomplete.
3. Every changed file is matched against the path map. A file can match more
   than one scope.
4. The declared scope is compared with the matched files. Findings and
   candidate scopes are written to the step summary and a JSON artifact.
5. The run exits 0 even when findings exist. Exit 1 is reserved for a bad
   configuration, an API failure, or invalid input.

## Configuration

`.github/pr-scopes.json` holds the allowed names and descriptions.
`.github/pr-scope-guard.yml` maps each name to repository-relative globs. The
two scope sets must match exactly; CI fails if one side is missing or extra.
Paths may overlap: a tool workflow is also CI, and a tool guide is also docs.
`ignore` lists files excluded from analysis, such as `LICENSE`.

When adding a scope, add it to both files in the same pull request.

## Findings

| Code | Meaning |
| ---- | ------- |
| `coverage_incomplete` | The fetched file count does not match `changed_files`, so the report may be partial. |
| `title_missing_scope` | The title does not start with `[scope]`. |
| `title_malformed` | The title does not have a lowercase scope and a description. |
| `unknown_scope` | The scope is not in the registry. |
| `scope_matches_no_changed_files` | The declared scope matches no changed file. |
| `files_outside_scope` | Some changed files match other scopes. |
| `files_matching_no_scope` | Some changed files match no scope at all. |

GitHub's changed-files endpoint returns at most 3,000 files. The guard does not
treat a short list as a clean result: it adds `coverage_incomplete`, and the
summary says coverage is incomplete.

Candidate scopes are counts, not a verdict. A multi-area change can legitimately
span scopes; the report names the files so the author can explain the split.

## Trust boundary

The workflow runs on `pull_request_target`, checks out only the default branch,
and grants `contents: read` and `pull-requests: read`. It never checks out or
executes pull request code and references no secret. The engine, registry and
path map therefore come from the base branch.

## Tests

```bash
python3 -m unittest discover -s pr-scope-guard/tests
```

Deployment notes are in [`../docs/pr-scope-guard.md`](../docs/pr-scope-guard.md).
