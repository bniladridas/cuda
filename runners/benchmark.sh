#!/usr/bin/env bash
# Runs the benchmark and stores a JSON result file named after the GPU and
# date. Refuses to continue on a machine without a CUDA device.
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

# The binary itself re-checks for a device and for correctness before timing,
# and writes nothing but the SKIPPED line if there is no GPU.
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
out="$RESULTS_DIR/${gpu_slug}-${stamp}-${commit}.json"

# shellcheck disable=SC2086
"$BIN" --json ${BENCH_ARGS:-} > "$out"
echo "wrote $out"
