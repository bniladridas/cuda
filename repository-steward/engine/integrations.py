"""Read-only adapters for workflow and per-pull-request evidence."""

from copy import deepcopy

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

PR_INTEGRATIONS = {
    "pr_confidence": {
        "entrypoint": ".github/workflows/pr-confidence.yml",
        "engine": "pr-confidence/engine/confidence.py",
        "artifact": "pr-confidence-evidence",
    },
    "pr_scope_guard": {
        "entrypoint": ".github/workflows/pr-scope-guard.yml",
        "engine": "pr-scope-guard/engine/scope_guard.py",
        "artifact": "pr-scope-guard-evidence",
    },
}

PR_STATES = {"current", "stale", "missing", "incomplete", "pending", "malformed", "failed"}


def _base_pr_result(name, pr_number, expected_sha):
    contract = PR_INTEGRATIONS[name]
    return {
        "state": "missing",
        "pr_number": pr_number,
        "expected_sha": expected_sha,
        "observed_sha": "",
        "revision_match": None,
        "source": "",
        "url": "",
        "details": "No matching workflow artifact was found for this pull request head.",
        "entrypoint": contract["entrypoint"],
        "engine": contract["engine"],
        "artifact": contract["artifact"],
        "approval_required": False,
        "approval_status": "not_applicable",
        "coordinator_write_performed": False,
    }


def _normalize_pr_evidence(name, pr_number, expected_sha, supplied):
    result = _base_pr_result(name, pr_number, expected_sha)
    if not isinstance(supplied, dict):
        return result

    for key in ("source", "url", "details"):
        if isinstance(supplied.get(key), str):
            result[key] = supplied[key]
    workflow_state = supplied.get("workflow_state")
    artifact = supplied.get("evidence")
    if workflow_state in {"pending", "failed"}:
        result["state"] = workflow_state
        result["details"] = result["details"] or "Workflow has not produced usable evidence."
        return result
    if artifact is None:
        result["state"] = supplied.get("state") if supplied.get("state") in PR_STATES else "missing"
        return result
    if not isinstance(artifact, dict):
        result["state"] = "malformed"
        result["details"] = "Artifact payload is not a JSON object."
        return result

    if name == "pr_confidence":
        observed_sha = artifact.get("head_sha")
        pr_record = artifact.get("pr")
        artifact_pr = pr_record.get("number") if isinstance(pr_record, dict) else None
        valid_shape = (
            artifact.get("rubric_version") == 1
            and isinstance(artifact.get("score"), int)
            and isinstance(artifact.get("categories"), list)
            and isinstance(artifact.get("blockers"), list)
            and isinstance(artifact.get("notes"), list)
            and isinstance(artifact.get("pr"), dict)
            and isinstance(artifact.get("files"), dict)
            and isinstance(artifact.get("checks"), dict)
            and isinstance(artifact.get("review"), dict)
        )
        complete = (
            valid_shape
            and all(
                (artifact.get(key) or {}).get("available") is True
                and not (artifact.get(key) or {}).get("truncated", False)
                for key in ("files", "checks")
            )
            and (artifact.get("review") or {}).get("available") is True
            and not ((artifact.get("review") or {}).get("threads_truncated", False))
        )
    else:
        observed_sha = artifact.get("head_sha")
        artifact_pr = artifact.get("pr_number")
        coverage = artifact.get("coverage")
        valid_shape = (
            artifact.get("version") == 1
            and isinstance(artifact.get("findings"), list)
            and isinstance(artifact.get("files"), list)
            and isinstance(coverage, dict)
            and isinstance(coverage.get("complete"), bool)
            and isinstance(artifact.get("counts"), dict)
        )
        complete = valid_shape and coverage.get("complete") is True

    result["observed_sha"] = observed_sha if isinstance(observed_sha, str) else ""
    result["revision_match"] = bool(expected_sha and result["observed_sha"] == expected_sha)
    if not valid_shape:
        result["state"] = "malformed"
        result["details"] = "Artifact is missing required schema fields."
    elif artifact_pr != pr_number:
        result["state"] = "malformed"
        result["details"] = "Artifact pull request number does not match its workflow association."
    elif not result["revision_match"] or (name == "pr_confidence" and (artifact.get("pr") or {}).get("head_mismatch")):
        result["state"] = "stale"
        result["details"] = (
            "Artifact head SHA does not match the current pull request head, or the PR moved during collection."
        )
    elif not complete:
        result["state"] = "incomplete"
        result["details"] = "Artifact is valid but its source evidence or changed-file coverage is incomplete."
    else:
        result["state"] = "current"
        result["details"] = "Complete artifact evidence matches the current pull request head."

    # Preserve source findings and score as data. Never translate them into
    # approval, readiness, or authorization decisions.
    result["evidence"] = deepcopy(artifact)
    return result


def integration_status(snapshot: dict) -> dict:
    """Normalize evidence without inferring approval or authorizing mutations."""
    supplied = snapshot.get("integration_evidence") or {}
    results = {}
    for name, contract in INTEGRATIONS.items():
        evidence = supplied.get(name)
        evidence_expected_sha = ""
        if not isinstance(evidence, dict):
            state, source, url, observed_sha, details = (
                State.UNAVAILABLE,
                "",
                "",
                "",
                ("No workflow evidence was supplied in this snapshot."),
            )
        else:
            state = parse_state(evidence.get("state"))
            source = str(evidence.get("source") or "")
            url = str(evidence.get("url") or "")
            observed_sha = str(evidence.get("head_sha") or "")
            evidence_expected_sha = str(evidence.get("expected_sha") or "")
            details = str(evidence.get("details") or "")
            if evidence_expected_sha and observed_sha != evidence_expected_sha:
                state = State.UNKNOWN
                details = details or "Workflow evidence does not match its declared expected SHA."
        results[name] = {
            "state": state.value,
            "source": source,
            "url": url,
            "observed_sha": observed_sha,
            "expected_sha": evidence_expected_sha if isinstance(evidence, dict) else "",
            "revision_match": (
                observed_sha == evidence_expected_sha
                if isinstance(evidence, dict) and evidence.get("expected_sha")
                else None
            ),
            "details": details,
            "entrypoint": contract["entrypoint"],
            "engine": contract["engine"],
            "approval_required": contract["approval_required"],
            "approval_environment": contract["approval_environment"],
            "write_capability": contract["write_capability"],
            "approval_status": "not_asserted",
            "coordinator_write_performed": False,
        }

    per_pr = snapshot.get("pull_request_integrations") or {}
    pull_requests = {}
    for pr in snapshot.get("pull_requests") or []:
        if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
            continue
        number = pr["number"]
        expected_sha = str(pr.get("head_sha") or "")
        supplied_pr = per_pr.get(str(number), per_pr.get(number, {}))
        normalized = {}
        for name in PR_INTEGRATIONS:
            normalized[name] = _normalize_pr_evidence(
                name, number, expected_sha, supplied_pr.get(name) if isinstance(supplied_pr, dict) else None
            )
        pull_requests[str(number)] = normalized

    results.update(
        {
            name: {
                "state": "per_pull_request",
                "entrypoint": contract["entrypoint"],
                "engine": contract["engine"],
                "approval_required": False,
                "approval_status": "not_applicable",
                "coordinator_write_performed": False,
                "pull_requests": {number: evidence[name] for number, evidence in pull_requests.items()},
            }
            for name, contract in PR_INTEGRATIONS.items()
        }
    )
    return {
        "mode": "read_only",
        "mutations_performed": False,
        "integrations": results,
    }
