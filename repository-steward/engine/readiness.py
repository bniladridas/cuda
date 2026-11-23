"""Conservative release-readiness aggregation. Never publishes releases."""

from .contracts import Evidence


def evaluate_readiness(evidence: list[Evidence], policy: dict | None = None) -> dict:
    policy = policy or {}
    required = set(policy.get("required_kinds", ["host_tests", "cuda_compile", "gpu_runtime"]))
    by_kind = {}
    for item in evidence:
        # Prefer current evidence; a stale success must not mask current failure.
        by_kind.setdefault(item.kind, []).append(item)
    results = {}
    blockers = []
    for kind in sorted(required):
        candidates = by_kind.get(kind, [])
        current = [item for item in candidates if item.current]
        if not current:
            state = "unknown" if candidates else "unavailable"
            reason = "no evidence tied to the observed head SHA"
        else:
            item = current[-1]
            state = item.state.value
            reason = item.details or item.source or state
        results[kind] = {"state": state, "reason": reason}
        if state != "success":
            blockers.append({"kind": kind, "state": state, "reason": reason})
    ready = not blockers
    return {
        "ready": ready,
        "state": "ready" if ready else "not_ready",
        "required_evidence": results,
        "blockers": blockers,
        "publication_performed": False,
    }
