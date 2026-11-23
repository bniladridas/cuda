#!/usr/bin/env python3
"""Authorize a read-only PR repair proposal dispatch against live GitHub metadata."""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
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
            "User-Agent": "cuda-pr-repair-proposal-gate",
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
        expected_head = os.environ["EXPECTED_HEAD_SHA"].lower()
        expected_base = os.environ["EXPECTED_BASE_SHA"].lower()
        maintainers = json.loads(os.environ.get("REPAIR_MAINTAINERS", "[]"))
        if not isinstance(maintainers, list) or actor not in maintainers:
            raise GateError("dispatch actor is not in the trusted REPAIR_MAINTAINERS allowlist")
        if number < 1 or not SHA.fullmatch(expected_head) or not SHA.fullmatch(expected_base):
            raise GateError("PR number and full 40-character head/base SHAs are required")
        repo = api("/repos/" + repository, token)
        if not repo:
            raise GateError("repository not found")
        default_branch = repo["default_branch"]
        if os.environ.get("GITHUB_REF") != "refs/heads/" + default_branch:
            raise GateError("workflow_dispatch must run from the trusted default branch")
        pr = api("/repos/" + repository + "/pulls/%d" % number, token)
        if not pr:
            raise GateError("pull request not found")
        if pr.get("state") != "open" or pr.get("merged"):
            raise GateError("PR must be open and unmerged")
        if pr.get("base", {}).get("repo", {}).get("full_name", "").lower() != repository.lower():
            raise GateError("PR base repository does not match workflow repository")
        head_repo = pr.get("head", {}).get("repo") or {}
        if head_repo.get("full_name", "").lower() != repository.lower():
            raise GateError("fork PRs are not eligible for proposal dispatch")
        if pr["head"]["sha"].lower() != expected_head:
            raise GateError("PR head SHA changed since dispatch was prepared")
        if pr["base"]["sha"].lower() != expected_base:
            raise GateError("PR base SHA changed since dispatch was prepared")
        head_branch = pr["head"]["ref"]
        base_branch = pr["base"]["ref"]
        for branch, expected, label in (
            (head_branch, expected_head, "PR head"),
            (base_branch, expected_base, "PR base"),
        ):
            info = api("/repos/%s/branches/%s" % (repository, urllib.parse.quote(branch, safe="")))
            if not info or info.get("commit", {}).get("sha", "").lower() != expected:
                raise GateError(label + " branch moved or could not be verified")
        print("branch=" + head_branch)
        print("base_branch=" + base_branch)
        print("head_sha=" + expected_head)
        print("base_sha=" + expected_base)
        print("pull_request=" + str(number))
    except (KeyError, ValueError, GateError) as exc:
        print("proposal authorization gate: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
