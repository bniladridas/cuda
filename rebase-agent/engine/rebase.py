#!/usr/bin/env python3
"""Approval-gated, fail-closed Git rebase and force-with-lease operations."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


class RebaseError(Exception):
    """A safe rebase could not be completed."""


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def validate_request(request):
    required = ("repository", "head_repository", "branch", "base_branch", "expected_remote_sha")
    missing = [key for key in required if not request.get(key)]
    if missing:
        raise RebaseError("missing required metadata: " + ", ".join(missing))
    if request["repository"].lower() != request["head_repository"].lower():
        raise RebaseError("fork PR branches cannot be modified")
    if request["branch"] == request["base_branch"]:
        raise RebaseError("PR branch cannot be its base branch")
    if request["branch"] in set(request.get("protected_branches") or []):
        raise RebaseError("protected branches cannot be modified")
    if request["branch"] == request.get("default_branch"):
        raise RebaseError("default branch cannot be modified")
    if not REF_RE.fullmatch(request["branch"]) or ".." in request["branch"] or request["branch"].endswith("/"):
        raise RebaseError("invalid PR branch name")
    if not REF_RE.fullmatch(request["base_branch"]) or ".." in request["base_branch"]:
        raise RebaseError("invalid base branch name")
    if not SHA_RE.fullmatch(request["expected_remote_sha"]):
        raise RebaseError("expected remote SHA must be a full 40-character commit SHA")
    if request.get("authorization") is not True:
        raise RebaseError("explicit maintainer authorization is required")
    if request.get("rebase_enabled") is not True:
        raise RebaseError("rebase is not enabled by repository policy")


def run_git(repo, args, runner=subprocess.run):
    """Run a fixed Git argument vector without a shell."""
    try:
        result = runner(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RebaseError("cannot execute Git: " + str(exc)) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown Git error").strip()[:600]
        raise RebaseError("git %s failed: %s" % (" ".join(args[:3]), detail))
    return result.stdout.strip()


def current_remote_sha(repo, branch, runner=subprocess.run):
    return run_git(repo, ["rev-parse", "--verify", "refs/remotes/origin/" + branch], runner)


def rebase_and_push(repo, request, runner=subprocess.run):
    """Rebase an authorized PR branch and push only under its exact observed lease."""
    validate_request(request)
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise RebaseError("repository worktree does not exist")

    branch = request["branch"]
    base_branch = request["base_branch"]
    expected = request["expected_remote_sha"]

    if run_git(repo, ["status", "--porcelain"], runner):
        raise RebaseError("worktree is not clean; refusing to rebase")
    if run_git(repo, ["branch", "--show-current"], runner) != branch:
        raise RebaseError("checked-out branch does not match the authorized PR branch")
    if run_git(repo, ["rev-parse", "HEAD"], runner) != expected:
        raise RebaseError("local branch HEAD does not match the approved PR head SHA")

    run_git(repo, ["fetch", "--no-tags", "origin", branch, base_branch], runner)
    if current_remote_sha(repo, branch, runner) != expected:
        raise RebaseError("remote PR branch moved before rebase; refresh PR state and request approval again")

    try:
        run_git(repo, ["rebase", "refs/remotes/origin/" + base_branch], runner)
    except RebaseError as exc:
        try:
            runner(
                ["git", "-C", str(repo), "rebase", "--abort"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            pass
        raise RebaseError("rebase failed or conflicted; rebase was aborted and requires human resolution") from exc

    run_git(repo, ["fetch", "--no-tags", "origin", branch], runner)
    if current_remote_sha(repo, branch, runner) != expected:
        raise RebaseError("remote PR branch moved during rebase; refusing to push")

    run_git(
        repo,
        [
            "push",
            "--force-with-lease=refs/heads/%s:%s" % (branch, expected),
            "origin",
            "HEAD:refs/heads/" + branch,
        ],
        runner,
    )
    return {
        "operation": "rebase",
        "repository": request["repository"],
        "branch": branch,
        "base_branch": base_branch,
        "old_sha": expected,
        "new_sha": run_git(repo, ["rev-parse", "HEAD"], runner),
        "force_with_lease": True,
        "authorization": "explicit maintainer approval",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Dedicated local Git worktree")
    parser.add_argument("--request", required=True, help="JSON file with trusted PR metadata and approval")
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        result = rebase_and_push(args.repo, request)
    except (OSError, ValueError, RebaseError) as exc:
        print("rebase-agent: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
