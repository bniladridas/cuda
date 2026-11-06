# cuda

[![CPU checks](https://github.com/bniladridas/cuda/actions/workflows/ci.yml/badge.svg)](https://github.com/bniladridas/cuda/actions/workflows/ci.yml)

CUDA C++ kernel engineering: correctness, optimization and reproducible GPU
benchmarks.

Hand-written kernels, checked against CPU references and measured against the
hardware's memory bandwidth limit. No wrappers around vendor libraries: the
point is the kernel, not the call into CUB.

> The badge above reports the **CPU-only** job: configuration, host-side build
> and reference checks. It does not indicate that the CUDA kernels have been
> compiled or run. See [Status](#status).

## Status

Two kernels, both implemented end to end:

| Kernel | What it does | Correctness tests | Validated |
| ------ | ------------ | ----------------- | --------- |
| `vecadd` | `c = a + b`, grid-stride | written | **GPU run pending** |
| `reduce` | sum over `float` / `double`, warp-shuffle tree, two passes | written | **GPU run pending** |

Neither kernel has been compiled with `nvcc` or executed on a device yet. No
performance numbers are published: they will be added only after a run on real
hardware with the recorded environment (see
[`docs/methodology.md`](docs/methodology.md)). A CPU-only build proves the tree
configures and the reference maths is right; it does not verify the kernels.

## Requirements

- CMake 3.24 or newer.
- Host-side build: any Linux or macOS machine. No CUDA install needed.
- Kernel build and GPU tests: NVIDIA Linux host, compute capability 7.0 or
  newer, driver 525 or newer, CUDA toolkit 12.x with `nvcc` on `PATH`.

Details, including self-hosted runner setup, are in
[`docs/hardware.md`](docs/hardware.md).

## Build

CPU-only, which builds the host-side tests only:

```bash
cmake -S . -B build -DCMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit=ON
cmake --build build -j
```

On a machine with `nvcc` and an NVIDIA driver:

```bash
./runners/build.sh
```

Defaults to `70;75;80;86;89;90` (Volta through Hopper). Narrow it to the target
device to cut build time, for example `86` on an A10:

```bash
CUDA_KERNELS_ARCH="86" ./runners/build.sh
```

## Test

```bash
./runners/test.sh
```

`test_host` runs anywhere and checks the CPU reference implementations.
`test_vecadd` and `test_reduce` need a GPU; without one they print
`SKIPPED: no CUDA device` and exit 0, so CTest counts them as passed.
**A skip is not a pass.** The runner re-runs each test verbosely, prints
`*** SKIPPED (not a pass)` for any test that skipped, and exits non-zero if
anything actually failed.

Set `GPU_REQUIRED=1` to make a skip a failure. CI uses it on the GPU runner,
which is supposed to have a device.

Covered edge cases: empty input, sub-warp sizes, block boundaries
(255/256/257), grid-stride sizes, odd non-power-of-two lengths, all-zero and
all-one data, large-magnitude values for float precision, and `double`
cancellation.

## Benchmark

```bash
./runners/benchmark.sh
./build/cuda_benchmarks --help
```

The binary verifies every kernel at every size against a CPU reference and
refuses to print timings if any case fails. Results are written as JSON with
the device, driver, toolkit, commit and timestamp recorded. Methodology
(events, warmup, median-of-batches, achieved vs peak bandwidth) is in
[`docs/methodology.md`](docs/methodology.md).

Once a result file exists, plot it against the device's spec-sheet peak:

```bash
PEAK_GBPS=600 ./runners/plot.sh   # writes benchmarks/results/<result>.png
```

`runners/plot.sh` uses the newest file in `benchmarks/results/` and needs
matplotlib (`pip install matplotlib`); it is not a build dependency. With no
result file or no `PEAK_GBPS` it exits 2 and draws nothing. The script has been
exercised against hand-made fixtures only: **no chart here has been produced
from a real device yet.**

## Layout

```
include/cuda_kernels/   public launcher APIs (no CUDA types in signatures)
src/                    kernel implementations
kernels/                library target
tests/                  host reference checks + GPU correctness tests
benchmarks/             timing harness and benchmark binary
runners/                build / test / benchmark scripts
docs/                   hardware requirements and methodology
```

## CI

- `cpu`: GitHub-hosted, runs on every push. CPU-only configure, build, and
  host reference checks.
- `gpu`: self-hosted NVIDIA Linux runner
  (`self-hosted, linux, x64, nvidia, cuda`), compiles the kernels, runs the
  GPU correctness tests and a benchmark. The test step sets `GPU_REQUIRED=1`, so
  a runner without a working device fails instead of skipping. Gated on the
  repository variable `CUDA_CI_ENABLED=true` so it is skipped, not queued, until
  that hardware is registered; it has never run. Setup in
  [`docs/hardware.md`](docs/hardware.md).

## Roadmap

Done: vector add, parallel reduction, correctness harness, benchmark harness,
CI.

Next, in order: matrix multiplication and tiling, shared-memory and occupancy
study, profiling-driven optimization, then comparison benchmarks against
vendor-library equivalents.

## License

MIT. See [`LICENSE`](LICENSE).
