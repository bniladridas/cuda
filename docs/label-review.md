# Label review

A proposal workflow for issues. It reads an issue, proposes labels, and applies
nothing until the owner approves the run on a protected environment. It exists
so that a label is a reviewed decision rather than a guess, and so that the
mapping stays visible in the repository instead of living in someone's head.

The engine and the reusable workflow are documented in
[`label-review/README.md`](https://github.com/bniladridas/cuda/blob/main/label-review/README.md).
This page covers the deployment in this repository.

## What runs

| Trigger | Mode | Effect |
| ------- | ---- | ------ |
| A new issue is opened | `propose` | A proposal comment, then a waiting apply job |
| Manual dispatch with an issue number | `correct` | A correction proposal comment, then a waiting apply job |

Existing issues are not processed automatically. A correction is only produced
when someone dispatches it, and a pull request number entered there is rejected
before the issue is read. Pull requests use a separate diff-aware reviewer,
documented in [PR metadata review](pr-label-review.md).

The workflow is inert until the setup below is complete. The pull request that
adds it does not create the environment, the secret or the variables; those are
repository settings configured separately. They exist in this repository now,
with apply disabled until the proposal-only check below passes.

## Label roles

| Label | Role |
| ----- | ---- |
| `ci`, `runners`, `build`, `benchmark`, `tests`, `kernels`, `documentation` | Component labels, from paths in the issue |
| `needs-gpu` | Model assessed, with a required quote from the issue |
| `cpu-verified` | Human only. Never proposed, applied or removed by the workflow |
| `bug`, `enhancement`, and the other default labels | Outside the taxonomy. Left untouched |

`gpu-verified` does not exist in this repository, so it is not configured. A
label that does not exist fails validation before any proposal is produced.

## Setup

Create these in order. The order is what keeps the gate real.

1. **Environment** named `label-review` with yourself as a required reviewer
   (Settings > Environments > New environment). This is the approval gate.
   Without it, the apply job runs as soon as the proposal is posted.
2. **Secret** `OPENROUTER_API_KEY`, an OpenRouter key for the free router:

   ```bash
   gh secret set OPENROUTER_API_KEY --repo bniladridas/cuda
   ```

3. **Variable** `LABEL_AGENT_ENABLED=true`. This enables proposals only.
4. **Variable** `LABEL_AGENT_APPLY=true`. This enables the apply job.

```bash
gh variable set LABEL_AGENT_ENABLED --repo bniladridas/cuda --body true
gh variable set LABEL_AGENT_APPLY --repo bniladridas/cuda --body true
```

If the apply variable is set before the environment exists, the apply job is not
gated by anything. The workflow cannot detect that case, so the two-variable
split is the safeguard: enabling proposals does not enable writes.

## Approval

The apply job appears as waiting for review in the Actions run. Approving it
runs the revalidation and then the label write. Rejecting it applies nothing.
GitHub records the approval on the run, and the workflow posts a comment
recording the mode, the actor, the additions, the removals and the run link.

No comment command applies labels. The environment approval is the only way to
reach the write step.

## Correction run

1. Actions > `label-review` > Run workflow, entering the issue number.
2. Read the proposal comment: current labels, proposed labels, each change with
   a reason, and a short hash of the current label set.
3. Approve or reject the waiting run. After approval the labels are read again,
   and a change made in between aborts the apply instead of overwriting it.

`human_only` labels and labels outside the taxonomy are never removed, even
when the evidence does not mention them. A model label is removed only after a
confident verdict that the criterion does not apply; if the model is uncertain,
fails or is not configured, the label already on the issue stays.

## What the apply job rechecks

After approval and before writing anything, it confirms that the artifact is
for this issue and this mode, that the issue is still open, that the issue title
and body still match the digest recorded in the proposal, that every label is
one the configuration manages, that no `human_only` label is being changed,
that the component labels still match the issue text, that each model label
still has a quote present in the text, and, for a correction, that the label
set still matches the approved hash. Any mismatch fails the run and nothing is
written.

## Known under-proposal

The component rule reads paths, not intent, so it proposes less than a human
sometimes would:

- An issue that names only symbols, such as `launch_vecadd` and
  `cudaStream_t`, names no path and gets no component label.
- A bare word in backticks is never treated as a directory. An issue that lists
  label names such as `runners` and `tests` does not get those components.
- An issue about documenting `include/cuda_kernels/vecadd.cuh` is proposed as
  `kernels` only, because the file is a kernel header; a human may also see it
  as `documentation`.
- Issue 31, which is about a GitHub Actions workflow, names no explicit file
  path, so the deterministic pass proposes no component label even though a
  human would add `ci`. Running the engine against its live text produces an
  empty proposal and marks `needs-gpu` for human classification.

Each of these is visible in the proposal comment, which lists the paths it used
or says that none were found.

## Smoke test

Two proposal-only live runs were exercised on 2026-11-15.

The first used issue #44:
[Actions run 43720322872](https://github.com/bniladridas/cuda/actions/runs/43720322872).

- The `review / propose` and `review / comment` jobs passed.
- The proposal identified the `documentation` component from the issue paths.
- The `needs-gpu` assessment remained human classification because its
  quoted evidence was not present in the issue text.

The second used a dedicated temporary test issue #48:
[Actions run 43722472795](https://github.com/bniladridas/cuda/actions/runs/43722472795).

- The `review / propose` and `review / comment` jobs passed.
- The proposal identified `kernels` from the explicit path
  `src/vecadd.cu`.
- The model proposed `needs-gpu` with an exact quote from the issue.
- The `review / apply` job was skipped because `LABEL_AGENT_APPLY` remains
  false. No labels were changed on the test issue.

These runs verify proposal generation, accepted model evidence, component
mapping, and proposal comments. They do not verify Environment approval,
label application, rejection, or concurrent-label revalidation. The temporary
issue #48 was closed after the proposal test.

The remaining gated test requires an owner to enable
`LABEL_AGENT_APPLY=true` after confirming the `label-review` Environment
has a required reviewer. Then:

1. Confirm the `label-review` Environment has a required reviewer, then
   set `LABEL_AGENT_APPLY=true`.
2. Open a dedicated test issue that names `src/vecadd.cu` and says the file
   must be compiled and run on an NVIDIA GPU. The `issues: opened` event
   should create the proposal and a waiting apply job.
3. Approve that waiting run. Expect the labels to be applied and an audit
   comment to appear.
4. Open a second test issue and reject its waiting run. Expect no labels.
5. Dispatch a correction on the first test issue, change a label by hand while
   the apply waits for approval, then approve and confirm revalidation fails
   without writing a label.
6. Close both test issues and set `LABEL_AGENT_APPLY=false` again.

## Turning it off

Unset `LABEL_AGENT_APPLY` first, then `LABEL_AGENT_ENABLED`. Writes stop
before proposals do. Labels already applied stay where they are. Deleting the
environment or the secret disables the workflow more completely.

## Tests

The engine has offline tests, which also run in the CPU CI job:

```bash
python3 -m pip install pyyaml==6.0.2 jsonschema==4.23.0
python3 -m unittest discover -s label-review/tests
```
