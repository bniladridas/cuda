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
approval labels, outstanding change requests, and PRs without an approval
from a reviewer other than the author.

The workflow inspects check runs and combined commit status before attempting
the merge. GitHub's merge API remains authoritative for branch protection,
required reviews, required status checks, and repository rulesets. If GitHub
rejects the squash merge, the workflow does not fall back to another method.

The approval label is removed only after GitHub confirms the squash merge.
The workflow then posts the approver, reviewed head SHA, and merge commit SHA.
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

1. Confirm CI is green and a non-author reviewer has approved it.
2. Apply `squash-merge:approved` as an authorized maintainer.
3. Confirm the PR is squash-merged, the label is removed, and the bot comment
   records the approver and merge SHA.
4. Repeat with a draft, fork, stale head, failing check, missing approval, and
   unauthorized label actor. Each must remain unmerged.
