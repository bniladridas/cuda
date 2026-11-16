#!/usr/bin/env python3
"""Evidence-based issue landing reports with an explicitly approved close path."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ENVIRONMENT_NAME = "issue-landing-close"
CRITERIA_HEADING = re.compile(r"^#{1,6}\s+.*\bacceptance criteria\b.*$", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(?:\[[ xX]\]\s*)?(.+?)\s*$")


class LandingError(Exception):
    """A fail-closed report or approval error."""


def run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise LandingError("cannot run %s: %s" % (command[0], exc)) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown error").strip()[:600]
        raise LandingError("command failed (%s): %s" % (" ".join(command[:3]), detail))
    return result.stdout


def gh_json(path, paginate=False):
    command = ["gh", "api", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        command += ["--paginate", "--slurp"]
    raw = run(command + [path])
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise LandingError("GitHub returned invalid JSON for %s" % path) from exc
    if paginate:
        if not isinstance(value, list):
            raise LandingError("paginated response was not a list: %s" % path)
        return [item for page in value if isinstance(page, list) for item in page]
    return value


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_digest(issue):
    return sha256_text(canonical_json({"title": issue.get("title") or "", "body": issue.get("body") or ""}))


def extract_acceptance_criteria(body, comments=None):
    """Extract criterion lists from the issue body and comments.

    This is deliberately not a semantic verifier. Every item, including a
    checked box, remains human-review-required.
    """
    sources = [{"source": "issue body", "url": "", "author": "", "body": body or ""}]
    for comment in comments or []:
        sources.append(
            {
                "source": "issue comment",
                "url": comment.get("html_url") or "",
                "author": (comment.get("user") or {}).get("login") or "unknown",
                "body": comment.get("body") or "",
            }
        )
    criteria = []
    for source in sources:
        in_section = False
        for line in source["body"].splitlines():
            if re.match(r"^\s*#{1,6}\s+", line):
                if in_section:
                    break
                in_section = bool(CRITERIA_HEADING.match(line))
                continue
            if in_section:
                match = LIST_ITEM.match(line)
                if match:
                    criteria.append(
                        {
                            "text": match.group(1).strip(),
                            "status": "human review required",
                            "evidence": [],
                            "source": source["source"],
                            "url": source["url"],
                            "author": source["author"],
                        }
                    )
    if not criteria:
        criteria.append(
            {
                "text": "No machine-verifiable acceptance criterion was extracted. Review the issue manually.",
                "status": "human review required",
                "evidence": [],
                "source": "manual review",
                "url": "",
                "author": "",
            }
        )
    return criteria


def source_issue_comments(comments):
    """Exclude this workflow's own report comments from approval evidence."""
    return [
        comment
        for comment in comments
        if not (
            (comment.get("user") or {}).get("login") == "github-actions[bot]"
            and (comment.get("body") or "").startswith("## Issue landing report")
        )
    ]


def issue_comment_digest(comments):
    records = [
        {
            "id": comment.get("id"),
            "updated_at": comment.get("updated_at") or comment.get("created_at") or "",
            "body_sha256": sha256_text(comment.get("body") or ""),
        }
        for comment in comments
    ]
    return sha256_text(canonical_json(records))


def relevant_comment_evidence(comments):
    """Surface comments that may contain implementation evidence without trusting them."""
    evidence = []
    pattern = re.compile(
        r"\b(acceptance|implemented|merged|tested|validation|verified|evidence|commit|pull request)\b|\bPR\s*#\d+",
        re.I,
    )
    for comment in comments:
        body = re.sub(r"\s+", " ", comment.get("body") or "").strip()
        if not body or not pattern.search(body):
            continue
        evidence.append(
            {
                "author": (comment.get("user") or {}).get("login") or "unknown",
                "url": comment.get("html_url") or "",
                "created_at": comment.get("created_at") or "",
                "excerpt": body[:500],
                "status": "human review required",
            }
        )
    return evidence


