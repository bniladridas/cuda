#!/usr/bin/env bash
# Regression tests for runners/test.sh. A fake CTest records each test body
# execution, allowing this check to prove the runner does not execute tests twice.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/build"
MOCK_LOG="$TMP/log"
export MOCK_LOG

cat > "$TMP/bin/ctest" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail

if [[ " $* " == *" -N "* ]]; then
  if [[ " $* " == *" -L gpu "* ]]; then
    if [[ "${MOCK_MODE:-}" != "no_gpu" ]]; then
      printf '  Test #2: vecadd\n  Test #3: reduce\n'
    fi
  else
    if [[ "${MOCK_MODE:-}" == "no_gpu" ]]; then
      printf '  Test #1: host_reference\n'
    else
      printf '  Test #1: host_reference\n  Test #2: vecadd\n  Test #3: reduce\n'
    fi
  fi
  exit 0
fi

if [[ "${MOCK_MODE:-}" == "failure" ]]; then
  printf '1: intentional test failure diagnostic\n'
  printf 'run:host_reference\nrun:vecadd\nrun:reduce\n' >> "$MOCK_LOG"
  exit 8
fi

if [[ "${MOCK_MODE:-}" == "no_gpu" ]]; then
  printf '1: host reference checks passed\n'
  printf 'run:host_reference\n' >> "$MOCK_LOG"
else
  printf '1: host reference checks passed\n'
  printf '2: SKIPPED [vecadd]: no CUDA device\n'
  printf '3: SKIPPED [reduce]: no CUDA device\n'
  printf 'run:host_reference\nrun:vecadd\nrun:reduce\n' >> "$MOCK_LOG"
fi
printf '100%% tests passed, 0 tests failed out of 3\n'
MOCK
chmod +x "$TMP/bin/ctest"

assert_tests_ran_once() {
  local test actual
  for test in "$@"; do
    actual="$(grep -c "^run:$test$" "$MOCK_LOG" || true)"
    [ "$actual" -eq 1 ] || {
      echo "expected $test to run once, got $actual executions" >&2
      cat "$MOCK_LOG" >&2
      exit 1
    }
  done
  actual="$(grep -c '^run:' "$MOCK_LOG" || true)"
  [ "$actual" -eq "$#" ] || {
    echo "expected $# total test executions, got $actual" >&2
    cat "$MOCK_LOG" >&2
    exit 1
  }
}

# Optional GPU skips are visible and each registered test runs once.
: > "$TMP/log"
output="$(PATH="$TMP/bin:$PATH" MOCK_MODE=skip MOCK_LOG="$TMP/log" \
  BUILD_DIR="$TMP/build" "$ROOT/runners/test.sh" 2>&1)"
assert_tests_ran_once host_reference vecadd reduce
[[ "$output" == *"SKIPPED (not a pass): vecadd"* ]]
[[ "$output" == *"SKIPPED (not a pass): reduce"* ]]
[[ "$output" == *"GPU kernels were NOT verified"* ]]

# GPU_REQUIRED rejects a skipped GPU test, without re-running the suite.
: > "$TMP/log"
if PATH="$TMP/bin:$PATH" MOCK_MODE=skip MOCK_LOG="$TMP/log" \
  BUILD_DIR="$TMP/build" GPU_REQUIRED=1 "$ROOT/runners/test.sh" >"$TMP/required.log" 2>&1; then
  echo "GPU_REQUIRED unexpectedly accepted skipped GPU tests" >&2
  exit 1
fi
assert_tests_ran_once host_reference vecadd reduce

# GPU_REQUIRED also rejects a build in which no GPU tests were registered.
: > "$TMP/log"
if PATH="$TMP/bin:$PATH" MOCK_MODE=no_gpu MOCK_LOG="$TMP/log" \
  BUILD_DIR="$TMP/build" GPU_REQUIRED=1 "$ROOT/runners/test.sh" >"$TMP/no-gpu.log" 2>&1; then
  echo "GPU_REQUIRED unexpectedly accepted a build with no GPU tests" >&2
  exit 1
fi
assert_tests_ran_once host_reference
grep -q "no GPU tests are registered" "$TMP/no-gpu.log"

# A real CTest failure remains non-zero and its diagnostics remain visible.
: > "$TMP/log"
if PATH="$TMP/bin:$PATH" MOCK_MODE=failure MOCK_LOG="$TMP/log" \
  BUILD_DIR="$TMP/build" "$ROOT/runners/test.sh" >"$TMP/failure.log" 2>&1; then
  echo "runner unexpectedly accepted a failing test" >&2
  exit 1
fi
assert_tests_ran_once host_reference vecadd reduce
grep -q "intentional test failure diagnostic" "$TMP/failure.log"

printf 'ok: single CTest execution, skip reporting, GPU_REQUIRED, and failure diagnostics\n'
