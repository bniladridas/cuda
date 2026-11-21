#!/usr/bin/env python3
"""Plot a benchmark result file as achieved-versus-peak bandwidth.

The input is one JSON file written by `runners/benchmark.sh`, i.e. by
`cuda_benchmarks --json` on a real device. Nothing here invents data: with no
result file the script refuses to run, and peak bandwidth is read from a value
you record from the vendor spec, not guessed.

Usage:
  benchmarks/plot_results.py RESULT.json --peak-gbps 600 [--out gate.png]

Requires matplotlib (pip install matplotlib). Deliberately not a build
dependency: the repository builds and tests without Python.

The chart follows the same idea as a publish gate: one bar per measured point,
one dashed line for the reference the measurement is judged against.
"""

import argparse
import json
import math
import re
import sys

RESULT_KEYS = {"gpu", "results"}
POINT_KEYS = {"kernel", "n", "gb_per_s"}
MAX_ELEMENT_COUNT = (1 << 63) - 1
DEVICE_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
PCI_BUS_ID_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$")


def load(path):
    """Load and validate benchmark JSON before any plotting dependencies load."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not a benchmark JSON file ({exc})") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")

    missing = RESULT_KEYS - data.keys()
    if missing:
        raise ValueError(f"{path}: missing top-level key(s) {sorted(missing)}")

    if not isinstance(data["gpu"], str) or not data["gpu"].strip():
        raise ValueError(f"{path}: field 'gpu' must be a non-empty string")

    has_commit = "git_commit" in data
    has_timestamp = "timestamp_utc" in data
    if has_commit != has_timestamp:
        raise ValueError(f"{path}: provenance requires both 'git_commit' and 'timestamp_utc'")
    has_device_uuid = "device_uuid" in data
    has_pci_bus_id = "pci_bus_id" in data
    if has_device_uuid != has_pci_bus_id:
        raise ValueError(f"{path}: device identity requires both 'device_uuid' and 'pci_bus_id'")
    if has_device_uuid:
        device_uuid = data["device_uuid"]
        if not isinstance(device_uuid, str) or not DEVICE_UUID_RE.fullmatch(device_uuid):
            raise ValueError(f"{path}: field 'device_uuid' must be a canonical UUID")
        pci_bus_id = data["pci_bus_id"]
        if pci_bus_id is not None and (
            not isinstance(pci_bus_id, str) or not PCI_BUS_ID_RE.fullmatch(pci_bus_id)
        ):
            raise ValueError(f"{path}: field 'pci_bus_id' must be a PCI bus ID or null")

    if has_commit:
        commit = data["git_commit"]
        if commit is not None and (
            not isinstance(commit, str)
            or len(commit) not in (40, 64)
            or any(char not in "0123456789abcdef" for char in commit)
        ):
            raise ValueError(f"{path}: field 'git_commit' must be a full hexadecimal commit or null")
        timestamp = data["timestamp_utc"]
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ValueError(f"{path}: field 'timestamp_utc' must be a UTC timestamp ending in Z")
        try:
            from datetime import datetime

            datetime.fromisoformat(timestamp[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError(f"{path}: field 'timestamp_utc' must be a valid ISO 8601 timestamp") from exc

    results = data["results"]
    if not isinstance(results, list) or not results:
        raise ValueError(f"{path}: field 'results' must be a non-empty list")

    for i, point in enumerate(results):
        prefix = f"{path}: results[{i}]"
        if not isinstance(point, dict):
            raise ValueError(f"{prefix} must be an object")

        missing = POINT_KEYS - point.keys()
        if missing:
            raise ValueError(f"{prefix} missing key(s) {sorted(missing)}")

        if not isinstance(point["kernel"], str) or not point["kernel"].strip():
            raise ValueError(f"{prefix}.kernel must be a non-empty string")

        n = point["n"]
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0 or n > MAX_ELEMENT_COUNT:
            raise ValueError(f"{prefix}.n must be a positive integer no greater than {MAX_ELEMENT_COUNT}")

        bandwidth = point["gb_per_s"]
        try:
            valid_bandwidth = (
                not isinstance(bandwidth, bool)
                and isinstance(bandwidth, (int, float))
                and math.isfinite(float(bandwidth))
                and bandwidth >= 0
            )
        except OverflowError:
            valid_bandwidth = False
        if not valid_bandwidth:
            raise ValueError(f"{prefix}.gb_per_s must be a finite, non-negative number")

    return data


def human_size(n):
    for unit, scale in (("Gi", 1 << 30), ("Mi", 1 << 20), ("Ki", 1 << 10)):
        if n >= scale:
            value = n / scale
            return f"{value:g}{unit}"
    return str(n)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result", help="JSON file written by runners/benchmark.sh")
    parser.add_argument(
        "--peak-gbps",
        type=float,
        required=True,
        help="device peak memory bandwidth in GB/s, from the vendor spec sheet",
    )
    parser.add_argument("--out", default="bandwidth.png", help="output PNG")
    args = parser.parse_args()

    if not math.isfinite(args.peak_gbps) or args.peak_gbps <= 0:
        parser.error("--peak-gbps must be finite and strictly positive")

    try:
        data = load(args.result)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("error: matplotlib is required (pip install matplotlib)", file=sys.stderr)
        return 1

    points = data["results"]
    labels = [f"{p['kernel']}\n{p['n']:,} ({human_size(p['n'])})" for p in points]
    achieved = [p["gb_per_s"] for p in points]
    fraction = [a / args.peak_gbps for a in achieved]

    fig, ax = plt.subplots(figsize=(max(6.5, 1.1 * len(points) + 2.5), 3.6))
    bars = ax.bar(range(len(points)), fraction, width=0.6, color="black")
    ax.axhline(1.0, linestyle="--", linewidth=1, color="0.35")
    top = max(1.15, 1.25 * max(fraction))
    # Label just above the line. Headroom is relative to the data, so a bar
    # above peak (a spec sheet underestimate) does not push the label out.
    ax.text(
        0.01,
        (1.0 / top) + 0.01,
        f"peak {args.peak_gbps:g} GB/s",
        transform=ax.transAxes,
        va="bottom",
        ha="left",
        fontsize=8,
        color="0.35",
    )
    for bar, gbps in zip(bars, achieved):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{gbps:.0f} GB/s\n({bar.get_height():.0%})",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.set_xticks(range(len(points)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("achieved / peak bandwidth")
    ax.set_ylim(0, top)
    if "timestamp_utc" in data:
        commit = data["git_commit"]
        revision = commit[:12] if commit else "unknown revision"
        provenance = f"commit {revision} | {data['timestamp_utc']}"
    else:
        provenance = "legacy result without embedded provenance"
    if "device_uuid" in data:
        device_identity = f"UUID {data['device_uuid']}"
        if data["pci_bus_id"] is not None:
            device_identity += f" | PCI {data['pci_bus_id']}"
    else:
        device_identity = "legacy result without device identifier"
    ax.set_title(
        f"{data['gpu']} (sm_{data.get('compute_capability', '?')})\\n"
        f"{device_identity}\\nachieved versus peak memory bandwidth\\n{provenance}",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
