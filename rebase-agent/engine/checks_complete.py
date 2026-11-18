#!/usr/bin/env python3
"""Return success only when at least one check run exists and all have completed."""

import json
import sys
from pathlib import Path


def main():
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    checks = report.get("check_runs", [])
    if not checks or not all(item.get("status") == "completed" for item in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
