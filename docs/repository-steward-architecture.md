# CUDA Repository Steward architecture

## Purpose

CUDA Repository Steward is the proposed coordination layer for the repository's
existing automation. It should make repository state, validation evidence,
policy decisions, and release readiness easier to inspect without replacing
GitHub Issues, GitHub Actions, or the tools that already perform those jobs.

This document defines boundaries and an incremental integration direction. It
does not create a new runtime, move existing engines, or authorize new write
permissions.

## Current state

The repository already has separate engines and workflows. They remain the
source of truth for their own behavior:

| Capability | Existing implementation | Current responsibility |
| --- | --- | --- |
| Issue labels | `label-review/`, `.github/workflows/label-review.yml` | Propose issue labels; apply only through the configured approval gate |
| Issue landing | `issue-landing/`, `.github/workflows/issue-landing.yml` | Report linked-PR evidence; issue closure is a separate approved operation |
| PR confidence | `pr-confidence/`, `.github/workflows/pr-confidence.yml` | Read-only evidence score and blocker report |
| PR scope | `pr-scope-guard/`, `.github/workflows/pr-scope-guard.yml` | Read-only, advisory title-to-file scope report |
| Formatting | `format-repair/`, `.github/workflows/format-repair.yml` | Report formatting findings; repair requires maintainer authorization |
| PR review | `cuda-review/`, `.github/workflows/cuda-review.yml` | Maintainer-triggered model-assisted review |
| PR title | `pr-title/`, `.github/workflows/pr-title-assistant.yml` | Title suggestions and validation |
| Rebase and repair | `rebase-agent/`, related workflows | Bounded PR branch operations with explicit authorization and SHA checks |
| Squash merge | `squash-merge/`, `.github/workflows/squash-merge.yml` | Maintainer-authorized squash-only merge gate |
| CI and GPU evidence | `.github/workflows/ci.yml`, other validation workflows | Build, test, security, and hardware-specific evidence |

The existing engines are not yet one application. Their workflows have
independent triggers, configuration, tests, permissions, and audit artifacts.
The first integration step is to document stable boundaries, not to centralize
their execution prematurely.

## Logical architecture

The intended design has four layers:

1. **Adapters** collect trusted GitHub and workflow metadata. GitHub Actions is
   the initial adapter and remains the default deployment model.
2. **Core contracts** normalize repository, issue, pull-request, check, review,
   validation, and audit evidence. Contracts must preserve source identifiers
   and observed commit SHAs.
3. **Modules** evaluate one responsibility at a time: tracking, label review,
   landing, scope, confidence, repository health, GPU validation, benchmark
   integrity, and release readiness.
4. **Reports** present evidence, policy findings, unknown states, and suggested
   next steps. Reports must distinguish observed facts from recommendations.

A future coordinator may invoke modules through these contracts. It must not
duplicate their policy or silently replace their existing workflows.

### Proposed shared contracts

The first reusable interfaces should remain small and data-oriented:

- **Repository context:** repository name, default branch, and observation time.
- **Change context:** issue or PR number, base/head SHA, changed paths, and
  current state.
- **Check evidence:** check name, head SHA, status, conclusion, URL, and whether
  the result is current for the observed head.
- **Validation evidence:** validation kind (host, CUDA compile, GPU runtime, or
  benchmark), result state, environment metadata, and source run.
- **Finding:** stable code, severity, summary, evidence references, and whether
  the finding is advisory or blocking under an explicit policy.
- **Audit record:** trigger, actor, observed identifiers, policy version,
  decision, approved action (if any), and resulting identifiers.

Use explicit states such as `success`, `failure`, `pending`, `skipped`,
`unavailable`, and `unknown`. Never coerce missing or skipped GPU evidence
into success. Never treat a model recommendation as deterministic evidence.

## Module boundaries

| Module | Owns | Must not own |
| --- | --- | --- |
| Issue tracking | Issue completeness, activity, dependencies, linked PR state | Closing issues or changing labels without an approved path |
| Label review | Label taxonomy, evidence, proposal and apply gate | Human-only labels or unrelated repository policy |
| Issue landing | Linked-PR evidence and closure readiness report | Implicit issue closure |
| PR scope and confidence | Advisory scope and evidence reports | Approval, merge, or overriding required checks |
| Repository health | Documentation links and configuration consistency findings | Automatic broad rewrites |
| GPU validation | CUDA compile and GPU runtime evidence, including runner metadata | Inferring runtime correctness from CPU checks or compilation |
| Benchmark integrity | Hardware, software, methodology, and reproducibility evidence | Publishing unverified performance claims |
| Release readiness | Aggregating required evidence and policy results | Publishing a release |
| Model integration | Optional summaries and recommendations with model identity | Overriding deterministic checks or authorization |

Each module should keep its own configuration schema, tests, and execution
entry point until a concrete shared dependency justifies extraction.

## Permission and trust model

Permissions are capability-specific. A module must not inherit write access
merely because another module needs it.

| Class | Allowed behavior | Examples |
| --- | --- | --- |
| Read-only | Read repository metadata and produce reports | Issue tracking, PR confidence, scope guard, repository health |
| Approval-gated | Perform only the exact action covered by a trusted approval, after re-fetching state | Label application, formatting repair, approved branch update |
| Human-only | Require a human to perform the action directly | PR approval, issue closure outside the existing approved workflow, release publication |

Additional invariants:

- Workflow code, policy, and configuration are loaded from a trusted base
  revision, not from untrusted PR content.
- Never execute untrusted PR code in a job that holds write credentials or
  model secrets.
- Re-fetch the issue or PR and verify its expected SHA immediately before any
  mutation.
- Keep review, branch update, approval, merge, issue closure, and release
  publication as separate decisions.
- Model output is untrusted input. It cannot grant permissions, select a
  privileged operation, or override deterministic validation.
- Use least-privilege GitHub token permissions and avoid paid services or
  runners in the default path.

## Integration sequence

1. **Architecture and boundaries:** this document records the current
   inventory, shared evidence concepts, and permission model.
2. **Contract tests:** add tests for evidence states, SHA freshness, and
   permission boundaries before introducing a coordinator.
3. **Read-only tracking:** aggregate existing issue, PR, and check evidence
   without changing current workflow behavior.
4. **Existing module adapters:** integrate Label Review, Issue Landing, PR
   Confidence, and PR Scope Guard through read-only interfaces first.
5. **Repository health:** add deterministic link and configuration checks.
6. **Validation and integrity:** normalize GPU and benchmark evidence without
   treating unavailable hardware as a failure or a success.
7. **Readiness reporting:** derive release readiness from explicit policy and
   evidence freshness. Reporting must not publish releases.
8. **Optional model assistance:** add only where deterministic reports leave a
   useful explanatory task. Keep provider access optional and bounded.

Every step should be independently reviewable and retain compatibility with the
existing workflows. Do not migrate or rewrite a module solely to make its
folder structure match a proposed architecture.

## Deployment decision

GitHub Actions remains the initial and default runtime. A standalone GitHub App
is a separate future decision documented in issue #58. Do not register, host,
or add App credentials until a demonstrated requirement for installation-level
permissions, webhooks, cross-repository operation, or a dedicated bot identity
cannot be met cleanly by repository-scoped workflows.

## Non-goals

- Replacing GitHub Issues, pull requests, or GitHub Actions.
- Moving every existing engine into a new package in one change.
- Adding a mandatory model provider, paid API, hosted service, or paid runner.
- Allowing unattended PR merges, issue closures, or release publication.
- Treating CPU-only checks or CUDA compilation as GPU runtime validation.
