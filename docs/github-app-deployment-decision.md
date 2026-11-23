# CUDA Repository Steward deployment decision

**Status:** Accepted direction, implementation deferred  
**Scope:** Architecture and deployment choice only  
**Related:** #55, #58

## Decision

Keep GitHub Actions as the default and current deployment model for CUDA Repository Steward. Keep the Steward's domain logic, evidence contracts, policy evaluation, and reporting independent from GitHub Actions-specific execution details.

A GitHub App is a possible future adapter, not a current implementation target. Do not register an App, provision hosting, add App credentials, or migrate workflows until a demonstrated requirement cannot be met cleanly with repository-scoped GitHub Actions and least-privilege tokens.

A hybrid model may be appropriate later: Actions remains available for repository-local execution while an App supplies installation-level event delivery or cross-repository coordination. This is a future option, not a commitment.

## Deployment model comparison

| Concern | Actions-only | Standalone GitHub App | Hybrid |
| --- | --- | --- | --- |
| Initial setup | Workflow files and repository configuration | App registration, installation, hosting, webhook endpoint | Both workflow setup and App operations |
| Trigger model | Workflow events, schedules, dispatch, polling where needed | Webhooks with reconciliation | Webhooks for shared coordination; Actions for local jobs |
| Permission scope | Repository-scoped GITHUB_TOKEN permissions | Installation permissions across selected repositories | Separate least-privilege permissions for each adapter |
| Cross-repository work | Requires explicit workflow/API coordination | Native installation-level access to selected repositories | App coordinates; Actions handles repository-local work |
| Bot identity | Workflow token identity | Dedicated App bot identity | App identity for App actions, workflow identity for Actions |
| Operations | GitHub-hosted workflow lifecycle | Hosting, availability, secrets, monitoring, incident response | Both operational surfaces |
| Cost and maintenance | Lowest operational burden; no separate service required | Ongoing hosting and service maintenance | Higher complexity than either model alone |
| Best fit | Current single-repository Steward | Demonstrated installation-level or webhook requirement | A proven need for both local execution and centralized coordination |

**Current choice:** Actions-only. Revisit the hybrid or App model only when measured operational friction or a concrete capability requirement justifies its additional complexity.

## Conditions that justify reconsideration

Revisit this decision when at least one concrete requirement is demonstrated and cannot be handled adequately with repository-scoped workflows:

- Owners need to install or uninstall the Steward for selected repositories without copying workflow files.
- Timely webhook-driven processing is required beyond the event and schedule model available to Actions.
- One authorized installation must coordinate policy or reporting across multiple repositories.
- A dedicated bot identity is required for auditable comments, checks, or statuses.
- Workflow token permissions or execution limits create a documented blocker that cannot be addressed with narrower repository-scoped workflows.

Before implementation, record the use case, affected repositories, expected event volume, permission requirements, operational owner, and why Actions is insufficient.

## Core and adapter boundary

Keep these responsibilities in the reusable Steward core:

- Domain models for repository, issue, pull request, check, validation, finding, and audit evidence.
- Deterministic policy evaluation and readiness calculations.
- Module interfaces and module-specific configuration.
- Report generation and provenance of observed evidence.

Keep these responsibilities in deployment adapters:

- Authentication and token acquisition.
- GitHub event and webhook parsing.
- Repository and installation context resolution.
- API transport, pagination, rate-limit handling, and retries.
- Scheduling, dispatch, and reconciliation.
- Runtime-specific logging, metrics, secrets, and operational health.

Adapters must pass normalized, source-identifiable evidence into the core. Core logic must not depend on webhook payload shapes, installation tokens, or a hosted service.

## Installation and permission strategy

If an App is later approved:

1. Begin with selected-repository installation scope. Do not request organization-wide access by default.
2. Start read-only. Add write permissions only for a separately reviewed capability with an explicit approval path.
3. Map each permission to a documented operation and module. Do not let one module inherit another module's write access.
4. Keep merge, issue closure, and release publication human-authorized under the existing repository policy.
5. Re-fetch the target resource and verify its expected state or SHA immediately before any approved mutation.
6. Keep Actions usable when the App is absent or unavailable.

The App must not execute untrusted pull-request code in a privileged context or expose installation credentials to workflow-controlled content.

## Webhook security and delivery

A future webhook adapter must:

- Verify the signature against the raw request body before parsing or processing the event.
- Reject invalid signatures and enforce a bounded request size.
- Use HTTPS and keep webhook secrets outside repository-controlled files.
- Validate the event type, delivery identifier, installation, repository, and action before dispatching work.
- Treat payload content as untrusted data, not as instructions or authorization.
- Avoid logging secrets or unnecessary personal data.

## Idempotency, retries, and reconciliation

Webhook delivery is at-least-once. Processing must therefore be idempotent.

- Record the delivery ID and a stable operation key before performing work.
- Make duplicate deliveries safe and prevent duplicate comments, check runs, or mutations.
- Use bounded retries with backoff for transient network errors, rate limits, and server errors.
- Do not retry authorization failures or invalid payloads as if they were transient.
- Persist enough state to identify incomplete work and its source event.
- Reconcile periodically against GitHub's current state to recover missed deliveries and stale processing.
- Re-fetch current repository and PR state before reporting freshness or attempting an approved action.
- Keep observed head/base SHAs and source URLs with every evidence record.

## Auditability and operations

For each processed event, retain an auditable record containing:

- Delivery ID and event type.
- Installation and repository identifiers.
- Actor and target resource identifiers.
- Observed commit SHA or resource version where applicable.
- Module and policy version.
- Evidence references and decision.
- Approval evidence for any permitted write.
- Resulting GitHub resource identifiers and outcome.

Define an operational owner, availability expectations, alerting, secret rotation, data retention, backup/recovery, and incident response before production hosting. Keep logs minimal and avoid retaining webhook payloads longer than necessary.

## Evolution path

1. Continue the Actions-first implementation under #55.
2. Gather concrete evidence of a requirement that Actions cannot satisfy cleanly.
3. Write a focused architecture decision record for that requirement, including security and operating cost.
4. Stabilize the relevant core contract before adding an adapter.
5. Prototype one read-only App capability and test installation scope, webhook verification, idempotency, retries, reconciliation, and auditability.
6. Review the prototype independently before any write permission or production deployment is considered.

## Explicitly deferred

This decision does not authorize:

- GitHub App registration or installation.
- Hosting, a control plane, or multi-tenant service.
- App credentials, webhook secrets, or production infrastructure.
- Broad organization permissions.
- Migration or replacement of existing Actions workflows.
- Automatic PR merges, issue closures, or release publication.

The Actions-based path remains the supported default until a separately reviewed decision changes it.
