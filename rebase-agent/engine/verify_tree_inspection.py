#!/usr/bin/env python3
"""Verify tree inspection metadata against approved pull-request SHAs."""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("expected_head")
    parser.add_argument("expected_base")
    args = parser.parse_args()
    report = json.loads(open(args.report, encoding="utf-8").read())
    if report["head"]["sha"] != args.expected_head:
        raise SystemExit("tree inspection head SHA differs from approved PR head")
    if report["base"]["sha"] != args.expected_base:
        raise SystemExit("tree inspection base SHA differs from approved base")


if __name__ == "__main__":
    main()
