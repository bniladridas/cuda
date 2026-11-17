#!/usr/bin/env python3
"""Read-only formatting reports and maintainer-approved clang-format repairs."""

import argparse
import base64
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

API = "https://api.github.com"
SHA = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_FILES = 3000


class RepairError(Exception):
    pass


def require_path(path):
    if not isinstance(path, str) or not path or any(c in path for c in ("\x00", "\n", "\r", "\\")):
        raise RepairError("invalid changed-file path")
    if PurePosixPath(path).is_absolute() or any(p in ("", ".", "..") for p in path.split("/")):
        raise RepairError("changed-file path must be repository-relative")
    return path


def load_config(path):
    try:
        import yaml
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (ImportError, OSError, ValueError) as exc:
        raise RepairError("cannot load format-repair configuration: %s" % exc) from exc
    keys = {"version", "formatter_version", "approval_label", "maintainers", "allowed_extensions", "allowed_paths"}
    if not isinstance(cfg, dict) or set(cfg) != keys or isinstance(cfg.get("version"), bool) or cfg["version"] != 1:
        raise RepairError("invalid format-repair configuration")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(cfg["formatter_version"])):
        raise RepairError("formatter_version must be pinned")
    for key in ("maintainers", "allowed_extensions", "allowed_paths"):
        if not isinstance(cfg[key], list) or not cfg[key] or not all(isinstance(x, str) and x for x in cfg[key]):
            raise RepairError("%s must be a non-empty string list" % key)
    if any(not re.fullmatch(r"[A-Za-z0-9-]+", x) for x in cfg["maintainers"]):
        raise RepairError("invalid maintainer login")
    if any(not re.fullmatch(r"\.[a-z0-9]+", x) for x in cfg["allowed_extensions"]):
        raise RepairError("invalid allowed extension")
    if any(x.startswith("/") or "\\" in x or ".." in x.split("/") for x in cfg["allowed_paths"]):
        raise RepairError("invalid allowed path pattern")
    cfg["maintainers"] = {x.lower() for x in cfg["maintainers"]}
    return cfg


def allowed(path, cfg):
    require_path(path)
    return PurePosixPath(path).suffix.lower() in cfg["allowed_extensions"] and any(
        fnmatch.fnmatchcase(path, pattern) for pattern in cfg["allowed_paths"]
    )


def validate_changed_paths(changed, selected):
    result = sorted(set(changed))
    if any(path not in set(selected) for path in result):
        raise RepairError("formatter changed an unapproved path")
    return result


def api_json(url, token):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "cuda-format-repair",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body, link = response.read().decode(), response.headers.get("Link", "")
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RepairError("GitHub API request failed: %s" % exc) from exc
    try:
        return json.loads(body), link
    except json.JSONDecodeError as exc:
        raise RepairError("GitHub API returned invalid JSON") from exc


def pages(url, token):
    items = []
    while url:
        data, link = api_json(url, token)
        if not isinstance(data, list):
            raise RepairError("GitHub API returned an invalid file list")
        items.extend(data)
        if len(items) > MAX_FILES:
            raise RepairError("pull request exceeds the 3,000-file API limit")
        url = None
        for part in link.split(","):
            match = re.search(r'<([^>]+)>;\s*rel="next"', part)
            if match:
                url = match.group(1)
                if not url.startswith(API + "/"):
                    raise RepairError("unexpected pagination host")
                break
    return items


def fetch_pr(repo, number, token):
    data, _ = api_json("%s/repos/%s/pulls/%d" % (API, repo, number), token)
    if not isinstance(data, dict):
        raise RepairError("invalid pull request metadata")
    return data


def pr_info(pr, repo, expected=None, same_repo=False):
    head, base = pr.get("head") or {}, pr.get("base") or {}
    sha, base_sha = head.get("sha"), base.get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or not isinstance(base_sha, str) or not SHA.fullmatch(base_sha):
        raise RepairError("invalid pull request SHA")
    head_repo = (head.get("repo") or {}).get("full_name")
    if (base.get("repo") or {}).get("full_name") != repo:
        raise RepairError("pull request base repository mismatch")
    if same_repo and head_repo != repo:
        raise RepairError("fork pull requests are report-only")
    if expected and sha != expected:
        raise RepairError("pull request head changed; apply approval again")
    branch = head.get("ref")
    if (not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)
            or any(p in ("", ".", "..") for p in branch.split("/")) or branch.endswith((".", ".lock")) or "@{" in branch):
        raise RepairError("invalid pull request branch")
    if pr.get("state") != "open" or not base.get("ref"):
        raise RepairError("pull request is not open or has no base branch")
    return {"sha": sha, "head_repo": head_repo, "branch": branch, "base": base["ref"]}