ISSUE_REFERENCE = re.compile(
    r"(?<![\w/])#(?P<number>\d+)\b"
    r"|https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)/issues/(?P<url_number>\d+)",
    re.I,
)


def issue_reference_candidates(texts, current_repo):
    """Collect candidate issue numbers explicitly mentioned by the PR itself."""
    numbers = set()
    owner, name = current_repo.split("/", 1)
    for body in texts:
        for match in ISSUE_REFERENCE.finditer(body or ""):
            if match.group("url_number"):
                if (match.group("owner").lower(), match.group("repo").lower()) != (
                    owner.lower(),
                    name.lower(),
                ):
                    continue
                numbers.add(int(match.group("url_number")))
            else:
                numbers.add(int(match.group("number")))
    return sorted(numbers)


def explicit_issue_numbers(current_repo, pull_request_number):
    """Verify PR-mentioned issue candidates against each issue's own timeline."""
    pr = gh_json("repos/%s/pulls/%d" % (current_repo, pull_request_number))
    comments = gh_json(
        "repos/%s/issues/%d/comments?per_page=100" % (current_repo, pull_request_number),
        paginate=True,
    )
    texts = [pr.get("title") or "", pr.get("body") or ""] + [comment.get("body") or "" for comment in comments]
    candidates = issue_reference_candidates(texts, current_repo)
    confirmed = set()
    for issue_number in candidates:
        timeline = gh_json(
            "repos/%s/issues/%d/timeline?per_page=100" % (current_repo, issue_number),
            paginate=True,
        )
        for event in timeline:
            if event.get("event") != "cross-referenced":
                continue
            source = (event.get("source") or {}).get("issue") or {}
            repository = (source.get("repository") or {}).get("full_name")
            if (
                int(source.get("number") or 0) == pull_request_number
                and source.get("pull_request")
                and repository
                and repository.lower() == current_repo.lower()
            ):
                confirmed.add(issue_number)
                break
    return sorted(confirmed)


def linked_pull_request_numbers(timeline):
    """Find PRs explicitly cross-referenced from an issue timeline."""
    numbers = set()
    for event in timeline:
        if event.get("event") != "cross-referenced":
            continue
        issue = (event.get("source") or {}).get("issue") or {}
        if issue.get("pull_request") and issue.get("number"):
            numbers.add(int(issue["number"]))
    return sorted(numbers)


def pull_request_snapshot(repo, number, default_branch):
    raw = gh_json("repos/%s/pulls/%d" % (repo, number))
    merged_at = raw.get("merged_at")
    merge_sha = raw.get("merge_commit_sha")
    reachability = "not_applicable"
    compare_status = None
    if merged_at and merge_sha:
        compare = gh_json("repos/%s/compare/%s...%s" % (repo, merge_sha, default_branch))
        compare_status = compare.get("status")
        reachability = "reachable" if compare_status in {"ahead", "identical"} else "not reachable"
    elif merged_at:
        reachability = "unknown: merge commit SHA unavailable"
    return {
        "number": int(raw.get("number") or number),
        "url": raw.get("html_url") or "",
        "title": raw.get("title") or "",
        "state": raw.get("state") or "unknown",
        "draft": bool(raw.get("draft")),
        "merged_at": merged_at,
        "head_sha": (raw.get("head") or {}).get("sha") or "",
        "base_branch": (raw.get("base") or {}).get("ref") or "",
        "base_sha": (raw.get("base") or {}).get("sha") or "",
        "merge_commit_sha": merge_sha or "",
        "default_branch_reachability": reachability,
        "compare_status": compare_status,
        "landed": bool(merged_at and merge_sha and reachability == "reachable"),
    }


