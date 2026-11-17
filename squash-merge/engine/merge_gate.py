#!/usr/bin/env python3
"""Fail-closed, maintainer-authorized squash merge gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def latest_review_states(reviews: list[dict[str, Any]]) -> dict[str, str]:
    latest: dict[str, tuple[str, str]] = {}
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        state = str(review.get("state", "")).upper()
        submitted = str(review.get("submitted_at") or "")
        if not login or state == "PENDING":
            continue
        if login not in latest or submitted >= latest[login][0]:
            latest[login] = (submitted, state)
    return {login: value[1] for login, value in latest.items()}


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
    if pr.get("mergeable_state") != "clean":
        errors.append(f"GitHub mergeable state is not clean: {pr.get('mergeable_state')}")
    labels = {label.get("name") for label in pr.get("labels", [])}
    if approval_label not in labels:
        errors.append("Squash-merge approval label is no longer present")

    author = (pr.get("user") or {}).get("login")
    states = latest_review_states(reviews)
    if any(state == "CHANGES_REQUESTED" for state in states.values()):
        errors.append("An outstanding change-request review remains")
    approvals = {
        login
        for login, state in states.items()
        if state == "APPROVED" and login != author and not login.endswith("[bot]")
    }
    if not approvals:
        errors.append("At least one approval from a non-author, non-bot reviewer is required")

    unfinished = [
        run.get("name", "unnamed check")
        for run in check_runs
        if run.get("status") != "completed"
    ]
    if unfinished:
        errors.append("Checks are still running: " + ", ".join(unfinished))
    unsuccessful = [
        f"{run.get('name', 'unnamed check')} ({run.get('conclusion')})"
        for run in check_runs
        if run.get("status") == "completed"
        and run.get("conclusion") not in {"success", "skipped", "neutral"}
    ]
    if unsuccessful:
        errors.append("Checks have not passed: " + ", ".join(unsuccessful))
    statuses = combined_status.get("statuses", [])
    if statuses and combined_status.get("state") != "success":
        errors.append(f"Combined commit status is {combined_status.get('state')}")
    return errors


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
    status = gh_json(f"repos/{repo}/commits/{head_sha}/status?per_page=100")
    return pr, reviews, checks, status


def write_summary(title: str, errors: list[str]) -> None:
    summary = "# " + title + "\n\n" + "\n".join(f"- {error}" for error in errors) + "\n"
    Path(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null")).write_text(
        summary, encoding="utf-8"
    )


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
    }
    pr, reviews, checks, status = collect_state(
        args.repo, args.pr, args.event_head
    )
    errors = validate_state(
        pr=pr,
        reviews=reviews,
        check_runs=checks,
        combined_status=status,
        **policy,
    )
    if errors:
        write_summary("Squash merge not performed", errors)
        print("\n".join(errors), file=sys.stderr)
        return 1

    # Re-fetch all decision inputs immediately before the merge to close the
    # review/check/head race between initial validation and the write.
    latest, latest_reviews, latest_checks, latest_status = collect_state(
        args.repo, args.pr, args.event_head
    )
    errors = validate_state(
        pr=latest,
        reviews=latest_reviews,
        check_runs=latest_checks,
        combined_status=latest_status,
        **policy,
    )
    if errors:
        write_summary("Squash merge not performed: state changed", errors)
        print("\n".join(errors), file=sys.stderr)
        return 1

    merge = gh_json(
        f"repos/{args.repo}/pulls/{args.pr}/merge",
        "--method",
        "PUT",
        "-f",
        f"sha={args.event_head}",
        "-f",
        "merge_method=squash",
    )
    if merge.get("merged") is not True:
        raise SystemExit("GitHub did not confirm a successful squash merge")

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
    body = (
        "Squash merge completed.\n\n"
        f"- Approved by: @{args.actor}\n"
        f"- Reviewed head: `{args.event_head}`\n"
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
