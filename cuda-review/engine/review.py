#!/usr/bin/env python3
"""Run the existing bounded reviewer in read-only mode for CUDA Review."""

import argparse
import json
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "rebase-agent" / "engine"
sys.path.insert(0, str(ENGINE))

import repair_agent  # noqa: E402


class CUDAReviewAgent(repair_agent.Agent):
    """Apply CUDA- and workflow-specific review guidance to the shared engine."""

    def call_model(self, messages):
        focus = (
            " CUDA-specific review focus when relevant: verify memory bounds and address spaces, "
            "race freedom, synchronization and atomics, stream/event ordering, launch dimensions, "
            "grid-stride coverage, asynchronous error handling, alignment and aliasing, integer "
            "overflow, reduction numerical behavior, and host/device compilation compatibility. "
            "For automation changes, inspect workflow permissions, untrusted PR data handling, "
            "secret isolation, idempotency, stale-SHA checks, and validation of model output. "
            "Never describe CPU-only checks as GPU validation."
        )
        if focus not in messages[0]["content"]:
            messages[0]["content"] += focus
        return super().call_model(messages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--diff", required=True)
    parser.add_argument("--files", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    config_path = Path(__file__).resolve().parents[2] / ".github" / "cuda-review.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model = (os.environ.get("OPENROUTER_MODEL") or config.get("default_model", "openrouter/free")).strip()
    if not model or len(model) > 200:
        raise SystemExit("configured model must be a non-empty model identifier")
    max_diff_bytes = config.get("max_diff_bytes", 180000)
    if not isinstance(max_diff_bytes, int) or isinstance(max_diff_bytes, bool) or not 1 <= max_diff_bytes <= 180000:
        raise SystemExit("max_diff_bytes must be between 1 and 180000")
    repair_agent.MODEL = model
    repair_agent.MAX_DIFF_BYTES = max_diff_bytes

    try:
        report = CUDAReviewAgent(
            Path(args.source),
            Path(args.diff),
            Path(args.report),
            allow_patch=False,
            files_path=args.files,
        ).run()
    except (OSError, repair_agent.AgentError) as exc:
        print("cuda-review: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        "Reviewed %d changed files with %s; %d finding(s)."
        % (len(report["changed_files"]), report["model"], len(report["findings"]))
    )


if __name__ == "__main__":
    main()