def report_payload(repo, issue_number, allow_closed=False):
    repository = gh_json("repos/%s" % repo)
    default_branch = repository.get("default_branch")
    if not default_branch:
        raise LandingError("repository default branch is unavailable")
    branch = gh_json("repos/%s/commits/%s" % (repo, default_branch))
    default_sha = branch.get("sha")
    if not default_sha:
        raise LandingError("default branch head SHA is unavailable")
    issue = gh_json("repos/%s/issues/%d" % (repo, issue_number))
    if issue.get("pull_request"):
        raise LandingError("#%d is a pull request, not an issue" % issue_number)
    if issue.get("state") != "open" and not allow_closed:
        raise LandingError("issue #%d is not open; refusing to create a close report" % issue_number)
    timeline = gh_json("repos/%s/issues/%d/timeline?per_page=100" % (repo, issue_number), paginate=True)
    comments = gh_json("repos/%s/issues/%d/comments?per_page=100" % (repo, issue_number), paginate=True)
    source_comments = source_issue_comments(comments)
    prs = [pull_request_snapshot(repo, n, default_branch) for n in linked_pull_request_numbers(timeline)]
    return {
        "schema_version": 1,
        "repo": repo,
        "issue": {
            "number": int(issue.get("number") or issue_number),
            "title": issue.get("title") or "",
            "url": issue.get("html_url") or "",
            "state": issue.get("state") or "",
            "digest": issue_digest(issue),
        },
        "default_branch": {"name": default_branch, "sha": default_sha},
        "pull_requests": prs,
        "issue_comments": {
            "count": len(source_comments),
            "digest": issue_comment_digest(source_comments),
            "evidence": relevant_comment_evidence(source_comments),
        },
        "acceptance_criteria": extract_acceptance_criteria(issue.get("body") or "", source_comments),
    }


def report_digest(payload):
    stable = {key: value for key, value in payload.items() if key not in {"generated_at", "report_digest"}}
    return sha256_text(canonical_json(stable))


