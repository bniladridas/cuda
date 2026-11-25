# PR creation and description refresh

CUDA Actions can open a pull request from an existing branch and refresh its
description when new commits arrive. These workflows create or update PR
metadata only; they do not change the source branch, apply labels, approve, or
merge pull requests.

## Configuration

Both workflows require a GitHub App installed on this repository with:

- **Contents: read**
- **Pull requests: write**

Configure the following repository settings:

| Setting | Type | Purpose |
| --- | --- | --- |
| `CUDA_ACTIONS_APP_ID` | Variable | GitHub App ID |
| `CUDA_ACTIONS_PRIVATE_KEY` | Secret | GitHub App private key |
| `OPENROUTER_API_KEY` | Secret | Model access for title and description generation |
| `CUDA_REVIEW_MODEL` | Variable, optional | OpenRouter model identifier; defaults to `openrouter/free` |

The workflow creates a short-lived installation token with only the permissions
shown above. Do not put credentials in workflow inputs or branch content.

## Create a pull request

1. Push the commits to a branch in this repository.
2. Open Actions and select **PR Creation**.
3. Run the workflow from the default branch.
4. Supply the existing head branch, target branch (normally `main`), and
   whether the new pull request should be a draft.

The workflow compares the selected branches, rejects empty or oversized
comparisons and an existing open PR for the same head and base, then generates
a scoped title and description from commit messages and file patches. The title
must use a registered scope and an approved action verb. Model output must meet
the confidence threshold and pass validation before the PR is opened as
`cuda-actions[bot]`.

The workflow does not rebase, push to, or otherwise modify the source branch.
It does not claim that tests or GPU validation have run. CI reports those
results separately.

## Description refresh

The **PR Description** workflow runs on `synchronize` events for pull requests
targeting `main`. It only processes branches in this repository. It regenerates
the description from the current base-to-head comparison and preserves the
existing title and commit authorship.

The refresh checks that the pull request remains open and that its head SHA has
not changed during generation. If the head moves, the run stops without
updating the description; a later push can trigger another attempt.

Both workflows check out trusted default-branch code. In particular, the
`pull_request_target` refresh workflow must never check out or execute code
from the pull request head while the GitHub App token or OpenRouter key is
available.

## Smoke test

After configuring the App and settings:

1. Push a small documentation-only branch to this repository.
2. Run **PR Creation** from the default branch with that head branch and
   `main` as the base. Start with a draft if the branch is not ready for review.
3. Confirm the PR is created by `cuda-actions[bot]`, has a valid scoped title,
   and describes only changes present in the comparison.
4. Push another commit to the test PR.
5. Confirm **PR Description** refreshes the body while preserving the title.
6. Confirm the source branch and commit authorship are unchanged.

Do not use a fork branch for this smoke test. The refresh workflow intentionally
skips fork pull requests.

## Limits and failure handling

- The model input is limited to 120,000 characters of available file patches.
- The creator refuses duplicate open pull requests for the same head and base.
- Invalid or low-confidence model output fails closed; it does not create a PR.
- A branch update during generation aborts creation or refresh rather than
  using a stale comparison.
- Provider, GitHub API, or configuration failures stop the workflow. They do
  not authorize a fallback title or an unreviewed write.
