# Maintainer-approved squash merge

The squash-merge workflow is separate from formatting repair. Applying
`format-fix:approved` never authorizes a merge. Only an authorized maintainer
applying `squash-merge:approved` requests a squash-merge attempt.

## Labels

| Label | Color | Action |
| --- | --- | --- |
| `format-fix:approved` | `#8250DF` purple | Request formatting repair only |
| `squash-merge:approved` | `#1F883D` green | Request a guarded squash merge |

Create the labels in **Settings → Labels** with the exact names and colors.
The workflow does not create or recolor repository labels.

## Merge policy

The trusted policy lives in `.github/squash-merge.json` on the default branch.
Only listed maintainers can trigger the operation. The workflow rejects bots,
fork PRs, draft or closed PRs, stale heads, non-clean merge states, missing
approval labels, and outstanding change requests. A separate GitHub review
approval is not required because applying the label is the maintainer's explicit
authorization.

The trusted policy explicitly lists required check-run names in
`.github/squash-merge.json`. Every configured check must be present and have
conclusion `success`; pending, skipped, neutral, failed, and missing required
checks block the merge. Required commit-status contexts can be listed separately.
The combined commit status must always be successful, including when its status
list is empty. Optional checks may be skipped when their policy permits it.

The current policy requires `cpu`, `python`, `PR Confidence`,
`PR Scope Guard`, `analyze (c-cpp)`, and `CodeQL`. Update this trusted list
when repository CI policy changes. GitHub's merge API remains authoritative for
branch protection, required reviews, required status checks, and repository
rulesets. The workflow does not claim to replace those controls. If GitHub
rejects the squash merge, the workflow does not fall back to another method.

The approval label is removed only after GitHub confirms the squash merge.
The workflow then posts the approver, reviewed head SHA, independent reviews observed (informational only), required checks and status contexts inspected, and merge commit SHA.
A stale-head rejection preserves the label and explains that the maintainer
must remove it, review the updated head, and reapply it for fresh approval. A failed GitHub
merge request preserves the label and writes an actionable failure summary.
It does not close issues or publish releases.

## Permissions and operation

The workflow uses the repository's `GITHUB_TOKEN` with narrowly scoped
contents, pull-request, and issue permissions. It checks out only trusted
default-branch policy and code. It does not execute PR code.

A successful label event is the explicit human authorization. The workflow
re-fetches PR state and pins the merge request to the exact approved head SHA.
Concurrent or stale requests fail closed.

## Smoke test

Use a disposable same-repository PR:

1. Confirm required CI is green. No GitHub review approval is required.
2. Apply `squash-merge:approved` as an authorized maintainer.
3. Confirm the PR is squash-merged, the label is removed, and the bot comment
   records the approver and merge SHA.
4. Repeat with a draft, fork, stale head, outstanding change request, failing
   check, missing approval label, and unauthorized label actor. Each must remain unmerged.
