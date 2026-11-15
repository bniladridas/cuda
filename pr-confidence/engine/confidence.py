#!/usr/bin/env python3
"""Deterministic PR evidence scoring for the PR Confidence check.

Collects read-only GitHub metadata, scores a five-point evidence rubric, writes
a Markdown job summary, and exits non-zero only when a configured hard blocker
is present. It never writes to the pull request or the repository.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CHECK_NAME = "PR Confidence"
RUBRIC_VERSION = 1
FAILURE_CONCLUSIONS = {"failure", "timed_out", "action_required", "startup_failure"}
INCOMPLETE_CONCLUSIONS = {"cancelled", "skipped", "neutral", "stale"}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
DEFAULT_HARD_BLOCKERS = {
    "failed_critical_checks": True,
    "changes_requested": True,
    "merge_conflict": True,
    "draft": False,
    "unresolved_threads": False,
    "security_check_failure": False,
}
CONFIG_KEYS = {
    "version",
    "critical_checks",
    "security_checks",
    "hard_blockers",
    "scope",
    "test_patterns",
    "security_sensitive_paths",
}

REVIEW_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewDecision
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          isResolved
          isOutdated
          comments(first: 1) {
            nodes { path url }
          }
        }
      }
    }
  }
}
"""


class ConfidenceError(Exception):
    pass


def run(cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise ConfidenceError("cannot run gh: %s" % exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:400]
        raise ConfidenceError("command failed: %s\n%s" % (" ".join(cmd[:2]), detail))
    return proc.stdout


def gh_json(args):
    raw = run(["gh", "api"] + args)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ConfidenceError("gh api returned invalid JSON: %s" % exc)


def check_pattern(pattern):
    if not pattern or pattern.startswith("/") or pattern.startswith("\\"):
        raise ConfidenceError("path pattern must be repository relative: %r" % pattern)
    if "\\" in pattern:
        raise ConfidenceError("use forward slashes in path patterns: %r" % pattern)
    if ".." in pattern.split("/"):
        raise ConfidenceError("path pattern must stay inside the repository: %r" % pattern)


def string_list(data, key, minimum=0):
    value = data.get(key)
    if not isinstance(value, list):
        raise ConfidenceError("%s must be a list" % key)
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfidenceError("%s must contain non-empty strings" % key)
        if item in result:
            raise ConfidenceError("%s contains a duplicate: %r" % (key, item))
        result.append(item)
    if len(result) < minimum:
        raise ConfidenceError("%s must contain at least %d item(s)" % (key, minimum))
    return result


def validate_config(data):
    if not isinstance(data, dict):
        raise ConfidenceError("configuration must be a mapping")
    unknown = set(data) - CONFIG_KEYS
    if unknown:
        raise ConfidenceError("unknown configuration keys: " + ", ".join(sorted(unknown)))
    if data.get("version") != 1:
        raise ConfidenceError("configuration version must be 1")

    critical = string_list(data, "critical_checks", 1)
    security = string_list(data, "security_checks", 1)
    overlap = set(critical) & set(security)
    if overlap:
        raise ConfidenceError(
            "a check cannot be both critical and a security check: "
            + ", ".join(sorted(overlap))
        )

    blockers_value = data.get("hard_blockers")
    if blockers_value is None:
        blockers_value = {}
    if not isinstance(blockers_value, dict):
        raise ConfidenceError("hard_blockers must be a mapping")
    unknown_blockers = set(blockers_value) - set(DEFAULT_HARD_BLOCKERS)
    if unknown_blockers:
        raise ConfidenceError(
            "unknown hard_blockers keys: " + ", ".join(sorted(unknown_blockers))
        )
    blockers = dict(DEFAULT_HARD_BLOCKERS)
    for key, value in blockers_value.items():
        if not isinstance(value, bool):
            raise ConfidenceError("hard_blockers.%s must be true or false" % key)
        blockers[key] = value

    scope_value = data.get("scope")
    if not isinstance(scope_value, dict):
        raise ConfidenceError("scope must be a mapping")
    unknown_scope = set(scope_value) - {"max_files", "max_changed_lines", "min_body_chars"}
    if unknown_scope:
        raise ConfidenceError("unknown scope keys: " + ", ".join(sorted(unknown_scope)))
    scope = {}
    for key in ("max_files", "max_changed_lines", "min_body_chars"):
        value = scope_value.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ConfidenceError("scope.%s must be a non-negative integer" % key)
        if key != "min_body_chars" and value < 1:
            raise ConfidenceError("scope.%s must be at least 1" % key)
        scope[key] = value

    tests = string_list(data, "test_patterns", 1)
    sensitive = string_list(data, "security_sensitive_paths", 1)
    for pattern in tests + sensitive:
        check_pattern(pattern)
    return {
        "version": 1,
        "critical_checks": critical,
        "security_checks": security,
        "hard_blockers": blockers,
        "scope": scope,
        "test_patterns": tests,
        "security_sensitive_paths": sensitive,
    }


def load_config(path):
    try:
        import yaml
    except ImportError:
        raise ConfidenceError("missing dependency: pyyaml")
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfidenceError("cannot read configuration: %s" % exc)
    except yaml.YAMLError as exc:
        raise ConfidenceError("invalid YAML in %s: %s" % (path, exc))
    return validate_config(data)


_GLOB_CACHE = {}


def glob_regex(pattern):
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]
    segments = pattern.split("/")
    pieces = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            pieces.append(".*" if last else "(?:[^/]+/)*")
        else:
            piece = re.escape(segment).replace("\\*", "[^/]*").replace("\\?", "[^/]")
            pieces.append(piece if last else piece + "/")
    compiled = re.compile("^" + "".join(pieces) + "$")
    _GLOB_CACHE[pattern] = compiled
    return compiled


