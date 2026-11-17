#!/usr/bin/env python3
"""Read-only GitHub Git Trees API inspection for pull-request integration."""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class InspectionError(Exception):
    """GitHub metadata or tree inspection was incomplete."""


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GitHubAPI:
    def __init__(self, token, api_url="https://api.github.com"):
        if not token:
            raise InspectionError("GITHUB_TOKEN is required")
        self.api_url = api_url.rstrip("/")
        self.token = token

    def get(self, path):
        url = self.api_url + path
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "cuda-pr-tree-inspector",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise InspectionError("GitHub API request failed: " + str(exc)) from exc


def api_path(repository, suffix):
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise InspectionError("repository must be owner/name")
    return "/repos/%s/%s" % (urllib.parse.quote(parts[0]), urllib.parse.quote(parts[1])) + suffix


def fetch_tree(api, repository, commit_sha):
    if not SHA_RE.fullmatch(commit_sha):
        raise InspectionError("tree commit must be a full 40-character SHA")
    commit = api.get(api_path(repository, "/git/commits/" + commit_sha))
    tree_sha = commit.get("tree", {}).get("sha")
    if not isinstance(tree_sha, str) or not SHA_RE.fullmatch(tree_sha):
        raise InspectionError("GitHub commit response has no valid tree SHA")
    result = api.get(api_path(repository, "/git/trees/" + tree_sha + "?recursive=1"))
    if result.get("sha") != tree_sha:
        raise InspectionError("GitHub returned a tree for an unexpected SHA")
    if result.get("truncated") is True:
        raise InspectionError("GitHub returned a truncated recursive tree; inspection is incomplete")
    entries = result.get("tree")
    if not isinstance(entries, list):
        raise InspectionError("GitHub tree response has no complete tree entry list")
    normalized = {}
    for entry in entries:
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise InspectionError("tree contains an invalid path entry")
        if path in normalized:
            raise InspectionError("tree contains duplicate path: " + path)
        normalized[path] = {
            "sha": entry.get("sha"),
            "type": entry.get("type"),
            "mode": entry.get("mode"),
        }
    return normalized


def fetch_pr_files(api, repository, number):
    files = []
    page = 1
    while True:
        result = api.get(api_path(repository, "/pulls/%d/files?per_page=100&page=%d" % (number, page)))
        if not isinstance(result, list):
            raise InspectionError("GitHub PR files response is not a list")
        files.extend(result)
        if len(result) < 100:
            break
        page += 1
        if page > 100:
            raise InspectionError("PR file pagination exceeded the safety limit")
    return files


def compare_trees(base_tree, head_tree):
    paths = sorted(set(base_tree) | set(head_tree))
    changed = {
        path
        for path in paths
        if base_tree.get(path) != head_tree.get(path)
        and ((base_tree.get(path) or head_tree.get(path) or {}).get("type") != "tree")
    }
    return changed


def overlapping_path_pairs(left_paths, right_paths):
    pairs = []
    for left in sorted(left_paths):
        for right in sorted(right_paths):
            if left == right or left.startswith(right + "/") or right.startswith(left + "/"):
                pairs.append({"base_path": left, "head_path": right})
    return pairs


def inspect_pull_request(api, repository, number):
    pr = api.get(api_path(repository, "/pulls/%d" % number))
    base_sha = pr.get("base", {}).get("sha")
    head_sha = pr.get("head", {}).get("sha")
    base_branch = pr.get("base", {}).get("ref")
    head_branch = pr.get("head", {}).get("ref")
    head_repository = pr.get("head", {}).get("repo", {}).get("full_name")
    if not all((base_sha, head_sha, base_branch, head_branch, head_repository)):
        raise InspectionError("PR metadata is incomplete")
    if pr.get("base", {}).get("repo", {}).get("full_name", "").lower() != repository.lower():
        raise InspectionError("PR base repository does not match requested repository")

    comparison = api.get(
        api_path(
            repository,
            "/compare/%s...%s" % (urllib.parse.quote(base_branch, safe=""), head_sha),
        )
    )
    merge_base_sha = comparison.get("merge_base_commit", {}).get("sha")
    status = comparison.get("status")
    if not merge_base_sha or status not in {"ahead", "behind", "diverged", "identical"}:
        raise InspectionError("GitHub compare response is incomplete or unknown")

    base_tree = fetch_tree(api, repository, base_sha)
    head_tree = fetch_tree(api, repository, head_sha)
    merge_base_tree = fetch_tree(api, repository, merge_base_sha)
    base_changes = compare_trees(merge_base_tree, base_tree)
    head_changes = compare_trees(merge_base_tree, head_tree)
    overlaps = sorted(base_changes & head_changes)
    overlap_pairs = overlapping_path_pairs(base_changes, head_changes)
    pr_files = fetch_pr_files(api, repository, number)
    inventory = []
    for item in pr_files:
        inventory.append(
            {
                "filename": item.get("filename"),
                "previous_filename": item.get("previous_filename"),
                "status": item.get("status"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
                "patch_available": isinstance(item.get("patch"), str),
                "binary_or_patchless": not isinstance(item.get("patch"), str),
            }
        )
    reported_paths = {
        path for item in inventory for path in (item.get("filename"), item.get("previous_filename")) if path
    }
    tree_paths = sorted(head_changes)
    return {
        "schema_version": 1,
        "repository": repository,
        "pull_request": number,
        "base": {"branch": base_branch, "sha": base_sha},
        "head": {"branch": head_branch, "sha": head_sha, "repository": head_repository},
        "merge_base_sha": merge_base_sha,
        "comparison_status": status,
        "branch_state": {
            "behind": status in {"behind", "diverged"},
            "ahead": status in {"ahead", "diverged"},
            "up_to_date": status == "identical",
        },
        "tree_inventory_complete": True,
        "base_tree_entries": len(base_tree),
        "head_tree_entries": len(head_tree),
        "base_changed_paths_since_merge_base": sorted(base_changes),
        "head_changed_paths_since_merge_base": tree_paths,
        "overlapping_paths": overlaps,
        "overlapping_path_pairs": overlap_pairs,
        "overlap_is_conflict_proof": False,
        "pr_file_inventory": inventory,
        "pr_file_inventory_matches_head_tree": reported_paths == set(tree_paths),
        "pr_files_missing_patch": [item["filename"] for item in inventory if item["binary_or_patchless"]],
        "semantic_conflict_resolution": "not_attempted",
        "branch_mutation": "not_attempted",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = inspect_pull_request(
            GitHubAPI(os.environ.get("GITHUB_TOKEN")),
            args.repository,
            args.pull_request,
        )
        with open(args.output, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, InspectionError) as exc:
        print("tree-inspector: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
