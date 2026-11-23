"""Conservative release-readiness aggregation. Never publishes releases."""

from .contracts import Evidence


def _artifact_check(state, reason):
    return {"state": state, "reason": reason}


def evaluate_readiness(
    evidence: list[Evidence],
    policy: dict | None = None,
    *,
    health: dict | None = None,
    benchmark: dict | None = None,
    files: dict | None = None,
    version_evidence: dict | None = None,
) -> dict:
    """Evaluate validation and release artifacts without authorizing publication."""
    policy = policy or {}
    required = set(policy.get("required_kinds", ["host_tests", "cuda_compile", "gpu_runtime"]))
    by_kind = {}
    for item in evidence:
        # Prefer current evidence; a stale success must not mask current failure.
        by_kind.setdefault(item.kind, []).append(item)

    results = {}
    blockers = []

    def record(name, state, reason):
        results[name] = _artifact_check(state, reason)
        if state != "success":
            blockers.append({"kind": name, "state": state, "reason": reason})

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
        record(kind, state, reason)

    required_docs = policy.get("required_docs", ["README.md", "LICENSE", "docs/methodology.md"])
    if not isinstance(required_docs, list) or any(not isinstance(path, str) for path in required_docs):
        record("documentation", "unknown", "required_docs policy must be a list of repository paths")
    else:
        missing = [path for path in required_docs if not isinstance(files, dict) or path not in files]
        record(
            "documentation",
            "failure" if missing else "success",
            "missing required documentation: " + ", ".join(missing)
            if missing
            else "all required documentation files are present",
        )

    if health is None:
        record("repository_health", "unavailable", "repository health evidence was not supplied")
    else:
        findings = health.get("findings", [])
        errors = [item for item in findings if item.get("severity") == "error"]
        warnings = [item for item in findings if item.get("severity") == "warning"]
        health_state = (
            "failure"
            if errors
            else ("warning" if warnings and policy.get("block_on_health_warnings", False) else "success")
        )
        record(
            "repository_health",
            health_state,
            f"{len(errors)} error finding(s); {len(warnings)} warning finding(s)",
        )
        results["repository_health"]["warning_count"] = len(warnings)
        results["repository_health"]["error_count"] = len(errors)

    if policy.get("require_benchmark_evidence", True):
        if benchmark is None:
            record("benchmark_integrity", "unavailable", "benchmark integrity evidence was not supplied")
        else:
            reports = benchmark.get("reports", [])
            valid_count = benchmark.get("valid_count", 0)
            invalid_count = len(reports) - valid_count
            state = (
                "success"
                if reports and valid_count == len(reports)
                else ("failure" if invalid_count else "unavailable")
            )
            reason = f"{valid_count} valid benchmark result(s), {max(invalid_count, 0)} incomplete or invalid"
            record("benchmark_integrity", state, reason)

    if policy.get("require_version_consistency", True):
        declared = (version_evidence or {}).get("declared_version")
        release = (version_evidence or {}).get("release_version")
        if not isinstance(declared, str) or not declared or not isinstance(release, str) or not release:
            record(
                "version_consistency",
                "unavailable",
                "declared project version and release version evidence are both required",
            )
        elif declared.lstrip("v") == release.lstrip("v"):
            record("version_consistency", "success", f"project version {declared} matches release {release}")
        else:
            record("version_consistency", "failure", f"project version {declared} does not match release {release}")

    ready = not blockers
    return {
        "ready": ready,
        "state": "ready" if ready else "not_ready",
        "required_evidence": results,
        "blockers": blockers,
        "publication_performed": False,
    }
