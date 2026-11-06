# Hardware and software requirements

## Why this matters

CUDA code cannot be built or run on an Apple Silicon Mac. There is no NVIDIA
driver and no CUDA toolkit for macOS. Everything outside the `.cu` files builds
and runs locally, but **compiling and executing the kernels requires an NVIDIA
Linux host**. Until you run on one, the kernels are unverified.

## CPU-only check

Host-side code, CMake configuration and the reference implementations build and
run without any CUDA install:

```bash
cmake -S . -B build-cpu -DCMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit=ON
cmake --build build-cpu
ctest --test-dir build-cpu --output-on-failure
```

This does not compile `src/*.cu` and does not run any GPU kernel. It validates
the build configuration and the reference maths only.

## GPU host requirements

| Component | Requirement | Notes |
| --------- | ----------- | ----- |
| GPU | NVIDIA, compute capability >= 7.0 (Volta or newer) | Default arch list is `70;75;80;86;89;90`. T4 (7.5) and A10 (8.6) are the cheapest common cloud options. |
| Driver | >= 525.60.13 (Linux) for CUDA 12.0+ | Must match the toolkit's maximum supported version. |
| CUDA toolkit | 12.x, `nvcc` on `PATH` | 12.4 or newer recommended for Hopper support. |
| OS | Linux x86_64 | CUDA is not available for macOS. |
| CMake | >= 3.24 | Needed for `CUDAToolkit` package and `CUDA_ARCHITECTURES` handling. |
| Disk | ~2 GB for toolkit plus build output | Multi-arch builds produce SASS for each listed `sm_XX`. |

Cheaper alternatives if you do not own a GPU: a rented cloud instance
(A10/T4/L4 class), Colab's free T4 tier for spot checks, or a used RTX 3060
(compute 8.6). None of these are assumed by the repository.

## Self-hosted CI runner

The `gpu` job in `.github/workflows/ci.yml` targets:

```
runs-on: [self-hosted, linux, x64, nvidia, cuda]
```

To enable it:

1. Register an NVIDIA Linux machine as a repository runner
   (Settings > Actions > Runners > New self-hosted runner) and give it the
   labels `linux`, `x64`, `nvidia`, `cuda`. `self-hosted` is applied
   automatically.
2. Confirm `nvidia-smi` and `nvcc --version` work for the runner user.
3. Set the repository variable `CUDA_CI_ENABLED=true`
   (Settings > Secrets and variables > Actions > Variables).
4. Run the workflow manually (`workflow_dispatch`) once to confirm.

The job is gated on `CUDA_CI_ENABLED` so that, before a runner exists, it is
skipped rather than left queuing on every push. Leave the variable unset until
hardware is in place.

The job runs the tests with `GPU_REQUIRED=1`. If the runner cannot see a device,
`runners/test.sh` fails instead of reporting skipped tests as a pass.

## Reproducibility notes

Benchmark numbers depend on the exact GPU, driver, toolkit and clock state.
`runners/benchmark.sh` records the GPU name, compute capability, driver and
CUDA runtime version alongside every result, and names the file after the GPU,
timestamp and commit. Do not compare results across different GPUs; compare only
within one device, or normalise by the device's peak memory bandwidth as
`docs/methodology.md` describes.
