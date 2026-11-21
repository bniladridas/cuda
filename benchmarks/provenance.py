#!/usr/bin/env python3
"""Attach source revision and UTC run time to a benchmark JSON result."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEVICE_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
PCI_BUS_ID_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}[.][0-7]$")


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


def validate_device_identity(data: dict) -> None:
    """Validate optional device identity fields before a result is published."""
    has_uuid = "device_uuid" in data
    has_pci_bus_id = "pci_bus_id" in data
    if has_uuid != has_pci_bus_id:
        raise ValueError("device identity requires both device_uuid and pci_bus_id")
    if not has_uuid:
        return

    device_uuid = data["device_uuid"]
    if not isinstance(device_uuid, str) or not DEVICE_UUID_RE.fullmatch(device_uuid):
        raise ValueError("device_uuid must be a canonical UUID")
    pci_bus_id = data["pci_bus_id"]
    if pci_bus_id is not None and (
        not isinstance(pci_bus_id, str) or not PCI_BUS_ID_RE.fullmatch(pci_bus_id)
    ):
        raise ValueError("pci_bus_id must be a PCI bus ID or None")


def attach_provenance(data: dict, commit: str | None, timestamp: str) -> dict:
    """Return benchmark data with explicit provenance fields."""
    if not isinstance(data, dict):
        raise ValueError("benchmark result must be a JSON object")
    validate_device_identity(data)
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
