#!/usr/bin/env python3
"""Write the deterministic validation record after all preceding checks pass."""

import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: write_validation_report.py OUTPUT")
    report = {
        "ruff_check": "passed",
        "ruff_format": "passed",
        "python_test_suites": [
            "rebase-agent",
            "label-review",
            "issue-landing",
            "pr-confidence",
            "pr-scope-guard",
            "format-repair",
            "benchmarks-if-present",
        ],
        "cmake_cpu_configure": "passed",
        "cmake_cpu_build": "passed",
        "ctest_cpu": "passed",
        "gpu_validation": "not_run_no_gpu_runner",
    }
    Path(sys.argv[1]).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
