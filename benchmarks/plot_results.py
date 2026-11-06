#!/usr/bin/env python3
"""Plot a benchmark result file as achieved-versus-peak bandwidth bars.

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
import sys

RESULT_KEYS = {"gpu", "results"}
POINT_KEYS = {"kernel", "n", "gb_per_s"}


def load(path):
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: not a benchmark JSON file ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    missing = RESULT_KEYS - data.keys()
    if missing:
        raise ValueError(f"{path}: missing top-level key(s) {sorted(missing)}")
    if not data["results"]:
        raise ValueError(f"{path}: contains no results")
    for i, point in enumerate(data["results"]):
        missing = POINT_KEYS - point.keys()
        if missing:
            raise ValueError(f"{path}: result {i} missing key(s) {sorted(missing)}")
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

    if args.peak_gbps <= 0:
        parser.error("--peak-gbps must be positive")

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
    ax.set_title(
        f"{data['gpu']} (sm_{data.get('compute_capability', '?')})\n"
        "achieved versus peak memory bandwidth",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(args.out, dpi=150)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
