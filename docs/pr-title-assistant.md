# PR title assistant

The title assistant uses an OpenAI API model to select the best matching scope
from `.github/pr-scopes.json` and propose a concise action-oriented title.

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

Add an `OPENAI_API_KEY` Actions secret. The model defaults to `gpt-5-mini`;
set the repository Actions variable `OPENAI_MODEL` to use another model
available to the API key.

The workflow needs `contents: read` and `pull-requests: write`. It uses
`pull_request_target`, so the workflow and script are loaded from the trusted
default branch and PR content is treated only as untrusted model input.
