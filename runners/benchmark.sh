#!/usr/bin/env bash
# Runs the benchmark and atomically publishes a uniquely named JSON result.
# Refuses to continue on a machine without a CUDA device.
#
# Environment:
#   BUILD_DIR   build directory (default: build)
#   RESULTS_DIR output directory (default: benchmarks/results)
#   BENCH_ARGS  extra arguments passed to cuda_benchmarks (word-split)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/benchmarks/results}"
BIN="$BUILD_DIR/cuda_benchmarks"
tmp=""

cleanup() {
  if [ -n "$tmp" ]; then
    rm -f -- "$tmp"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ ! -x "$BIN" ]; then
  echo "cuda_benchmarks not found at $BIN" >&2
  echo "Build on a host with the CUDA toolkit and an NVIDIA GPU." >&2
  exit 2
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  if ! nvidia-smi -L | grep -q "GPU"; then
    echo "nvidia-smi reports no GPU; refusing to benchmark" >&2
    exit 2
  fi
else
  echo "note: nvidia-smi not on PATH; relying on the runtime device probe" >&2
fi

mkdir -p "$RESULTS_DIR"

# The binary itself re-checks for a device and for correctness before timing.
probe="$("$BIN" --iterations 5 --reps 1 --warmup 1 --json)"
if printf '%s' "$probe" | grep -q "^SKIPPED"; then
  echo "no CUDA device; nothing to benchmark" >&2
  exit 2
fi

gpu_slug="$(printf '%s' "$probe" | sed -n 's/.*"gpu": "\([^"]*\)".*/\1/p' \
  | tr -c 'A-Za-z0-9\n' '-' | sed 's/-\{2,\}/-/g; s/^-//; s/-$//')"
gpu_slug="${gpu_slug:-gpu}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
base="${gpu_slug}-${stamp}-${commit}"

# Keep the temporary file in the destination directory so publication is a
# same-filesystem operation. mktemp supplies a collision-resistant suffix.
tmp="$(mktemp "$RESULTS_DIR/.${base}.tmp.XXXXXX")"
# shellcheck disable=SC2086
if ! "$BIN" --json ${BENCH_ARGS:-} > "$tmp"; then
  echo "benchmark failed; result was not published" >&2
  exit 1
fi

# Reject truncated or otherwise invalid output before it becomes visible as
# a completed result. The plotter expects a JSON object at the top level.
if ! python3 - "$tmp" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as result_file:
        value = json.load(result_file)
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    print(f"invalid benchmark JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)

if not isinstance(value, dict):
    print("invalid benchmark JSON: expected a JSON object", file=sys.stderr)
    raise SystemExit(1)
PY
then
  echo "benchmark result was not published" >&2
  exit 1
fi

# Refresh the temp file's mtime after the benchmark finishes. The plotter uses
# nanosecond mtimes, so concurrent runs finishing in the same second stay ordered.
touch "$tmp"

# link(2) creates the final name atomically and fails rather than overwriting
# an existing result. The temporary file and final file are on one filesystem.
suffix="${tmp##*.tmp.}"
out="$RESULTS_DIR/${base}-${suffix}.json"
if ! ln -- "$tmp" "$out"; then
  echo "could not publish benchmark result without overwriting: $out" >&2
  exit 1
fi
rm -f -- "$tmp"
tmp=""
echo "wrote $out"
