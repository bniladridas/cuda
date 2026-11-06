# Benchmark methodology

The rule this repository follows: **correctness gates performance**. The
benchmark binary checks every kernel against a CPU reference at every size
before it collects a single timing, and exits non-zero if any case is wrong.

## Harness

`benchmarks/bench.h`.

- **Timing unit**: `cudaEventRecord` around a batch of `--iterations` launches,
  then `cudaEventSynchronize`. Event-based timing measures device execution
  without host-side wall-clock noise, but the figure is still launch-to-
  completion for the batch, which is what a caller actually pays.
- **Warmup**: a discarded batch of `--warmup` launches runs first, so first-touch
  page faults, context setup and clock ramp-up do not land in samples.
- **Replication**: `--reps` independent timed batches. Each batch's total is
  divided by its iteration count to give a per-launch time, and those per-batch
  times are summarised.
- **Reported statistic**: the **median** of per-batch times. The mean is
  sensitive to a single scheduler hiccup; the min is the best case and is
  reported too but is not the headline figure. p90 is included to show spread.
- **Defaults**: 200 iterations, 7 batches, 20 warmup launches.

## Metrics

- Raw time in milliseconds per launch.
- **Achieved bandwidth** = bytes moved / time, in GB/s (decimal). Bytes moved:
  `vecadd` reads 2 arrays and writes 1, so `3 * n * sizeof(float)`; `reduce`
  reads 1 array, so `n * sizeof(float)`, excluding the small partials and the
  second pass.
- Report achieved bandwidth as a fraction of the device's theoretical peak
  (from the vendor spec sheet) to compare against the hardware limit rather
  than against other code on other GPUs. The harness prints GB/s; the peak
  comparison is left to the reader with the device name recorded in every
  result file.

## Recorded context

Every JSON result carries the GPU name, compute capability, driver version,
CUDA runtime version, iteration/batch/warmup counts, and (via the filename) the
commit SHA and UTC timestamp. A number without this context is not a result.

## What would make a result invalid

- Comparing figures across different GPUs without normalising by peak bandwidth.
- Timing without a warmup batch, or with a batch too short to exceed event
  resolution (~0.5 ms).
- Reporting only the minimum.
- Any timing from a build whose correctness gate failed.
- A GPU with background load or thermal throttling; check clocks before a run
  if the numbers look low.

## Sizes

`2^16`, `2^20`, `2^24` elements. The smallest fits in cache on most devices and
is dominated by launch overhead; the largest is memory-bound on every current
card and is the meaningful bandwidth figure; the middle one falls between.
