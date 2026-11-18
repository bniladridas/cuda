#!/usr/bin/env python3
"""Validate a maintainer dispatch against live GitHub PR metadata."""

import json
import os
import re
import sys
import urllib.error
import urllib.request


API = "https://api.github.com"
SHA = re.compile(r"^[0-9a-f]{40}$")


class GateError(Exception):
    pass


def api(path, token):
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cuda-pr-repair-gate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise GateError("GitHub API returned HTTP %d for %s" % (exc.code, path)) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GateError("GitHub API request failed: " + str(exc)) from exc


def main():
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GITHUB_TOKEN"]
        actor = os.environ["GITHUB_ACTOR"]
        number = int(os.environ["PR_NUMBER"])
        operation = os.environ["OPERATION"]
        expected_head = os.environ["EXPECTED_HEAD_SHA"].lower()
        expected_base = os.environ["EXPECTED_BASE_SHA"].lower()
        approval = os.environ["APPROVAL"]
        maintainers = json.loads(os.environ.get("REPAIR_MAINTAINERS", "[]"))
        if not isinstance(maintainers, list) or actor not in maintainers:
            raise GateError("dispatch actor is not in the trusted REPAIR_MAINTAINERS allowlist")
        if operation not in {"rebase", "merge"}:
            raise GateError("operation must be rebase or merge")
        if os.environ.get("REPAIR_WRITE_ENVIRONMENT_CONFIRMED") != "true":
            raise GateError(
                "the protected pr-repair-write environment must be configured and confirmed by a repository admin"
            )
        if not SHA.fullmatch(expected_head) or not SHA.fullmatch(expected_base):
            raise GateError("both approved SHAs must be full 40-character commit SHAs")
        expected_phrase = "UPDATE %d %s %s %s" % (number, expected_head, expected_base, operation)
        if approval != expected_phrase:
            raise GateError("approval phrase does not bind this PR, head SHA, base SHA, and operation")
        repo = api("/repos/" + repository, token)
        if not repo:
            raise GateError("repository not found")
        default_branch = repo["default_branch"]
        expected_ref = "refs/heads/" + default_branch
        if os.environ.get("GITHUB_REF") != expected_ref:
            raise GateError("workflow_dispatch must run from the trusted default branch")
        pr = api("/repos/" + repository + "/pulls/%d" % number, token)
        if not pr:
            raise GateError("pull request not found")
        if pr.get("state") != "open" or pr.get("merged") or pr.get("draft"):
            raise GateError("PR must be open, unmerged, and ready for review")
        if pr["base"]["repo"]["full_name"].lower() != repository.lower():
            raise GateError("PR base repository does not match workflow repository")
        if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"].lower() != repository.lower():
            raise GateError("fork PR branches cannot be modified")
        if pr["head"]["sha"].lower() != expected_head:
            raise GateError("PR head changed since approval")
        if pr["base"]["sha"].lower() != expected_base:
            raise GateError("base SHA changed since approval")
        branch = pr["head"]["ref"]
        base_branch = pr["base"]["ref"]
        default_branch = repo["default_branch"]
        if branch == default_branch or branch == base_branch:
            raise GateError("default/base branch cannot be used as the PR head")
        branch_info = api(
            "/repos/%s/branches/%s"
            % (
                repository,
                __import__("urllib.parse", fromlist=["quote"]).quote(branch, safe=""),
            ),
            token,
        )
        if not branch_info:
            raise GateError("PR head branch could not be verified")
        if branch_info.get("protected"):
            raise GateError("protected PR branches cannot be modified")
        if operation == "rebase" and os.environ.get("REPAIR_REBASE_ENABLED") != "true":
            raise GateError("repository policy has not enabled rebase")
        if operation == "merge" and os.environ.get("REPAIR_MERGE_ENABLED") != "true":
            raise GateError("repository policy has not enabled merge-based integration")
        print("branch=" + branch)
        print("base_branch=" + base_branch)
        print("default_branch=" + default_branch)
        print("head_sha=" + expected_head)
        print("base_sha=" + expected_base)
        print("operation=" + operation)
    except (KeyError, ValueError, GateError) as exc:
        print("authorization gate: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
