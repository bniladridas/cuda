#!/usr/bin/env python3
"""Fail-closed, maintainer-authorized squash merge gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

GATE_CHECK_NAME = "squash-merge approval gate"
ASYNC_API_VERSION = "2026-03-10"


def latest_review_states(reviews: list[dict[str, Any]], expected_head: str) -> dict[str, str]:
    latest: dict[str, tuple[str, str]] = {}
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        state = str(review.get("state", "")).upper()
        submitted = str(review.get("submitted_at") or "")
        # Informational comments do not revoke an approval. Keep the latest
        # decisive review state for this head; CHANGES_REQUESTED and DISMISSED
        # still supersede an earlier approval.
        if not login or state in {"PENDING", "COMMENTED"} or review.get("commit_id") != expected_head:
            continue
        if login not in latest or submitted >= latest[login][0]:
            latest[login] = (submitted, state)
    return {login: value[1] for login, value in latest.items()}


def outstanding_change_request_reviewers(reviews: list[dict[str, Any]]) -> set[str]:
    """Return reviewers whose latest effective decision is still changes requested.

    A change request remains blocking across head updates. Only a later
    approval or explicit dismissal by that reviewer clears it; comments and
    pending reviews do not.
    """
    ordered = sorted(
        reviews,
        key=lambda review: (
            str(review.get("submitted_at") or ""),
            int(review.get("id") or 0),
        ),
    )
    blocking: set[str] = set()
    for review in ordered:
        login = (review.get("user") or {}).get("login", "")
        state = str(review.get("state", "")).upper()
        if not login or state == "PENDING":
            continue
        if state == "CHANGES_REQUESTED":
            blocking.add(login)
        elif state in {"APPROVED", "DISMISSED"}:
            blocking.discard(login)
    return blocking


def validate_state(
    *,
    pr: dict[str, Any],
    reviews: list[dict[str, Any]],
    check_runs: list[dict[str, Any]],
    combined_status: dict[str, Any],
    repo: str,
    target_branch: str,
    expected_head: str,
    actor: str,
    maintainers: set[str],
    approval_label: str,
    required_check_runs: set[str],
    required_status_contexts: set[str],
) -> list[str]:
    errors: list[str] = []
    if actor not in maintainers or actor.endswith("[bot]"):
        errors.append(f"Unauthorized approval actor: {actor}")
    if pr.get("state") != "open":
        errors.append("Pull request is not open")
    if pr.get("draft") is True:
        errors.append("Draft pull requests cannot be merged")
    if (pr.get("head") or {}).get("repo", {}).get("full_name") != repo:
        errors.append("Fork pull requests are report-only")
    if (pr.get("base") or {}).get("repo", {}).get("full_name") != repo:
        errors.append("Pull request base repository does not match")
    if (pr.get("base") or {}).get("ref") != target_branch:
        errors.append(f"Pull request must target {target_branch}")
    if (pr.get("head") or {}).get("sha") != expected_head:
        errors.append("Pull request head changed after approval")
    if pr.get("mergeable") is not True:
        errors.append("GitHub has not confirmed that the pull request is mergeable")
    if pr.get("mergeable_state") == "dirty":
        errors.append("GitHub reports merge conflicts with the target branch")
    labels = {label.get("name") for label in pr.get("labels", [])}
    if approval_label not in labels:
        errors.append("Squash-merge approval label is no longer present")

    blocking_reviewers = outstanding_change_request_reviewers(reviews)
    if blocking_reviewers:
        errors.append("Outstanding change-request review remains from: " + ", ".join(sorted(blocking_reviewers)))
    # Applying the trusted approval label is the maintainer's explicit
    # authorization. A separate GitHub review approval is not required.

    observed_names = {str(run.get("name", "")) for run in check_runs}
    missing_checks = sorted(required_check_runs - observed_names)
    if missing_checks:
        errors.append("Required check runs are missing: " + ", ".join(missing_checks))
    required_runs = [run for run in check_runs if run.get("name") in required_check_runs]
    unsuccessful_required = [
        f"{run.get('name')} ({run.get('status')}/{run.get('conclusion')})"
        for run in required_runs
        if run.get("status") != "completed" or run.get("conclusion") != "success"
    ]
    if unsuccessful_required:
        errors.append("Required checks are not successful: " + ", ".join(unsuccessful_required))
    failed_optional = [
        f"{run.get('name', 'unnamed check')} ({run.get('conclusion')})"
        for run in check_runs
        if run.get("name") not in required_check_runs
        and run.get("name") != GATE_CHECK_NAME
        and run.get("status") == "completed"
        and run.get("conclusion") not in {"success", "skipped", "neutral"}
    ]
    if failed_optional:
        errors.append("Checks have failed: " + ", ".join(failed_optional))

    statuses = combined_status.get("statuses", [])
    # GitHub's combined-status endpoint reports "pending" when a commit has
    # no legacy statuses, even if all required GitHub Actions check runs pass.
    # Only explicitly configured legacy contexts are authoritative here.
    observed_contexts = {str(status.get("context", "")) for status in statuses}
    missing_contexts = sorted(required_status_contexts - observed_contexts)
    if missing_contexts:
        errors.append("Required commit status contexts are missing: " + ", ".join(missing_contexts))
    failed_contexts = [
        f"{status.get('context', 'unnamed status')} ({status.get('state')})"
        for status in statuses
        if status.get("context") in required_status_contexts and status.get("state") != "success"
    ]
    if failed_contexts:
        errors.append("Required commit status contexts are not successful: " + ", ".join(failed_contexts))
    return errors


def is_already_merged(pr: dict[str, Any]) -> bool:
    """Return whether GitHub has already completed this pull request."""
    return pr.get("merged") is True


def gh_json(*args: str) -> Any:
    result = subprocess.run(
        ["gh", "api", *args],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    return json.loads(result.stdout)


def collect_state(
    repo: str, pr_number: int, head_sha: str
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    pr = gh_json(f"repos/{repo}/pulls/{pr_number}")
    review_pages = gh_json(
        f"repos/{repo}/pulls/{pr_number}/reviews",
        "--paginate",
        "--slurp",
    )
    reviews = [review for page in review_pages for review in page]
    check_pages = gh_json(
        f"repos/{repo}/commits/{head_sha}/check-runs",
        "--paginate",
        "--slurp",
        "-H",
        "Accept: application/vnd.github+json",
    )
    checks = [
        run
        for page in check_pages
        for run in page.get("check_runs", [])
        if run.get("name") != "squash-merge approval gate"
    ]
    status_pages = gh_json(
        f"repos/{repo}/commits/{head_sha}/status",
        "--paginate",
        "--slurp",
    )
    status = {
        "state": status_pages[0].get("state") if status_pages else None,
        "statuses": [status for page in status_pages for status in page.get("statuses", [])],
    }
    return pr, reviews, checks, status


def perform_squash_merge(
    repo: str, pr_number: int, head_sha: str, api=gh_json, sleep=time.sleep
) -> tuple[dict[str, Any] | None, str | None]:
    """Start one SHA-pinned async squash merge and poll until it settles.

    The asynchronous endpoint is required for stacked pull requests. The
    expected head SHA pins the merge to the approved commit.
    """
    headers = ("-H", f"X-GitHub-Api-Version: {ASYNC_API_VERSION}")
    try:
        request = api(
            f"repos/{repo}/pulls/{pr_number}/merge-async",
            "--method",
            "PUT",
            *headers,
            "-f",
            f"sha={head_sha}",
            "-f",
            "merge_method=squash",
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return None, f"GitHub rejected the squash merge request: {detail}"
    except Exception as exc:
        return None, f"Squash merge request failed: {exc}"
    status = request.get("status")
    if status == "merged":
        return {"merged": True, **request}, None
    request_id = request.get("uuid")
    if status != "pending" or not request_id:
        return None, f"GitHub did not accept an asynchronous squash merge: {request}"
    for _ in range(40):
        sleep(3)
        try:
            result = api(
                f"repos/{repo}/pulls/{pr_number}/merge-async/{request_id}",
                *headers,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            return None, f"GitHub squash merge status check failed: {detail}"
        except Exception as exc:
            return None, f"Squash merge status check failed: {exc}"
        status = result.get("status")
        if status == "merged":
            return {"merged": True, **result}, None
        if status != "pending":
            detail = (result.get("details") or {}).get("message") or result
            return None, f"GitHub asynchronous squash merge did not complete: {detail}"
    return None, "Timed out waiting for the asynchronous squash merge to finish."


def write_summary(title: str, errors: list[str], details: list[str] | None = None) -> None:
    lines = ["# " + title, "", *[f"- {error}" for error in errors]]
    if details:
        lines.extend(["", "## Audit", *[f"- {detail}" for detail in details]])
    Path(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null")).write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_details(
    actor: str,
    head_sha: str,
    pr: dict[str, Any],
    reviews: list[dict[str, Any]],
    checks: list[dict[str, Any]],
    status: dict[str, Any],
) -> list[str]:
    author = (pr.get("user") or {}).get("login")
    reviewers = sorted(
        login
        for login, state in latest_review_states(reviews, head_sha).items()
        if state == "APPROVED" and login != author and not login.endswith("[bot]")
    )
    return [
        f"Approval actor: @{actor}",
        f"Event head SHA: {head_sha}",
        f"Independent approving reviewers (informational): {', '.join('@' + name for name in reviewers) or 'none'}",
        f"Review submissions inspected: {len(reviews)}",
        f"Check runs inspected: {len(checks)}",
        f"Commit statuses inspected: {len(status.get('statuses', []))}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--event-head", required=True)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--config", default=".github/squash-merge.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if config.get("version") != 1 or config.get("merge_method") != "squash":
        raise SystemExit("Unsupported or unsafe squash-merge configuration")
    if config.get("target_branch") != args.target_branch:
        raise SystemExit("Workflow target branch does not match trusted policy")

    policy = {
        "repo": args.repo,
        "target_branch": args.target_branch,
        "expected_head": args.event_head,
        "actor": args.actor,
        "maintainers": set(config.get("maintainers", [])),
        "approval_label": config["approval_label"],
        "required_check_runs": set(config.get("required_check_runs", [])),
        "required_status_contexts": set(config.get("required_status_contexts", [])),
    }
    if not policy["required_check_runs"] and not policy["required_status_contexts"]:
        raise SystemExit("Trusted policy must define at least one required check or status context")
    # A label event can race with another merge workflow. Once GitHub confirms
    # the PR is merged, this event has no remaining work and must be a success.
    initial_pr = gh_json(f"repos/{args.repo}/pulls/{args.pr}")
    if is_already_merged(initial_pr):
        write_summary(
            "Squash merge skipped: pull request already merged",
            ["GitHub confirms this pull request was already merged; no further action was taken."],
        )
        print("Pull request is already merged; treating this event as a no-op.")
        return 0

    pr, reviews, checks, status = collect_state(args.repo, args.pr, args.event_head)
    errors = validate_state(
        pr=pr,
        reviews=reviews,
        check_runs=checks,
        combined_status=status,
        **policy,
    )
    if errors:
        if any("head changed" in error for error in errors):
            errors.append(
                "The approval label was preserved. Remove it, review the new head, then reapply it to create a fresh approval event."
            )
        write_summary(
            "Squash merge not performed",
            errors,
            audit_details(args.actor, args.event_head, pr, reviews, checks, status),
        )
        print("\n".join(errors), file=sys.stderr)
        return 1

    # Re-fetch all decision inputs immediately before the merge to close the
    # review/check/head race between initial validation and the write.
    latest, latest_reviews, latest_checks, latest_status = collect_state(args.repo, args.pr, args.event_head)
    errors = validate_state(
        pr=latest,
        reviews=latest_reviews,
        check_runs=latest_checks,
        combined_status=latest_status,
        **policy,
    )
    if errors:
        if any("head changed" in error for error in errors):
            errors.append(
                "The approval label was preserved. Remove it, review the new head, then reapply it to create a fresh approval event."
            )
        write_summary(
            "Squash merge not performed: state changed",
            errors,
            audit_details(args.actor, args.event_head, latest, latest_reviews, latest_checks, latest_status),
        )
        print("\n".join(errors), file=sys.stderr)
        return 1

    merge, merge_error = perform_squash_merge(args.repo, args.pr, args.event_head)
    if merge_error:
        write_summary(
            "Squash merge failed; approval label preserved",
            [merge_error],
            audit_details(args.actor, args.event_head, latest, latest_reviews, latest_checks, latest_status),
        )
        print(merge_error, file=sys.stderr)
        return 1

    # Consume the approval only after GitHub confirms the merge.
    subprocess.run(
        [
            "gh",
            "api",
            f"repos/{args.repo}/issues/{args.pr}/labels/{config['approval_label']}",
            "--method",
            "DELETE",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    reviewed_by = sorted(
        login
        for login, state in latest_review_states(latest_reviews, args.event_head).items()
        if state == "APPROVED" and login != (latest.get("user") or {}).get("login")
    )
    required_run_report = sorted(f"{name}: success" for name in policy["required_check_runs"])
    required_status_report = sorted(f"{name}: success" for name in policy["required_status_contexts"])
    body = (
        "Squash merge completed.\n\n"
        f"- Approved by: @{args.actor}\n"
        f"- Reviewed head: `{args.event_head}`\n"
        f"- Independent approving reviewers (informational): {', '.join('@' + name for name in reviewed_by)}\n"
        f"- Required check runs: {', '.join(required_run_report) or 'none configured'}\n"
        f"- Required status contexts: {', '.join(required_status_report) or 'none configured'}\n"
        f"- Check runs inspected: {len(latest_checks)}\n"
        f"- Commit statuses inspected: {len(latest_status.get('statuses', []))}\n"
        f"- Merge commit: `{merge.get('sha', 'unknown')}`\n"
        "- Merge method: squash\n"
        "- GitHub enforced the repository's configured merge rules."
    )
    subprocess.run(
        [
            "gh",
            "pr",
            "comment",
            str(args.pr),
            "--repo",
            args.repo,
            "--body",
            body,
        ],
        check=True,
        env=os.environ.copy(),
    )
    Path(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null")).write_text(
        "# Squash merge completed\n\n" + body + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"merged": True, "sha": merge.get("sha")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