def matches_any(path, patterns):
    return any(glob_regex(pattern).match(path) for pattern in patterns)


def is_docs_file(path):
    if Path(path).name == "CMakeLists.txt":
        return False
    return (
        path.startswith("docs/")
        or Path(path).suffix.lower() in DOC_SUFFIXES
        or path in {"LICENSE", ".github/CODEOWNERS"}
    )


def latest_check(runs, name):
    matching = [run for run in runs if run.get("name") == name]
    if not matching:
        return None
    return max(
        matching,
        key=lambda run: (run.get("started_at") or "", run.get("completed_at") or ""),
    )


def check_state(run):
    if run is None:
        return "missing", "not reported for this head"
    if run.get("status") != "completed":
        return "pending", run.get("status") or "not completed"
    conclusion = run.get("conclusion")
    if conclusion == "success":
        return "success", "success"
    if conclusion in FAILURE_CONCLUSIONS:
        return "failure", conclusion
    if conclusion in INCOMPLETE_CONCLUSIONS or not conclusion:
        return "incomplete", conclusion or "no conclusion"
    return "unknown", conclusion


def check_line(run):
    if run is None:
        return "Not reported for this head."
    name = run.get("name") or "unnamed"
    app = run.get("app") or "unknown app"
    status = run.get("status") or "unknown"
    conclusion = run.get("conclusion") or "none"
    url = run.get("details_url") or ""
    line = "`%s` (%s): %s/%s" % (name, app, status, conclusion)
    if url:
        line += " ([details](%s))" % url
    return line


def optional_json(args):
    try:
        return gh_json(args), None
    except ConfidenceError as exc:
        return None, str(exc)


def parse_check_runs(raw):
    items = []
    for item in raw.get("check_runs") or []:
        items.append(
            {
                "name": item.get("name") or "",
                "app": (item.get("app") or {}).get("slug") or "",
                "status": item.get("status") or "",
                "conclusion": item.get("conclusion"),
                "details_url": item.get("details_url") or item.get("html_url") or "",
                "started_at": item.get("started_at") or "",
                "completed_at": item.get("completed_at") or "",
            }
        )
    total = int(raw.get("total_count") or len(items))
    return {"truncated": total > len(items), "items": items}


def wait_for_checks(repo, head_sha, config, timeout, interval, clock=time.monotonic, sleep=time.sleep):
    names = list(config["critical_checks"]) + list(config["security_checks"])
    started = clock()
    deadline = started + timeout
    url = "repos/%s/commits/%s/check-runs?filter=latest&per_page=100" % (repo, head_sha)
    while True:
        parsed = parse_check_runs(gh_json([url]))
        if parsed["truncated"]:
            print("%s: more than 100 check runs; scoring available evidence now" % CHECK_NAME)
            return
        incomplete = []
        for name in names:
            run = latest_check(parsed["items"], name)
            if run is None or run.get("status") != "completed":
                incomplete.append(name)
        if not incomplete:
            print(
                "%s: configured checks complete after %ds"
                % (CHECK_NAME, int(clock() - started))
            )
            return
        if clock() >= deadline:
            print(
                "%s: timed out after %ds waiting for: %s"
                % (CHECK_NAME, int(clock() - started), ", ".join(incomplete))
            )
            return
        sleep(min(interval, deadline - clock()))


