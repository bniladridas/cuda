# Manual validation run on Kaggle

This is a manual procedure. Nothing in this repository automates it, no token is
stored in a notebook, and no result is claimed until a session has produced the
logs described at the end.

Its purpose is to turn unverified kernel code into evidence: a compile, a test
run, and a benchmark that were actually executed on a named device. Until that
exists, kernel changes in this repository are unbuilt and unvalidated.

## What Kaggle provides

Free accounts get a weekly GPU quota (roughly 30 hours) and 12-hour sessions.
The available device has changed over time; check what the session actually
gets rather than assuming. Both commonly offered cards are supported by the
default architecture list in `cmake/CudaArch.cmake`:

| Device | Compute capability | Arch |
| ------ | ------------------ | ---- |
| Tesla T4 | 7.5 | `75` |
| Tesla P100 | 6.0 | **not supported** |

If the session gives a P100, this repository will not run on it. Supporting
compute capability 6.0 is a deliberate compatibility decision, not something to
work around in a session. Do not add `60` to the build to make a run work.

The CUDA toolkit is not installed on the image. Installing it is a hypothesis
about this environment, not an established fact: a session must confirm `nvcc`,
a compile and a kernel execution before any of it counts.

## Session procedure

1. Start a notebook session, enable the GPU accelerator, and confirm the device
   before doing anything else. On this image the driver is visible through
   `nvidia-smi` even though the toolkit is absent:

   ```bash
   nvidia-smi --query-gpu=name,compute_cap,driver_version --format=csv
   ```

   Record the output. If the compute capability is below 7.0, stop.

2. Install the toolkit, version 12.x, and put `nvcc` on `PATH`. Whatever the
   image ships with may be older than the minimum this repository documents.

   ```bash
   !nvcc --version || echo "no toolkit on the image"
   ```

   Only the toolkit matching the installed driver is usable. If `nvcc` reports
   a version whose release notes exclude the driver, install a different one.
3. Clone the exact commit to validate and build for its architecture. Narrowing
   the list cuts build time substantially; the full default list compiles six
   architectures and is not needed when one device is the target.

   ```bash
   git clone https://github.com/bniladridas/cuda.git
   cd cuda
   git checkout <commit>
   git rev-parse HEAD          # record this in the log
   CUDA_KERNELS_ARCH=75 BUILD_DIR=build-gpu ./runners/build.sh
   ```

   The build prints `CUDA toolkit <version> found; kernels will be built` and
   the architecture list. If it prints `CUDA toolkit not found`, the kernels
   were not compiled and nothing downstream is valid. `-Xptxas=-v` prints
   register and shared-memory use per kernel; keep that output.

4. Run the full test suite with `GPU_REQUIRED=1`. Without it, a skipped GPU test
   is only a warning, and a run that never touched a kernel could look clean.

   ```bash
   set -o pipefail
   BUILD_DIR=build-gpu GPU_REQUIRED=1 ./runners/test.sh 2>&1 \
     | tee "test-$(git rev-parse --short HEAD).log"
   ```

   `set -o pipefail` is required in the notebook cell. The pipeline's exit
   status is `tee`'s unless pipefail is on, and `tee` succeeds as long as it can
   write, so a failing suite would otherwise leave the cell looking successful.
   The script's own `set -o pipefail` applies inside the script, not to a
   pipeline the caller builds outside it.

   The run is only a pass if no line reads `*** SKIPPED (not a pass)`. Exit code
   0 with `vecadd` and `reduce` reported as skipped means the device was not
   reachable from the binary and the session proved nothing. Exit code 1 with
   `no GPU tests are registered` means the kernels were never built, which is
   the step 3 failure showing up two steps later.

5. Benchmark only after the tests pass. `runners/benchmark.sh` re-checks
   correctness itself and refuses to run without a device, so a timing from it
   cannot come from a broken build.

   ```bash
   BUILD_DIR=build-gpu RESULTS_DIR=benchmarks/results ./runners/benchmark.sh
   cp benchmarks/results/*.json .
   ```

   The JSON carries the device name, compute capability, driver and runtime
   versions, iteration counts, commit SHA and timestamp. A number without that
   file is not a result.

6. Download the session output. The three artifacts are the test log, the
   benchmark JSON, and the recorded `nvidia-smi` line.

## What not to do

- Do not raise the iteration count to produce a bigger sample from a shared
  device. Timing on Kaggle is isolated from other sessions, but the card is a
  shared resource and background load from the host is not visible from inside.
- Do not compare a T4 figure against a P100 or V100 figure without normalising
  by peak bandwidth, as `methodology.md` requires.
- Do not commit a notebook with a Kaggle API token, and do not automate the
  session. The procedure is manual on purpose.
- Do not treat a compile as validation. `nvcc` succeeding says the code is
  well-formed for that architecture. It says nothing about whether the results
  are correct.

## Once a run exists

A completed run is the point at which larger kernel test cases become worth
adding, because they can be compiled and run in the same session that produced
the baseline. Adding them before any session does is how this repository would
accumulate more code nobody has built.

The results themselves go in `benchmarks/results/` via a pull request that
quotes the device line from the log, so a reader can check which card produced
the numbers.
