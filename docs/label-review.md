# Label review

A proposal workflow for new issues. It reads the issue, proposes labels, and
applies nothing until the owner approves. It exists so that a label on a new
issue is a reviewed decision rather than a guess, and so that the mapping stays
visible in the repository instead of living in someone's head.

## What is deterministic and what is not

| Decision | How it is made |
| -------- | -------------- |
| Component labels | Lookup. Paths in backticks in the issue text are checked against `git ls-files`; only real paths count, and each maps to one label by a fixed table |
| `needs-gpu` | A model call, which must quote evidence from the issue |
| Anything else | Never proposed |

The model is asked one question. It never chooses component labels, and its
answer is only used if it is well formed, confident enough and backed by a
quote. A refusal, a timeout, malformed JSON, low confidence or a missing API key
all produce "needs human classification" instead of a label.

The issue text is untrusted input to the model, and a body can contain
instructions aimed at it. The proposal is therefore a suggestion with no write
access, and the approval is the control that decides whether anything is
applied.

`cpu-verified` and `gpu-verified` are never proposed by any code path. They
record evidence that the workflow cannot see. A `verify` step rejects an
artifact containing them, so importing one is not possible either.

## Known under-proposal

The component rule reads paths, not intent, so it proposes less than a human
sometimes would:

- An issue that names only symbols, such as `launch_vecadd` and
  `cudaStream_t`, names no path and gets no component label.
- An issue about documenting `include/cuda_kernels/vecadd.cuh` is proposed as
  `kernels` only, because the file is a kernel header; the human may also see
  it as `documentation`.

Both cases are visible in the proposal comment, which lists the paths it used
or says that none were found.

## Setup

The workflow is inert until all four items exist. Create them in this order,
because the order is what keeps the gate real.

1. **Environment** named `label-review` with yourself as a required reviewer.
   This is the approval gate. Without it, the apply job runs as soon as the
   proposal is posted.
2. **Secret** `OPENROUTER_API_KEY`. An OpenRouter key for the free router.
3. **Variable** `LABEL_AGENT_ENABLED=true`. This enables proposals only.
4. **Variable** `LABEL_AGENT_APPLY=true`. This enables the apply job.

If step 4 is done before step 1, the apply job is not gated by anything. The
workflow cannot detect that case, so the two-variable split is the safeguard:
enabling proposals does not enable writes.

## Model policy

The model is `openrouter/free`, written into the workflow rather than read from
a variable. Changing to a paid model requires a reviewed diff and nothing else,
so the cost of the workflow is visible in version control.

Requests set `provider.data_collection` to `deny`. If no free provider meets
that, the request fails and the issue is marked for human classification rather
than being sent somewhere that trains on it.

## What the apply job rechecks

After approval and before writing anything, the apply job confirms that the
artifact is for this issue, that every label is one this workflow may apply,
that the issue is still open, and that the component proposal still matches the
current issue text. An issue edited between proposal and approval fails the
check rather than applying a stale proposal.
