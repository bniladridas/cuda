#!/usr/bin/env python3
"""Verify tree inspection metadata against approved pull-request SHAs."""

import argparse
import json


def verify_report(report, expected_head, expected_base):
    if report["head"]["sha"] != expected_head:
        raise ValueError("tree inspection head SHA differs from approved PR head")
    if report["base"]["sha"] != expected_base:
        raise ValueError("tree inspection base SHA differs from approved base")
    if report.get("tree_inventory_complete") is not True:
        raise ValueError("tree inspection inventory is incomplete")
    if report.get("pr_file_inventory_matches_head_tree") is not True:
        raise ValueError("GitHub PR file inventory does not match the inspected head tree")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("expected_head")
    parser.add_argument("expected_base")
    args = parser.parse_args()
    with open(args.report, encoding="utf-8") as stream:
        report = json.load(stream)
    try:
        verify_report(report, args.expected_head, args.expected_base)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
