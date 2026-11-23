"""Deterministic local repository-health checks for Markdown links and JSON config."""

import json
import re
from pathlib import PurePosixPath

MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")


def check_markdown_links(files: dict[str, str]) -> list[dict]:
    findings = []
    paths = set(files)
    for name, content in files.items():
        if not name.lower().endswith(".md"):
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for match in MARKDOWN_LINK.finditer(line):
                target = match.group(1).strip().split("#", 1)[0].split("?", 1)[0]
                if not target or target.startswith(("http://", "https://", "mailto:", "data:")):
                    continue
                if target.startswith("<") and target.endswith(">"):
                    target = target[1:-1]
                resolved = PurePosixPath(name).parent / target
                normalized = str(resolved)
                parts = []
                for part in PurePosixPath(normalized).parts:
                    if part == "..":
                        if parts:
                            parts.pop()
                    elif part not in ("", "."):
                        parts.append(part)
                normalized = "/".join(parts)
                if normalized not in paths:
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
            json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            findings.append(
                {
                    "code": "config.json_invalid",
                    "severity": "error",
                    "path": name,
                    "summary": f"Invalid JSON configuration: {exc}",
                }
            )
    return findings


def analyze_health(files: dict[str, str]) -> dict:
    findings = check_markdown_links(files) + check_json_configs(files)
    return {"findings": findings, "finding_count": len(findings), "mutations_performed": False}
