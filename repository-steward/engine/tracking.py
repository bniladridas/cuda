"""Read-only issue ownership, activity, dependency and closure-readiness analysis."""

import re
from datetime import datetime, timezone

from .contracts import Finding, Severity

ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")


def _numbers(text: str) -> set[int]:
    return {int(value) for value in ISSUE_REF.findall(text or "")}


def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _criteria_states(issue):
    criteria = issue.get("acceptance_criteria") or []
    explicit = issue.get("acceptance_criteria_status")
    if not isinstance(criteria, list) or not criteria:
        return []
    if isinstance(explicit, list) and len(explicit) == len(criteria):
        return [value if isinstance(value, bool) else None for value in explicit]
    states = []
    for item in criteria:
        if isinstance(item, dict):
            value = item.get("checked")
            states.append(value if isinstance(value, bool) else None)
        else:
            states.append(None)
    return states


def analyze_tracking(snapshot: dict, *, stale_after_days: int = 30) -> dict:
    issues = snapshot.get("issues", [])
    prs = snapshot.get("pull_requests", [])
    if not isinstance(issues, list) or not isinstance(prs, list):
        raise ValueError("snapshot issues and pull_requests must be lists")
    if not isinstance(stale_after_days, int) or isinstance(stale_after_days, bool) or stale_after_days < 1:
        raise ValueError("stale_after_days must be a positive integer")

    generated_at = _timestamp(snapshot.get("generated_at"))
    pr_by_number = {int(pr["number"]): pr for pr in prs if isinstance(pr, dict) and "number" in pr}
    issue_by_number = {int(issue["number"]): issue for issue in issues if isinstance(issue, dict) and "number" in issue}
    findings: list[Finding] = []
    records = []

    for issue in sorted(issues, key=lambda item: int(item.get("number", 0))):
        number = int(issue["number"])
        body = issue.get("body") or ""
        title = issue.get("title") or ""
        state = str(issue.get("state", "open")).lower()
        references = set()
        for pr in prs:
            text = (pr.get("title") or "") + "\n" + (pr.get("body") or "")
            if number in _numbers(text) or number in set(pr.get("linked_issue_numbers", [])):
                references.add(int(pr["number"]))
        references |= set(int(value) for value in issue.get("linked_pr_numbers", []))
        linked = []
        for pr_number in sorted(references):
            pr = pr_by_number.get(pr_number)
            if pr is None:
                linked.append(
                    {
                        "number": pr_number,
                        "state": "unknown",
                        "merge_state": "unknown",
                        "reason": "PR not present in snapshot",
                    }
                )
                continue
            merged = pr.get("merged") is True or pr.get("merge_state") == "merged"
            pr_state = str(pr.get("state", "unknown")).lower()
            merge_state = (
                "merged"
                if merged
                else "open"
                if pr_state == "open"
                else "closed_unmerged"
                if pr_state == "closed"
                else "unknown"
            )
            linked.append(
                {
                    "number": pr_number,
                    "state": pr_state,
                    "merge_state": merge_state,
                    "draft": bool(pr.get("draft", False)),
                    "head_sha": pr.get("head_sha") or "",
                    "checks": pr.get("checks", []),
                    "review_decision": pr.get("review_decision") or "unknown",
                    "url": pr.get("url") or "",
                }
            )

        dependencies = sorted((_numbers(body) | set(int(v) for v in issue.get("dependency_numbers", []))) - {number})
        unknown_dependencies = [value for value in dependencies if value not in issue_by_number]
        open_dependencies = [
            value
            for value in dependencies
            if value in issue_by_number and str(issue_by_number[value].get("state", "unknown")).lower() != "closed"
        ]
        acceptance = issue.get("acceptance_criteria") or []
        criteria_states = _criteria_states(issue)
        metadata_blockers = []
        if not title.strip():
            metadata_blockers.append("missing title")
        if not body.strip():
            metadata_blockers.append("missing description")

        activity_at = issue.get("updated_at") or ""
        updated = _timestamp(activity_at)
        activity_age_days = None
        activity_state = "unknown"
        if generated_at and updated:
            activity_age_days = max(0, (generated_at - updated).days)
            activity_state = "stale" if activity_age_days >= stale_after_days else "recent"

        owner_present = bool(issue.get("assignees"))
        if state == "open" and not owner_present:
            findings.append(
                Finding(
                    code="issue.unowned",
                    severity=Severity.WARNING,
                    summary=f"Open issue #{number} has no assignee.",
                    evidence=(str(number),),
                    blocking=False,
                )
            )
        if state == "open" and activity_state == "stale":
            findings.append(
                Finding(
                    code="issue.stale_activity",
                    severity=Severity.WARNING,
                    summary=f"Open issue #{number} has had no recorded activity for {activity_age_days} days.",
                    evidence=(str(number), activity_at),
                    blocking=False,
                )
            )
        if state == "open" and not linked:
            findings.append(
                Finding(
                    code="issue.unlinked",
                    severity=Severity.WARNING,
                    summary=f"Open issue #{number} has no linked pull request in the snapshot.",
                    evidence=(str(number),),
                    blocking=False,
                )
            )
        if state == "open" and not acceptance:
            findings.append(
                Finding(
                    code="issue.acceptance_missing",
                    severity=Severity.WARNING,
                    summary=f"Open issue #{number} has no structured acceptance criteria.",
                    evidence=(str(number),),
                    blocking=False,
                )
            )

        closure_blockers = list(metadata_blockers)
        if not acceptance:
            closure_blockers.append("acceptance criteria are missing")
        elif not criteria_states or any(value is not True for value in criteria_states):
            closure_blockers.append("acceptance criteria are not all explicitly checked")
        if unknown_dependencies:
            closure_blockers.append("dependency references are absent from the snapshot")
        if open_dependencies:
            closure_blockers.append("one or more dependencies remain open")
        if any(item["merge_state"] != "merged" for item in linked):
            closure_blockers.append("one or more linked pull requests are not verified merged")
        closure_ready = state == "open" and not closure_blockers
        records.append(
            {
                "number": number,
                "title": title,
                "state": state,
                "url": issue.get("url") or "",
                "labels": issue.get("labels", []),
                "assignees": issue.get("assignees", []),
                "owner_present": owner_present,
                "dependencies": dependencies,
                "unknown_dependencies": unknown_dependencies,
                "open_dependencies": open_dependencies,
                "linked_prs": linked,
                "acceptance_criteria": acceptance,
                "acceptance_criteria_status": criteria_states,
                "activity_at": activity_at,
                "activity_age_days": activity_age_days,
                "activity_state": activity_state,
                "metadata_blockers": metadata_blockers,
                "closure_readiness": {
                    "status": "candidate" if closure_ready else "not_ready",
                    "candidate": closure_ready,
                    "human_review_required": True,
                    "blockers": closure_blockers,
                    "issue_mutation_performed": False,
                },
            }
        )

    return {
        "issues": records,
        "open_issue_count": sum(str(item.get("state", "open")).lower() == "open" for item in issues),
        "unlinked_open_issue_count": sum(record["state"] == "open" and not record["linked_prs"] for record in records),
        "unowned_open_issue_count": sum(
            record["state"] == "open" and not record["owner_present"] for record in records
        ),
        "stale_open_issue_count": sum(
            record["state"] == "open" and record["activity_state"] == "stale" for record in records
        ),
        "closure_candidate_count": sum(record["closure_readiness"]["candidate"] for record in records),
        "stale_after_days": stale_after_days,
        "findings": [item.to_dict() for item in findings],
        "mutations_performed": False,
    }