def build_report(repo, issue_number, allow_closed=False):
    payload = report_payload(repo, issue_number, allow_closed=allow_closed)
    payload["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload["report_digest"] = report_digest(payload)
    return payload


def markdown_report(report):
    issue = report["issue"]
    branch = report["default_branch"]
    tick = chr(96)
    lines = [
        "## Issue landing report",
        "",
        "**Issue:** [#%d: %s](%s)" % (issue["number"], issue["title"], issue["url"]),
        "**Report digest:** %s%s%s" % (tick, report["report_digest"], tick),
        "**Issue title/body SHA-256:** %s%s%s" % (tick, issue["digest"], tick),
        "**Default branch:** %s%s%s at %s%s%s" % (tick, branch["name"], tick, tick, branch["sha"], tick),
        "",
        "### Linked pull requests",
        "",
    ]
    if not report["pull_requests"]:
        lines.append("No explicitly cross-referenced pull requests were found.")
    else:
        lines += [
            "| PR | State | Head | Base branch | Base SHA | Merge commit | Default-branch reachability | Landing |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for pr in report["pull_requests"]:
            state = "draft" if pr["draft"] else pr["state"]
            lines.append(
                "| [#%d](%s) | %s | %s%s%s | %s%s%s | %s%s%s | %s%s%s | %s | %s |"
                % (
                    pr["number"],
                    pr["url"],
                    state,
                    tick,
                    pr["head_sha"][:12],
                    tick,
                    tick,
                    pr["base_branch"],
                    tick,
                    tick,
                    pr["base_sha"][:12],
                    tick,
                    tick,
                    pr["merge_commit_sha"][:12],
                    tick,
                    pr["default_branch_reachability"],
                    "landed" if pr["landed"] else "not verified as landed",
                )
            )
    lines += ["", "### Relevant issue comments", ""]
    if report["issue_comments"]["evidence"]:
        for item in report["issue_comments"]["evidence"]:
            excerpt = item["excerpt"].replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|")
            lines.append("- [Comment by %s](%s): %s" % (item["author"], item["url"], excerpt))
    else:
        lines.append("No comments with explicit implementation or validation language were found.")
    lines += [
        "",
        "**Issue comments inspected:** %d (SHA-256: `%s`)"
        % (report["issue_comments"]["count"], report["issue_comments"]["digest"]),
        "",
        "### Acceptance criteria",
        "",
        "| Criterion | Status | Source |",
        "| --- | --- | --- |",
    ]
    for item in report["acceptance_criteria"]:
        source = item.get("source") or "manual review"
        if item.get("url"):
            source = "[%s](%s)" % (source, item["url"])
        lines.append(
            "| %s | %s | %s |" % (item["text"].replace("|", "\\|"), item["status"], source.replace("|", "\\|"))
        )
    lines += [
        "",
        "> This report verifies GitHub state only. It does not decide whether implementation behavior satisfies an acceptance criterion. A merged PR alone is not proof of completion.",
        "",
        "A close action, when enabled, requires separate approval on the protected %sissue-landing-close%s environment. The close job re-fetches the issue, linked PRs and default-branch head and aborts if this report is stale."
        % (tick, tick),
    ]
    return "\n".join(lines) + "\n"


def write_report(report, output_dir):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    number = report["issue"]["number"]
    (directory / ("issue-%d.json" % number)).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (directory / ("issue-%d.md" % number)).write_text(markdown_report(report), encoding="utf-8")


def command_report(args):
    if args.issue_number:
        numbers = [args.issue_number]
        allow_closed = False
    else:
        pr = gh_json("repos/%s/pulls/%d" % (args.repo, args.pull_request_number))
        if not pr.get("merged_at"):
            raise LandingError("pull request #%d is not merged" % args.pull_request_number)
        numbers = explicit_issue_numbers(args.repo, args.pull_request_number)
        allow_closed = True
        if not numbers:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            (Path(args.output_dir) / "NO_LINKED_ISSUES.md").write_text(
                "No explicitly cross-referenced issues were found for PR #%d.\n" % args.pull_request_number,
                encoding="utf-8",
            )
            return
    for number in numbers:
        write_report(build_report(args.repo, number, allow_closed=allow_closed), args.output_dir)
    print("Generated landing reports for: %s" % ", ".join("#%d" % n for n in numbers))


def validate_approved_report(approved, repo, issue_number, approved_digest):
    if approved.get("repo") != repo or approved.get("issue", {}).get("number") != issue_number:
        raise LandingError("approved report does not identify this repository and issue")
    if approved.get("report_digest") != report_digest(approved):
        raise LandingError("approved report digest is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", approved_digest or ""):
        raise LandingError("an exact 64-character report digest is required for approval")
    if approved_digest != approved.get("report_digest"):
        raise LandingError("approval digest does not match this issue report revision")


def command_close(args):
    try:
        approved = json.loads(Path(args.report).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LandingError("cannot read approved report: %s" % exc) from exc
    validate_approved_report(approved, args.repo, args.issue_number, args.approved_digest)
    current = build_report(args.repo, args.issue_number)
    if current["report_digest"] != approved["report_digest"]:
        raise LandingError(
            "approved report is stale: issue, linked PR state, or default-branch head changed; generate a fresh report and approval"
        )
    run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            "repos/%s/issues/%d" % (args.repo, args.issue_number),
            "-f",
            "state=closed",
            "-f",
            "state_reason=completed",
        ]
    )
    print("Closed issue #%d after explicit digest approval and stale-state revalidation." % args.issue_number)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="generate a read-only issue landing report")
    report.add_argument("--repo", required=True)
    selection = report.add_mutually_exclusive_group(required=True)
    selection.add_argument("--issue-number", type=int)
    selection.add_argument("--pull-request-number", type=int)
    report.add_argument("--output-dir", default="reports")
    report.set_defaults(function=command_report)
    close = sub.add_parser("close", help="close one issue after protected approval")
    close.add_argument("--repo", required=True)
    close.add_argument("--issue-number", required=True, type=int)
    close.add_argument("--report", required=True)
    close.add_argument("--approved-digest", required=True)
    close.set_defaults(function=command_close)
    return root


def main():
    args = parser().parse_args()
    if not args.repo or "/" not in args.repo:
        raise SystemExit("repository must be owner/name")
    try:
        args.function(args)
    except LandingError as exc:
        print("issue-landing: %s" % exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
