# Approval-gated PR formatting repair

The formatting automation reports and repairs formatting in changed C++, CUDA
and Python source files. It is deterministic formatter automation, not an AI
code-repair system. Ordinary CI formatter checks remain authoritative.

## Supported formatters

- C++ and CUDA: pinned clang-format 22.1.8, using trusted default-branch
  `.clang-format` configuration.
- Python: pinned Ruff 0.17.5, using trusted default-branch `pyproject.toml`.

The allowlist is extension- and path-based. Documentation and arbitrary
repository files are not formatted by this bot.

## Report path

The `format-repair` workflow runs on pull-request open, synchronize, reopen
and ready-for-review events, plus manual dispatch. It checks out the default
branch with credentials disabled, fetches pull-request metadata and changed
source contents through the read-only GitHub API, then runs the pinned
formatter. It writes file names, formatter names and replacement line numbers
to the job summary and JSON artifact.

The separate `format-suggestions` workflow posts GitHub inline review
suggestions for formatter replacements that overlap lines changed in the PR.
Suggestions use GitHub's native `suggestion` block, so a reviewer can apply a
specific replacement from the review UI. The workflow uses only pinned
formatters and trusted default-branch code. It fetches PR source as data and
never checks out or executes PR code. It has `contents: read` and
`pull-requests: write` permissions; it cannot push, approve, change labels,
or merge. Suggestions are deterministic formatter output, not model-generated
opinions. Repeated runs on the same head avoid reposting an existing suggestion.

The suggestion workflow deliberately comments only on replacement hunks whose
entire original line range is part of the PR diff. Insertions, deletions,
context-only formatting changes, unsupported paths and suggestions longer
than GitHub's 100-line range are omitted rather than anchored inaccurately.
The summary report remains available for all detected formatting violations.

## Approval and repair

Before first use, create the repository label `format-fix:approved` in
Issues > Labels. The workflow does not create labels. An authorized maintainer
can apply it. The repair job checks the event actor against the maintainers
allowlist in `.github/format-repair.yml`. The label requests a
formatting-only commit. It does not approve the pull request.

Before formatting, the repair job requires that the PR is open, targets the
default branch, comes from this repository rather than a fork, still has the
exact head SHA from the label event, retains the approval label, and has a
complete changed-file listing.

The PR head is checked out as data only. The workflow runs only the pinned
formatters against allowlisted changed files, with trusted configuration from
the default branch. It does not run PR scripts, build commands, tests, or
actions. It stages only formatter-changed files, verifies the staged path set,
and re-fetches PR metadata before commit. The push is non-force, so a
concurrent branch advance is rejected rather than overwritten.

After a successful push, the workflow verifies that the PR head still equals
the formatter commit, then explicitly dispatches the normal `ci.yml` workflow
against that branch using `workflow_dispatch`. The acknowledgement records
the dispatch request and commit SHA; the CI run itself remains asynchronous
and its checks must finish normally. Only then does the workflow remove
`format-fix:approved` and post the acknowledgement with the commit SHA and
changed files. On dispatch failure, it leaves the label in place.

Fork pull requests are report-only for repair. No automated push to a fork is
attempted.

## Configuration and permissions

`.github/format-repair.yml` pins both formatter versions, the approval label,
authorized maintainer logins, supported extensions, and allowed paths. The
versions must match the workflow installation pins. Python formatting uses
Ruff's formatter only. Ruff lint autofixes are never run.

The report job has contents-read and pull-requests-read permissions. The
suggestion job has contents-read and pull-requests-write permissions. The
repair job has actions-write, contents-write, issues-write and
pull-requests-read permissions. No GPU, paid runner, hosted service, model
provider or API key is required.

GitHub exposes at most 3,000 changed files. Incomplete coverage fails closed
for reporting or repair.

## Tests

Run `python3 -m unittest discover -s format-repair/tests`. The offline tests
cover path allowlisting, actor authorization, fork and stale-head guards,
both formatter paths, incomplete coverage, commit path scope, workflow
permission policy, changed-line mapping and suggestion generation. A live
GitHub smoke test is still needed to verify review-comment delivery.