def collect_evidence(repo, pr_number, head_sha):
    if not repo or "/" not in repo:
        raise ConfidenceError("repository must be owner/name")
    if pr_number < 1:
        raise ConfidenceError("pull request number must be positive")
    if not head_sha:
        raise ConfidenceError("head SHA is required")

    pr_raw = gh_json(["repos/%s/pulls/%d" % (repo, pr_number)])
    head = pr_raw.get("head") or {}
    api_head = head.get("sha") or ""
    pr = {
        "number": int(pr_raw.get("number") or pr_number),
        "title": pr_raw.get("title") or "",
        "body": pr_raw.get("body") or "",
        "draft": bool(pr_raw.get("draft")),
        "state": (pr_raw.get("state") or "").lower(),
        "mergeable": pr_raw.get("mergeable"),
        "mergeable_state": pr_raw.get("mergeable_state") or "",
        "changed_files": int(pr_raw.get("changed_files") or 0),
        "additions": int(pr_raw.get("additions") or 0),
        "deletions": int(pr_raw.get("deletions") or 0),
        "commits": int(pr_raw.get("commits") or 0),
        "user": (pr_raw.get("user") or {}).get("login") or "",
        "api_head_sha": api_head,
        "head_mismatch": bool(api_head and api_head != head_sha),
    }

    files_raw, files_error = optional_json(
        ["repos/%s/pulls/%d/files?per_page=100" % (repo, pr_number)]
    )
    if files_raw is None:
        files = {"available": False, "truncated": False, "items": [], "error": files_error}
    else:
        items = []
        for item in files_raw:
            items.append(
                {
                    "filename": item.get("filename") or "",
                    "status": item.get("status") or "",
                    "additions": int(item.get("additions") or 0),
                    "deletions": int(item.get("deletions") or 0),
                    "changes": int(item.get("changes") or 0),
                }
            )
        truncated = len(items) >= 100 or pr["changed_files"] > len(items)
        files = {"available": True, "truncated": truncated, "items": items, "error": None}

    checks_raw, checks_error = optional_json(
        [
            "repos/%s/commits/%s/check-runs?filter=latest&per_page=100"
            % (repo, head_sha)
        ]
    )
    if checks_raw is None:
        checks = {"available": False, "truncated": False, "items": [], "error": checks_error}
    else:
        parsed = parse_check_runs(checks_raw)
        checks = {
            "available": True,
            "truncated": parsed["truncated"],
            "items": parsed["items"],
            "error": None,
        }

    review = {
        "available": False,
        "decision": None,
        "unresolved": [],
        "threads_truncated": False,
        "error": None,
    }
    owner, name = repo.split("/", 1)
    try:
        data = gh_json(
            [
                "graphql",
                "-f",
                "query=" + REVIEW_QUERY,
                "-F",
                "owner=" + owner,
                "-F",
                "name=" + name,
                "-F",
                "number=%d" % pr_number,
            ]
        )
        if data.get("errors"):
            raise ConfidenceError(str(data["errors"])[:400])
        node = data["data"]["repository"]["pullRequest"]
        threads = (node.get("reviewThreads") or {}).get("nodes") or []
        unresolved = []
        for thread in threads:
            if thread.get("isResolved"):
                continue
            comments = (thread.get("comments") or {}).get("nodes") or []
            first = comments[0] if comments else {}
            unresolved.append(
                {
                    "path": first.get("path") or "",
                    "url": first.get("url") or "",
                    "outdated": bool(thread.get("isOutdated")),
                }
            )
        review = {
            "available": True,
            "decision": node.get("reviewDecision"),
            "unresolved": unresolved,
            "threads_truncated": bool(
                ((node.get("reviewThreads") or {}).get("pageInfo") or {}).get(
                    "hasNextPage"
                )
            ),
            "error": None,
        }
    except (ConfidenceError, KeyError, TypeError, IndexError) as exc:
        review["error"] = str(exc)

    return {
        "rubric_version": RUBRIC_VERSION,
        "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "repo": repo,
        "head_sha": head_sha,
        "pr": pr,
        "files": files,
        "checks": checks,
        "review": review,
    }


