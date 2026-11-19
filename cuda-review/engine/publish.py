#!/usr/bin/env python3
"""Validate a model report and prepare a comment-only GitHub PR review."""

import argparse
import json
from pathlib import Path


def added_lines(diff):
    """Return added new-side line numbers for each changed path."""
    result = {}
    path = None
    new_line = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            result.setdefault(path, set())
            new_line = None
        elif line.startswith("+++ "):
            path = None
            new_line = None
        elif line.startswith("@@"):
            try:
                new_range = line.split(" +", 1)[1].split(" ", 1)[0]
                start = new_range.split(",", 1)[0]
                new_line = int(start)
            except (IndexError, ValueError):
                path = None
                new_line = None
        elif path is not None and new_line is not None:
            if line.startswith("+") and not line.startswith("+++"):
                result[path].add(new_line)
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                continue
            elif line.startswith("\\"):
                continue
            else:
                new_line += 1
    return result


def build_review(report, diff, commit_id):
    if not isinstance(report, dict):
        raise ValueError("review report must be an object")
    if report.get("patch_applied") is not False:
        raise ValueError("review report must not contain a patch")
    if report.get("complete_diff_supplied") is not True:
        raise ValueError("review did not inspect the complete diff")
    if report.get("complete_file_inventory") is not True:
        raise ValueError("review did not inspect the complete changed-file inventory")
    if not isinstance(commit_id, str) or len(commit_id) != 40:
        raise ValueError("commit id must be a full Git SHA")

    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")
    additions = added_lines(diff)
    comments = []
    summary_findings = []
    allowed_severity = {"critical", "high", "medium", "low", "info"}

    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("each finding must be an object")
        severity = finding.get("severity")
        path = finding.get("path")
        line = finding.get("line")
        reason = finding.get("reason")
        confidence = finding.get("confidence")
        if severity not in allowed_severity:
            raise ValueError("finding has an invalid severity")
        if not isinstance(path, str) or path not in additions:
            raise ValueError("finding must reference a changed file")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise ValueError("finding line must be a positive integer")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 3000:
            raise ValueError("finding reason must be 1 to 3000 characters")
        if confidence not in {"low", "medium", "high"}:
            raise ValueError("finding has an invalid confidence")
        entry = {
            "severity": severity,
            "path": path,
            "line": line,
            "reason": reason.strip(),
            "confidence": confidence,
        }
        if line in additions[path]:
            comments.append(
                {
                    "path": path,
                    "line": line,
                    "side": "RIGHT",
                    "body": "**%s severity** (%s confidence): %s" % (severity.upper(), confidence, reason.strip()),
                }
            )
        else:
            summary_findings.append(entry)

    summary = report.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 5000:
        raise ValueError("review summary must be 1 to 5000 characters")
    model = report.get("model", "configured OpenRouter model")
    body = [
        "## CUDA Review",
        "",
        summary.strip(),
        "",
        "**Model:** `%s`" % str(model)[:200],
        "**Findings:** %d" % len(findings),
    ]
    if summary_findings:
        body.extend(["", "### Findings without an inline anchor"])
        for item in summary_findings:
            body.append(
                "- **%s** `%s:%d` (%s confidence): %s"
                % (
                    item["severity"].upper(),
                    item["path"],
                    item["line"],
                    item["confidence"],
                    item["reason"],
                )
            )
    if not findings:
        body.extend(["", "No actionable findings were identified in the reviewed diff."])
    body.extend(
        [
            "",
            "This is an advisory model review, not an approval. CI and human review remain required.",
            "",
            "<!-- cuda-review:%s -->" % commit_id,
        ]
    )
    return {"commit_id": commit_id, "body": "\n".join(body), "event": "COMMENT", "comments": comments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--diff", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    diff = Path(args.diff).read_text(encoding="utf-8", errors="replace")
    payload = build_review(report, diff, args.commit)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
