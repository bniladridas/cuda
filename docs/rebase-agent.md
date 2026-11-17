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
default_branch, protected_branches, expected_remote_sha, authorization,
and rebase_enabled. The SHA must be the exact 40-character PR head SHA
returned by GitHub immediately before the operation.

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
