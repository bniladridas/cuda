# Approval-gated PR formatting repair

The formatting repair workflow reports and repairs formatting in changed C++,
CUDA and Python source files. It is deterministic formatter automation, not an
AI code-repair system. The ordinary CI formatter checks remain authoritative.

## Supported formatters

- C++ and CUDA: pinned clang-format 22.1.8, using the trusted default-branch
  `.clang-format` configuration.
- Python: pinned Ruff 0.17.5, using the trusted default-branch
  `pyproject.toml` configuration.

The allowlist is extension- and path-based. C++ and CUDA files are limited to
the existing source, include, kernel, test and benchmark directories. Python
files are limited to repository tooling and test directories configured in
`.github/format-repair.yml`. Documentation and arbitrary repository files are
not formatted by this bot.

## Report path

The workflow runs on pull-request open, synchronize, reopen and
ready-for-review events, plus manual dispatch. The report job checks out the
default branch with credentials disabled, fetches pull-request metadata and
changed source contents through the read-only GitHub API, then runs the pinned
formatter for each eligible changed file. It writes file names, formatter
names and replacement line numbers to the job summary and JSON artifact.

The report job never checks out or executes pull-request code. It has only
contents-read and pull-requests-read permissions. It cannot push, comment,
approve, or change labels.

## Approval and repair

Before first use, create the repository label `format-fix:approved` in the
Issues > Labels settings. The workflow does not create labels. An authorized
maintainer can then apply it. The repair job checks the event actor against
the maintainers allowlist in `.github/format-repair.yml`. The label requests
a formatting-only commit. It does not approve the pull request.

Before formatting, the job requires that the PR is open, targets the default
branch, comes from this repository rather than a fork, still has the exact head
SHA from the label event, retains the approval label, and has a complete
changed-file listing.

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
changed files. On dispatch failure, it does not push partial changes and
leaves the label in place. A duplicate label event either sees the label
missing or finds no formatting diff.

Fork pull requests are report-only. No automated push to a fork is attempted.

## Configuration and permissions

`.github/format-repair.yml` pins both formatter versions, the approval label,
authorized maintainer logins, supported extensions, and allowed paths. The
versions must match the workflow installation pins. Python formatting uses
Ruff's formatter only. Ruff lint autofixes are never run.

The report job has contents: read and pull-requests: read. The repair job has
actions: write, contents: write, pull-requests: read and issues: write only.
The Actions permission is used only to dispatch the normal CI workflow after
a successful formatter push. It does not automatically approve, merge, close
issues, or modify unrelated labels. No GPU, paid runner, hosted service, or
model provider is required.

GitHub exposes at most 3,000 changed files. Incomplete coverage fails closed
for repair.

## Manual smoke test

Use disposable same-repository PRs with C++ and Python formatting violations.
Verify that the report lists paths and line numbers without changing the
branch; an unauthorized actor cannot push; an authorized maintainer's label
creates only formatter changes; the acknowledgement contains the formatter
versions, commit SHA and changed files; and fork PRs remain report-only. Also
test stale-head and duplicate label events, formatter failures, and clean runs.

## Tests

Run `python3 -m unittest discover -s format-repair/tests`. The offline tests
cover path allowlisting, actor authorization, fork and stale-head guards,
both formatter paths, incomplete coverage, commit path scope, and workflow
permission/trigger policy. A live GitHub smoke test is still needed to verify
event delivery and push behavior.
