#!/usr/bin/env bash
# Builds the repository. The kernels are only compiled when a CUDA toolkit is
# found; otherwise this still produces the host-side test binary.
#
# Environment:
#   BUILD_DIR             build directory (default: build)
#   CUDA_KERNELS_ARCH     semicolon-separated sm_XX list (default set in CMake)
#   CMAKE_ARGS            extra configure arguments, word-split
#
# Configures as Release unless the caller chose otherwise. Benchmark numbers
# from an unoptimized build are meaningless, and this is the documented build
# and benchmark path. An explicit CMAKE_BUILD_TYPE, via CMAKE_ARGS or carried
# in an existing build directory's cache, is left alone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
# Intentional word splitting: CMAKE_ARGS is a list of arguments.
# shellcheck disable=SC2206
CMAKE_ARGS=(${CMAKE_ARGS:-})

# True if the arguments set CMAKE_BUILD_TYPE in any form CMake accepts:
# -DNAME=V, -DNAME:TYPE=V, and the same with a space after -D. Returns the
# value so a caller passing -DCMAKE_BUILD_TYPE= (an empty value) is recognised
# too: CMake leaves the cache entry alone or fails, and adding Release instead
# would contradict an explicit choice either way.
build_type_supplied() {
  local i arg
  for ((i = 0; i < ${#CMAKE_ARGS[@]}; i++)); do
    arg="${CMAKE_ARGS[i]}"
    if [ "$arg" = "-D" ]; then
      i=$((i + 1))
      arg="${CMAKE_ARGS[i]-}"
    elif [ "${arg#-D}" != "$arg" ]; then
      arg="${arg#-D}"
    fi
    case "$arg" in
      CMAKE_BUILD_TYPE=* | CMAKE_BUILD_TYPE:*=*) return 0 ;;
    esac
  done
  return 1
}
has_build_type=0
if [ "${#CMAKE_ARGS[@]}" -ne 0 ] && build_type_supplied; then
  has_build_type=1
fi
if [ "$has_build_type" -eq 0 ] && [ -f "$BUILD_DIR/CMakeCache.txt" ] \
  && grep -q '^CMAKE_BUILD_TYPE:[A-Z]*=.' "$BUILD_DIR/CMakeCache.txt"; then
  has_build_type=1
fi
if [ "$has_build_type" -eq 0 ]; then
  CMAKE_ARGS+=(-DCMAKE_BUILD_TYPE=Release)
fi

cmake -S "$ROOT" -B "$BUILD_DIR" "${CMAKE_ARGS[@]}"
cmake --build "$BUILD_DIR" -j "${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"

echo
echo "build: $BUILD_DIR"
if [ ! -x "$BUILD_DIR/cuda_benchmarks" ]; then
  echo "note: CUDA kernels were not built (no toolkit). Run tests on a GPU host"
  echo "      to exercise test_vecadd and test_reduce."
fi
