#!/usr/bin/env python3
"""Write bounded reviewer feedback supplied to a manual integration dispatch."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    args = parser.parse_args()
    feedback = os.environ.get("REVIEW_FEEDBACK", "").strip()
    if len(feedback.encode("utf-8")) > 10000:
        raise SystemExit("review feedback exceeds 10000 UTF-8 bytes")
    Path(args.output).write_text(feedback + ("\n" if feedback else ""), encoding="utf-8")


if __name__ == "__main__":
    main()
