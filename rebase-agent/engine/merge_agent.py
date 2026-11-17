#!/usr/bin/env python3
"""Separately authorized, non-rewriting merge-based PR branch integration."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


class MergeError(Exception):
    """A safe merge-based integration could not be completed."""


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def validate_request(request):
    required = (
        "repository",
        "head_repository",
        "branch",
        "base_branch",
        "expected_head_sha",
        "expected_base_sha",
    )
    missing = [key for key in required if not request.get(key)]
    if missing:
        raise MergeError("missing required metadata: " + ", ".join(missing))
    if request["repository"].lower() != request["head_repository"].lower():
        raise MergeError("fork PR branches cannot be modified")
    if request["branch"] == request.get("default_branch"):
        raise MergeError("default branch cannot be modified")
    if request["branch"] in set(request.get("protected_branches") or []):
        raise MergeError("protected branches cannot be modified")
    if request["branch"] == request["base_branch"]:
        raise MergeError("PR branch cannot be its base branch")
    for key in ("branch", "base_branch"):
        value = request[key]
        if not REF_RE.fullmatch(value) or ".." in value or value.endswith("/"):
            raise MergeError("invalid " + key.replace("_", " ") + " name")
    for key in ("expected_head_sha", "expected_base_sha"):
        if not SHA_RE.fullmatch(request[key]):
            raise MergeError(key + " must be a full 40-character commit SHA")
    if request.get("merge_authorization") is not True:
        raise MergeError("separate explicit maintainer merge authorization is required")
    if request.get("merge_enabled") is not True:
        raise MergeError("merge-based integration is not enabled by repository policy")


def run_git(repo, args, runner=subprocess.run, allow_failure=False):
    try:
        result = runner(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise MergeError("cannot execute Git: " + str(exc)) from exc
    if result.returncode and not allow_failure:
        detail = (result.stderr or result.stdout or "unknown Git error").strip()[:600]
        raise MergeError("git %s failed: %s" % (" ".join(args[:3]), detail))
    return result


def remote_sha(repo, branch, runner=subprocess.run):
    return run_git(
        repo,
        ["rev-parse", "--verify", "refs/remotes/origin/" + branch],
        runner,
    ).stdout.strip()


def merge_and_push(repo, request, runner=subprocess.run):
    """Create a two-parent merge commit and push it as a normal fast-forward."""
    validate_request(request)
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise MergeError("repository worktree does not exist")

    branch = request["branch"]
    base_branch = request["base_branch"]
    expected_head = request["expected_head_sha"]
    expected_base = request["expected_base_sha"]

    if run_git(repo, ["status", "--porcelain"], runner).stdout.strip():
        raise MergeError("worktree is not clean; refusing merge")
    if run_git(repo, ["branch", "--show-current"], runner).stdout.strip() != branch:
        raise MergeError("checked-out branch does not match the authorized PR branch")
    if run_git(repo, ["rev-parse", "HEAD"], runner).stdout.strip() != expected_head:
        raise MergeError("local HEAD does not match the separately approved PR head SHA")

    run_git(
        repo,
        [
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/" + branch + ":refs/remotes/origin/" + branch,
            "+refs/heads/" + base_branch + ":refs/remotes/origin/" + base_branch,
        ],
        runner,
    )
    if remote_sha(repo, branch, runner) != expected_head:
        raise MergeError("remote PR branch moved before merge; request approval again")
    if remote_sha(repo, base_branch, runner) != expected_base:
        raise MergeError("base branch moved before merge; refresh metadata and request approval again")

    merge_result = run_git(
        repo,
        ["merge", "--no-ff", "--no-commit", "refs/remotes/origin/" + base_branch],
        runner,
        allow_failure=True,
    )
    if merge_result.returncode:
        run_git(repo, ["merge", "--abort"], runner, allow_failure=True)
        raise MergeError("merge conflicted or failed; merge was aborted for human resolution")

    merge_head = run_git(repo, ["rev-parse", "--verify", "MERGE_HEAD"], runner, allow_failure=True)
    if merge_head.returncode:
        raise MergeError("Git did not create a merge state; no merge commit was made")

    try:
        run_git(repo, ["diff", "--cached", "--check"], runner)
        run_git(repo, ["commit", "--no-ff", "-m", "Merge " + base_branch + " into " + branch], runner)
        new_sha = run_git(repo, ["rev-parse", "HEAD"], runner).stdout.strip()
        parents = run_git(repo, ["rev-list", "--parents", "-n", "1", "HEAD"], runner).stdout.split()
        if parents != [new_sha, expected_head, expected_base]:
            raise MergeError("result is not the expected two-parent merge commit")
        run_git(
            repo,
            [
                "fetch",
                "--no-tags",
                "origin",
                "+refs/heads/" + branch + ":refs/remotes/origin/" + branch,
                "+refs/heads/" + base_branch + ":refs/remotes/origin/" + base_branch,
            ],
            runner,
        )
        if remote_sha(repo, branch, runner) != expected_head:
            raise MergeError("remote PR branch moved during merge; refusing to push")
        if remote_sha(repo, base_branch, runner) != expected_base:
            raise MergeError("base branch moved during merge; refusing to push")
        run_git(
            repo,
            ["push", "origin", "HEAD:refs/heads/" + branch],
            runner,
        )
    except MergeError:
        run_git(repo, ["merge", "--abort"], runner, allow_failure=True)
        current_head = run_git(repo, ["rev-parse", "HEAD"], runner).stdout.strip()
        if current_head != expected_head:
            run_git(repo, ["reset", "--hard", expected_head], runner)
        raise

    return {
        "operation": "merge",
        "repository": request["repository"],
        "branch": branch,
        "base_branch": base_branch,
        "old_head_sha": expected_head,
        "base_sha": expected_base,
        "new_sha": new_sha,
        "parents": parents[1:],
        "force_push": False,
        "authorization": "separate explicit maintainer merge authorization",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Dedicated isolated Git worktree")
    parser.add_argument("--request", required=True, help="JSON with trusted metadata and separate approval")
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        result = merge_and_push(args.repo, request)
    except (OSError, ValueError, MergeError) as exc:
        print("merge-agent: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
