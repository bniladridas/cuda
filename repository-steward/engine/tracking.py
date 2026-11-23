"""Read-only issue and pull-request tracking over a normalized GitHub snapshot."""

import re

from .contracts import Finding, Severity

ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")


def _numbers(text: str) -> set[int]:
    return {int(value) for value in ISSUE_REF.findall(text or "")}


def analyze_tracking(snapshot: dict) -> dict:
    issues = snapshot.get("issues", [])
    prs = snapshot.get("pull_requests", [])
    if not isinstance(issues, list) or not isinstance(prs, list):
        raise ValueError("snapshot issues and pull_requests must be lists")

    pr_by_number = {int(pr["number"]): pr for pr in prs if "number" in pr}
    issue_by_number = {int(issue["number"]): issue for issue in issues if "number" in issue}
    findings: list[Finding] = []
    records = []

    for issue in sorted(issues, key=lambda item: int(item.get("number", 0))):
        number = int(issue["number"])
        body = issue.get("body") or ""
        title = issue.get("title") or ""
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
                linked.append(
                    {
                        "number": pr_number,
                        "state": "unavailable",
                        "reason": "PR not present in snapshot",
                    }
                )
                continue
            state = str(pr.get("state") or "unknown").lower()
            merged_at = pr.get("merged_at") or ""
            merge_status = pr.get("merge_status") or (
                "merged" if merged_at else "unknown"
            )
            linked.append(
                {
                    "number": pr_number,
                    "state": state,
                    "merge_status": merge_status,
                    "merged_at": merged_at,
                    "merge_commit_sha": pr.get("merge_commit_sha") or "",
                    "base_ref": pr.get("base_ref") or "",
                    "base_sha": pr.get("base_sha") or "",
                    "draft": bool(pr.get("draft", False)),
                    "head_sha": pr.get("head_sha") or "",
                    "checks": pr.get("checks", []),
                    "review_decision": pr.get("review_decision") or "unknown",
                    "url": pr.get("url") or "",
                }
            )
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
        if not linked and str(issue.get("state", "open")).lower() == "open":
            findings.append(
                Finding(
                    code="issue.unlinked",
                    severity=Severity.WARNING,
                    summary=f"Open issue #{number} has no linked pull request in the snapshot.",
                    evidence=(str(number),),
                    blocking=False,
                )
            )
        if str(issue.get("state", "open")).lower() == "open" and not acceptance:
            findings.append(
                Finding(
                    code="issue.acceptance_missing",
                    severity=Severity.WARNING,
                    summary=f"Open issue #{number} has no structured acceptance criteria.",
                    evidence=(str(number),),
                    blocking=False,
                )
            )
        criteria_status = issue.get("acceptance_criteria_status") or [
            {"text": item, "state": "unverified"} for item in acceptance
        ]
        closure_blockers = []
        closure_unknowns = []
        if not acceptance:
            closure_blockers.append("acceptance criteria are missing")
        for criterion in criteria_status:
            if criterion.get("state") == "incomplete":
                closure_blockers.append(f"acceptance criterion is incomplete: {criterion.get('text', '')}")
            elif criterion.get("state") != "complete":
                closure_unknowns.append(f"acceptance criterion is not explicitly checked: {criterion.get('text', '')}")
        if not linked:
            closure_blockers.append("no linked pull request")
        for pr in linked:
            status = pr.get("merge_status", "unknown")
            if status == "open":
                closure_blockers.append(f"linked PR #{pr['number']} is still open")
            elif status == "closed_unmerged":
                closure_blockers.append(f"linked PR #{pr['number']} was closed without merging")
            elif status != "merged":
                closure_unknowns.append(f"merge state for linked PR #{pr['number']} is unknown")
        for dependency in dependencies:
            dependency_issue = issue_by_number.get(dependency)
            if dependency_issue is None:
                closure_unknowns.append(f"dependency issue #{dependency} is absent from snapshot")
            elif str(dependency_issue.get("state", "unknown")).lower() != "closed":
                closure_blockers.append(f"dependency issue #{dependency} is not closed")
        if closure_blockers:
            closure_state = "blocked"
        elif closure_unknowns:
            closure_state = "unknown"
        else:
            closure_state = "ready_for_human_review"

        records.append(
            {
                "number": number,
                "title": title,
                "state": issue.get("state", "unknown"),
                "url": issue.get("url") or "",
                "labels": issue.get("labels", []),
                "assignees": issue.get("assignees", []),
                "dependencies": dependencies,
                "unknown_dependencies": unknown_dependencies,
                "linked_prs": linked,
                "acceptance_criteria": acceptance,
                "acceptance_criteria_status": criteria_status,
                "closure_readiness": {
                    "state": closure_state,
                    "ready_for_human_review": closure_state == "ready_for_human_review",
                    "blockers": closure_blockers,
                    "unknowns": closure_unknowns,
                    "closure_performed": False,
                },
                "activity_at": issue.get("updated_at") or "",
                "metadata_blockers": blockers,
            }
        )

    return {
        "issues": records,
        "open_issue_count": sum(str(item.get("state", "open")).lower() == "open" for item in issues),
        "unlinked_open_issue_count": sum(record["state"] == "open" and not record["linked_prs"] for record in records),
        "findings": [item.to_dict() for item in findings],
    }