def category(key, title, status, detail, evidence):
    return {
        "key": key,
        "title": title,
        "status": status,
        "points": 1 if status == "pass" else 0,
        "detail": detail,
        "evidence": evidence,
    }


def evaluate(evidence, config):
    pr = evidence.get("pr") or {}
    files = evidence.get("files") or {}
    checks = evidence.get("checks") or {}
    review = evidence.get("review") or {}
    categories = []
    blockers = []
    notes = []

    def add_blocker(message):
        if message not in blockers:
            blockers.append(message)

    if pr.get("head_mismatch"):
        add_blocker("The pull request head moved during collection; this result is stale.")
        notes.append(
            "The event head %s does not match the API head %s."
            % (evidence.get("head_sha") or "unknown", pr.get("api_head_sha") or "unknown")
        )
    if pr.get("mergeable") is None:
        notes.append("GitHub has not computed mergeability yet.")
    if pr.get("draft"):
        notes.append("This is a draft pull request; review evidence may be incomplete.")
    if pr.get("state") and pr.get("state") != "open":
        notes.append("The pull request is %s; this result is informational." % pr["state"])

    observed = [run for run in checks.get("items") or [] if run.get("name") != CHECK_NAME]
    critical = config["critical_checks"]
    automated_evidence = []
    if not checks.get("available"):
        automated = category(
            "automated_validation",
            "Automated validation",
            "unassessed",
            "Check runs were unavailable: %s" % (checks.get("error") or "unknown error"),
            [],
        )
    elif checks.get("truncated"):
        automated = category(
            "automated_validation",
            "Automated validation",
            "unassessed",
            "More than 100 check runs were returned, so critical checks cannot be confirmed.",
            [],
        )
    else:
        failed, pending, missing = [], [], []
        for name in critical:
            run = latest_check(observed, name)
            state, _ = check_state(run)
            if run:
                automated_evidence.append(check_line(run))
            else:
                automated_evidence.append("`%s`: not reported for this head." % name)
            if state == "success":
                continue
            if state == "failure":
                failed.append(name)
            elif state == "pending":
                pending.append(name)
            else:
                missing.append(name)
        if failed:
            status = "blocked"
            detail = "Critical checks did not pass: " + ", ".join("`%s`" % n for n in failed)
            if config["hard_blockers"]["failed_critical_checks"]:
                for name in failed:
                    add_blocker("Critical check `%s` did not pass." % name)
        elif pending:
            status = "pending"
            detail = "Critical checks are still running: " + ", ".join("`%s`" % n for n in pending)
        elif missing:
            status = "missing"
            detail = "Critical checks are missing or incomplete: " + ", ".join(
                "`%s`" % n for n in missing
            )
        else:
            status = "pass"
            detail = "All critical checks completed successfully."
        automated = category(
            "automated_validation",
            "Automated validation",
            status,
            detail,
            automated_evidence,
        )
    categories.append(automated)

    for run in observed:
        if run.get("name") in critical:
            continue
        state, _ = check_state(run)
        if state == "failure":
            notes.append(
                "Non-critical check `%s` concluded `%s`; it is not configured as a hard blocker."
                % (run.get("name") or "unnamed", run.get("conclusion") or "none")
            )

    test_files = []
    if files.get("available") and not files.get("truncated"):
        test_files = [
            item["filename"]
            for item in files.get("items") or []
            if matches_any(item["filename"], config["test_patterns"])
        ]
    code_files = [
        item["filename"]
        for item in files.get("items") or []
        if not is_docs_file(item["filename"])
    ]
    if not files.get("available") or files.get("truncated"):
        tests = category(
            "tests",
            "Relevant tests and regression coverage",
            "unassessed",
            "The changed-file list was unavailable or truncated.",
            [],
        )
    elif test_files:
        tests = category(
            "tests",
            "Relevant tests and regression coverage",
            "pass",
            "Test files changed: " + ", ".join("`%s`" % name for name in test_files[:10]),
            ["`%s`" % name for name in test_files],
        )
    elif not code_files:
        tests = category(
            "tests",
            "Relevant tests and regression coverage",
            "not_applicable",
            "Only documentation or metadata changed, so a test-file change is not applicable.",
            [],
        )
    else:
        tests = category(
            "tests",
            "Relevant tests and regression coverage",
            "missing",
            "Code changed without a test-file change. The diff does not show regression coverage; "
            "this is not proof that tests are inadequate.",
            ["Changed code files: " + ", ".join("`%s`" % name for name in code_files[:10])],
        )
    categories.append(tests)

    review_evidence = []
    if not review.get("available"):
        review_category = category(
            "review",
            "Review feedback",
            "unassessed",
            "Review data was unavailable: %s" % (review.get("error") or "unknown error"),
            [],
        )
    elif review.get("threads_truncated"):
        review_category = category(
            "review",
            "Review feedback",
            "unassessed",
            "More than 100 review threads were returned, so the unresolved set is incomplete.",
            [],
        )
    else:
        decision = (review.get("decision") or "").upper()
        unresolved = review.get("unresolved") or []
        review_evidence.append("Decision: `%s`." % (decision or "none"))
        review_evidence.append("Unresolved review threads: %d." % len(unresolved))
        for thread in unresolved[:5]:
            line = "Unresolved thread"
            if thread.get("path"):
                line += " in `%s`" % thread["path"]
            if thread.get("url"):
                line += " ([link](%s))" % thread["url"]
            if thread.get("outdated"):
                line += " (outdated)"
            review_evidence.append(line)
        if decision == "CHANGES_REQUESTED":
            hard = config["hard_blockers"]["changes_requested"]
            if hard:
                add_blocker("The latest review requests changes.")
            review_category = category(
                "review",
                "Review feedback",
                "blocked" if hard else "missing",
                "The latest review requests changes.",
                review_evidence,
            )
        elif unresolved:
            hard = config["hard_blockers"]["unresolved_threads"]
            if hard:
                add_blocker("%d unresolved review thread(s) remain." % len(unresolved))
            review_category = category(
                "review",
                "Review feedback",
                "blocked" if hard else "missing",
                "%d unresolved review thread(s) remain." % len(unresolved),
                review_evidence,
            )
        elif decision == "APPROVED":
            review_category = category(
                "review",
                "Review feedback",
                "pass",
                "The pull request is approved with no unresolved review threads.",
                review_evidence,
            )
        else:
            review_category = category(
                "review",
                "Review feedback",
                "missing",
                "No approving review is recorded.",
                review_evidence,
            )
    categories.append(review_category)

    body_chars = len((pr.get("body") or "").strip())
    items = files.get("items") or []
    changed = int(pr.get("changed_files") or len(items))
    changed_lines = int(pr.get("additions") or 0) + int(pr.get("deletions") or 0)
    if not files.get("available") or files.get("truncated"):
        scope = category(
            "scope",
            "Change scope and implementation evidence",
            "unassessed",
            "The changed-file list was unavailable or truncated.",
            [],
        )
    else:
        limits = config["scope"]
        problems = []
        if body_chars < limits["min_body_chars"]:
            problems.append(
                "the description is %d characters, below %d"
                % (body_chars, limits["min_body_chars"])
            )
        if changed > limits["max_files"]:
            problems.append("the diff changes %d files, above %d" % (changed, limits["max_files"]))
        if changed_lines > limits["max_changed_lines"]:
            problems.append(
                "the diff changes %d lines, above %d"
                % (changed_lines, limits["max_changed_lines"])
            )
        detail = "%d file(s), %d addition(s), %d deletion(s), %d description character(s)." % (
            changed,
            int(pr.get("additions") or 0),
            int(pr.get("deletions") or 0),
            body_chars,
        )
        if problems:
            status = "missing"
            detail += " " + "; ".join(problems) + "."
        else:
            status = "pass"
        scope = category(
            "scope",
            "Change scope and implementation evidence",
            status,
            detail,
            [
                "Limits: %d files, %d changed lines, %d description characters."
                % (
                    limits["max_files"],
                    limits["max_changed_lines"],
                    limits["min_body_chars"],
                )
            ],
        )
    categories.append(scope)

    security_evidence = []
    if not checks.get("available"):
        security = category(
            "security",
            "Security and failure-handling evidence",
            "unassessed",
            "Check runs were unavailable: %s" % (checks.get("error") or "unknown error"),
            [],
        )
    elif checks.get("truncated"):
        security = category(
            "security",
            "Security and failure-handling evidence",
            "unassessed",
            "More than 100 check runs were returned, so security checks cannot be confirmed.",
            [],
        )
    else:
        failed, pending, missing = [], [], []
        for name in config["security_checks"]:
            run = latest_check(observed, name)
            state, _ = check_state(run)
            if run:
                security_evidence.append(check_line(run))
            else:
                security_evidence.append("`%s`: not reported for this head." % name)
            if state == "success":
                continue
            if state == "failure":
                failed.append(name)
            elif state == "pending":
                pending.append(name)
            else:
                missing.append(name)
        sensitive = [
            item["filename"]
            for item in items
            if matches_any(item["filename"], config["security_sensitive_paths"])
        ]
        if failed:
            hard = config["hard_blockers"]["security_check_failure"]
            if hard:
                for name in failed:
                    add_blocker("Security check `%s` did not pass." % name)
            else:
                notes.append(
                    "Security check(s) did not pass: %s. They are not configured as hard blockers."
                    % ", ".join("`%s`" % name for name in failed)
                )
            security = category(
                "security",
                "Security and failure-handling evidence",
                "blocked" if hard else "missing",
                "Security checks did not pass: "
                + ", ".join("`%s`" % name for name in failed),
                security_evidence,
            )
        elif pending:
            security = category(
                "security",
                "Security and failure-handling evidence",
                "pending",
                "Security checks are still running: "
                + ", ".join("`%s`" % name for name in pending),
                security_evidence,
            )
        elif missing:
            security = category(
                "security",
                "Security and failure-handling evidence",
                "missing",
                "Security checks are missing or incomplete: "
                + ", ".join("`%s`" % name for name in missing),
                security_evidence,
            )
        elif not files.get("available") or files.get("truncated"):
            security = category(
                "security",
                "Security and failure-handling evidence",
                "unassessed",
                "Security checks passed, but the changed-file list was unavailable or truncated.",
                security_evidence,
            )
        else:
            security_evidence.extend("Sensitive path: `%s`" % name for name in sensitive[:10])
            if sensitive and not test_files:
                security = category(
                    "security",
                    "Security and failure-handling evidence",
                    "missing",
                    "Security-sensitive paths changed without a test-file change.",
                    security_evidence,
                )
            elif sensitive:
                security = category(
                    "security",
                    "Security and failure-handling evidence",
                    "pass",
                    "Security checks passed; security-sensitive paths changed alongside test files.",
                    security_evidence,
                )
            else:
                security = category(
                    "security",
                    "Security and failure-handling evidence",
                    "pass",
                    "Security checks passed; no configured security-sensitive path changed.",
                    security_evidence,
                )
    categories.append(security)

    if config["hard_blockers"]["merge_conflict"] and pr.get("mergeable") is False:
        add_blocker("The pull request has a merge conflict.")
    if config["hard_blockers"]["draft"] and pr.get("draft"):
        add_blocker("The pull request is a draft.")

    score = sum(item["points"] for item in categories)
    return {
        "rubric_version": RUBRIC_VERSION,
        "check_name": CHECK_NAME,
        "score": max(0, min(5, score)),
        "categories": categories,
        "blockers": blockers,
        "notes": notes,
        "observed_checks": sorted(observed, key=lambda run: run.get("name") or ""),
        "pr": pr,
        "head_sha": evidence.get("head_sha") or "",
        "collected_at": evidence.get("collected_at") or "",
    }


