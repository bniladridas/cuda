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
            linked.append(
                {
                    "number": pr_number,
                    "state": pr.get("state", "unknown"),
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
