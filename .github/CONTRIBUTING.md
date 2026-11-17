# Contributing

This repository is CUDA C++ kernel work measured against CPU references.
Changes are judged on correctness first, reproducibility second, and
performance claims last.

## Before you start

- **Kernel changes need a GPU.** `src/vecadd.cu` and `src/reduce.cu` cannot be
  compiled or run without an NVIDIA Linux host (compute capability 7.0 or
  newer, CUDA toolkit 12.x). See
  [hardware](https://github.com/bniladridas/cuda/blob/main/docs/hardware.md).
- **A change you could not compile is not a finished change.** Say which GPU,
  driver and toolkit you validated on. Anything not built with `nvcc` is
  treated as unverified, however simple it looks.
- For non-kernel changes (docs, scripts, CMake) a CPU-only machine is enough.

## Workflow

```bash
./runners/build.sh          # CUDA_KERNELS_ARCH=86 narrows the build
./runners/test.sh
./runners/benchmark.sh      # only meaningful on a GPU
```

Include the output of the build and test commands in your pull request. On a
machine without a device the GPU tests print `SKIPPED` and exit 0; a skip is not
a pass, so paste the runner's output rather than just the exit code. Use
`GPU_REQUIRED=1 ./runners/test.sh` on any machine that is supposed to have a
device, so a missing device fails the run instead of warning.

## Pull request title convention

Use `[scope] Short action-oriented description` for every pull request title.
Choose the most specific scope that describes the main area of the change. The
allowed scopes and their meanings are maintained in
[.github/pr-scopes.json](https://github.com/bniladridas/cuda/blob/main/.github/pr-scopes.json).
Add a scope there when a new area of work needs one, rather than introducing an
undocumented variation.

Begin the description with an action verb, use sentence case, and keep the
title concise and specific. Apply this convention to new pull requests and
when updating existing pull request titles.

Examples include `[kernels] Add tiled matrix multiplication`,
`[benchmarks] Improve benchmark reliability`, `[tests] Cover empty reductions`,
`[build] Simplify CUDA architecture configuration`, `[docs] Clarify GPU
validation requirements`, and `[ci] Run CPU validation on pull requests`.
Use `[pr-confidence]`, `[label-review]` or `[pr-scope-guard]` for changes
specific to those systems, and `[automation]` for repository automation that
does not fit a more specific scope.

The `pr-scope-guard` check is advisory. It reports when the declared scope does
not match the changed files, but it does not block a pull request. Fix a
mismatch or explain the cross-scope change in the pull request.

## Tests

Every kernel change needs an edge case that would have caught the bug if the bug
had existed. The current suites cover empty input, sub-warp sizes, block
boundaries (255/256/257), grid-stride sizes, non-power-of-two lengths, and
values chosen to expose float precision loss.

Tests compare against a host reference with an explicit tolerance. Do not tighten
or loosen a tolerance without saying why in the pull request.

## Python checks

Python dependencies are pinned in `requirements-dev.txt`, and Ruff is
configured in `pyproject.toml`. CI runs Ruff lint, a Ruff format check, every
Python test suite present in the checkout, and coverage. Coverage is reported
for visibility and is not used as a pass/fail gate.

Run the same checks locally:

```bash
python3 -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
coverage erase
for suite in pr-confidence label-review pr-scope-guard format-repair; do
  if [ -d "$suite/tests" ]; then
    coverage run --append -m unittest discover -s "$suite/tests"
  fi
done
coverage report --show-missing --omit="*/tests/*,*/test_*.py"
```

The C++ quality workflow policy test lives in `pr-confidence/tests` and runs with
the other Python suites.

## Performance claims

Any claim of a speedup needs:

- a result file from `./runners/benchmark.sh`, not a number typed into a message;
- the GPU name, driver, toolkit and architecture used;
- a comparison against the same kernel on the same device, or against the
  device's peak memory bandwidth.

Requirements for a valid measurement are in
[methodology](https://github.com/bniladridas/cuda/blob/main/docs/methodology.md).
Timings from a build whose correctness gate failed are not results.

## Reduction results are not bit-reproducible

Floating-point addition is not associative, so changing the block count changes
the last bits of a sum. Do not "fix" a reduction by comparing for exact
equality, and do not restructure the partitioning without re-running the GPU
tests.

## Style

- C++17. Host C++ targets use `-Wall -Wextra -Wpedantic` and, by default,
  `-Werror`; pass `-DCUDA_KERNELS_WERROR=OFF` to keep the warnings without
  failing the build. CUDA host compilation gets `-Wall -Wextra` through
  `-Xcompiler`; `-Wpedantic` is host-only. Details are in
  [C++ quality](https://github.com/bniladridas/cuda/blob/main/docs/cpp-quality.md).
- Comments explain why, not what. Non-obvious device constraints (warp-aligned
  block sizes, reduced-safe assumptions) should be a `static_assert` where
  possible rather than prose.
- No vendor wrapper libraries in `src/`. CUB and Thrust are useful as comparison
  baselines in benchmarks, not as kernel implementations.

## C++ quality

The formatted set is every tracked `.cpp`, `.h`, `.cu`, and `.cuh` file. Host
static analysis covers `tests/test_host.cpp` and the CUDA-free public headers.
It does not cover the kernels. Install the pinned tools in a virtual environment
if your Python environment is externally managed.

```bash
python3 -m pip install clang-format==22.1.8 clang-tidy==22.1.8

git ls-files -z '*.cpp' '*.h' '*.cu' '*.cuh' |
  xargs -0 clang-format --dry-run --Werror

cmake -S . -B build-cpu -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build-cpu
clang-tidy --config-file=.clang-tidy --warnings-as-errors='*' \
  -p build-cpu tests/test_host.cpp
```

The pinned versions, check set, exclusions, and CUDA limitations are in
[C++ quality](https://github.com/bniladridas/cuda/blob/main/docs/cpp-quality.md).

## Reporting a bug

Include the GPU, driver, toolkit, compute capability, the exact command, and
whether the failure is a compile error, a wrong result, or a crash. A wrong
result is far more useful with the input size and the expected versus actual
sum.
