# PR title check

The title assistant uses the repository's configured OpenRouter model to select
the best matching scope from `.github/pr-scopes.json` and propose a concise
action-oriented title.

## Behavior

- Runs for opened, edited, synchronized, reopened, and ready-for-review PRs.
- Reads the PR metadata and changed-file patches through the GitHub API.
- Uses only the trusted base-branch registry and script. It does not check out
  or execute pull request code.
- Updates the title only when the model selects a registered scope, confidence
  is at least 0.85, and deterministic title validation passes.
- If no registered scope fits, it reports a proposed new scope in the Actions
  run summary. It never adds a scope automatically.
- A title that already matches the recommendation is left unchanged.

## Configuration

Add the `OPENROUTER_API_KEY` Actions secret. The assistant uses the same
`CUDA_REVIEW_MODEL` repository Actions variable as CUDA Review and CUDA title
suggestions. If it is unset, the model defaults to `openrouter/free`.

Requests use OpenRouter's `provider.data_collection=deny` setting.

The workflow needs `contents: read` and `pull-requests: write`. It uses
`pull_request_target`, so the workflow and script are loaded from the trusted
base branch and PR content is treated only as untrusted model input.
