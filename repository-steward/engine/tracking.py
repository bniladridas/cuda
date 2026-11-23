"""Read-only issue and pull-request tracking over a normalized GitHub snapshot."""

import re
from datetime import datetime, timezone

from .contracts import Finding, Severity

ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")


def _numbers(text: str) -> set[int]:
    return {int(value) for value in ISSUE_REF.findall(text or "")}


def _parse_timestamp(value: str):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def analyze_tracking(snapshot: dict, *, stale_after_days: int = 30) -> dict:
    if not isinstance(stale_after_days, int) or isinstance(stale_after_days, bool) or stale_after_days < 1:
        raise ValueError("stale_after_days must be a positive integer")
    issues = snapshot.get("issues", [])
    prs = snapshot.get("pull_requests", [])
    if not isinstance(issues, list) or not isinstance(prs, list):
        raise ValueError("snapshot issues and pull_requests must be lists")

    generated_at = _parse_timestamp(snapshot.get("generated_at"))
    pr_by_number = {int(pr["number"]): pr for pr in prs if "number" in pr}
    issue_by_number = {int(issue["number"]): issue for issue in issues if "number" in issue}
    findings: list[Finding] = []
    records = []

    for issue in sorted(issues, key=lambda item: int(item.get("number", 0))):
        number = int(issue["number"])
        body = issue.get("body") or ""
        title = issue.get("title") or ""
        state = str(issue.get("state", "unknown")).lower()
        references = set()
        for pr in prs:
            text = (pr.get("title") or "") + "\n" + (pr.get("body") or "")
            if number in _numbers(text) or number in set(pr.get("linked_issue_numbers", [])):
                references.add(int(pr["number"]))
        explicit = set(int(value) for value in issue.get("linked_pr_numbers", []))
        references |= explicit
        linked = []
        for pr_number in sorted(references):
            pr = pr_by_number.get(pr_number)
            if pr is None:
                linked.append({"number": pr_number, "state": "unavailable", "reason": "PR not present in snapshot"})
                continue
            linked.append({
                "number": pr_number,
                "state": pr.get("state", "unknown"),
                "draft": bool(pr.get("draft", False)),
                "head_sha": pr.get("head_sha") or "",
                "checks": pr.get("checks", []),
                "review_decision": pr.get("review_decision") or "unknown",
                "url": pr.get("url") or "",
            })
        dependencies = sorted((_numbers(body) | set(int(v) for v in issue.get("dependency_numbers", []))) - {number})
        unknown_dependencies = [value for value in dependencies if value not in issue_by_number]
        acceptance = issue.get("acceptance_criteria") or []
        blockers = []
        if not title.strip():
            blockers.append("missing title")
        if not body.strip():
            blockers.append("missing description")
        if unknown_dependencies:
            blockers.append("dependency references absent from snapshot")

        updated_at = issue.get("updated_at") or ""
        updated = _parse_timestamp(updated_at)
        age_days = None
        activity_state = "unknown"
        if updated and generated_at:
            age_days = max(0, (generated_at - updated).days)
            activity_state = "stale" if age_days >= stale_after_days else "recent"
        assignees = issue.get("assignees", [])
        has_owner = bool(assignees)
        if state == "open" and not has_owner:
            findings.append(Finding(
                code="issue.unowned",
                severity=Severity.WARNING,
                summary=f"Open issue #{number} has no assigned owner.",
                evidence=(str(number),),
                blocking=False,
            ))
        if state == "open" and activity_state == "stale":
            findings.append(Finding(
                code="issue.stale",
                severity=Severity.WARNING,
                summary=f"Open issue #{number} has had no recorded activity for {age_days} days.",
                evidence=(str(number), updated_at),
                blocking=False,
            ))
        if not linked and state == "open":
            findings.append(Finding(
                code="issue.unlinked",
                severity=Severity.WARNING,
                summary=f"Open issue #{number} has no linked pull request in the snapshot.",
                evidence=(str(number),),
                blocking=False,
            ))
        if state == "open" and not acceptance:
            findings.append(Finding(
                code="issue.acceptance_missing",
                severity=Severity.WARNING,
                summary=f"Open issue #{number} has no structured acceptance criteria.",
                evidence=(str(number),),
                blocking=False,
            ))
        records.append({
            "number": number,
            "title": title,
            "state": issue.get("state", "unknown"),
            "url": issue.get("url") or "",
            "labels": issue.get("labels", []),
            "assignees": assignees,
            "has_owner": has_owner,
            "dependencies": dependencies,
            "unknown_dependencies": unknown_dependencies,
            "linked_prs": linked,
            "acceptance_criteria": acceptance,
            "activity_at": updated_at,
            "activity_age_days": age_days,
            "activity_state": activity_state,
            "metadata_blockers": blockers,
        })

    return {
        "issues": records,
        "stale_after_days": stale_after_days,
        "open_issue_count": sum(str(item.get("state", "open")).lower() == "open" for item in issues),
        "unowned_open_issue_count": sum(record["state"] == "open" and not record["has_owner"] for record in records),
        "stale_open_issue_count": sum(record["state"] == "open" and record["activity_state"] == "stale" for record in records),
        "unlinked_open_issue_count": sum(record["state"] == "open" and not record["linked_prs"] for record in records),
        "findings": [item.to_dict() for item in findings],
    }
