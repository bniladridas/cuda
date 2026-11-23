"""Validate benchmark provenance and measurement completeness without publishing claims."""

import math
import re
from datetime import datetime

COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
UUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
PCI = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}[.][0-7]$")


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_benchmark_result(result: dict) -> dict:
    problems = []
    if not isinstance(result, dict):
        return {"state": "invalid", "problems": ["result must be a JSON object"], "publishable": False}
    if not isinstance(result.get("git_commit"), str) or not COMMIT.fullmatch(result["git_commit"]):
        problems.append("missing or invalid full git_commit")
    timestamp = result.get("timestamp_utc")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        problems.append("missing UTC timestamp_utc")
    else:
        try:
            datetime.fromisoformat(timestamp[:-1] + "+00:00")
        except ValueError:
            problems.append("timestamp_utc is not a valid ISO-8601 timestamp")
    for key in ("gpu", "compute_capability", "driver", "cuda_runtime"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            problems.append(f"missing {key}")
    if not isinstance(result.get("device_uuid"), str) or not UUID.fullmatch(result["device_uuid"]):
        problems.append("missing or invalid device_uuid")
    pci = result.get("pci_bus_id")
    if pci is not None and (not isinstance(pci, str) or not PCI.fullmatch(pci)):
        problems.append("invalid pci_bus_id")
    if not _positive_int(result.get("iterations_per_batch")):
        problems.append("iterations_per_batch must be a positive integer")
    if not _positive_int(result.get("batches")):
        problems.append("batches must be a positive integer")
    if not isinstance(result.get("warmup"), int) or isinstance(result.get("warmup"), bool) or result["warmup"] < 0:
        problems.append("warmup must be a non-negative integer")
    rows = result.get("results")
    if not isinstance(rows, list) or not rows:
        problems.append("results must be a non-empty list")
    else:
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                problems.append(f"results[{index}] must be an object")
                continue
            if not isinstance(row.get("kernel"), str) or not row["kernel"].strip():
                problems.append(f"results[{index}] is missing kernel")
            if not _positive_int(row.get("n")):
                problems.append(f"results[{index}].n must be a positive integer")
            for key in ("median_ms", "min_ms", "p90_ms"):
                if not _finite_number(row.get(key)) or row[key] <= 0:
                    problems.append(f"results[{index}].{key} must be finite and positive")
            if not _finite_number(row.get("gb_per_s")) or row["gb_per_s"] < 0:
                problems.append(f"results[{index}].gb_per_s must be finite and non-negative")
    return {
        "state": "valid" if not problems else "incomplete",
        "problems": problems,
        "publishable": not problems,
        "methodology_reference": "docs/methodology.md",
        "performance_claim_authorized": False,
    }


def analyze_benchmarks(results: list) -> dict:
    if not isinstance(results, list):
        raise ValueError("benchmark_results must be a list")
    reports = [validate_benchmark_result(item) for item in results]
    return {
        "result_count": len(reports),
        "valid_count": sum(item["state"] == "valid" for item in reports),
        "reports": reports,
        "performance_claims_published": False,
    }
