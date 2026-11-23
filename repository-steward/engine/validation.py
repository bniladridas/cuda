"""Normalize CI, CUDA, GPU runtime and benchmark evidence without inference."""

from .contracts import Evidence, State, parse_state


def normalize_validation(snapshot: dict) -> list[Evidence]:
    result = []
    expected_sha = snapshot.get("head_sha") or ""
    for item in snapshot.get("validations", []):
        kind = str(item.get("kind") or "unknown")
        state = parse_state(item.get("state"))
        observed_sha = str(item.get("head_sha") or "")
        # Evidence without an observed commit is never considered current.
        result.append(
            Evidence(
                kind=kind,
                state=state,
                source=str(item.get("source") or ""),
                observed_sha=observed_sha,
                expected_sha=expected_sha,
                url=str(item.get("url") or ""),
                details=str(item.get("details") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return result


def validation_findings(evidence: list[Evidence]) -> list[dict]:
    findings = []
    for item in evidence:
        if item.kind in {"gpu_runtime", "gpu"} and item.state != State.SUCCESS:
            findings.append(
                {
                    "code": "gpu.validation_" + item.state.value,
                    "severity": "warning",
                    "summary": f"GPU runtime validation is {item.state.value}, not verified success.",
                    "evidence": [item.source] if item.source else [],
                    "blocking": False,
                }
            )
        if item.state == State.SUCCESS and not item.current:
            findings.append(
                {
                    "code": "validation.stale",
                    "severity": "warning",
                    "summary": f"{item.kind} success is not tied to the observed head SHA.",
                    "evidence": [item.source] if item.source else [],
                    "blocking": False,
                }
            )
    return findings
