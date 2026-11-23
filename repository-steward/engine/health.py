"""Deterministic, read-only repository-health checks."""

import json
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import yaml

MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(\s*(<[^>]+>|[^\s)]+)")
WORKFLOW_PATH = PurePosixPath(".github/workflows")
WORKFLOW_REFERENCE = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")


class DuplicateKeyError(ValueError):
    """Raised when a JSON or YAML mapping repeats a key."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise DuplicateKeyError("unhashable YAML mapping key") from exc
        if duplicate:
            raise DuplicateKeyError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _normalize_repo_path(path: str) -> str:
    parts = []
    for part in PurePosixPath(path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", ".", "/"):
            parts.append(part)
    return "/".join(parts)


def _markdown_target(source: str, raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    path = unquote(parsed.path)
    if path.startswith("/"):
        return _normalize_repo_path(path)
    return _normalize_repo_path(str(PurePosixPath(source).parent / path))


def check_markdown_links(files: dict[str, str]) -> list[dict]:
    findings = []
    paths = set(files)
    for name, content in files.items():
        if not name.lower().endswith(".md"):
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for match in MARKDOWN_LINK.finditer(line):
                target = match.group(1).strip()
                resolved = _markdown_target(name, target)
                if resolved is None:
                    continue
                candidates = {resolved}
                if resolved and not PurePosixPath(resolved).suffix:
                    candidates.update(
                        {
                            f"{resolved}/README.md",
                            f"{resolved}/readme.md",
                            f"{resolved}/index.md",
                        }
                    )
                if not candidates.intersection(paths):
                    findings.append(
                        {
                            "code": "docs.link_missing",
                            "severity": "warning",
                            "path": name,
                            "line": line_number,
                            "target": target,
                            "summary": f"Local Markdown link does not resolve: {target}",
                        }
                    )
    return findings


def check_json_configs(files: dict[str, str]) -> list[dict]:
    findings = []
    for name, content in files.items():
        if not (name.startswith(".github/") and name.endswith(".json")):
            continue
        try:
            json.loads(content, object_pairs_hook=_reject_duplicate_json_keys)
        except (json.JSONDecodeError, DuplicateKeyError, TypeError) as exc:
            findings.append(
                {
                    "code": "config.json_invalid",
                    "severity": "error",
                    "path": name,
                    "summary": f"Invalid JSON configuration: {exc}",
                }
            )
    return findings


def _walk_local_action_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "uses" and isinstance(item, str) and item.startswith("./"):
                yield item[2:]
            else:
                yield from _walk_local_action_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_local_action_refs(item)


def check_github_workflows(files: dict[str, str]) -> list[dict]:
    findings = []
    for name, content in files.items():
        path = PurePosixPath(name)
        if path.parent != WORKFLOW_PATH or path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        try:
            workflow = yaml.load(content, Loader=_UniqueKeyLoader)
        except (yaml.YAMLError, DuplicateKeyError, TypeError) as exc:
            findings.append(
                {
                    "code": "config.yaml_invalid",
                    "severity": "error",
                    "path": name,
                    "summary": f"Invalid GitHub Actions YAML: {exc}",
                }
            )
            continue
        for local_ref in _walk_local_action_refs(workflow):
            action_path = _normalize_repo_path(local_ref)
            candidates = {
                action_path,
                f"{action_path}/action.yml",
                f"{action_path}/action.yaml",
                f"{action_path}/Dockerfile",
            }
            if not candidates.intersection(files):
                findings.append(
                    {
                        "code": "workflow.local_action_missing",
                        "severity": "error",
                        "path": name,
                        "target": local_ref,
                        "summary": f"Local GitHub Action does not exist: ./{local_ref}",
                    }
                )
    return findings



def check_workflow_documentation_references(files: dict[str, str]) -> list[dict]:
    """Find Markdown guidance that still points at workflow files no longer present."""
    findings = []
    for name, content in files.items():
        if not name.lower().endswith(".md"):
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for match in WORKFLOW_REFERENCE.finditer(line):
                target = match.group(0)
                if target not in files:
                    findings.append(
                        {
                            "code": "docs.workflow_reference_missing",
                            "severity": "warning",
                            "path": name,
                            "line": line_number,
                            "target": target,
                            "summary": f"Documentation references a workflow that is not present: {target}",
                        }
                    )
    return findings


def analyze_health(files: dict[str, str]) -> dict:
    if not isinstance(files, dict):
        raise TypeError("files must be a mapping of repository paths to text")
    findings = (check_markdown_links(files) + check_json_configs(files) + check_github_workflows(files)
                 + check_workflow_documentation_references(files))
    return {
        "findings": findings,
        "finding_count": len(findings),
        "mutations_performed": False,
    }
