#!/usr/bin/env python3
"""Attach source revision and UTC run time to a benchmark JSON result."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def current_commit(root: Path) -> str | None:
    """Return the full Git commit, or None when the run is outside a checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    commit = result.stdout.strip()
    return commit if commit else None


def attach_provenance(data: dict, commit: str | None, timestamp: str) -> dict:
    """Return benchmark data with explicit provenance fields."""
    if not isinstance(data, dict):
        raise ValueError("benchmark result must be a JSON object")
    if commit is not None and (len(commit) not in (40, 64) or any(c not in "0123456789abcdef" for c in commit)):
        raise ValueError("commit must be a full hexadecimal Git object ID or None")
    if not timestamp.endswith("Z"):
        raise ValueError("timestamp must be UTC and end in Z")

    result = dict(data)
    result["git_commit"] = commit
    result["timestamp_utc"] = timestamp
    return result


def write_provenance(result_path: Path, root: Path) -> None:
    """Update the completed temporary result in place with run provenance."""
    try:
        with result_path.open(encoding="utf-8") as result_file:
            data = json.load(result_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid benchmark JSON: {exc}") from exc

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = attach_provenance(data, current_commit(root), timestamp)
    with result_path.open("w", encoding="utf-8") as result_file:
        json.dump(result, result_file, indent=2, allow_nan=False)
        result_file.write("\n")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: provenance.py RESULT.json REPOSITORY_ROOT", file=sys.stderr)
        return 2
    try:
        write_provenance(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
