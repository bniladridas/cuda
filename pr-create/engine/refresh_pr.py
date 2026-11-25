#!/usr/bin/env python3
"""Refresh an open PR body from its current base-to-head comparison."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from create_pr import API, generate_metadata, linked_references, render_body, request_json


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    api_key = os.environ["OPENROUTER_API_KEY"]
    model = (os.environ.get("OPENROUTER_MODEL") or "openrouter/free").strip()
    number = int(os.environ["PR_NUMBER"])
    pr_url = f"{API}/repos/{repo}/pulls/{number}"
    pr = request_json(pr_url, token)
    if pr.get("state") != "open":
        raise ValueError(f"Pull request #{number} is not open")
    head_repo = (pr.get("head") or {}).get("repo") or {}
    if head_repo.get("full_name") != repo:
        raise ValueError("Refusing to update a pull request from a fork")
    head = pr["head"]["ref"]
    base = pr["base"]["ref"]
    head_sha = pr["head"]["sha"]
    encoded_head = quote(head, safe="/")
    encoded_base = quote(base, safe="/")
    compare = request_json(
        f"{API}/repos/{repo}/compare/{encoded_base}...{encoded_head}",
        token,
    )
    if compare.get("status") not in {"ahead", "diverged"} or compare.get("ahead_by", 0) < 1:
        raise ValueError("The pull request has no commits ahead of its base")
    files = compare.get("files", [])
    if not files:
        raise ValueError("The pull request comparison contains no changed files")
    if sum(len(item.get("patch") or "") for item in files) > 120_000:
        raise ValueError("The diff exceeds the 120 KB model-input limit")
    with open(".github/pr-scopes.json", encoding="utf-8") as file:
        registry = json.load(file)
    result = generate_metadata(compare, registry["scopes"], head, base, api_key, model)
    body = render_body(
        result,
        linked_references(
            [
                commit.get("commit", {}).get("message", "")
                for commit in compare.get("commits", [])
            ]
        ),
    )
    current = request_json(pr_url, token)
    if current.get("state") != "open" or current["head"]["sha"] != head_sha:
        raise ValueError("The pull request changed during generation; retry on its latest commit")
    request_json(pr_url, token, method="PATCH", payload={"body": body})
    print(f"Updated body for {pr['html_url']} at head {head_sha}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"CUDA bot PR body refresh failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