def changed_files(repo, number, token):
    return pages("%s/repos/%s/pulls/%d/files?per_page=100" % (API, repo, number), token)


def source_bytes(repo, path, sha, token):
    url = "%s/repos/%s/contents/%s?ref=%s" % (API, repo, urllib.parse.quote(path, safe="/"), sha)
    data, _ = api_json(url, token)
    if not isinstance(data, dict) or data.get("type") != "file" or not isinstance(data.get("content"), str):
        raise RepairError("could not fetch source file %s" % path)
    return base64.b64decode(data["content"])


def line_numbers(source, xml_text):
    try:
        root = ET.fromstring(xml_text)
        offsets = [int(node.attrib["offset"]) for node in root.findall("replacement")]
    except (ET.ParseError, KeyError, ValueError) as exc:
        raise RepairError("clang-format returned invalid replacement XML") from exc
    if any(offset < 0 or offset > len(source) for offset in offsets):
        raise RepairError("clang-format returned an invalid replacement offset")
    return sorted({source[:offset].count(b"\n") + 1 for offset in offsets})


def inspect(path, source, style_file):
    result = subprocess.run(
        ["clang-format", "--style=file:" + str(Path(style_file).resolve()),
         "--output-replacements-xml", "--assume-filename=" + path],
        input=source, capture_output=True, check=False,
    )
    if result.returncode:
        raise RepairError("clang-format failed for %s: %s" % (path, result.stderr.decode("utf-8", "replace")[:400]))
    lines = line_numbers(source, result.stdout.decode("utf-8", "replace"))
    return {"path": path, "lines": lines, "formatted": not lines}


def make_report(repo, pr, files, cfg, token, style_file):
    info = pr_info(pr, repo)
    if not isinstance(pr.get("changed_files"), int) or len(files) != pr["changed_files"]:
        raise RepairError("changed-file coverage is incomplete")
    checked, skipped = [], []
    for item in files:
        path = require_path(item.get("filename"))
        if item.get("status") == "removed":
            continue
        if allowed(path, cfg):
            checked.append(inspect(path, source_bytes(info["head_repo"], path, info["sha"], token), style_file))
        else:
            skipped.append(path)
    violations = [item for item in checked if not item["formatted"]]
    return {
        "version": 1, "repo": repo, "pr_number": pr["number"], "head_sha": info["sha"],
        "head_repo": info["head_repo"], "formatter_version": cfg["formatter_version"],
        "approval_label": cfg["approval_label"], "repair_eligible": info["head_repo"] == repo,
        "files_checked": checked, "files_skipped": skipped, "violations": violations, "clean": not violations,
    }


def report_markdown(report):
    lines = ["## Formatting check", "", "Formatter: clang-format %s" % report["formatter_version"],
             "Files checked: %d. Outside allowlist: %d." % (len(report["files_checked"]), len(report["files_skipped"])), ""]
    if report["clean"]:
        lines.append("No formatting violations found.")
    else:
        lines.append("Formatting violations:")
        for item in report["violations"][:50]:
            nums = ", ".join(str(n) for n in item["lines"][:20]) or "line unavailable"
            lines.append("- %s: replacement required near line(s) %s." % (item["path"], nums))
        lines += ["", "An authorized maintainer can request a formatting-only repair with label %s." % report["approval_label"]]
    if not report["repair_eligible"]:
        lines += ["", "Fork pull request: report-only, no automated push."]
    lines += ["", "This report is advisory. Normal CI remains authoritative."]
    return "\n".join(lines) + "\n"


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_report(args, cfg, token):
    pr = fetch_pr(args.repo, args.pr, token)
    files = changed_files(args.repo, args.pr, token)
    result = make_report(args.repo, pr, files, cfg, token, args.style_file)
    write_json(args.artifact, result)
    Path(args.summary).write_text(report_markdown(result), encoding="utf-8")


