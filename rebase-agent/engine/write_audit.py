#!/usr/bin/env python3
"""Create the durable pre-check audit record for an approved PR update."""

import json
import os
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    report = load("review/final-review.json")
    audit = {
        "pull_request": int(os.environ["PR_NUMBER"]),
        "actor": os.environ.get("GITHUB_ACTOR"),
        "operation": os.environ["OPERATION"],
        "old_head_sha": os.environ["EXPECTED_HEAD"],
        "new_head_sha": os.environ["RESULT_SHA"],
        "base_sha": os.environ["EXPECTED_BASE"],
        "tree_sha": os.environ["RESULT_TREE"],
        "force_with_lease": os.environ["OPERATION"] == "rebase",
        "initial_agent_review": load("proposal/agent-report.json"),
        "tree_inspection": load("proposal/tree-inspection.json"),
        "final_review": report,
        "validation": load("prepared/validation.json"),
        "diff_stat": Path("prepared/prepared-diff-stat.txt").read_text(encoding="utf-8"),
        "post_update_checks": "pending",
    }
    Path("audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
