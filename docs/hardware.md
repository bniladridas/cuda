# Hardware and software requirements

## Why this matters

CUDA code cannot be built or run on an Apple Silicon Mac. There is no NVIDIA
driver and no CUDA toolkit for macOS. Everything outside the `.cu` files builds
and runs locally, but **compiling and executing the kernels requires an NVIDIA
Linux host**. Until you run on one, the kernels are unverified.

The runner scripts are Bash, so native Windows is not supported.

## CPU-only check

Host-side code, CMake configuration and the reference implementations build and
run without any CUDA install:

```bash
CMAKE_ARGS="-DCMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit=ON" \
  BUILD_DIR=build-cpu ./runners/build.sh
BUILD_DIR=build-cpu ./runners/test.sh
```

`runners/build.sh` leaves the kernels unbuilt when it finds no toolkit and says
so, but it does not stop the lookup on a host that has one. The
`CMAKE_DISABLE_FIND_PACKAGE_CUDAToolkit` argument keeps this check free of
`nvcc` even there. `runners/test.sh` runs the host reference checks and reports
any GPU test it could not run as a skip rather than a pass. Use the same
`BUILD_DIR` for both, separate from the GPU build so the two configurations do
not overwrite each other.

This does not compile `src/*.cu` and does not run any GPU kernel. It validates
the build configuration and the reference maths only.

## Hosted CUDA compile check

The `cuda-compile` job in `.github/workflows/ci.yml` uses the versioned
`nvidia/cuda:12.6.3-devel-ubuntu22.04` development image on a standard
GitHub-hosted Ubuntu runner. It installs CMake 3.31.6, reports the NVCC, host
compiler, and CMake versions, then configures and builds the kernel library,
GPU test executables, and benchmark for architectures `70;75;80;86;89;90`.

This job does not need an NVIDIA device. It compiles device code and verifies
that the expected binaries exist, but it does not execute those binaries,
run CTest, perform sanitizer checks, or produce benchmark results. A passing
compile job therefore establishes CUDA source compilation for the reported
toolchain and architecture list only. Runtime correctness still requires the
separate optional NVIDIA GPU job or a documented manual GPU session.

The same CPU-only configuration can export a compilation database for
`clang-tidy`; [C++ quality](cpp-quality.md) documents the pinned formatter and
static-analysis commands. Those checks are host-only and do not compile the
kernels.

## GPU host requirements

| Component | Requirement | Notes |
| --------- | ----------- | ----- |
| GPU | NVIDIA, compute capability >= 7.0 (Volta or newer) | Default arch list is `70;75;80;86;89;90`. T4 (7.5) and A10 (8.6) are the cheapest common cloud options. |
| Driver | >= 525.60.13 (Linux) for CUDA 12.0+ | Must match the toolkit's maximum supported version. |
| CUDA toolkit | 12.x, `nvcc` on `PATH` | 12.4 or newer recommended for Hopper support. |
| OS | Linux x86_64 | The runner scripts need Bash. CUDA is not available for macOS. |
| CMake | >= 3.24 | Needed for `CUDAToolkit` package and `CUDA_ARCHITECTURES` handling. |
| Disk | ~2 GB for toolkit plus build output | Multi-arch builds produce SASS for each listed `sm_XX`. |

Cheaper alternatives if you do not own a GPU: a rented cloud instance
(A10/T4/L4 class), Kaggle's free T4 x2 notebook accelerator for spot checks
(each T4 is compute 7.5, so it runs the default architecture list), or a used
RTX 3060 (compute 8.6). None of these are assumed by the repository.

## Self-hosted CI runner

The `gpu` job in `.github/workflows/ci.yml` targets only one-shot runners:

```yaml
runs-on: [self-hosted, linux, x64, nvidia, cuda, ephemeral]
```

### Runner isolation

Register the runner with GitHub's ephemeral-runner option. The runner must
accept exactly one job and deregister after it completes. Do not use a
persistent runner for this workflow. For example, when configuring the runner,
pass the `--ephemeral` option and the labels
`linux,x64,nvidia,cuda,ephemeral`. The custom `ephemeral` label is a scheduling
guard, not proof by itself: verify that the runner was actually configured with
`--ephemeral`. Do not attach long-lived cloud credentials, deployment secrets,
or access to unrelated workspaces to this machine. Prefer a disposable VM or
instance that is destroyed after the job. If one-shot runner lifecycle cannot
be guaranteed, leave `CUDA_CI_ENABLED` unset.

### Pull-request authorization

The GPU job is deliberately narrower than the hosted CPU and Python jobs:

- Only the `pull_request` event is eligible. Push and `workflow_dispatch`
  events cannot schedule GPU work.
- The PR head repository must equal this repository. Fork PRs are denied even
  if someone adds the authorization label.
- A maintainer must explicitly add `gpu-ci:approved` after reviewing the
  proposed changes. A maintainer must remove the label if that approval is
  withdrawn.
- The repository variable `CUDA_CI_ENABLED=true` must also be set.

The condition is evaluated by the workflow from the base branch. PR-controlled
workflow changes cannot grant themselves authorization. The label does not
replace review of build scripts, CMake files, tests, or kernel code.

To enable the job:

1. Create the repository label `gpu-ci:approved` in Settings > Issues > Labels.
2. Register and verify an NVIDIA Linux runner using the one-shot isolation
   requirements above.
3. Confirm `nvidia-smi` and `nvcc --version` work for the runner user.
4. Set `CUDA_CI_ENABLED=true` in Settings > Secrets and variables > Actions >
   Variables. Leave it unset until isolated hardware is ready.
5. Review a same-repository PR, then add the `gpu-ci:approved` label to
   authorize its GPU run.

The GPU job checks out with credential persistence disabled and requires the
`ephemeral` runner label. If one-shot runner configuration is unavailable, do
not enable this job. The hosted checks remain available to all PRs.

The job runs the tests with `GPU_REQUIRED=1`. If the runner cannot see a device,
`runners/test.sh` fails instead of reporting skipped tests as a pass.

## Reproducibility notes

Benchmark numbers depend on the exact GPU, driver, toolkit and clock state.
`runners/benchmark.sh` records the GPU name, compute capability, driver and
CUDA runtime version alongside every result, and names the file after the GPU,
timestamp and commit. Do not compare results across different GPUs; compare only
within one device, or normalise by the device's peak memory bandwidth as
`docs/methodology.md` describes.
