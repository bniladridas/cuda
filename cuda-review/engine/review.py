#!/usr/bin/env python3
"""Run the existing bounded reviewer in read-only mode for CUDA Review."""

import argparse
import os
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "rebase-agent" / "engine"
sys.path.insert(0, str(ENGINE))

import repair_agent  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--diff", required=True)
    parser.add_argument("--files", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    model = os.environ.get("OPENROUTER_MODEL", "openrouter/free").strip()
    if not model or len(model) > 200:
        raise SystemExit("OPENROUTER_MODEL must be a non-empty model identifier")
    repair_agent.MODEL = model

    try:
        report = repair_agent.Agent(
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
