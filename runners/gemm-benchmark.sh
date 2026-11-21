#!/usr/bin/env bash
# Correctness-gated GEMM benchmark with embedded Git and UTC provenance.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
RESULTS_DIR="${RESULTS_DIR:-$ROOT/benchmarks/results}"
BIN="$BUILD_DIR/cuda_gemm_benchmarks"
tmp=""

cleanup() {
  if [ -n "$tmp" ]; then rm -f -- "$tmp"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ ! -x "$BIN" ]; then
  echo "cuda_gemm_benchmarks not found at $BIN; build on a CUDA host" >&2
  exit 2
fi
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to validate benchmark provenance" >&2
  exit 2
}
if command -v nvidia-smi >/dev/null 2>&1 && ! nvidia-smi -L | grep -q GPU; then
  echo "nvidia-smi reports no GPU" >&2
  exit 2
fi

mkdir -p "$RESULTS_DIR"
gpu_json="$("$BIN")"
printf '%s\n' "$gpu_json" | grep -q '"results"' || {
  echo "benchmark did not produce result JSON" >&2
  exit 1
}
gpu_slug="$(printf '%s' "$gpu_json" | sed -n 's/.*"gpu": "\([^"]*\)".*/\1/p' |
  tr -c 'A-Za-z0-9\n' '-' | sed 's/-\{2,\}/-/g; s/^-//; s/-$//')"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
commit="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
base="${gpu_slug:-gpu}-gemm-$stamp-$commit"
tmp="$(mktemp "$RESULTS_DIR/.${base}.tmp.XXXXXX")"
printf '%s\n' "$gpu_json" > "$tmp"
python3 "$ROOT/benchmarks/provenance.py" "$tmp" "$ROOT"
touch "$tmp"
suffix="${tmp##*.tmp.}"
out="$RESULTS_DIR/$base-$suffix.json"
ln -- "$tmp" "$out"
rm -f -- "$tmp"
tmp=""
echo "wrote $out"
