"""Read-only status adapters for existing approval-gated workflows.

The coordinator consumes explicit evidence supplied by its snapshot adapter.
It never executes the underlying workflows or treats a proposed action as
approved. Missing evidence remains unavailable.
"""

from .contracts import State, parse_state


INTEGRATIONS = {
    "label_review": {
        "entrypoint": ".github/workflows/label-review.yml",
        "engine": "label-review/engine/review.py",
        "approval_required": True,
        "approval_environment": "label-review",
        "write_capability": "apply approved issue labels",
    },
    "issue_landing": {
        "entrypoint": ".github/workflows/issue-landing.yml",
        "engine": "issue-landing/engine/landing.py",
        "approval_required": True,
        "approval_environment": "issue-landing-close",
        "write_capability": "close the exact issue covered by an approved report",
    },
}


def integration_status(snapshot: dict) -> dict:
    """Normalize externally observed workflow evidence without inferring approval."""
    supplied = snapshot.get("integration_evidence") or {}
    expected_sha = str(snapshot.get("head_sha") or "")
    results = {}

    for name, contract in INTEGRATIONS.items():
        evidence = supplied.get(name)
        if not isinstance(evidence, dict):
            state = State.UNAVAILABLE
            source = ""
            url = ""
            observed_sha = ""
            details = "No workflow evidence was supplied in this snapshot."
        else:
            state = parse_state(evidence.get("state"))
            source = str(evidence.get("source") or "")
            url = str(evidence.get("url") or "")
            observed_sha = str(evidence.get("head_sha") or "")
            details = str(evidence.get("details") or "")
            if not observed_sha or not expected_sha or observed_sha != expected_sha:
                state = State.UNKNOWN
                details = details or "Workflow evidence is not tied to the observed repository head."

        results[name] = {
            "state": state.value,
            "source": source,
            "url": url,
            "observed_sha": observed_sha,
            "expected_sha": expected_sha,
            "current": bool(observed_sha and expected_sha and observed_sha == expected_sha),
            "details": details,
            "entrypoint": contract["entrypoint"],
            "engine": contract["engine"],
            "approval_required": contract["approval_required"],
            "approval_environment": contract["approval_environment"],
            "write_capability": contract["write_capability"],
            "approval_status": "not_asserted",
            "coordinator_write_performed": False,
        }
    return {
        "mode": "read_only",
        "mutations_performed": False,
        "integrations": results,
    }
