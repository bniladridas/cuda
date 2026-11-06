#!/usr/bin/env bash
# Builds the repository. The kernels are only compiled when a CUDA toolkit is
# found; otherwise this still produces the host-side test binary.
#
# Environment:
#   BUILD_DIR             build directory (default: build)
#   CUDA_KERNELS_ARCH     semicolon-separated sm_XX list (default set in CMake)
#   CMAKE_ARGS            extra configure arguments, word-split
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"

# shellcheck disable=SC2086
cmake -S "$ROOT" -B "$BUILD_DIR" ${CMAKE_ARGS:-}
cmake --build "$BUILD_DIR" -j "${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"

echo
echo "build: $BUILD_DIR"
if [ ! -x "$BUILD_DIR/cuda_benchmarks" ]; then
  echo "note: CUDA kernels were not built (no toolkit). Run tests on a GPU host"
  echo "      to exercise test_vecadd and test_reduce."
fi
