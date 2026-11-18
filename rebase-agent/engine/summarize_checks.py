#!/usr/bin/env python3
"""Add post-update check conclusions to the audit and fail on pending/failing checks."""

import json
import sys
from pathlib import Path


def main():
    checks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("check_runs", [])
    audit_path = Path(sys.argv[2])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    summary = [
        {"name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")}
        for item in checks
    ]
    audit["post_update_checks"] = summary
    audit["all_checks_completed"] = bool(checks) and all(item["status"] == "completed" for item in checks)
    audit["all_reported_checks_acceptable"] = bool(checks) and all(
        item["conclusion"] in {"success", "skipped", "neutral"} for item in checks
    )
    audit["branch_protection_required_checks_verified"] = False
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not audit["all_checks_completed"] or not audit["all_reported_checks_acceptable"]:
        raise SystemExit("post-update checks are pending or failing; inspect audit artifact")


if __name__ == "__main__":
    main()