def run_repair(args, cfg, token):
    if args.actor.lower() not in cfg["maintainers"]:
        raise RepairError("actor is not authorized to approve formatting repairs")
    pr = fetch_pr(args.repo, args.pr, token)
    info = pr_info(pr, args.repo, args.event_head_sha, same_repo=True)
    labels = {x.get("name") for x in pr.get("labels", []) if isinstance(x, dict)}
    if cfg["approval_label"] not in labels or info["base"] != args.default_branch:
        raise RepairError("approval label or default-branch requirement is not satisfied")
    files = changed_files(args.repo, args.pr, token)
    if not isinstance(pr.get("changed_files"), int) or len(files) != pr["changed_files"]:
        raise RepairError("changed-file coverage is incomplete; no repair")
    paths = sorted({require_path(x.get("filename")) for x in files
                    if x.get("status") != "removed" and allowed(x.get("filename"), cfg)})
    if not paths:
        raise RepairError("no eligible changed source files")
    work = Path(args.workdir).resolve()
    for path in paths:
        candidate = work / path
        if candidate.is_symlink() or work not in candidate.resolve().parents or not candidate.is_file():
            raise RepairError("unsafe or missing worktree file: %s" % path)
        result = subprocess.run(
            ["clang-format", "--style=file:" + str(Path(args.style_file).resolve()),
             "--assume-filename=" + path],
            input=candidate.read_bytes(), capture_output=True, check=False,
        )
        if result.returncode:
            raise RepairError("clang-format failed for %s" % path)
        candidate.write_bytes(result.stdout)
    diff = subprocess.run(["git", "diff", "--name-only"], cwd=work, capture_output=True, check=True)
    changed = validate_changed_paths(diff.stdout.decode().splitlines(), paths)
    if not changed:
        write_json(args.artifact, {"status": "no_changes", "changed_files": []})
        return
    check = subprocess.run(["git", "diff", "--check"], cwd=work, capture_output=True)
    if check.returncode:
        raise RepairError("formatted diff failed git diff --check")
    latest = fetch_pr(args.repo, args.pr, token)
    latest_info = pr_info(latest, args.repo, args.event_head_sha, same_repo=True)
    latest_labels = {x.get("name") for x in latest.get("labels", []) if isinstance(x, dict)}
    if latest_info["branch"] != info["branch"] or latest_info["base"] != info["base"] or cfg["approval_label"] not in latest_labels:
        raise RepairError("PR state or approval changed before commit")
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=work, check=True)
    subprocess.run(["git", "add", "--", *changed], cwd=work, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=work, capture_output=True, check=True)
    if sorted(staged.stdout.decode().splitlines()) != changed:
        raise RepairError("staged paths differ from formatter output")
    subprocess.run(["git", "commit", "-m", "style: apply approved clang-format fixes"], cwd=work, check=True)
    if subprocess.run(["git", "check-ref-format", "--branch", info["branch"]], cwd=work).returncode:
        raise RepairError("invalid PR branch ref")
    remote = "https://x-access-token:%s@github.com/%s.git" % (token, args.repo)
    subprocess.run(["git", "remote", "set-url", "origin", remote], cwd=work, check=True)
    push = subprocess.run(["git", "push", "origin", "HEAD:refs/heads/" + info["branch"]], cwd=work, capture_output=True)
    if push.returncode:
        raise RepairError("non-force push failed; PR branch may have advanced: " + push.stderr.decode("utf-8", "replace")[:500])
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, check=True).stdout.decode().strip()
    write_json(args.artifact, {"status": "pushed", "commit_sha": commit, "changed_files": changed})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("report", "repair"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--config", required=True)
    parser.add_argument("--style-file", default=".clang-format")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--summary", default="format-repair.md")
    parser.add_argument("--actor")
    parser.add_argument("--event-head-sha")
    parser.add_argument("--default-branch", default="main")
    parser.add_argument("--workdir", default=".")
    args = parser.parse_args()
    try:
        if not REPO.fullmatch(args.repo) or args.pr < 1:
            raise RepairError("invalid repository or pull request number")
        import yaml  # noqa: F401
        cfg = load_config(args.config)
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RepairError("GH_TOKEN is required")
        if args.mode == "report":
            run_report(args, cfg, token)
        else:
            if not args.actor or not args.event_head_sha:
                raise RepairError("repair mode requires actor and event head SHA")
            run_repair(args, cfg, token)
        return 0
    except (RepairError, subprocess.CalledProcessError) as exc:
        print("format-repair: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
