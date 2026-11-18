#!/usr/bin/env python3
"""Extract review text and inline context from a GitHub review event payload."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    args = parser.parse_args()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise SystemExit("GITHUB_EVENT_PATH is required")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    comment = event.get("comment") or {}
    review = event.get("review") or {}
    pull_request = event.get("pull_request") or {}
    payload = {
        "event": event.get("action"),
        "actor": (comment.get("user") or review.get("user") or {}).get("login"),
        "body": comment.get("body") or review.get("body") or "",
        "path": comment.get("path"),
        "line": comment.get("line") or comment.get("original_line"),
        "diff_hunk": comment.get("diff_hunk"),
        "commit_id": comment.get("commit_id"),
        "review_state": review.get("state"),
        "pull_request": pull_request.get("number"),
        "head_sha": (pull_request.get("head") or {}).get("sha"),
        "base_sha": (pull_request.get("base") or {}).get("sha"),
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(serialized.encode("utf-8")) > 10000:
        raise SystemExit("review event context exceeds 10000 UTF-8 bytes")
    if not payload["body"].strip():
        raise SystemExit("review event contains no textual feedback")
    Path(args.output).write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
