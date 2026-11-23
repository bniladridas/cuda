"""Offline-first, read-only CUDA Repository Steward report coordinator."""

import argparse
import json
import sys
from pathlib import Path

from .contracts import Finding, Report, Severity
from .health import analyze_health
from .readiness import evaluate_readiness
from .tracking import analyze_tracking
from .validation import normalize_validation, validation_findings


def build_report(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")
    report = Report(repository=str(snapshot.get("repository") or ""))
    tracking = analyze_tracking(snapshot)
    report.modules["issue_tracking"] = tracking
    for item in tracking["findings"]:
        report.findings.append(
            Finding(
                code=item["code"],
                severity=Severity(item["severity"]),
                summary=item["summary"],
                evidence=tuple(item.get("evidence", [])),
                blocking=bool(item.get("blocking", False)),
            )
        )

    evidence = normalize_validation(snapshot)
    report.evidence.extend(evidence)
    for item in validation_findings(evidence):
        report.findings.append(
            Finding(
                code=item["code"],
                severity=Severity(item["severity"]),
                summary=item["summary"],
                evidence=tuple(item.get("evidence", [])),
                blocking=bool(item.get("blocking", False)),
            )
        )
    report.modules["validation"] = {
        "evidence": [item.to_dict() for item in evidence],
        "findings": validation_findings(evidence),
    }

    health = analyze_health(snapshot.get("files", {}))
    report.modules["repository_health"] = health
    for item in health["findings"]:
        report.findings.append(
            Finding(
                code=item["code"],
                severity=Severity(item["severity"]),
                summary=item["summary"],
                evidence=(item.get("path", ""),),
                blocking=False,
            )
        )

    report.modules["release_readiness"] = evaluate_readiness(evidence, snapshot.get("readiness_policy"))
    report.modules["integrations"] = {
        "label_review": {
            "status": "existing_engine",
            "path": "label-review/engine/review.py",
            "mode": "read-only adapter boundary",
        },
        "issue_landing": {
            "status": "existing_engine",
            "path": "issue-landing/engine/landing.py",
            "mode": "read-only adapter boundary",
        },
        "pr_confidence": {
            "status": "existing_engine",
            "path": "pr-confidence/engine/confidence.py",
            "mode": "read-only adapter boundary",
        },
        "pr_scope_guard": {
            "status": "existing_engine",
            "path": "pr-scope-guard/engine/scope_guard.py",
            "mode": "read-only adapter boundary",
        },
        "squash_merge": {
            "status": "existing_engine",
            "path": "squash-merge/engine/merge_gate.py",
            "mode": "maintainer approval remains separate",
        },
        "rebase_agent": {
            "status": "existing_engine",
            "path": "rebase-agent/engine/rebase.py",
            "mode": "bounded repair remains authorization gated",
        },
    }
    report.modules["model_integration"] = {
        "enabled": False,
        "provider": None,
        "status": "not_configured",
        "note": "Model assistance is optional and is not used for evidence or authorization.",
    }
    return report.to_dict()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="JSON snapshot of GitHub and repository evidence")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        result = build_report(snapshot)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"steward: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
