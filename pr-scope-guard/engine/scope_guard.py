#!/usr/bin/env python3
"""Read-only PR Scope Guard.

Compares the scope declared in a pull request title with the files the pull
request changes. The report is advisory: findings never fail the check.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - reported by require_dependencies
    yaml = None

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - reported by require_dependencies
    Draft202012Validator = None

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "config.schema.json"
REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TITLE_RE = re.compile(r"^\[([^\[\]]+)\]\s+(\S.*)$")
SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
API_ROOT = "https://api.github.com"
MAX_LISTED_FILES = 20
MAX_SUMMARY_FILES = 10


class EngineError(Exception):
    pass


def require_dependencies():
    if yaml is None:
        raise EngineError("PyYAML is required (pip install pyyaml)")
    if Draft202012Validator is None:
        raise EngineError("jsonschema is required (pip install jsonschema)")


def load_yaml(path):
    require_dependencies()
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise EngineError("cannot read %s: %s" % (path, exc))
    except yaml.YAMLError as exc:
        raise EngineError("invalid YAML in %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise EngineError("%s must contain a mapping" % path)
    return data


def check_pattern(pattern, label):
    if not isinstance(pattern, str) or not pattern:
        raise EngineError("%s must be a non-empty string" % label)
    if pattern.startswith("/"):
        raise EngineError("%s %r must be repository-relative" % (label, pattern))
    if "\\" in pattern:
        raise EngineError("%s %r must use forward slashes" % (label, pattern))
    for segment in pattern.split("/"):
        if segment in ("", ".", ".."):
            raise EngineError("%s %r has an invalid segment" % (label, pattern))


@lru_cache(maxsize=None)
def glob_regex(pattern):
    parts = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**/", index):
                parts.append("(?:.*/)?")
                index += 3
                continue
            if pattern.startswith("**", index):
                parts.append(".*")
                index += 2
                continue
            parts.append("[^/]*")
            index += 1
            continue
        if char == "?":
            parts.append("[^/]")
            index += 1
            continue
        parts.append(re.escape(char))
        index += 1
    return re.compile("^" + "".join(parts) + "$")


def matches(path, pattern):
    return bool(glob_regex(pattern).match(path))


def normalize_path(path):
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def load_registry(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise EngineError("cannot read %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise EngineError("invalid JSON in %s: %s" % (path, exc))
    if not isinstance(data, dict) or not isinstance(data.get("scopes"), list):
        raise EngineError("%s must contain a scopes list" % path)
    names = {}
    for index, item in enumerate(data["scopes"]):
        if not isinstance(item, dict) or set(item) != {"name", "description"}:
            raise EngineError("%s scope %d must contain name and description" % (path, index))
        name = item["name"]
        description = item["description"]
        if not isinstance(name, str) or not SCOPE_RE.match(name):
            raise EngineError("%s scope %d has an invalid name" % (path, index))
        if not isinstance(description, str) or not description.strip():
            raise EngineError("%s scope %s needs a description" % (path, name))
        if name in names:
            raise EngineError("%s has a duplicate scope %s" % (path, name))
        names[name] = description
    if not names:
        raise EngineError("%s must define at least one scope" % path)
    return names


def load_config(path, registry_names):
    require_dependencies()
    data = load_yaml(path)
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineError("cannot read configuration schema: %s" % exc)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: str(list(error.path)))
    if errors:
        details = "; ".join(
            "%s: %s" % ("/".join(str(part) for part in error.path) or "<root>", error.message)
            for error in errors
        )
        raise EngineError("invalid %s: %s" % (path, details))
    mapped = set(data["scopes"])
    missing = sorted(set(registry_names) - mapped)
    extra = sorted(mapped - set(registry_names))
    if missing or extra:
        problems = []
        if missing:
            problems.append("missing " + ", ".join(missing))
        if extra:
            problems.append("unknown " + ", ".join(extra))
        raise EngineError("%s scopes must match the registry (%s)" % (path, "; ".join(problems)))
    for scope, patterns in data["scopes"].items():
        for pattern in patterns:
            check_pattern(pattern, "%s path" % scope)
    for pattern in data.get("ignore", []):
        check_pattern(pattern, "ignore path")
    return data


def parse_title(title):
    text = " ".join(str(title).split())
    if not text.startswith("["):
        return None, "missing"
    match = TITLE_RE.match(text)
    if not match:
        return None, "malformed"
    scope = match.group(1)
    if scope != scope.strip() or not SCOPE_RE.match(scope):
        return None, "malformed"
    return scope, "ok"


def code_span(value):
    text = " ".join(str(value).split())
    longest = 0
    for match in re.finditer(r"`+", text):
        longest = max(longest, len(match.group(0)))
    fence = "`" * (longest + 1)
    if text.startswith(("`", " ")) or text.endswith(("`", " ")):
        text = " " + text + " "
    return fence + text + fence


def fetch_json(url, token):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-scope-guard",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            link = response.headers.get("Link", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise EngineError("GitHub API %s for %s: %s" % (exc.code, url, detail))
    except urllib.error.URLError as exc:
        raise EngineError("GitHub API request failed for %s: %s" % (url, exc.reason))
    try:
        return json.loads(body), link
    except json.JSONDecodeError as exc:
        raise EngineError("GitHub API returned invalid JSON for %s: %s" % (url, exc))


def next_link(header):
    for part in header.split(","):
        match = re.search(r'<([^>]+)>;\s*rel="([^"]+)"', part)
        if not match or "next" not in match.group(2).split():
            continue
        url = match.group(1)
        if not url.startswith(API_ROOT + "/"):
            raise EngineError("GitHub API returned an unexpected pagination URL")
        return url
    return None


def fetch_pages(url, token):
    items = []
    while url:
        data, link = fetch_json(url, token)
        if not isinstance(data, list):
            raise EngineError("expected a list from %s" % url)
        items.extend(data)
        url = next_link(link)
    return items


def fetch_pr(repo, number, token):
    data, _ = fetch_json("%s/repos/%s/pulls/%d" % (API_ROOT, repo, number), token)
    if not isinstance(data, dict):
        raise EngineError("pull request response is not an object")
    return data


def fetch_files(repo, number, token):
    return fetch_pages(
        "%s/repos/%s/pulls/%d/files?per_page=100" % (API_ROOT, repo, number), token
    )


def load_fixture(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise EngineError("cannot read %s: %s" % (path, exc))
    except json.JSONDecodeError as exc:
        raise EngineError("invalid JSON in %s: %s" % (path, exc))
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("pull_request"), dict)
        or not isinstance(data.get("files"), list)
    ):
        raise EngineError("%s must contain pull_request and files" % path)
    return data["pull_request"], data["files"]


def pr_fields(pr):
    number = pr.get("number")
    if not isinstance(number, int) or number <= 0:
        raise EngineError("pull request number is invalid")
    title = pr.get("title")
    if not isinstance(title, str):
        raise EngineError("pull request title is missing")
    head_sha = (pr.get("head") or {}).get("sha")
    base_sha = (pr.get("base") or {}).get("sha")
    for label, sha in (("head", head_sha), ("base", base_sha)):
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise EngineError("pull request %s SHA is invalid" % label)
    return number, title, head_sha, base_sha


def file_records(files, ignore_patterns, scope_patterns):
    records = []
    ignored = 0
    for index, item in enumerate(files):
        if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
            raise EngineError("changed file %d has no filename" % index)
        filename = item["filename"]
        path = normalize_path(filename)
        if any(matches(path, pattern) for pattern in ignore_patterns):
            ignored += 1
            continue
        scopes = sorted(
            scope
            for scope, patterns in scope_patterns.items()
            if any(matches(path, pattern) for pattern in patterns)
        )
        records.append(
            {
                "filename": filename,
                "status": item.get("status")
                if isinstance(item.get("status"), str)
                else "unknown",
                "previous_filename": item.get("previous_filename")
                if isinstance(item.get("previous_filename"), str)
                else None,
                "scopes": scopes,
            }
        )
    return records, ignored


def make_finding(code, severity, message, files=None, scopes=None, scope=None):
    finding = {"code": code, "severity": severity, "message": message}
    if files is not None:
        finding["files"] = [record["filename"] for record in files[:MAX_LISTED_FILES]]
        finding["count"] = len(files)
    if scopes:
        finding["scopes"] = scopes
    if scope:
        finding["scope"] = scope
    return finding


def analyze(repo, pr, files, registry, config):
    number, title, head_sha, base_sha = pr_fields(pr)
    scope, title_status = parse_title(title)
    if scope is not None and scope not in registry:
        title_status = "unknown"

    records, ignored = file_records(files, config.get("ignore", []), config["scopes"])
    touched = sorted({name for record in records for name in record["scopes"]})
    findings = []

    if title_status == "missing":
        findings.append(
            make_finding(
                "title_missing_scope",
                "warning",
                "The title does not start with a [scope].",
            )
        )
    elif title_status == "malformed":
        findings.append(
            make_finding(
                "title_malformed",
                "warning",
                "The title must be [scope] Description with a lowercase scope and a description.",
            )
        )
    elif title_status == "unknown":
        findings.append(
            make_finding(
                "unknown_scope",
                "warning",
                "The declared scope is not in the scope registry.",
                scope=scope,
            )
        )

    declared_known = title_status == "ok"
    matched = [record for record in records if declared_known and scope in record["scopes"]]
    outside = [record for record in records if declared_known and scope not in record["scopes"]]

    if declared_known and not matched:
        findings.append(
            make_finding(
                "scope_matches_no_changed_files",
                "warning",
                "The declared scope does not match any changed file.",
                scope=scope,
            )
        )
    if outside:
        findings.append(
            make_finding(
                "files_outside_scope",
                "warning",
                "Some changed files are outside the declared scope.",
                files=outside,
            )
        )

    unmapped = [record for record in records if not record["scopes"]]
    if unmapped:
        findings.append(
            make_finding(
                "files_matching_no_scope",
                "info",
                "Some changed files match no scope in the path map.",
                files=unmapped,
            )
        )

    counts = Counter(name for record in records for name in record["scopes"])
    candidates = [
        {"scope": name, "files": count}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
    ]

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": repo,
        "pr_number": number,
        "title": title,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "declared_scope": scope,
        "title_status": title_status,
        "files": records,
        "findings": findings,
        "candidates": candidates,
        "counts": {
            "files": len(records),
            "matched": len(matched),
            "outside": len(outside),
            "unmapped": len(unmapped),
            "ignored": ignored,
            "scopes_touched": len(touched),
        },
    }


def render_summary(result):
    lines = ["# PR Scope Guard", ""]
    lines.append(
        "Pull request #%d: %s" % (result["pr_number"], code_span(result["title"]))
    )
    if result["declared_scope"]:
        lines.append(
            "Declared scope: %s (%s)"
            % (code_span(result["declared_scope"]), result["title_status"])
        )
    else:
        lines.append("Declared scope: none (%s)" % result["title_status"])
    counts = result["counts"]
    lines.append(
        "Changed files: %d, matched: %d, outside: %d, unmapped: %d, ignored: %d."
        % (counts["files"], counts["matched"], counts["outside"], counts["unmapped"], counts["ignored"])
    )
    lines.append("")
    lines.append("Advisory only. This report does not block the pull request.")
    lines.append("")
    if result["findings"]:
        lines.append("## Findings")
        lines.append("")
        for finding in result["findings"]:
            line = "- %s: %s" % (code_span(finding["code"]), finding["message"])
            if finding.get("scope"):
                line += " Declared scope: %s." % code_span(finding["scope"])
            if finding.get("scopes"):
                line += " Scopes: %s." % ", ".join(code_span(name) for name in finding["scopes"])
            lines.append(line)
            for filename in finding.get("files", [])[:MAX_SUMMARY_FILES]:
                lines.append("  - %s" % code_span(filename))
            remaining = finding.get("count", 0) - MAX_SUMMARY_FILES
            if remaining > 0:
                lines.append("  - and %d more" % remaining)
    else:
        lines.append("No scope mismatches found.")
    if result["candidates"] and (result["findings"] or counts["outside"]):
        lines.append("")
        lines.append("## Candidate scopes")
        lines.append("")
        for candidate in result["candidates"]:
            lines.append(
                "- %s: %d changed file(s)"
                % (code_span(candidate["scope"]), candidate["files"])
            )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only PR scope check")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--config", default=".github/pr-scope-guard.yml")
    parser.add_argument("--registry", default=".github/pr-scopes.json")
    parser.add_argument("--fixture")
    parser.add_argument("--summary")
    parser.add_argument("--artifact-out", required=True)
    args = parser.parse_args(argv)

    try:
        if not REPO_RE.match(args.repo):
            raise EngineError("repository must be owner/name")
        owner, name = args.repo.split("/", 1)
        if owner in (".", "..") or name in (".", ".."):
            raise EngineError("repository must not contain dot segments")
        if args.pr <= 0:
            raise EngineError("pull request number must be positive")
        registry = load_registry(args.registry)
        config = load_config(args.config, set(registry))
        if args.fixture:
            pr, files = load_fixture(args.fixture)
        else:
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not token:
                raise EngineError("GH_TOKEN or GITHUB_TOKEN is required")
            pr = fetch_pr(args.repo, args.pr, token)
            files = fetch_files(args.repo, args.pr, token)
        if pr.get("number") != args.pr:
            raise EngineError(
                "pull request number %s does not match --pr %d" % (pr.get("number"), args.pr)
            )
        result = analyze(args.repo, pr, files, registry, config)
        artifact_path = Path(args.artifact_out)
        try:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            raise EngineError("cannot write artifact: %s" % exc)
        summary = render_summary(result)
        if args.summary:
            try:
                with open(args.summary, "a", encoding="utf-8") as handle:
                    handle.write(summary)
            except OSError as exc:
                raise EngineError("cannot write summary: %s" % exc)
        else:
            print(summary, end="")
        return 0
    except EngineError as exc:
        print("pr-scope-guard: %s" % exc, file=sys.stderr)
        if args.summary:
            try:
                with open(args.summary, "a", encoding="utf-8") as handle:
                    handle.write("## PR Scope Guard error\n\n%s\n" % code_span(str(exc)))
            except OSError:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
