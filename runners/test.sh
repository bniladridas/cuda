#!/usr/bin/env bash
# Runs the test suite. Host-only checks always run. CUDA tests report SKIPPED
# rather than passing when no device is present, so a green exit code alone does
# not mean the kernels were verified -- read the output.
#
# Exit codes: 0 all attempted checks passed (skips allowed),
#             1 a check failed, 2 no build directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"

if [ ! -d "$BUILD_DIR" ]; then
  echo "no build directory at $BUILD_DIR; run runners/build.sh first" >&2
  exit 2
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

ctest --test-dir "$BUILD_DIR" --output-on-failure | tee "$LOG"

skipped=0
if grep -q "SKIPPED" "$LOG"; then
  skipped=$(grep -c "SKIPPED" "$LOG")
  echo
  echo "WARNING: $skipped test(s) skipped because no CUDA device was available."
  echo "         The GPU kernels were NOT verified by this run."
fi
