#!/usr/bin/env bash
# Plots the newest benchmark result as achieved-versus-peak bandwidth.
# There is no default peak: pass the device's spec-sheet number so the chart
# compares against a recorded reference rather than a guessed one.
#
# Environment:
#   RESULTS_DIR  where result JSON files live (default: benchmarks/results)
#   PEAK_GBPS    device peak memory bandwidth in GB/s (required)
#   OUT          output PNG (default: benchmarks/results/<result>.png)
#
# Exit codes: 0 wrote the chart, 2 no result file or PEAK_GBPS unset,
#             1 plotting failed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/benchmarks/results}"

if [ -z "${PEAK_GBPS:-}" ]; then
  echo "set PEAK_GBPS to the device's peak memory bandwidth in GB/s" >&2
  echo "(vendor spec sheet; see docs/methodology.md)" >&2
  exit 2
fi

# Newest by modification time; the file name also carries a timestamp.
# GNU stat uses -c, BSD/macOS stat uses -f, so both are attempted.
latest=""
latest_time=-1
while IFS= read -r candidate; do
  candidate_time="$(stat -c '%Y' "$candidate" 2>/dev/null \
    || stat -f '%m' "$candidate" 2>/dev/null || echo 0)"
  if [ "$candidate_time" -ge "$latest_time" ]; then
    latest="$candidate"
    latest_time="$candidate_time"
  fi
done < <(find "$RESULTS_DIR" -maxdepth 1 -name '*.json' -type f)
if [ -z "$latest" ]; then
  echo "no result files in $RESULTS_DIR; run runners/benchmark.sh on a GPU first" >&2
  exit 2
fi

out="${OUT:-${latest%.json}.png}"
exec python3 "$ROOT/benchmarks/plot_results.py" "$latest" \
  --peak-gbps "$PEAK_GBPS" --out "$out"
