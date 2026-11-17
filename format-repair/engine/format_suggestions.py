#!/usr/bin/env python3
"""Post deterministic formatter suggestions as inline GitHub PR review comments."""

import base64
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


class SuggestionError(Exception):
    pass


def request_json(url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cuda-format-suggestions",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise SuggestionError("GitHub API request failed: %s" % exc) from exc


def api_url(repo, path):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or ".." in repo.split("/"):
        raise SuggestionError("invalid repository")
    return "%s/repos/%s/%s" % (API, repo, path.lstrip("/"))


def changed_files(repo, pr_number, token, expected_count):
    files = []
    page = 1
    while True:
        batch = request_json(
            api_url(repo, "pulls/%s/files?per_page=100&page=%s" % (pr_number, page)),
            token,
        )
        if not isinstance(batch, list):
            raise SuggestionError("changed-file response is invalid")
        files.extend(batch)
        if len(files) > expected_count:
            raise SuggestionError("changed-file count exceeds the PR metadata")
        if len(batch) < 100:
            break
        page += 1
    if len(files) != expected_count:
        raise SuggestionError("changed-file coverage is incomplete")
    return files


def changed_right_lines(patch):
    changed = set()
    current = None
    for line in (patch or "").splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            current = int(match.group(1)) if match else None
        elif current is not None:
            if line.startswith("+++") or line.startswith("---") or line.startswith("\\"):
                continue
            if line.startswith("+"):
                changed.add(current)
                current += 1
            elif line.startswith("-"):
                continue
            elif line.startswith(" "):
                current += 1
    return changed


def formatted_source(path, source):
    if path.endswith(".py"):
        command = ["ruff", "format", "--config", "pyproject.toml", "--stdin-filename", path, "-"]
    else:
        command = [
            "clang-format",
            "--style=file:.clang-format",
            "--assume-filename=" + path,
        ]
    result = subprocess.run(command, input=source, capture_output=True, check=False)
    if result.returncode:
        raise SuggestionError("formatter failed for %s: %s" % (path, result.stderr.decode("utf-8", "replace")[:300]))
    return result.stdout


def suggestions_for(path, source, formatted, changed_lines, head_sha):
    old = source.decode("utf-8").splitlines()
    new = formatted.decode("utf-8").splitlines()
    matcher = difflib.SequenceMatcher(a=old, b=new)
    comments = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i1 == i2 or j1 == j2:
            continue
        start, end = i1 + 1, i2
        if end - start + 1 > 100 or not all(line in changed_lines for line in range(start, end + 1)):
            continue
        replacement = "\n".join(new[j1:j2])
        marker = "<!-- format-repair-suggestion:v1:%s:%s:%s:%s -->" % (head_sha, path, start, end)
        body = (
            "The pinned formatter recommends this replacement. Apply it if the change is intended.\n\n"
            "```suggestion\n" + replacement + "\n```\n\n" + marker
        )
        comment = {"path": path, "line": end, "side": "RIGHT", "body": body}
        if start != end:
            comment.update({"start_line": start, "start_side": "RIGHT"})
        comments.append(comment)
    return comments


def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    if not token or not pr_number.isdigit() or int(pr_number) < 1:
        raise SuggestionError("GH_TOKEN and a positive PR_NUMBER are required")

    pr = request_json(api_url(repo, "pulls/%s" % pr_number), token)
    if pr.get("state") != "open":
        print("PR is not open; no suggestions posted.")
        return
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    head_sha = head.get("sha")
    head_repo = (head.get("repo") or {}).get("full_name")
    if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise SuggestionError("invalid PR head SHA")
    if (base.get("repo") or {}).get("full_name") != repo:
        raise SuggestionError("PR base repository mismatch")
    if not isinstance(head_repo, str):
        raise SuggestionError("PR head repository is unavailable")

    files = changed_files(repo, pr_number, token, pr.get("changed_files"))
    existing = request_json(api_url(repo, "pulls/%s/comments?per_page=100" % pr_number), token)
    existing_bodies = {item.get("body", "") for item in existing if isinstance(item, dict)}
    comments = []
    for item in files:
        path = item.get("filename", "")
        if item.get("status") == "removed" or not item.get("patch"):
            continue
        if not path.endswith((".py", ".cpp", ".h", ".cu", ".cuh")):
            continue
        if not path.startswith(
            (
                "src/",
                "include/",
                "kernels/",
                "tests/",
                "benchmarks/",
                "format-repair/",
                "pr-confidence/",
                "pr-scope-guard/",
                "label-review/",
                "issue-landing/",
                "runners/",
            )
        ):
            continue
        changed_lines = changed_right_lines(item["patch"])
        if not changed_lines:
            continue
        encoded = request_json(
            api_url(head_repo, "contents/%s?ref=%s" % (urllib.parse.quote(path, safe="/"), head_sha)),
            token,
        )
        if encoded.get("type") != "file" or encoded.get("encoding") != "base64":
            raise SuggestionError("GitHub did not return complete source for %s" % path)
        source = base64.b64decode("".join(encoded.get("content", "").split()), validate=True)
        formatted = formatted_source(path, source)
        for comment in suggestions_for(path, source, formatted, changed_lines, head_sha):
            if comment["body"].splitlines()[-1] not in "\n".join(existing_bodies):
                comments.append(comment)

    if not comments:
        print("No applicable formatter suggestions for changed lines.")
        return
    request_json(
        api_url(repo, "pulls/%s/reviews" % pr_number),
        token,
        {"commit_id": head_sha, "event": "COMMENT", "comments": comments},
    )
    print("Posted %d deterministic formatter suggestion(s)." % len(comments))


if __name__ == "__main__":
    try:
        main()
    except (SuggestionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("format-suggestions: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
