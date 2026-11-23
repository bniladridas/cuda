# PR label and milestone review

The PR reviewer extends the existing Label Review system without changing the
issue-review path. It reads the live PR title, body, changed files and diff,
then asks the explicitly configured OpenRouter model (openrouter/free) to
recommend existing repository labels and one open milestone, or abstain.

## Enablement

1. Add the repository secret OPENROUTER_API_KEY.
2. Add repository variable PR_LABEL_REVIEW_ENABLED=true to enable proposals.
3. Add a protected GitHub Environment named pr-label-review and configure
   required reviewers.
4. Only when ready to allow approved writes, set
   PR_LABEL_REVIEW_APPLY=true. The apply job pauses at the protected
   Environment before it receives issues: write.

The provider and model are explicit in label-review/engine/pr_review.py.
There is no alternate provider or paid-model fallback. If the secret is
missing or the provider fails, the proposal job fails closed.

## Trust boundaries

- The workflow uses pull_request_target so it runs the base-branch workflow.
  It never checks out or executes code from the pull request.
- Proposal generation has read-only pull-requests and issues permissions.
  Commenting is a separate job. Metadata writes are a separate Environment-
  protected job with only issues: write.
- The model can select only labels returned by the live repository labels API
  and milestones returned by the live open-milestones API.
- Evidence must name a changed file and quote text present in the actual diff.
  Empty, oversized, unavailable or malformed diffs fail closed.
- The artifact binds the proposal to the PR title, body, base/head SHAs, file
  list, full diff, current labels and current milestone. The apply job fetches
  all of these again and aborts if any have changed.
- Applying only adds labels and optionally sets a milestone. Existing labels
  are preserved. The reviewer never removes labels, closes or merges a PR,
  assigns people, changes branches or publishes releases.

The proposal job is enabled only after the repository variable is set.
Existing issue review continues through label-review.yml unchanged.

## Local tests

Run the existing engine tests and the PR-specific tests with:

    python3 -m unittest discover -s label-review/tests

No CUDA toolkit or GPU is required. These tests do not claim GPU runtime
validation.
