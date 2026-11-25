# Safe PR branch rebase

This is the Git-operation layer for issue #79. It is separate from the
model-assisted repair agent and never approves or merges a pull request.

The repository workflow `.github/workflows/rebase-approved.yml` invokes a
real Git rebase when a maintainer adds `rebase:approved`. It checks the actor
against the trusted maintainer list, verifies the exact PR head SHA, captures
the live base-branch SHA, rejects forks and protected branches, and pushes
only with an exact `--force-with-lease`. The captured base SHA is checked again
before the push, so a stale cached `pull_request.base.sha` does not silently
pin the operation to an old base. It does not use GitHub's update-branch API, which
creates a merge commit rather than rebasing. A conflict aborts the operation,
reports the conflicting paths, and requires human resolution. The workflow
requires the `PR_REBASE_TOKEN` secret with contents-write access.

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
- Offline policy and command-sequence tests are included. Real-Git integration
  tests cover clean rebases, conflicting rebases, abort/recovery, and stale refs.

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
remain required before autonomous merge-based integration.

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

The read-only `merge-conflict-check` workflow (`.github/workflows/conflict-inspection.yml`) remains
available through manual `workflow_dispatch`. It checks out only the trusted
base SHA, has read-only repository permissions, executes no PR code, and
uploads the JSON report as an artifact. It does not update a branch.

Tree overlap is not proof of a textual or semantic conflict. The report
distinguishes tree inventory from actual Git rebase/merge outcomes.

## Maintainer-dispatched repair workflow

The end-to-end caller is the `pr-repair` workflow (`.github/workflows/pr-repair.yml`).
It is a manual workflow and is available for dispatch only after the workflow
has landed on the repository's default branch.

Configure these repository variables before dispatch:

- `REPAIR_MAINTAINERS`: JSON array of exact GitHub login names allowed to
  authorize branch updates, for example `["maintainer-a","maintainer-b"]`.
- `REPAIR_REBASE_ENABLED`: set to the literal string `true` only when rebase
  updates are permitted.
- `REPAIR_MERGE_ENABLED`: set to the literal string `true` only when
  merge-based updates are permitted.
- `REPAIR_WRITE_ENVIRONMENT_CONFIRMED`: set to `true` only after an admin
  creates the `pr-repair-write` environment and configures required reviewers.
  The workflow fails closed if this confirmation is absent. Enable the
  environment's prevent-self-review option where available.

Configure a protected GitHub environment named `pr-repair-write` with required
reviewers. The initial dispatch authorization is not sufficient by itself:
the `publish` job waits for this second human approval after the patch has been
validated and the final diff review artifact is available. Review the
`prepared-integration`, `repair-proposal`, and `final-review` artifacts
before approving the environment deployment. GitHub records the environment
reviewer and decision separately from the workflow audit artifact.

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
2. Agent job checks out trusted workflow code, runs the read-only Git Trees API
   inspector against live PR metadata, and verifies the inspected head/base
   SHAs match the approval. It then treats the PR snapshot as data and uses only
   bounded read/search/diff/patch tools. It has read-only GitHub API access and
   the model secret, but no GitHub write permission and does not execute PR code.
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

## Review-comment feedback proposals

The `review-feedback` workflow (`.github/workflows/review-feedback.yml`) runs on submitted PR reviews and
new inline review comments for same-repository, non-draft PRs. It snapshots the
exact event head/base SHAs without executing PR code, extracts the reviewer
text and inline diff context, verifies the live Git Trees API state, and asks
the bounded repair agent for a patch proposal. The result is uploaded as a
`review-feedback-proposal` artifact. It does not push, approve, or merge.

For a controlled branch update, a maintainer can dispatch
`pr-repair.yml` with the exact SHAs and copy the review request
into its optional `review_feedback` input. The model treats that text as
untrusted context and must still inspect the full diff and every changed text
file. The final protected-environment approval remains mandatory.

## Conflict resolution

The `conflict:resolve` label starts the `conflict-resolution` workflow
(`.github/workflows/ai-conflict-resolution.yml`). It is separate from
`rebase:approved`: the latter performs a normal Git rebase and aborts on
conflict, while the former explicitly authorizes a bounded model-assisted
attempt to resolve textual conflicts during a rebase.

The workflow:

1. Accepts only a maintainer in the trusted `.github/squash-merge.json`
   allowlist and an open, non-draft, same-repository PR targeting `main`.
2. Rejects protected PR branches and pins the exact PR head and live base
   commit before doing any work.
3. Checks out trusted default-branch workflow code. PR files are fetched as
   Git data and are never executed in the model job.
4. Attempts a real Git rebase. On textual conflicts, the resolver sends only
   bounded base/ours/theirs file contents to `openrouter/free`. It accepts
   complete replacement text for exactly the conflicted paths, rejects
   path traversal, symlinks, binary files, oversized inputs, incomplete
   model output, ambiguous responses, and more than three resolution rounds.
5. Aborts on any unresolved conflict or failed rebase. It does not run PR
   build scripts or tests while the model secret is present.
6. Uploads the resulting Git bundle, complete patch, changed-path summary,
   and model report. The `publish` job waits for approval in the protected
   `pr-repair-write` environment, rechecks the exact live PR head and base,
   and pushes only with an exact force-with-lease.

Configure the existing `OPENROUTER_API_KEY` secret and
`PR_REBASE_TOKEN` secret. The latter needs contents write access. Configure
the `pr-repair-write` environment with required reviewers and prevent
self-review where available. The actor who applies `conflict:resolve` must
be listed in `.github/squash-merge.json`.

This is a guarded conflict-resolution proposal, not proof of semantic
correctness. Review the uploaded patch and report before approving the
environment deployment. After publication, the PR must pass its normal CI
and human code review. The workflow never approves or merges the PR.

