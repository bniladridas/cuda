# cuda

[![CPU checks](https://github.com/bniladridas/cuda/actions/workflows/ci.yml/badge.svg)](https://github.com/bniladridas/cuda/actions/workflows/ci.yml)
![GPU validation: pending](https://img.shields.io/badge/GPU%20validation-pending-orange)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

CUDA C++ kernel engineering: correctness, optimization and reproducible GPU
benchmarks.

Hand-written kernels, checked against CPU references and measured against the
hardware's memory bandwidth limit. No wrappers around vendor libraries: the
point is the kernel, not the call into CUB.

> Two badges, two different claims. **CPU checks** reports the GitHub-hosted
> job: configuration, host-side build, reference checks, formatting, and host
> static analysis. The separate CUDA compile job builds device code without a
> GPU. **GPU validation: pending** is static because no device has
> run this code. See [Status](#status).

## Status

Five kernels, all implemented end to end:

| Kernel | What it does | Correctness tests | Validated |
| ------ | ------------ | ----------------- | --------- |
| `vecadd` | `c = a + b`, grid-stride | written | **GPU run pending** |
| `reduce` | sum over `float` / `double`, warp-shuffle tree, two passes | written | **GPU run pending** |
| `softmax` | stable row-wise FP32 normalization, one block per row | written | **GPU run pending** |
| `gemm` | row-major FP32 matrix multiplication, 16×16 shared-memory tiles | written | **GPU run pending** |
| `layernorm` | row-wise FP32 normalization with population variance | written | **GPU run pending** |

The hosted `cuda-compile` job compiles the CUDA sources with `nvcc`, but no
kernel has been executed on a device yet. No performance numbers are published:
they will be added only after a run on real hardware with the recorded
environment (see
[`docs/methodology.md`](docs/methodology.md)). A CPU-only build proves the tree
configures and the reference maths is right; it does not verify the kernels.

### How `softmax` works

One CUDA block processes each row. Threads make strided passes to find the row maximum, sum the max-subtracted exponentials, and write normalized values. Warp shuffles and shared memory combine the eight warp partials. Arbitrary positive widths are supported, including widths that are not powers of two. Empty dimensions are no-ops.

### How `layernorm` works

One CUDA block processes each row. It computes the row mean, then the population variance in a second pass, and applies `(x - mean) / sqrt(variance + epsilon) * gamma + beta`. The default epsilon is `1e-5`; callers may provide another finite positive value. Invalid epsilon aborts under the library's fail-fast error policy. The output must not overlap input, gamma, or beta. Arbitrary positive feature widths are supported.

### How `gemm` works

One CUDA block computes a 16×16 output tile. Threads cooperatively load A and B tiles into shared memory, accumulate dot products with FP32 fused multiply-add, and mask partial edge tiles. The row-major launcher accepts an explicit stream and treats zero dimensions as no-ops.

### How `reduce` works

Two passes over the data, so any `n` uses at most 4096 blocks regardless of
size. Both passes share the same block reduction: a warp shuffle tree, the 8
warp totals in shared memory, then a second shuffle tree.

```mermaid
flowchart TB
    subgraph P1["Pass 1: reduce_partial_kernel, one block per chunk"]
        direction TB
        A["Grid-stride load<br/>x[start + tid], stride 256"] --> B["Warp shuffle down<br/>offsets 16, 8, 4, 2, 1"]
        B --> C["Lane 0 of each warp writes<br/>warp_sums[warp] in shared memory"]
        C --> D["__syncthreads"]
        D --> E["Warp 0 reduces the 8 warp totals<br/>lanes past 8 contribute 0"]
        E --> F["Thread 0 writes partials[blockIdx.x]"]
    end
    P1 --> G["partials: at most 4096 values<br/>in caller-supplied scratch"]
    G --> P2["Pass 2: reduce_final_kernel, one block<br/>same shuffle tree, writes out[0]"]
```

The last block extends to `n`, so the remainder left by ceil-scaled chunks is
never stranded. The result is not bit-reproducible across launch
configurations: float addition is not associative, so a different block count
reorders the sums. Tests compare with a relative tolerance, not for equality.

## Public API contract

The launchers are asynchronous and report immediate launch failures using a fail-fast check. Callers must synchronize the relevant stream before consuming results. See [`docs/api.md`](docs/api.md) for the error-reporting details and usage examples.

## Requirements

- CMake 3.24 or newer, and a C++17 compiler with `nvcc`-compatible flags:
  GCC or Clang. Host C++ targets build with `-Wall -Wextra -Wpedantic` and,
  unless `-DCUDA_KERNELS_WERROR=OFF` is passed, `-Werror`. CUDA host compilation
  gets `-Wall -Wextra` through `-Xcompiler`; `-Wpedantic` is host-only.
- Host-side build: any Linux or macOS machine. No CUDA install needed.
- Kernel build and GPU tests: NVIDIA Linux host, compute capability 7.0 or
  newer, driver 525 or newer, CUDA toolkit 12.x with `nvcc` on `PATH`.
- Python 3 for benchmark JSON validation and selecting the newest result when
  plotting. The benchmark runner checks for it before probing or running the GPU.
  Plotting also needs matplotlib (`pip install matplotlib`).
- Bash. The build, test and benchmark scripts are shell scripts, so native
  Windows is not supported. macOS can run the host checks but not the kernels:
  there is no CUDA toolchain for it.

Details, including self-hosted runner setup, are in
[`docs/hardware.md`](docs/hardware.md).

## Build

`./runners/build.sh` works on any Linux or macOS machine. Without a CUDA
toolkit it builds the host-side tests only and says so; the kernels are simply
not compiled. With `nvcc` present it compiles the kernels too. It configures as
`Release`, and honours an explicit `CMAKE_BUILD_TYPE` passed through
`CMAKE_ARGS`.

```bash
./runners/build.sh
```

The kernel architecture list is separate. It defaults to `70;75;80;86;89;90`
(Volta through Hopper). Narrow it to the target device to cut build time, for
example `86` on an A10:

```bash
CUDA_KERNELS_ARCH="86" ./runners/build.sh
```

## Test

```bash
./runners/test.sh
```

`test_host` runs anywhere and checks the CPU reference implementations.
`test_vecadd`, `test_reduce`, `test_softmax`, `test_gemm`, and `test_layernorm` need a GPU. A successful device query that
reports zero devices, or CUDA's explicit `cudaErrorNoDevice`, prints
`SKIPPED: no CUDA device` and exits 0, so CTest counts them as passed.
Other `cudaGetDeviceCount` failures, including insufficient-driver and
initialization errors, print the CUDA diagnostic and exit non-zero.
**A skip is not a pass.** The runner invokes CTest once with verbose
output, reports any GPU test that emitted `SKIPPED` as
`*** SKIPPED (not a pass)`, and exits non-zero if anything actually failed.
It does not execute tests a second time.

Set `GPU_REQUIRED=1` to make a skip a failure. CI uses it on the GPU runner,
which is supposed to have a device.

If a GPU test aborts with "no kernel image is available for execution on the
device", the build does not contain code for that GPU's architecture. The
default list is `70;75;80;86;89;90`; rebuild with the target's value, for
example `CUDA_KERNELS_ARCH="86" ./runners/build.sh`, then run the tests against
the same `BUILD_DIR`.

Layer-normalization tests cover zero dimensions, constant rows, single-feature
rows, large magnitudes, irregular feature widths, and a non-default stream.

Softmax tests cover empty dimensions, one-column rows, uniform rows, large positive and negative logits, mixed magnitudes, irregular widths, multiple rows, and a non-default stream. GEMM tests cover scalar, rectangular, partial 16×16 edge tiles, K-edge cases, and a non-default stream.

Covered reduction edge cases: empty input, sub-warp sizes, block boundaries
(255/256/257), grid-stride sizes, odd non-power-of-two lengths, all-zero and
all-one data, large-magnitude values for float precision, and `double`
cancellation.

## Benchmark

```bash
./runners/benchmark.sh
./build/cuda_benchmarks --help
bash ./runners/gemm-benchmark.sh
bash ./runners/layernorm-benchmark.sh
```

The existing binary benchmarks vector add and reduction. The separate GEMM
benchmark checks each matrix shape against the CPU reference before timing and
records M, N, K, tile shape, GPU, driver, CUDA runtime, commit and UTC timestamp
in JSON. The LayerNorm benchmark checks three representative row/feature
shapes against the double-precision CPU reference before timing and records
shape, epsilon, median/min/p90 latency, GPU, compute capability, driver, CUDA
runtime, commit and UTC timestamp in JSON. No result is recorded until the
benchmark runs on a real NVIDIA device. Methodology is in
[`docs/methodology.md`](docs/methodology.md).

Until a GPU run has been performed, there are no recorded results in this
repository. [`docs/kaggle-run.md`](docs/kaggle-run.md) is the manual procedure
for performing one on a free Kaggle GPU session and capturing the evidence.

Correctness runs before any timing. Each size is then warmed up and measured
with replicated batches. The median is the headline figure; min and p90 show
spread. A batch is timed launch-to-completion, so the figure includes what a
caller actually pays.

## Layout

```
include/cuda_kernels/   public launcher APIs (no CUDA types in signatures)
src/                    kernel implementations
kernels/                library target
tests/                  host reference checks + GPU correctness tests
benchmarks/             timing harness and benchmark binaries
pr-confidence/          PR Confidence engine and its offline tests
pr-scope-guard/         read-only PR title scope and changed-file check
runners/                build / test / benchmark scripts
docs/                   hardware, methodology, C++ quality, PR confidence, label review and PR Scope Guard
label-review/           reusable issue label review engine and tests
format-repair/          approval-gated C/C++/CUDA and Python formatting repair
issue-landing/          auditable linked-issue reports
squash-merge/            maintainer-approved squash-merge policy engine and tests
rebase-agent/            safe PR rebase and bounded repair engines with tests
```

## CI

- `cpu`: GitHub-hosted, runs on every push and pull request. Checks repository
  YAML with yamllint and GitHub Actions workflows with actionlint, runs the
  host-only CMake build and reference tests, verifies GPU binaries are absent,
  checks runner skip handling, formats C++/CUDA sources, and runs host-side
  clang-tidy. It also runs offline tests for label review, issue landing, PR
  confidence, PR Scope Guard, format repair, squash-merge, and rebase-agent.
  CUDA sources are formatted but not compiled or analyzed here.
- `python`: GitHub-hosted, runs Ruff lint and format checks, coverage, and the
  selected Python suites. No CUDA toolkit is required.
- `cuda-compile`: GitHub-hosted Ubuntu 22.04 container using the pinned
  `nvidia/cuda:12.6.3-devel-ubuntu22.04` image and CMake 3.31.6. It compiles the
  kernel library, all GPU test executables, and the benchmark binaries for
  architectures 70, 75, 80, 86, 89, and 90. It does not execute tests or require
  an NVIDIA device. This is compile evidence only, not GPU runtime validation.
- `gpu`: self-hosted NVIDIA Linux runner
  (`self-hosted, linux, x64, nvidia, cuda`), compiles the kernels, runs the
  GPU correctness tests and benchmarks. The test step sets `GPU_REQUIRED=1`,
  so a runner without a working device fails instead of skipping. Gated on
  `CUDA_CI_ENABLED=true` so it is skipped until that hardware is registered.

## Review automation

Repository review and merge workflows are documented in their respective
files under `docs/`.

## License

MIT. See [`LICENSE`](LICENSE).
