# Issue landing

Issue landing separates evidence that code reached the default branch from the
human decision that an issue is complete. It never merges pull requests and
never treats a merged PR or a closing keyword as sufficient proof that all
acceptance criteria were met.

## Triggers

| Trigger | Report behavior | Close behavior |
| --- | --- | --- |
| Merged pull request | Finds issues explicitly cross-referenced in the PR timeline and posts a report for each | Never closes issues |
| Manual dispatch with an open issue number | Reports explicitly cross-referenced PRs and acceptance criteria | Can close only after the protected environment approval |

The workflow does not scan the backlog or guess links from branch names, titles,
commit subjects, or similar text. An issue with no explicit linked PR receives
a report that says so.

## Report evidence

For each linked PR, the report records its number, URL, state, draft status,
head SHA, base branch and SHA, merge commit SHA, and whether that merge commit
is reachable from the repository's current default branch. A PR is reported as
landed only when GitHub says it merged, a merge commit SHA is present, and the
compare API confirms that commit is an ancestor of the current default branch.

Issue comments are read alongside the body. Their identifiers and content hashes
are included in the report revision, and comments with implementation or
validation language are surfaced as linked excerpts for human inspection.
Acceptance criteria are extracted from Markdown headings named
`Acceptance criteria` in the body and comments. Every criterion is marked
`human review required`.
A checked checkbox is not proof, and the workflow does not use an LLM to
interpret implementation behavior. Criteria that cannot be extracted are
called out for manual review.

The report contains a SHA-256 digest over the issue title/body digest, linked PR
state and SHAs, criteria, and default-branch head. The digest deliberately
excludes the report timestamp so the same evidence has a stable revision.

## Approval and close safety

Report generation is read-only. Posting the report is a separate job with only
`issues: write`. Closing is a third job, enabled only when the repository
variable `ISSUE_LANDING_CLOSE_ENABLED=true`.

Before enabling close:

1. Create a GitHub Environment named `issue-landing-close`.
2. Configure at least one required reviewer for that environment.
3. Verify the reviewer rule is active.
4. Set `ISSUE_LANDING_CLOSE_ENABLED=true`.

The close job waits for approval on that environment. It then checks that the
environment still has a required-reviewer rule, validates the downloaded
report digest, re-fetches the issue and all linked PR evidence, and recomputes
the report digest. It aborts unless the issue is still open and the evidence is
identical, including the default-branch head. Any change requires a fresh
report and a new approval. The issue is closed only after these checks pass.

If the variable is unset or false, manual dispatch only produces and posts the
report. If the environment is missing or has no required reviewers, the close
command fails closed.

## Manual use

Actions > `issue-landing` > Run workflow, enter an open issue number, then
inspect the posted report. If close is enabled, approve or reject the waiting
`issue-landing-close` job after reviewing the exact report for that run.

The engine can also be tested offline:

```bash
python3 -m unittest discover -s issue-landing/tests
```

## Limits

- GitHub timeline cross-reference events are the source of linked-PR discovery.
  Unlinked or ambiguous work is not inferred.
- Default-branch reachability is checked against the head observed during
  report generation. Any subsequent default-branch movement invalidates the
  approval, even when the merge commit itself remains reachable.
- A successful close approval is a human attestation that the listed criteria
  have been reviewed. The workflow does not claim semantic verification.
- Pull-request-merged events can report an issue that GitHub has already
  auto-closed through a closing keyword. Manual close dispatch accepts only an
  open issue.
