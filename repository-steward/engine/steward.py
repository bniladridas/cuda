"""Offline-first, read-only CUDA Repository Steward report coordinator."""

import argparse
import json
import sys
from pathlib import Path

from .contracts import Finding, Report, Severity
from .model_summary import ModelSummaryError
from .benchmark_integrity import analyze_benchmarks
from .health import analyze_health
from .integrations import integration_status
from .readiness import evaluate_readiness
from .tracking import analyze_tracking
from .validation import normalize_validation, validation_findings


def build_report(snapshot: dict, *, include_model_summary: bool = False) -> dict:
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

    benchmark = analyze_benchmarks(snapshot.get("benchmark_results", []))
    report.modules["benchmark_integrity"] = benchmark
    for index, item in enumerate(benchmark["reports"]):
        if item["state"] != "valid":
            report.findings.append(
                Finding(
                    code="benchmark.incomplete",
                    severity=Severity.WARNING,
                    summary=f"Benchmark result {index + 1} lacks complete provenance or measurements.",
                    evidence=tuple(item.get("problems", [])),
                    blocking=False,
                )
            )
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
    report.modules["integrations"] = integration_status(snapshot)
    report.modules["integrations"]["integrations"].update(
        {
        "pr_confidence": {
            "state": "unavailable",
            "entrypoint": ".github/workflows/pr-confidence.yml",
            "approval_required": False,
            "approval_status": "not_applicable",
            "coordinator_write_performed": False,
        },
        "pr_scope_guard": {
            "state": "unavailable",
            "entrypoint": ".github/workflows/pr-scope-guard.yml",
            "approval_required": False,
            "approval_status": "not_applicable",
            "coordinator_write_performed": False,
        },
        "squash_merge": {
            "state": "unavailable",
            "entrypoint": ".github/workflows/squash-merge.yml",
            "approval_required": True,
            "approval_status": "not_asserted",
            "coordinator_write_performed": False,
        },
        "rebase_agent": {
            "state": "unavailable",
            "entrypoint": ".github/workflows/rebase-approved.yml",
            "approval_required": True,
            "approval_status": "not_asserted",
            "coordinator_write_performed": False,
            },
        }
    )
    result = report.to_dict()
    if include_model_summary:
        from .model_summary import summarize_report

        result["modules"]["model_integration"] = summarize_report(result)
    else:
        result["modules"]["model_integration"] = {
            "enabled": False,
            "provider": None,
            "status": "not_requested",
            "note": "Model assistance is optional and is not used for evidence or authorization.",
        }
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="JSON snapshot of GitHub and repository evidence")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    parser.add_argument(
        "--model-summary", action="store_true", help="request an optional advisory summary from configured provider"
    )
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        result = build_report(snapshot, include_model_summary=args.model_summary)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError, json.JSONDecodeError, ModelSummaryError) as exc:
        print(f"steward: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
