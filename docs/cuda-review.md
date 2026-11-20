# CUDA Review

CUDA Review is a repository-owned, model-assisted pull request reviewer. It is
independent of the connected Codex GitHub integration.

## Request a review

A maintainer can comment on an open, same-repository pull request:

```text
@cuda review
```

The workflow reviews the current head once. A later commit can be reviewed by
posting the command again. Duplicate requests for the same head are ignored.

## PR title suggestions

A maintainer can request a title suggestion with `@cuda suggest-title`. The bot reads the PR diff and the title guidance in `CONTRIBUTING.md`, then posts one suggestion as a comment. It never edits the PR title.

Reply with `@cuda decline-title` to decline the suggestion for the current PR head. The decline is recorded against that head, so the same suggestion is not repeated. A new commit allows a fresh suggestion. A maintainer can apply an accepted title manually.

Title suggestions use the configured OpenRouter model and require `OPENROUTER_API_KEY`. Suggestions are advisory and must be checked by a maintainer.

## Configuration

- Add authorized GitHub usernames to `.github/cuda-review.json`.
- Set the `OPENROUTER_API_KEY` repository secret.
- The default model is `openrouter/free`. Set the `CUDA_REVIEW_MODEL`
  repository Actions variable to select another OpenRouter model that reports
  zero cost. The existing bounded agent intentionally stops if the provider
  reports a non-zero cost.
- The review uses the existing OpenRouter privacy setting
  `provider.data_collection=deny`.

## Review behavior

The model receives the complete bounded diff and a read-only snapshot of every
changed text file. It focuses on concrete correctness and regression risks,
including CUDA memory safety, races, synchronization, launch configuration,
error handling, test coverage, and build compatibility.

Findings are posted as inline comments only when their line is part of the
added diff. Other findings are retained in the review summary with their
reported file and line. A clean review produces an explicit no-findings result.

## Safety boundaries

- Only usernames in the maintainer allowlist can invoke the workflow.
- Fork pull requests are not eligible.
- PR content is treated as untrusted data and is never executed.
- The model job has read-only repository permissions and no PR write token.
- A separate publish job rechecks the exact head SHA before posting a
  `COMMENT` review.
- The bot never approves, requests changes, pushes commits, applies labels,
  or merges.
- Diff size, model iterations, tool calls, and runtime are bounded by the
  existing review engine.
- Model output is advisory. It does not replace CI or human review.

The first live test should use a small CPU-only pull request. CUDA GPU
validation remains separate and cannot be inferred from a model review.
