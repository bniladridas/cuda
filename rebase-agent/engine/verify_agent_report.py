#!/usr/bin/env python3
"""Fail closed unless a structured model report meets the requested gate."""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    report = json.loads(open(args.report, encoding="utf-8").read())
    if not report.get("ready_for_validation"):
        raise SystemExit("model review did not approve validation")
    if args.final:
        if report.get("patch_applied"):
            raise SystemExit("final review unexpectedly modified the source")
        if any(item.get("severity") in {"critical", "high"} for item in report.get("findings", [])):
            raise SystemExit("final review found critical or high severity issues")
    elif not report.get("patch_applied"):
        raise SystemExit("agent did not produce a patch for independent validation")


if __name__ == "__main__":
    main()
