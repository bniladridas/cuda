# Safe PR branch rebase

This is the first Git-operation slice of issue #79. It is not the autonomous
repair agent and is not wired to a GitHub workflow.

## Contract

The operation requires trusted PR metadata and explicit maintainer approval.
It refuses fork branches, the default branch, protected branches, dirty
worktrees, mismatched local branches, disabled rebase policy, and stale
remote SHAs.

It fetches the PR and base refs, rebases onto the base branch, then fetches
the PR branch again immediately before pushing. The push uses an exact
force-with-lease value for the originally approved SHA. A changed remote SHA
stops the run. A failed or conflicting rebase is aborted and requires human
resolution. There is no merge-commit fallback.

## Invocation

The caller must create a dedicated isolated worktree and a request JSON file
from trusted GitHub API metadata plus explicit maintainer approval.

    python3 rebase-agent/engine/rebase.py \
      --repo /path/to/dedicated-worktree \
      --request /path/to/trusted-request.json

Request fields: repository, head_repository, branch, base_branch,
default_branch, protected_branches, expected_remote_sha, expected_base_sha,
authorization, and rebase_enabled. Both SHAs must be the exact 40-character
PR head and base SHAs returned by GitHub immediately before the operation.

## Security boundary

- Never derive authorization from PR files, comments, commit messages, or model output.
- Keep GitHub write credentials out of any environment executing untrusted PR code.
- Derive repository identity, branch protection, default branch, expected SHA,
  policy, and authorization from trusted sources.
- A rejected lease is a hard failure, not a reason to retry with a newer SHA.
- The module does not resolve conflicts, approve reviews, merge PRs, or close issues.
- A merge-commit fallback requires separate explicit authorization and audit.
- Offline policy and command-sequence tests are included. End-to-end Git
  integration tests and workflow integration remain follow-up work.


## Separate merge-based integration mode

The merge helper is a separate operation, not a rebase fallback:

    python3 rebase-agent/engine/merge_agent.py \
      --repo /path/to/dedicated-worktree \
      --request /path/to/trusted-merge-request.json

Its request uses `expected_head_sha`, `expected_base_sha`,
`merge_authorization`, and `merge_enabled`. Merge authorization is
independent of rebase authorization. The helper refuses fork, default, and
protected branches; dirty worktrees; stale head/base SHAs; and ambiguous
conflicts. It creates a two-parent merge commit with the PR head first and
base second, then performs a normal non-force push. It never force-pushes.

The helper does not resolve conflicts or decide that a merge is preferable.
The caller must validate the merge result and inspect its complete diff before
the operation is authorized to update a PR branch. The helper itself is a
Git-operation primitive, not a GitHub workflow or the complete model-assisted
repair agent. End-to-end orchestration, trusted metadata acquisition, sandbox
isolation, validation-before-write enforcement, and post-update CI reporting
remain required before autonomous use.


## GitHub API tree inspection

The read-only inspector uses the GitHub REST Git Commits and Git Trees APIs.
For the base, PR head, and merge-base commits it resolves each commit's tree
SHA, fetches the complete recursive tree, and rejects truncated responses.
It compares leaf paths changed on each side of the merge base, reports
overlapping paths as diagnostics only, and checks the PR files API inventory
against the tree-derived head changes. Patchless files are explicitly listed.

Run it with a read-only token:

    GITHUB_TOKEN=... python3 rebase-agent/engine/tree_inspector.py \
      --repository owner/repo --pull-request 123 \
      --output conflict-inspection.json

The `conflict:inspect` label triggers the read-only
`.github/workflows/conflict-inspection.yml` workflow. It checks out only the
trusted base SHA, has read-only repository permissions, executes no PR code,
and uploads the JSON report as an artifact. It does not update a branch.

Tree overlap is not proof of a textual or semantic conflict. The report
distinguishes tree inventory from actual Git rebase/merge outcomes.


## Maintainer-dispatched repair workflow

The end-to-end caller is `.github/workflows/pr-repair-integration.yml`.
It is a manual workflow and is available for dispatch only after the workflow
has landed on the repository's default branch.

Configure these repository variables before dispatch:

- `REPAIR_MAINTAINERS`: JSON array of exact GitHub login names allowed to
  authorize branch updates, for example `["maintainer-a","maintainer-b"]`.
- `REPAIR_REBASE_ENABLED`: set to the literal string `true` only when rebase
  updates are permitted.
- `REPAIR_MERGE_ENABLED`: set to the literal string `true` only when
  merge-based updates are permitted.

Configure the existing `OPENROUTER_API_KEY` repository secret. The agent
uses only `openrouter/free`, requests provider data-collection denial, has a
bounded tool loop and token budget, and stops if tool calling is unavailable.
There is no paid fallback.

Dispatch requires the PR number, operation, exact current head SHA, exact
current base SHA, and this exact confirmation string:

    UPDATE <PR> <HEAD_SHA> <BASE_SHA> <OPERATION>

The authorization job verifies the dispatch actor against the allowlist,
re-reads the live PR through the GitHub API, rejects fork/draft/closed/merged
PRs, verifies both SHAs, checks that the head branch is not protected, and
checks the operation-specific policy. Rebase and merge approvals are distinct
because the operation is part of the confirmation string.

The workflow separates trust boundaries:

1. Snapshot job exports the PR source and complete diff without executing it.
2. Agent job checks out trusted workflow code, treats the PR snapshot as data,
   and uses only bounded read/search/diff/patch tools. It has the model secret
   but no GitHub write token and does not execute PR code.
3. Validation job applies the proposed patch and performs rebase or merge in an
   unprivileged runner with no model secret or write credential. It runs Python
   tests and a CPU-only CMake build/test. GPU validation remains unavailable
   unless a GPU runner is configured.
4. Final-review job re-reads the complete final diff and every changed text
   file. It has the model secret but does not execute repository code or write
   branches. Incomplete coverage, unavailable model routing, or critical/high
   findings blocks publication.
5. Publish job runs trusted workflow code only. It verifies the original PR
   head and base refs again, verifies the prepared Git bundle and commit tree,
   and updates only the approved PR branch. Rebase uses the exact
   `--force-with-lease`; merge uses a normal non-force push and checks the
   two-parent order.
6. The workflow polls checks on the updated head and uploads an audit artifact
   with the actor, operation, old/new SHAs, tree, model report, and check
   conclusions. Skipped GPU checks are not GPU validation.

The repair agent never executes shell commands requested by the model. Its
allowlisted tools are bounded file listing, complete diff chunks, changed-file
reads, literal text search, constrained unified-diff application, and final
structured review. Repository code is executed only in the isolated validation
job, without secrets or write credentials.

A failed or unavailable model call, incomplete file/diff coverage, failed
validation, stale branch/base SHA, conflict, or failed post-update checks stops
the run and produces no claim of success. A push can succeed before a later
post-update CI failure is discovered; in that case the audit artifact reports
the failure and a maintainer must decide whether to revert or repair. The
workflow never approves or merges the PR.

This workflow is an initial bounded implementation, not a guarantee of
semantic correctness. Model review is advisory. Deterministic tests, exact
SHA gates, independent human review, and repository branch protections remain
necessary. The first successful run should be on a low-risk CPU-only PR.