def markdown_cell(value):
    return " ".join(str(value).split()).replace("|", "\\|")


def render_summary(result):
    lines = ["# PR Confidence", ""]
    lines.append("Rubric v%d. Score: **%d / 5**." % (result["rubric_version"], result["score"]))
    lines.append("")
    lines.append(
        "This score measures evidence coverage. It is not a probability that the pull "
        "request is correct, safe, or ready to merge."
    )
    lines.append("")
    pr = result.get("pr") or {}
    if pr.get("number"):
        line = "Pull request #%d" % int(pr["number"])
        if pr.get("title"):
            line += ": " + markdown_cell(pr["title"])
        if result.get("head_sha"):
            line += " at `%s`" % result["head_sha"][:12]
        lines.append(line + ".")
        lines.append("")
    lines.append("| Category | Points | Status |")
    lines.append("| -------- | ------ | ------ |")
    for item in result["categories"]:
        lines.append(
            "| %s | %d/1 | %s |"
            % (
                markdown_cell(item["title"]),
                item["points"],
                markdown_cell(item["status"].replace("_", " ")),
            )
        )
    lines.append("")
    lines.append("## Evidence")
    for item in result["categories"]:
        lines.append("### " + item["title"])
        if item["evidence"]:
            lines.extend("- " + line for line in item["evidence"])
        else:
            lines.append("- No evidence collected.")
        lines.append("")
    lines.append("## Hard blockers")
    if result["blockers"]:
        lines.extend("- " + blocker for blocker in result["blockers"])
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Missing, pending, or unassessed evidence")
    gaps = [item for item in result["categories"] if item["status"] != "pass"]
    if gaps:
        for item in gaps:
            lines.append(
                "- **%s** (%s): %s"
                % (item["title"], item["status"].replace("_", " "), item["detail"])
            )
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Observed checks")
    observed = result.get("observed_checks") or []
    if observed:
        for run in observed[:25]:
            lines.append("- " + check_line(run))
        if len(observed) > 25:
            lines.append("- %d more check run(s) not shown." % (len(observed) - 25))
    else:
        lines.append("No check runs were reported for this head.")
    if result.get("notes"):
        lines.append("")
        lines.append("## Notes")
        lines.extend("- " + note for note in result["notes"])
    lines.append("")
    lines.append("## Limits")
    lines.append("- The result uses the diff, check conclusions, and review metadata available at collection time.")
    lines.append("- It does not run the pull request code as a test, prove correctness, or replace required checks.")
    lines.append("- A low score does not fail the check. Only configured hard blockers fail it.")
    lines.append("- Changed files and review threads are read up to 100 items and marked unassessed when truncated.")
    lines.append("- Skipped, cancelled, neutral, pending, and missing checks do not count as evidence.")
    return "\n".join(lines).rstrip() + "\n"


