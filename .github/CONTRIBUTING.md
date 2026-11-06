# Contributing

This repository is CUDA C++ kernel work measured against CPU references.
Changes are judged on correctness first, reproducibility second, and
performance claims last.

## Before you start

- **Kernel changes need a GPU.** `src/vecadd.cu` and `src/reduce.cu` cannot be
  compiled or run without an NVIDIA Linux host (compute capability 7.0 or
  newer, CUDA toolkit 12.x). See [hardware](../docs/hardware.md).
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
a pass, so paste the output rather than just the exit code.

## Tests

Every kernel change needs an edge case that would have caught the bug if the bug
had existed. The current suites cover empty input, sub-warp sizes, block
boundaries (255/256/257), grid-stride sizes, non-power-of-two lengths, and
values chosen to expose float precision loss.

Tests compare against a host reference with an explicit tolerance. Do not tighten
or loosen a tolerance without saying why in the pull request.

## Performance claims

Any claim of a speedup needs:

- a result file from `./runners/benchmark.sh`, not a number typed into a message;
- the GPU name, driver, toolkit and architecture used;
- a comparison against the same kernel on the same device, or against the
  device's peak memory bandwidth.

Requirements for a valid measurement are in [methodology](../docs/methodology.md).
Timings from a build whose correctness gate failed are not results.

## Reducing results are not bit-reproducible

Floating-point addition is not associative, so changing the block count changes
the last bits of a sum. Do not "fix" a reduction by comparing for exact
equality, and do not restructure the partitioning without re-running the GPU
tests.

## Style

- C++17, `-Wall -Wextra -Wpedantic -Werror`. A warning is a build failure.
- Comments explain why, not what. Non-obvious device constraints (warp-aligned
  block sizes, reduced-safe assumptions) should be a `static_assert` where
  possible rather than prose.
- No vendor wrapper libraries in `src/`. CUB and Thrust are useful as comparison
  baselines in benchmarks, not as kernel implementations.

## Reporting a bug

Include the GPU, driver, toolkit, compute capability, the exact command, and
whether the failure is a compile error, a wrong result, or a crash. A wrong
result is far more useful with the input size and the expected versus actual
sum.
