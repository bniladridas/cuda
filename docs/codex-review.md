# Label-triggered Codex review

Apply `codex:review` to a same-repository pull request to ask the connected Codex GitHub integration for a review.

## Flow

1. An allowlisted maintainer applies `codex:review`.
2. The `codex-review` workflow validates the actor and repository.
3. It posts `@codex review` as a PR conversation comment.
4. It removes the request label after the comment is posted. A hidden marker prevents duplicate requests for the same PR head.

The workflow checks out only the trusted default branch. It does not check out or execute PR code, use an API key, modify files, approve reviews, or merge.

## Important integration limitation

The workflow can reliably post the documented `@codex review` command. Whether Codex starts a review from a comment authored by `github-actions[bot]` depends on the connected Codex GitHub integration. OpenAI documents requesting a review with `@codex review`, but does not document bot-authored comments as a supported trigger.

Therefore, the first live test is required:

1. Open a disposable same-repository PR.
2. Apply `codex:review` as an allowlisted maintainer.
3. Confirm the workflow posts the command and consumes the label.
4. Confirm Codex actually starts and reports a review.

If Codex does not respond to the workflow comment, use a human-authored `@codex review` comment. Do not treat the workflow's successful comment post as proof that Codex completed a review.

## Setup

- Create the repository label `codex:review` (suggested color: `#1F6FEB`).
- Keep `.github/codex-review.json` synchronized with the maintainers authorized to request reviews.
- Ensure the Codex GitHub integration is installed and Code Review is enabled for this repository.

## Boundaries

- This label requests a review only. It is not a review approval or merge authorization.
- It is separate from `format-fix:approved` and `squash-merge:approved`.
- Fork PRs and bot/unauthorized label actors are rejected.
- The label is consumed only after the request comment exists.
