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

The report contains a SHA-256 digest over the issue title/body digest, relevant
issue comments, linked PR state and SHAs, criteria, and default-branch head.
The workflow excludes its own generated report comments from this digest so
posting the report does not invalidate the approval that follows. The digest deliberately
excludes the report timestamp so the same evidence has a stable revision.

## Approval and close safety

Report generation is read-only. Posting the report is a separate job with only
`issues: write`. Closing is a third job, disabled unless the repository
variable `ISSUE_LANDING_CLOSE_ENABLED=true`.

The approval is bound to the exact report revision:

1. Dispatch the workflow with an open issue number and leave
   `approved-report-digest` empty. The workflow posts the report and does not
   close the issue.
2. Review the report, including the issue comments, linked PR state, merge
   commit reachability and every acceptance criterion.
3. Dispatch the workflow again for the same issue and paste the exact
   `report digest` value into `approved-report-digest`.
4. The close job checks that the supplied digest matches the report generated
   in that run, re-fetches the issue and linked PRs, recomputes the report
   digest, and aborts if the issue, comments, PR state or default-branch head
   changed. A fresh report and digest are then required.

The digest input is mandatory for closure and acts as the explicit human
approval for one issue and one report revision. The close job also targets the
`issue-landing-close` GitHub Environment. Configure at least one required
reviewer there to add a second, independent approval before the job can run.
Without environment protection, the exact-digest dispatch remains the required
approval; the workflow does not claim that the Environment is protected unless
you configure it in repository settings.

If the variable is unset or false, manual dispatch only produces and posts the
report. The issue is never closed by the merged-PR event.

## Manual use

From the default branch, open Actions > `issue-landing` > Run workflow and enter an open issue number. Leave the digest input empty to report only. To authorize closure, run it again with the exact digest from the posted report. If the Environment has required reviewers, approve or reject the waiting `issue-landing-close` job.

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
