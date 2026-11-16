# C++ quality checks

## What runs

The CPU CI job runs three host-side checks on pushes to `main` and on pull
requests:

- `clang-format` over every tracked `.cpp`, `.h`, `.cu`, and `.cuh` file, with
  `--dry-run --Werror`.
- Host C++ targets compile with `-Wall -Wextra -Wpedantic` and, by default,
  `-Werror`.
- `clang-tidy` over `tests/test_host.cpp` and the CUDA-free headers it includes,
  using the CPU compilation database.

The GPU job is unchanged. It still requires a self-hosted NVIDIA runner and is
gated on `CUDA_CI_ENABLED`. A green CPU job does not compile, run, or validate
the kernels.

## Pinned tools

The tools are installed from PyPI rather than from apt. The apt package version
is tied to the Ubuntu release and its patch level can move with the
`ubuntu-latest` image, which would make formatting results depend on the runner
date.

`clang-format==22.1.8` and `clang-tidy==22.1.8` are published as Linux x86_64
and macOS arm64 wheels. The wheel tags include `manylinux_2_27_x86_64` and
`manylinux_2_28_x86_64`, and `macosx_11_0_arm64`. The workflow pins both
versions, and `pr-confidence/tests/test_cpp_quality_workflow.py` asserts the
pins.

To install the same tools locally in a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install clang-format==22.1.8 clang-tidy==22.1.8
```

## Formatting

The configuration is `.clang-format`: an LLVM base, C++17, a 90-column limit,
two-space indentation, left-aligned pointers, no include sorting, and the
existing short `if` and escaped-newline style preserved.

Check every tracked C++ and CUDA file:

```bash
git ls-files -z '*.cpp' '*.h' '*.cu' '*.cuh' |
  xargs -0 clang-format --dry-run --Werror
```

Apply the formatter:

```bash
git ls-files -z '*.cpp' '*.h' '*.cu' '*.cuh' |
  xargs -0 clang-format -i
```

The formatting baseline is a separate commit and a mechanical change.
Regenerate it with the pinned version, not with a different clang-format
release, because the output can change between releases. The `.cu` files are
formatted even though the CPU job does not compile them.

## Compiler warnings

Host C++ targets call `cuda_kernels_set_host_warnings` from
`cmake/CompilerWarnings.cmake`. For GCC, Clang, and AppleClang the helper adds
`-Wall -Wextra -Wpedantic`, and adds `-Werror` only when
`CUDA_KERNELS_WERROR` is on. The option defaults to on; passing
`-DCUDA_KERNELS_WERROR=OFF` keeps the warnings but allows the build to continue.

The helper is target-scoped and is applied to `test_host`, `test_vecadd`,
`test_reduce`, and `cuda_benchmarks`. It is not global. CUDA language rules
would otherwise receive host-only flags.

The CUDA language flags are separate. When a toolkit is present,
`cmake/CudaArch.cmake` adds `-Xcompiler=-Wall,-Wextra,-Werror` by default, or
`-Xcompiler=-Wall,-Wextra` when `CUDA_KERNELS_WERROR` is off. `-Wpedantic` is
host-only and is never passed to `nvcc`. The `CudaArch.cmake` include comes
after the option declarations so the warning branch is defined when it is read.

The CPU job builds only `test_host`. The CUDA-gated host targets need a toolkit,
so their warning flags are not exercised there.

## Static analysis

`.clang-tidy` enables `clang-analyzer-*`, `bugprone-*`, and `performance-*`,
with `WarningsAsErrors: '*'`. The exclusions are:

- `bugprone-easily-swappable-parameters`: the host test has small float helpers
  with same-typed arguments.
- `bugprone-narrowing-conversions`: the reference test intentionally mixes
  float and double.
- `bugprone-exception-escape`: `main` may terminate on an allocation failure.

Generate the compile database and run the analysis:

```bash
cmake -S . -B build-cpu -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build-cpu
clang-tidy --config-file=.clang-tidy --warnings-as-errors='*' \
  -p build-cpu tests/test_host.cpp
```

The CPU database contains `tests/test_host.cpp` and no `.cu` entries. The
analysis covers `tests/test_host.cpp`, `tests/host_utils.h`,
`include/cuda_kernels/reduce.cuh`, and `include/cuda_kernels/vecadd.cuh`. It does
not cover the `.cu` implementations, `src/cuda_check.h`, or the CUDA-gated test
and benchmark sources, because they need CUDA headers or a toolkit.

On macOS, the PyPI clang-tidy binary does not inherit the Xcode SDK from the
compile database. If it reports that `<cstddef>` is not found, add
`--extra-arg=-isysroot --extra-arg="$(xcrun --show-sdk-path)"` after
`-p build-cpu`. The Linux CI run does not need this.

## What this does not verify

- The `.cu` sources are formatted, but they are not compiled, analyzed, or run
  by the CPU job.
- `clang-tidy` is host-only. It is not a CUDA compile, a sanitizer run, or
  evidence of kernel correctness.
- The warning flags for the CUDA host pass and the CUDA-gated host targets need
  a toolkit and are not exercised on the CPU runner.
- Benchmark methodology and performance are unchanged and unverified.
- GPU validation remains optional and gated on `CUDA_CI_ENABLED`. A green CPU
  job does not mean the kernels were validated.
