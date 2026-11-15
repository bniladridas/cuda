# label-review

A reusable issue label review engine for GitHub Actions. It reads an issue,
proposes labels, and applies nothing until a reviewer approves the run on a
protected environment.

The first consumer is this repository. The engine and workflow live here, and
another repository can call the workflow with a small caller file and its own
configuration.

## Layout

```
label-review/
  engine/review.py            proposal and verification logic
  schema/config.schema.json   configuration contract
  tests/test_review.py        unit and offline end to end tests
.github/
  label-review.yml            this repository's configuration
  workflows/label-review.yml  reusable workflow, exposed through workflow_call
  workflows/label-review-caller.yml  the caller for this repository
```

## How a review runs

1. A caller passes an issue number, a mode and its configuration path to the
   reusable workflow.
2. The proposal job checks out the caller and the engine, validates the
   configuration against the caller's labels, reads the issue, and writes a
   comment draft and a proposal artifact. It has read-only issue access.
3. A comment job posts the draft. It does not run the engine.
4. The apply job waits for approval on the `label-review` environment. After
   approval it re-reads the issue and the artifact, rejects anything that no
   longer holds, and only then writes labels.

The job that reads the issue text and model output cannot change labels. The
only `gh issue edit` call is in the apply job.

## Configuration

The schema is [`schema/config.schema.json`](schema/config.schema.json). Unknown
keys are rejected, and a label may have exactly one role.

```yaml
version: 1

components:
  kernels:
    paths:
      - src/**
      - include/**

model_proposed:
  needs-gpu: The change cannot be completed or verified without compiling or running CUDA code on an NVIDIA GPU.

human_only:
  - cpu-verified
```

| Key | Meaning |
| --- | ------- |
| `components` | Label to path patterns. A path can match more than one label |
| `model_proposed` | Labels the model may propose, each with the criterion it answers |
| `human_only` | Labels backed by evidence the workflow cannot see. Never proposed, applied or removed |

Every configured label must already exist in the target repository. A missing
label fails the run before a proposal is produced.

The model name is not configuration. It is `openrouter/free` in the engine, so
reaching a paid model requires a reviewed code change.

## Path rules

Component labels come only from explicit path evidence.

- Only backticked spans in the issue title or body are considered.
- A token must resolve against `git ls-files`. Anything unknown is ignored.
- A file path maps to its label. In `path::symbol`, the file part is used.
- A directory must contain a slash or end with one. A bare word is never read
  as a directory, because an issue that lists label names in backticks would
  otherwise name the directories of the same name.
- An issue with no usable path gets no component label. The proposal says so
  rather than guessing.

## Model policy

The model is asked one question per configured label, and only for labels
listed under `model_proposed`. A verdict counts only when it is well formed,
is not low confidence, and quotes a span that appears verbatim in the issue
text. Anything else is reported as needing human classification.

- `openrouter/free` is the only model.
- Requests set `provider.data_collection` to `deny`, so no provider that would
  train on the issue can serve the request.
- A rejected structured output request is retried once without the schema.
  There is no paid fallback.
- A missing key, an HTTP failure, a malformed response or a low confidence
  verdict never adds a label.

The issue text is untrusted input to the model. The allowlist, the quote check
and the approval gate bound what a successful injection could achieve.

## Correction mode

Dispatching the caller with an issue number produces a correction proposal
instead of a new-issue proposal. It diffs the evidence against the current
labels:

- Component labels are proposed for addition where a path supports them, and
  for removal where no path does.
- A model label is added on a positive verdict and removed only on a confident
  negative verdict. An uncertain, failed or missing verdict leaves it alone.
- `human_only` labels are never added or removed.
- Labels outside the taxonomy are left alone.

The comment shows the current set, the proposed set, each change with a reason,
and a hash of the current label set. After approval the apply job re-reads the
labels and aborts if they changed, so a concurrent human edit is not
overwritten.

## Consuming the workflow

Caller YAML for another repository:

```yaml
name: label-review

on:
  issues:
    types: [opened]

permissions:
  contents: read
  issues: write

jobs:
  review:
    uses: bniladridas/cuda/.github/workflows/label-review.yml@<commit-sha>
    permissions:
      contents: read
      issues: write
    with:
      issue-number: ${{ github.event.issue.number }}
      mode: propose
    secrets:
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

Pin the reference to a full commit SHA. A moving tag defeats the point of
pinning, and the engine runs from the commit the workflow was called at.

Inside the called workflow the engine is checked out with
`job.workflow_repository` and `job.workflow_sha`, so the executed code is the
same commit as the `uses:` reference. Those properties are available on
GitHub.com but not on GitHub Enterprise Server.

Each consuming repository supplies:

1. `.github/label-review.yml`, validated against the schema.
2. The `OPENROUTER_API_KEY` secret, unless it configures no `model_proposed`
   labels.
3. An environment named `label-review` with at least one required reviewer.
   Environments are per repository; the reusable workflow can name one but
   cannot create its protection rules.
4. `LABEL_AGENT_ENABLED=true` to post proposals and `LABEL_AGENT_APPLY=true` to
   also apply them. Both are repository variables.

The caller must grant `issues: write`, because a reusable workflow can only
keep or reduce the caller's permissions. Posting a proposal comment needs that
permission; GitHub has no comment-only scope.

For corrections, add a `workflow_dispatch` trigger with an issue number input
and pass `mode: correct`. The caller in this repository does both in one file.

## Failure behavior

Every failure below ends with no label change.

| Situation | Result |
| --------- | ------ |
| Invalid or incomplete configuration | Run fails before reading the issue |
| Configured label missing from the repository | Run fails before the model call |
| Missing or failing model | Labels reported as needing human classification |
| Malformed, unquoted or low confidence verdict | That label is not proposed |
| Issue closed between proposal and apply | Apply rejects the artifact |
| Pull request number dispatched | Run fails before reading or labelling it |
| Issue text edited between proposal and apply | Apply rejects the artifact |
| Labels changed between proposal and apply | Apply rejects a correction |
| Issue deleted or inaccessible | Run fails |

## Tests

```bash
python3 -m pip install pyyaml==6.0.2 jsonschema==4.23.0
python3 -m unittest discover -s label-review/tests
```

The suite covers glob matching, configuration validation, path extraction
including the bare word rule, model response validation and uncertainty, label
diffing, human-only protection, taxonomy drift, evidence that no longer
matches, and correction state checks. It runs offline: the model is not called
and no GitHub request is made.

The OpenRouter path itself is not covered, because a test that needs a real key
is not a unit test. The first live run is the first real call.

## Limits

- A new issue gets at most one review, and existing issues are not processed
  automatically.
- Pull requests are not reviewed. The issue endpoint returns them and
  `gh issue view` reads them as issues, so a dispatched pull request number is
  rejected explicitly.
- The model never chooses component labels.
- The engine proposes less than a human sometimes would. That is visible in
  the proposal, which lists the paths it used or says that none were found.
- The job that runs the engine holds only `issues: read`. Posting the proposal
  needs `issues: write`, so it is a separate job that does nothing else. The
  apply job holds `issues: write` for the label write and the audit comment.