def build_parser():
    parser = argparse.ArgumentParser(description="Score pull request evidence.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name")
    parser.add_argument("--pr", type=int, help="pull request number")
    parser.add_argument("--head-sha", help="pull request head SHA")
    parser.add_argument("--config", default=".github/pr-confidence.yml")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--evidence", help="score a saved evidence JSON instead of collecting")
    parser.add_argument("--evidence-out", help="write the collected evidence JSON here")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="wait for configured checks to complete before collecting",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=600,
        help="seconds to wait for configured checks (default: 600)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=15.0,
        help="seconds between check status polls (default: 15)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.evidence:
            try:
                evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ConfidenceError("cannot read evidence: %s" % exc)
        else:
            if not args.repo:
                raise ConfidenceError("repository is required")
            if not args.pr:
                raise ConfidenceError("pull request number is required")
            if not args.head_sha:
                raise ConfidenceError("head SHA is required")
            if args.wait and (args.wait_timeout < 0 or args.poll_interval <= 0):
                raise ConfidenceError(
                    "wait timeout must be non-negative and poll interval must be positive"
                )
            if args.wait:
                wait_for_checks(
                    args.repo,
                    args.head_sha,
                    config,
                    args.wait_timeout,
                    args.poll_interval,
                )
            evidence = collect_evidence(args.repo, args.pr, args.head_sha)
        result = evaluate(evidence, config)
        summary = render_summary(result)
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as handle:
                handle.write(summary)
        else:
            print(summary)
        if args.evidence_out:
            Path(args.evidence_out).write_text(
                json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
            )
        print(
            "%s: %d/5, %d hard blocker(s)"
            % (CHECK_NAME, result["score"], len(result["blockers"]))
        )
        return 1 if result["blockers"] else 0
    except (ConfidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        message = "Evidence collection failed: %s" % exc
        if args.summary:
            try:
                with open(args.summary, "a", encoding="utf-8") as handle:
                    handle.write("# PR Confidence\n\n%s\n" % message)
            except OSError:
                pass
        else:
            print("# PR Confidence\n\n%s" % message)
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
