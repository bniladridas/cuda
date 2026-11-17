#!/usr/bin/env bash
# Runs the test suite once. Host-only checks always run. CUDA tests report
# SKIPPED rather than passing when no device is present.
#
# A skipped test exits 0, so CTest counts it as passed and normally hides its
# output. Run CTest verbosely once, capture its output, and classify tests that
# emitted the explicit SKIPPED marker without executing them again.
#
# Environment:
#   BUILD_DIR     build directory (default: build)
#   GPU_REQUIRED  set to 1 to fail when GPU tests are skipped (use in CI on a
#                 machine that is supposed to have a device)
#
# Exit codes: 0 tests passed (optional GPU skips are reported),
#             1 a test failed, or a GPU test was skipped while GPU_REQUIRED=1,
#               or no GPU tests are registered while GPU_REQUIRED=1,
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
ctest --test-dir "$BUILD_DIR" --output-on-failure --verbose 2>&1 | tee "$LOG" || status=$?

# A build without a toolkit never defines the GPU test targets. Keep this
# registration guard separate from execution so GPU_REQUIRED cannot silently
# pass after running only host tests.
gpu_tests="$(ctest --test-dir "$BUILD_DIR" -N -L gpu 2>/dev/null \
  | sed -n 's/^ *Test *#[0-9][0-9]*: //p')"
gpu_registered="$(printf '%s\n' "$gpu_tests" | awk 'NF { count++ } END { print count + 0 }')"

# GPU test binaries print `SKIPPED [name]: ...` and return success when no
# device is present. Match those names against the CTest gpu label so a skip
# cannot be mistaken for an ordinary passing test.
skipped_tests="$(sed -n 's/.*SKIPPED \[\([^]]*\)\].*/\1/p' "$LOG" | sort -u)"
skipped=()
gpu_skipped=()
other_skipped=()
while IFS= read -r test; do
  [ -n "$test" ] || continue
  skipped+=("$test")
  if printf '%s\n' "$gpu_tests" | grep -Fxq -- "$test"; then
    gpu_skipped+=("$test")
  else
    other_skipped+=("$test")
  fi
done <<< "$skipped_tests"

for test in "${skipped[@]}"; do
  echo "*** SKIPPED (not a pass): $test"
done

if [ "$GPU_REQUIRED" = "1" ] && [ "$gpu_registered" -eq 0 ]; then
  echo
  echo "FAILED: GPU_REQUIRED=1 but no GPU tests are registered in $BUILD_DIR."
  echo "        The kernels were not built, so nothing about them was verified."
  echo "        Build with a CUDA toolkit before treating this run as validation."
  exit 1
fi

if [ "$status" -ne 0 ]; then
  echo
  echo "FAILED: CTest reported one or more test failures; see output above."
  exit 1
fi

if [ "${#gpu_skipped[@]}" -ne 0 ]; then
  echo
  echo "WARNING: ${#gpu_skipped[@]} GPU test(s) skipped because no CUDA device was available:"
  printf '         %s\n' "${gpu_skipped[@]}"
  echo "         The GPU kernels were NOT verified by this run."
  if [ "$GPU_REQUIRED" = "1" ]; then
    echo "         GPU_REQUIRED=1, so this is a failure."
    exit 1
  fi
fi

if [ "${#other_skipped[@]}" -ne 0 ]; then
  echo
  echo "WARNING: non-GPU test(s) emitted SKIPPED:"
  printf '         %s\n' "${other_skipped[@]}"
fi
