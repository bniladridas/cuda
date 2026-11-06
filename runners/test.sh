#!/usr/bin/env bash
# Runs the test suite. Host-only checks always run. CUDA tests report SKIPPED
# rather than passing when no device is present.
#
# A skipped test exits 0, so CTest counts it as passed and normally hides its
# output. This script therefore re-runs every test verbosely and marks any test
# whose output contains SKIPPED as "*** SKIPPED (not a pass) ***", then refuses
# to describe a run containing skips as successful.
#
# Environment:
#   BUILD_DIR     build directory (default: build)
#   GPU_REQUIRED  set to 1 to fail when GPU tests are skipped (use in CI on a
#                 machine that is supposed to have a device)
#
# Exit codes: 0 every test executed and passed,
#             1 a test failed, or a GPU test was skipped while GPU_REQUIRED=1,
#             2 no build directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
GPU_REQUIRED="${GPU_REQUIRED:-0}"

if [ ! -d "$BUILD_DIR" ]; then
  echo "no build directory at $BUILD_DIR; run runners/build.sh first" >&2
  exit 2
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

status=0
ctest --test-dir "$BUILD_DIR" --output-on-failure 2>&1 | tee "$LOG" || status=$?

skipped=()
failed=0
# Each test is re-run on its own and verbosely, because that is the only way
# CTest will show the output of a test that exited 0 after skipping.
while IFS= read -r test; do
  test_status=0
  output="$(ctest --test-dir "$BUILD_DIR" -R "^${test}\$" -V 2>&1)" || test_status=$?
  if grep -q "SKIPPED" <<<"$output"; then
    skipped+=("$test")
    echo "*** SKIPPED (not a pass): $test"
    sed -n 's/^[0-9]*: \(.*SKIPPED.*\)$/    \1/p' <<<"$output"
  elif [ "$test_status" -ne 0 ]; then
    failed=$((failed + 1))
  fi
done < <(ctest --test-dir "$BUILD_DIR" -N \
  | sed -n 's/^ *Test *#[0-9][0-9]*: //p')

if [ "$failed" -ne 0 ] || [ "$status" -ne 0 ]; then
  echo
  echo "FAILED: $failed test(s) did not pass; see output above."
  exit 1
fi

if [ "${#skipped[@]}" -ne 0 ]; then
  echo
  echo "WARNING: ${#skipped[@]} test(s) skipped because no CUDA device was available:"
  printf '         %s\n' "${skipped[@]}"
  echo "         The GPU kernels were NOT verified by this run."
  if [ "$GPU_REQUIRED" = "1" ]; then
    echo "         GPU_REQUIRED=1, so this is a failure."
    exit 1
  fi
fi
